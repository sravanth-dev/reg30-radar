"""backfill/announcements.py: which records a company keeps, and when it counts as done.
No network, no database."""

from datetime import date

from tradebot.backfill import announcements as ann
from tradebot.collector import nse

ISIN = "INE263A01024"   # BEL


def rec(an_dt, *, isin=ISIN, seq=1, industry="Aerospace & Defense", desc="General Updates"):
    return {"seq_id": seq, "symbol": "BEL", "sm_isin": isin, "an_dt": an_dt,
            "smIndustry": industry, "desc": desc}


def test_keeps_only_this_company_inside_the_window():
    rows = [
        rec("18-Sep-2026 10:00:00", seq=1),                          # in
        rec("01-Jan-2020 10:00:00", seq=2),                          # before the window
        rec("18-Sep-2026 11:00:00", seq=3, isin="INE999X01010"),     # another company
        rec("18-Sep-2026 12:00:00", seq=4, isin=""),                 # no ISIN: kept
        {"seq_id": 5, "symbol": "BEL", "an_dt": None},               # no date: dropped
    ]
    kept = ann.select_records(rows, ISIN, date(2025, 8, 1), date(2026, 11, 1))
    assert [r["seq_id"] for r in kept] == [1, 4]


def test_industry_comes_from_the_most_recent_own_record():
    rows = [rec("01-Jan-2026 10:00:00", industry="Old Name"),
            rec("18-Sep-2026 10:00:00", industry="Aerospace & Defense"),
            rec("19-Sep-2026 10:00:00", isin="INE999X01010", industry="Banks")]
    assert ann.latest_industry(rows, ISIN) == "Aerospace & Defense"


class FakeConn:
    def __init__(self):
        self.sql: list[str] = []
        self.commits = 0

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def commit(self):
        self.commits += 1


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def fetch_symbol(self, symbol):
        self.asked.append(symbol)
        return self.answers[symbol]


def test_a_company_is_checkpointed_only_when_every_symbol_succeeded(monkeypatch):
    inserted = []
    monkeypatch.setattr(ann.raw_store, "insert_announcements",
                        lambda conn, raws, first_seen_at: inserted.extend(raws)
                        or ann.raw_store.InsertOutcome(len(raws), 0, 0))
    conn = FakeConn()
    ok_rows = [rec("18-Sep-2026 10:00:00")]
    client = FakeClient({"OLDSYM": nse.PollResult(True, 200, 5, rows=ok_rows),
                         "BEL": nse.PollResult(False, None, 5, error="ConnectionError")})

    ok, _ = ann.fetch_company(conn, client, ISIN, ["OLDSYM", "BEL"], date(2025, 8, 1),
                              date(2026, 11, 1), pause=lambda: None)
    assert ok is False
    assert inserted == [] and conn.commits == 0          # nothing stored, nothing marked

    client.answers["BEL"] = nse.PollResult(True, 200, 5, rows=ok_rows)
    ok, _ = ann.fetch_company(conn, client, ISIN, ["OLDSYM", "BEL"], date(2025, 8, 1),
                              date(2026, 11, 1), pause=lambda: None)
    assert ok is True
    assert any("backfill_checkpoints" in s for s in conn.sql)
