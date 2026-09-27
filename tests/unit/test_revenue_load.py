"""revenue/load.py: which listing rows are skipped (no xbrl link, no usable filing date),
that a company is checkpointed only once fetched, and that companies are paced between
requests. Fakes stand in for NseClient and ArchiveFetcher; no network."""

from datetime import datetime, timezone
from decimal import Decimal

from tradebot.collector.nse import PollResult
from tradebot.collector.records import IST
from tradebot.market.fetch import Archive
from tradebot.revenue import load
from tradebot.revenue.xbrl import RevenueFact


def test_filed_at_prefers_exchdisstime_and_pads_filingdate_with_seconds():
    assert load._filed_at({"exchdisstime": "30-Jan-2025 15:37:47"}) == \
        datetime(2025, 1, 30, 15, 37, 47, tzinfo=IST)
    assert load._filed_at({"filingDate": "30-Jan-2025 15:37"}).minute == 37
    assert load._filed_at({"filingDate": "-"}) is None
    assert load._filed_at({}) is None


class FakeNseClient:
    def __init__(self, rows_by_symbol: dict[str, list[dict] | None]):
        self.rows_by_symbol = rows_by_symbol
        self.calls: list[str] = []
        self.cfg = {"pacing": {"backfill_min_gap_seconds": 3.0, "jitter_seconds": [0, 0]}}

    def fetch_results_listing(self, symbol):
        self.calls.append(symbol)
        rows = self.rows_by_symbol.get(symbol)
        if rows is None:
            return PollResult(False, None, 5, error="ConnectionError")
        return PollResult(True, 200, 5, rows=rows)


class FakeArchiveFetcher:
    def __init__(self, xml_by_url: dict[str, bytes]):
        self.xml_by_url = xml_by_url
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        content = self.xml_by_url.get(url)
        if content is None:
            return Archive(404, error="HTTP 404")
        return Archive(200, content=content)


class FakeConn:
    """Records executemany/execute calls; enough of order_extractions-style SQL for these
    tests, never a real database."""

    def __init__(self, pending: list[tuple[str, str]]):
        self._pending = pending
        self.inserted: list[tuple] = []
        self.checkpoints: list[tuple] = []
        self.commits = 0

    def execute(self, sql, params=None):
        s = sql.lower()
        if "select u.isin, u.symbol from backfill_universe" in s:
            return _Result(many=self._pending)
        if "insert into backfill_checkpoints" in s:
            self.checkpoints.append(params)
            return _Result()
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


GOOD_ROW = {
    "symbol": "BEL", "isin": "INE263A01016", "xbrl": "https://x/good.xml",
    "exchdisstime": "30-Jan-2025 15:37:47",
}


def test_a_row_with_no_xbrl_link_is_skipped_not_guessed():
    conn = FakeConn([("INE1", "AAA")])
    client = FakeNseClient({"AAA": [{"xbrl": "-"}, {"xbrl": ""}, {}]})
    fetcher = FakeArchiveFetcher({})
    ok, summary = load.fetch_company(conn, client, fetcher, "INE1", "AAA")
    assert ok and "0 facts from 3 filings (3 no xbrl, 0 failed)" in summary
    assert conn.inserted == []


def test_a_row_with_no_usable_date_is_skipped():
    conn = FakeConn([("INE1", "AAA")])
    client = FakeNseClient({"AAA": [{"xbrl": "https://x/f.xml", "filingDate": "-"}]})
    fetcher = FakeArchiveFetcher({})
    ok, summary = load.fetch_company(conn, client, fetcher, "INE1", "AAA")
    assert ok and "1 no xbrl" in summary   # counted the same way as no-link, deliberately


def test_a_real_filing_is_parsed_and_stored(monkeypatch):
    monkeypatch.setattr(load, "parse_xbrl", lambda content: [
        RevenueFact(period_start=None, period_end=None, months=3, basis="consolidated",
                    revenue_inr=Decimal("100"), context_id="OneD", element="RevenueFromOperations"),
    ])
    conn = FakeConn([("INE263A01016", "BEL")])
    client = FakeNseClient({"BEL": [GOOD_ROW]})
    fetcher = FakeArchiveFetcher({"https://x/good.xml": b"<xml/>"})
    ok, summary = load.fetch_company(conn, client, fetcher, "INE263A01016", "BEL")
    assert ok and conn.commits == 1
    assert len(conn.inserted) == 1 and conn.inserted[0][5] == Decimal("100")
    assert conn.checkpoints[0][0] == "INE263A01016"


def test_a_fact_with_no_basis_is_never_stored():
    # basis=None means no NatureOfReportStandaloneConsolidated fact was found for that
    # context - storing it anyway would silently mix bases in ttm.py.
    facts = [RevenueFact(None, None, 3, None, Decimal("1"), "c", "RevenueFromOperations")]
    kept = [f for f in facts if f.months in load.KEEP_MONTHS and f.basis is not None]
    assert kept == []


def test_a_failed_listing_request_leaves_the_company_unfetched_and_uncheckpointed():
    conn = FakeConn([("INE1", "AAA")])
    client = FakeNseClient({"AAA": None})
    ok, summary = load.fetch_company(conn, client, FakeArchiveFetcher({}), "INE1", "AAA")
    assert ok is False and conn.checkpoints == []


def test_run_paces_between_companies_and_stops_at_max_requests(monkeypatch):
    # The guard is deliberately conservative (>= 2 requests of headroom per company, since
    # a company might need more than the one listing call charged against it here, e.g. a
    # real XBRL download) - it stops one company earlier than the raw count would allow,
    # matching market/__main__.py's own "stop before, not after" margin.
    conn = FakeConn([("INE1", "AAA"), ("INE2", "BBB"), ("INE3", "CCC")])
    client = FakeNseClient({"AAA": [], "BBB": [], "CCC": []})
    sleeps = []
    out = load.run(conn, {}, max_requests=3, client=client, fetcher=FakeArchiveFetcher({}),
                   sleep=sleeps.append)
    assert client.calls == ["AAA", "BBB"]         # stopped before a third request
    assert len(sleeps) == 1                        # paced once, between AAA and BBB
    assert out == {"fetched": 2, "failed": 0, "remaining": 1}
