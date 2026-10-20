"""tradebot.live (D30) and tradebot.catchup, offline: no NSE, no database, no model."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest

from tradebot.catchup import __main__ as catchup
from tradebot.collector import nse
from tradebot.common import calendar as cal
from tradebot.common.calendar import IST
from tradebot.live import __main__ as live
from tradebot.orders.run import Summary

CAL = cal.load(2026)
WEDNESDAY = datetime(2026, 10, 21, 11, 0, tzinfo=IST)    # a trading day, in the 60 s band (20 Oct is Dussehra)


# ------------------------------------------------------------------ live: the warnings

def test_no_successful_poll_for_ten_minutes_in_the_window_warns_once():
    w = live.Watch()
    assert w.poll_result(True, WEDNESDAY, CAL) is None
    assert w.poll_result(False, WEDNESDAY + timedelta(minutes=5), CAL) is None
    assert "11:00" in w.poll_result(False, WEDNESDAY + timedelta(minutes=11), CAL)
    assert w.poll_result(False, WEDNESDAY + timedelta(minutes=12), CAL) is None   # said once
    assert w.poll_result(True, WEDNESDAY + timedelta(minutes=13), CAL) is None


def test_outside_the_window_a_quiet_spell_is_not_a_warning():
    w = live.Watch()
    night = datetime(2026, 10, 21, 23, 0, tzinfo=IST)
    w.poll_result(True, night, CAL)
    assert w.poll_result(False, night + timedelta(minutes=30), CAL) is None


def test_the_next_year_file_warning_comes_once_a_day_in_december(monkeypatch):
    monkeypatch.setattr(cal, "next_year_file_warning",
                        lambda d: "missing" if d.month == 12 else None)
    w = live.Watch()
    dec = datetime(2026, 12, 3, 9, 0, tzinfo=IST)
    assert w.next_year(dec) == "missing"
    assert w.next_year(dec + timedelta(hours=5)) is None
    assert w.next_year(dec + timedelta(days=1)) == "missing"


# ------------------------------------------------------------------ live: stops and the loop

def test_a_missing_holidays_file_stops_the_process(monkeypatch):
    def missing(year):
        raise cal.CalendarError(f"missing config/holidays_{year}.yaml")
    monkeypatch.setattr(cal, "load", missing)
    assert live.run(once=True) == live.EXIT_CALENDAR


def test_one_cycle_polls_then_runs_orders_on_a_budget(monkeypatch):
    calls = []

    @contextmanager
    def fake_connect(url=None):
        yield object()

    def fake_poll(conn, client, seen):
        calls.append("poll")
        return True, 0, False

    def fake_follow(conn, *, fetcher, client, work_dir, lookback_days, limit, stop_when):
        calls.append(("orders", limit, lookback_days, stop_when()))
        return Summary()

    monkeypatch.setattr(live, "connect", fake_connect)
    monkeypatch.setattr(live.store, "known_hashes", lambda conn, source: set())
    monkeypatch.setattr(live.collector, "poll_once", fake_poll)
    import tradebot.orders.__main__ as orders_main
    monkeypatch.setattr(orders_main, "follow_cycle", fake_follow)
    import tradebot.documents.fetch as fetch
    monkeypatch.setattr(fetch, "PdfFetcher", lambda: None)
    import tradebot.llm.client as llm_client
    monkeypatch.setattr(llm_client, "LlmClient", lambda conn: None)
    monkeypatch.setattr(nse, "NseClient", lambda: None)

    assert live.run(once=True) == 0
    assert calls[0] == "poll"
    # The order step gets the per-cycle cap and the long lookback, and is not yet due to
    # stop: the next poll is a full interval away.
    assert calls[1] == ("orders", 6, 14.0, False)


# ------------------------------------------------------------------ catchup

def _row(day: str) -> dict:
    return {"an_dt": f"{day} 10:00:00"}


def test_catchup_flags_rows_from_other_days_and_round_sized_answers():
    d = date(2026, 10, 5)
    assert catchup.suspect(d, [_row("05-Oct-2026")] * 3) == []
    assert catchup.suspect(d, [_row("05-Oct-2026"), _row("04-Oct-2026")]) == [
        "1 rows dated another day"]
    assert "round number" in catchup.suspect(d, [_row("05-Oct-2026")] * 1000)[0]
    assert catchup.suspect(d, [_row("05-Oct-2026")] * 1001) == []


def test_catchup_sends_one_request_per_day_and_marks_rows(monkeypatch):
    asked, stored, polls = [], [], []

    class FakeClient:
        def fetch_range(self, a, b):
            asked.append((a, b))
            if a == date(2026, 10, 2):
                return nse.PollResult(False, None, 5, error="ConnectionError")
            return nse.PollResult(True, 200, 5, rows=[])

    class FakeConn:
        def execute(self, sql, params=None):
            class R:
                def fetchone(self):
                    return (datetime(2026, 10, 1, 9, 31, tzinfo=IST),)
            return R()

        def commit(self):
            pass

    @contextmanager
    def fake_connect(url=None):
        yield FakeConn()

    def fake_insert(conn, rows, first_seen_at, *, collected_via):
        stored.append(collected_via)
        return catchup.store.InsertOutcome(0, 0, 0)

    monkeypatch.setattr(catchup, "connect", fake_connect)
    monkeypatch.setattr(catchup.nse, "NseClient", FakeClient)
    monkeypatch.setattr(catchup.store, "insert_announcements", fake_insert)
    monkeypatch.setattr(catchup.store, "record_poll", lambda conn, **kw: polls.append(kw))
    monkeypatch.setattr(catchup.time, "sleep", lambda s: None)

    # From the day of the last successful poll (1 Oct) to the given end.
    assert catchup.run(None, date(2026, 10, 3)) == 1          # one day failed
    assert asked == [(date(2026, 10, d), date(2026, 10, d)) for d in (1, 2, 3)]
    assert stored == ["catchup", "catchup"]
    assert [p["ok"] for p in polls] == [True, False, True]     # one health row per request
