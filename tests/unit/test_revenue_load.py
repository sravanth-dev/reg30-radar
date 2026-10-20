"""revenue/load.py: how each listing's rows become filings, which are downloaded (only
quarters from `results_from` on), when a company is checkpointed, and that requests are
paced and counted. Fakes stand in for NseClient and ArchiveFetcher; no network. The last
tests read three real BEL Integrated Filing XBRLs (Spike C2) with the production parser."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from tradebot.collector.nse import PollResult
from tradebot.collector.records import IST
from tradebot.market.fetch import Archive
from tradebot.revenue import load
from tradebot.revenue.xbrl import RevenueFact
from tradebot.revenue.xbrl import parse as parse_xbrl

SINCE = date(2024, 9, 1)
XBRL = Path(__file__).resolve().parents[1] / "fixtures" / "xbrl"


def test_filed_at_prefers_exchdisstime_and_pads_filingdate_with_seconds():
    assert load._filed_at({"exchdisstime": "30-Jan-2025 15:37:47"}) == \
        datetime(2025, 1, 30, 15, 37, 47, tzinfo=IST)
    assert load._filed_at({"filingDate": "30-Jan-2025 15:37"}).minute == 37
    assert load._filed_at({"filingDate": "-"}) is None
    assert load._filed_at({}) is None


def test_old_listing_rows_without_a_link_or_a_date_are_skipped_not_guessed():
    assert load.old_filing({"xbrl": "-", "exchdisstime": "30-Jan-2025 15:37:47",
                            "toDate": "31-Dec-2024"}) is None
    assert load.old_filing({"xbrl": "https://x/a/-", "toDate": "31-Dec-2024"}) is None
    assert load.old_filing({"xbrl": "https://x/f.xml", "filingDate": "-",
                            "toDate": "31-Dec-2024"}) is None
    f = load.old_filing({"xbrl": "https://x/f.xml", "exchdisstime": "30-Jan-2025 15:37:47",
                         "toDate": "31-Dec-2024"})
    assert f.period_end == date(2024, 12, 31) and f.filed_at.day == 30


def test_an_integrated_row_is_filed_at_its_broadcast_or_its_later_revision():
    row = {"xbrl": "https://x/i.xml", "qe_Date": "30-JUN-2026",
           "broadcast_Date": "27-Jul-2026 16:38:40", "revised_Date": None}
    f = load.integrated_filing(row)
    assert f.period_end == date(2026, 6, 30)
    assert f.filed_at == datetime(2026, 7, 27, 16, 38, 40, tzinfo=IST)
    revised = load.integrated_filing({**row, "revised_Date": "02-Aug-2026 10:00:00"})
    assert revised.filed_at == datetime(2026, 8, 2, 10, 0, tzinfo=IST)


class FakeNseClient:
    """`old` and `integrated` map symbol -> rows, or None for a failed request."""

    def __init__(self, old: dict, integrated: dict, totals: dict | None = None):
        self.old, self.integrated, self.totals = old, integrated, totals or {}
        self.calls: list[tuple[str, str]] = []
        self.cfg = {"pacing": {"backfill_min_gap_seconds": 3.0, "jitter_seconds": [0, 0]}}

    def _answer(self, rows, total=None):
        if rows is None:
            return PollResult(False, None, 5, error="ConnectionError")
        return PollResult(True, 200, 5, rows=rows, total=total)

    def fetch_results_listing(self, symbol):
        self.calls.append(("old", symbol))
        return self._answer(self.old.get(symbol, []))

    def fetch_integrated_results(self, symbol, page=1):
        # `integrated[symbol]` is one page of rows, or a list of pages (a list of lists)
        self.calls.append(("integrated", symbol))
        rows = self.integrated.get(symbol, [])
        if rows and isinstance(rows[0], list):
            rows = rows[page - 1] if page <= len(rows) else []
        elif page > 1:
            rows = []
        return self._answer(rows, self.totals.get(symbol))


class FakeArchiveFetcher:
    def __init__(self, xml_by_url: dict[str, bytes], status_for_missing: int | None = 404):
        self.xml_by_url = xml_by_url
        self.status_for_missing = status_for_missing
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        content = self.xml_by_url.get(url)
        if content is None:
            s = self.status_for_missing
            return Archive(s, error=f"HTTP {s}" if s else "ConnectionError: reset")
        return Archive(200, content=content)


class FakeConn:
    """Records inserts and checkpoints; never a real database."""

    def __init__(self, pending: list[tuple[str, str]]):
        self._pending = pending
        self.inserted: list[tuple] = []
        self.checkpoints: list[tuple] = []
        self.commits = 0

    def execute(self, sql, params=None):
        s = sql.lower()
        if "from backfill_universe" in s:
            return _Result(many=self._pending)
        if "insert into backfill_checkpoints" in s:
            self.checkpoints.append(params)
            return _Result()
        if "from financials" in s:          # the end-of-run FY check reads what is stored
            return _Result(many=[])
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, seq):
        self.inserted.extend(seq)

    def commit(self):
        self.commits += 1


class _Result:
    def __init__(self, many=None):
        self._many = many or []

    def fetchall(self):
        return self._many


OLD_DEC24 = {"xbrl": "https://x/dec24.xml", "exchdisstime": "30-Jan-2025 15:37:47",
             "toDate": "31-Dec-2024"}
OLD_JUN24 = {"xbrl": "https://x/jun24.xml", "exchdisstime": "29-Jul-2024 18:40:35",
             "toDate": "30-Jun-2024"}
INT_JUN26 = {"xbrl": "https://x/jun26.xml", "qe_Date": "30-JUN-2026",
             "broadcast_Date": "27-Jul-2026 16:38:40"}
ONE_FACT = [RevenueFact(period_start=None, period_end=None, months=3, basis="consolidated",
                        revenue_inr=Decimal("100"), context_id="OneD",
                        element="RevenueFromOperations")]


def test_both_listings_are_read_and_quarters_before_the_window_are_never_downloaded(monkeypatch):
    monkeypatch.setattr(load, "parse_xbrl", lambda content: ONE_FACT)
    conn = FakeConn([])
    client = FakeNseClient({"BEL": [OLD_JUN24, OLD_DEC24]}, {"BEL": [INT_JUN26]})
    fetcher = FakeArchiveFetcher({"https://x/dec24.xml": b"x", "https://x/jun26.xml": b"x"})

    ok, summary, sent = load.fetch_company(conn, client, fetcher, "INE263A01024", "BEL", SINCE)
    assert ok and sent == 4                              # two listings, two downloads
    assert client.calls == [("old", "BEL"), ("integrated", "BEL")]
    assert fetcher.calls == ["https://x/dec24.xml", "https://x/jun26.xml"]   # not jun24
    assert [row[6] for row in conn.inserted] == [       # each fact keeps its filing's time
        datetime(2025, 1, 30, 15, 37, 47, tzinfo=IST), datetime(2026, 7, 27, 16, 38, 40, tzinfo=IST)]
    assert conn.checkpoints and '"before_window": 1' in conn.checkpoints[0][2]


def test_a_fact_with_no_basis_is_never_stored(monkeypatch):
    # basis=None means no NatureOfReportStandaloneConsolidated fact was found for that
    # context - storing it anyway would silently mix bases in ttm.py.
    monkeypatch.setattr(load, "parse_xbrl", lambda content: [
        RevenueFact(None, None, 3, None, Decimal("1"), "c", "RevenueFromOperations")])
    conn = FakeConn([])
    client = FakeNseClient({}, {"BEL": [INT_JUN26]})
    load.fetch_company(conn, client, FakeArchiveFetcher({"https://x/jun26.xml": b"x"}),
                       "INE263A01024", "BEL", SINCE)
    assert conn.inserted == []


def test_a_failed_listing_leaves_the_company_uncheckpointed():
    conn = FakeConn([])
    client = FakeNseClient({"BEL": [OLD_DEC24]}, {"BEL": None})
    ok, summary, sent = load.fetch_company(conn, client, FakeArchiveFetcher({}),
                                           "INE263A01024", "BEL", SINCE)
    assert ok is False and sent == 2 and conn.checkpoints == []
    assert "integrated_filing listing" in summary


def test_a_failed_download_leaves_the_company_to_be_retried(monkeypatch):
    monkeypatch.setattr(load, "parse_xbrl", lambda content: ONE_FACT)
    conn = FakeConn([])
    client = FakeNseClient({"BEL": [OLD_DEC24]}, {"BEL": [INT_JUN26]})
    fetcher = FakeArchiveFetcher({"https://x/dec24.xml": b"x"}, status_for_missing=None)
    ok, summary, sent = load.fetch_company(conn, client, fetcher, "INE263A01024", "BEL", SINCE)
    assert ok is False and "1 failed" in summary
    assert conn.checkpoints == [] and len(conn.inserted) == 1   # kept, and skipped on retry


def test_a_listed_file_nse_does_not_serve_is_an_answer(monkeypatch):
    # A clean 404 for a listed XBRL link fails the same way on every retry (20 Oct 2026).
    monkeypatch.setattr(load, "parse_xbrl", lambda content: ONE_FACT)
    conn = FakeConn([])
    client = FakeNseClient({"BEL": [OLD_DEC24]}, {"BEL": [INT_JUN26]})
    fetcher = FakeArchiveFetcher({"https://x/dec24.xml": b"x"})     # jun26 answers 404
    ok, summary, sent = load.fetch_company(conn, client, fetcher, "INE263A01024", "BEL", SINCE)
    assert ok is True and "0 failed, 1 not served (404)" in summary
    assert len(conn.checkpoints) == 1 and len(conn.inserted) == 1


INT_MAR26 = {"xbrl": "https://x/mar26.xml", "qe_Date": "31-MAR-2026",
             "broadcast_Date": "14-May-2026 16:00:00"}


def test_an_integrated_listing_is_read_to_its_last_page(monkeypatch):
    # ITI, MCLOUD and AHLUCONT had more than one page and lost their oldest rows when only
    # page 1 was read (4 Oct 2026).
    monkeypatch.setattr(load, "parse_xbrl", lambda content: ONE_FACT)
    conn = FakeConn([])
    client = FakeNseClient({}, {"BEL": [[INT_JUN26], [INT_MAR26]]}, totals={"BEL": 2})
    fetcher = FakeArchiveFetcher({"https://x/jun26.xml": b"x", "https://x/mar26.xml": b"x"})
    ok, summary, sent = load.fetch_company(conn, client, fetcher, "INE263A01024", "BEL", SINCE)
    assert ok and sent == 1 + 2 + 2                      # old listing, two pages, two files
    assert sorted(fetcher.calls) == ["https://x/jun26.xml", "https://x/mar26.xml"]
    assert '"truncated": false' in conn.checkpoints[0][2]


def test_a_listing_still_short_is_retried_not_checkpointed(monkeypatch):
    monkeypatch.setattr(load, "parse_xbrl", lambda content: ONE_FACT)
    conn = FakeConn([])
    client = FakeNseClient({}, {"BEL": [INT_JUN26]}, totals={"BEL": 25})
    ok, summary, _ = load.fetch_company(conn, client,
                                        FakeArchiveFetcher({"https://x/jun26.xml": b"x"}),
                                        "INE263A01024", "BEL", SINCE)
    assert ok is False and conn.checkpoints == []


def test_two_values_for_one_period_in_one_file_store_neither():
    def fact(value, ctx):
        return RevenueFact(period_start=None, period_end=date(2025, 9, 30), months=6,
                           basis="consolidated", revenue_inr=Decimal(value), context_id=ctx,
                           element="RevenueFromOperations")
    kept, dropped = load.distinct_facts([fact(100, "OneD"), fact(100, "FourD")])
    assert len(kept) == 1 and dropped == 0               # the same figure twice: one fact
    kept, dropped = load.distinct_facts([fact(100, "OneD"), fact(250, "FourD")])
    assert kept == [] and dropped == 2                   # a conflict: never first-wins


def test_run_paces_counts_every_request_and_stops_before_the_cap(monkeypatch):
    monkeypatch.setattr(load, "parse_xbrl", lambda content: ONE_FACT)
    conn = FakeConn([("INE1", "AAA"), ("INE2", "BBB"), ("INE3", "CCC")])
    client = FakeNseClient({}, {"AAA": [INT_JUN26], "BBB": [], "CCC": []})
    sleeps = []
    out = load.run(conn, {"window": {"results_from": "2024-09-01"}}, max_requests=22,
                   client=client, fetcher=FakeArchiveFetcher({"https://x/jun26.xml": b"x"}),
                   sleep=sleeps.append)
    # AAA sends 3 and BBB 2 (3 + 18 <= 22 lets BBB start); a third company could need 18
    # more, and 5 + 18 > 22, so it is not started
    assert out == {"fetched": 2, "failed": 0, "requests": 5, "remaining": 1, "fy_mismatches": 0}
    assert len(sleeps) == 3        # between AAA's listings, between companies, BBB's listings


def test_real_integrated_filings_give_q4_as_fy_minus_9m_to_the_rupee():
    # BEL, Spike C2 (27 Sep 2026). The FY26 Q4 filing states both the discrete quarter and
    # the full year; the Q3 filing states the nine months. FY - 9M must equal the stated Q4.
    def consolidated(name, months):
        facts = parse_xbrl((XBRL / name).read_bytes())
        return [f.revenue_inr for f in facts if f.months == months and f.basis == "consolidated"]

    fy = consolidated("bel_integrated_fy26_q4_consolidated.xml", 12)
    q4 = consolidated("bel_integrated_fy26_q4_consolidated.xml", 3)
    nine = consolidated("bel_integrated_fy26_q3_consolidated.xml", 9)
    assert fy == [Decimal("276101100000")] and nine == [Decimal("173856800000")]
    assert q4 == [fy[0] - nine[0]] == [Decimal("102244300000")]


def test_a_real_integrated_quarter_parses_with_its_period():
    facts = parse_xbrl((XBRL / "bel_integrated_2026q1_consolidated.xml").read_bytes())
    assert [(f.period_start, f.period_end, f.months, f.revenue_inr) for f in facts] == [
        (date(2026, 4, 1), date(2026, 6, 30), 3, Decimal("55469800000"))]


def test_only_event_companies_are_pending_and_under_their_latest_symbol(scratch_conn):
    # SABTNL's ISIN was reissued with a new symbol, AQYLON (Mar 2026); NSE files the
    # company's results under the current symbol. A company with no event is not fetched.
    c = scratch_conn
    for isin, sym in (("INE416A01044", "SABTNL"), ("INE263A01024", "BEL")):
        c.execute("insert into backfill_universe (isin, symbol, series, as_of_date)"
                  " values (%s, %s, 'EQ', '2025-09-22')", (isin, sym))
    for isin, sym, first, last in (("INE416A01044", "SABTNL", "2025-03-03", "2026-03-04"),
                                   ("INE416A01051", "AQYLON", "2026-03-05", "2026-09-25"),
                                   ("INE263A01024", "BEL", "2025-03-03", "2026-09-25")):
        c.execute("insert into instrument_symbols (isin, symbol, series, first_seen, last_seen)"
                  " values (%s, %s, 'EQ', %s, %s)", (isin, sym, first, last))
    c.execute("insert into backfill_events (isin, symbol, event_ts, raw_ids, primary_raw_id,"
              " bucket, state) values ('INE416A01044', 'SABTNL', now(), '{1}', 1, 'order_win',"
              " 'calculated')")
    c.commit()
    assert load.pending_companies(c) == [("INE416A01044", "AQYLON")]
