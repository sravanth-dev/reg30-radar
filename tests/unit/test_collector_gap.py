"""The overflow path: what happens when more than 20 filings arrive between two polls.
No network, no database - a fake NSE and a fake store stand in for both.

The live endpoint only ever shows the newest 20 filings. These tests pin down the thing an
earlier version got wrong: polling that endpoint again cannot reach a filing that has
already rolled off it, so the gap has to be closed with a date-range query instead.
"""

from datetime import datetime, timedelta

import pytest

from tradebot.collector import __main__ as collector
from tradebot.collector import nse
from tradebot.collector.records import IST, payload_hash

NOW = datetime(2026, 9, 26, 17, 5, tzinfo=IST)


def filing(n: int) -> dict:
    return {
        "seq_id": 200000000 + n,
        "symbol": f"CO{n}",
        "sm_isin": f"INE{n:06d}A01",
        "an_dt": (NOW - timedelta(minutes=100 - n)).strftime("%d-%b-%Y %H:%M:%S"),
        "desc": "General Updates",
    }


class FakeNse:
    """Holds every filing, newest first. The live poll sees only the top 20; the
    date-range query sees them all, as the real endpoint's two query modes do."""

    def __init__(self, filings: list[dict]):
        self.filings = filings
        self.range_calls: list[tuple] = []
        self.range_ok = True

    def poll_announcements(self):
        return nse.PollResult(True, 200, 5, rows=self.filings[:20])

    def fetch_range(self, date_from, date_to):
        self.range_calls.append((date_from, date_to))
        if not self.range_ok:
            return nse.PollResult(False, None, 5, error="ConnectionError: reset")
        return nse.PollResult(True, 200, 5, rows=list(self.filings))


class FakeConn:
    def commit(self):
        pass


@pytest.fixture
def db(monkeypatch):
    """Replace the store with an in-memory table keyed on payload hash."""
    table: dict[str, object] = {}
    polls: list[dict] = []

    def insert(conn, rows, first_seen_at):
        inserted = 0
        for r in rows:
            if r.payload_sha256 not in table:
                table[r.payload_sha256] = r
                inserted += 1
        return collector.store.InsertOutcome(inserted, len(rows) - inserted, 0)

    def record_poll(conn, **kw):
        polls.append(kw)

    monkeypatch.setattr(collector.store, "insert_announcements", insert)
    monkeypatch.setattr(collector.store, "record_poll", record_poll)
    monkeypatch.setattr(collector.cal, "now_ist", lambda: NOW)
    return table, polls


def _already_held(oldest: int, newest: int) -> set[str]:
    return {payload_hash(filing(n)) for n in range(oldest, newest + 1)}


def test_live_repoll_cannot_recover_filings_that_rolled_off(db):
    # The bug this module used to have, kept as a test so it cannot quietly come back.
    # We hold filings 1-10. Then 45 arrive (11-55) before the next poll.
    table, _ = db
    fake = FakeNse([filing(n) for n in range(55, 0, -1)])
    seen = _already_held(1, 10)

    ok, new, overflow = collector.poll_once(FakeConn(), fake, seen)
    assert (ok, new, overflow) == (True, 20, True)

    # A second live poll overlaps the 20 just stored, so it reports no overflow...
    ok, new, overflow = collector.poll_once(FakeConn(), fake, seen)
    assert (new, overflow) == (0, False)
    # ...while 25 filings (11-35) are still missing. Overlap proved nothing.
    missing = [n for n in range(11, 56) if payload_hash(filing(n)) not in table]
    assert missing == list(range(11, 36))


def test_gap_query_recovers_every_filing_that_rolled_off(db):
    table, polls = db
    fake = FakeNse([filing(n) for n in range(55, 0, -1)])
    seen = _already_held(1, 10)

    _, _, overflow = collector.poll_once(FakeConn(), fake, seen)
    assert overflow
    assert collector.close_gap(FakeConn(), fake, seen) is True

    missing = [n for n in range(11, 56) if payload_hash(filing(n)) not in table]
    assert missing == []
    # The gap query is recorded like a poll, with its true size, so it is auditable.
    assert polls[-1]["ok"] is True
    assert polls[-1]["records_returned"] == 55
    assert polls[-1]["new_records"] == 25  # 11-35; 1-10 and 36-55 were already held


def test_gap_query_covers_yesterday_and_today(db):
    # A morning restart has last evening's filings to recover, dated yesterday.
    fake = FakeNse([filing(n) for n in range(25, 0, -1)])
    collector.close_gap(FakeConn(), fake, set())
    assert fake.range_calls == [(NOW.date() - timedelta(days=1), NOW.date())]


def test_failed_gap_query_is_recorded_and_reported_not_raised(db):
    _, polls = db
    fake = FakeNse([filing(n) for n in range(25, 0, -1)])
    fake.range_ok = False

    assert collector.close_gap(FakeConn(), fake, set()) is False
    assert polls[-1]["ok"] is False
    assert "reset" in polls[-1]["error"]
