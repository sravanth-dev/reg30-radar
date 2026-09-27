"""backfill/__main__.py's own logic, offline: the study window filter, and the documents
stage's gate-audit exit code (§5.4's hard invariant, mirroring orders/__main__.py's
own check on the live path). No database, no network."""

from dataclasses import dataclass, field
from datetime import date, datetime

import pytest

from tradebot.backfill import __main__ as backfill
from tradebot.common.calendar import IST


@dataclass
class FakeEvent:
    event_ts: datetime


def test_events_in_window_uses_the_filing_timestamp_not_day0():
    since, until = date(2025, 9, 22), date(2026, 9, 18)
    inside = FakeEvent(datetime(2026, 1, 15, 11, 0, tzinfo=IST))
    margin_only = FakeEvent(datetime(2025, 9, 1, 11, 0, tzinfo=IST))     # before the window
    kept = backfill.events_in_window([inside, margin_only], since, until)
    assert kept == [inside]


def test_events_in_window_is_inclusive_of_both_ends():
    since, until = date(2025, 9, 22), date(2026, 9, 18)
    first_day = FakeEvent(datetime(2025, 9, 22, 8, 0, tzinfo=IST))
    last_day = FakeEvent(datetime(2026, 9, 18, 23, 0, tzinfo=IST))
    day_after = FakeEvent(datetime(2026, 9, 19, 0, 1, tzinfo=IST))
    kept = backfill.events_in_window([first_day, last_day, day_after], since, until)
    assert kept == [first_day, last_day]


# --------------------------------------------------------------- documents stage gate audit

@dataclass
class FakeDocSummary:
    considered: int = 0
    downloaded: int = 0
    download_failed: int = 0
    order_related: int = 0
    verified: int = 0
    pending_llm: int = 0
    not_order: int = 0
    ocr_pages: int = 0
    stopped_early: str | None = None
    gate_violations: list = field(default_factory=list)


class FakeConn:
    def commit(self):
        pass


class FakeConnCtx:
    def __enter__(self):
        return FakeConn()

    def __exit__(self, *exc):
        return False


@pytest.fixture
def isolated(monkeypatch):
    """Route backfill/__main__.py's database, market and universe calls to fakes, so the
    documents-stage test only exercises the gate-audit wiring."""
    monkeypatch.setattr(backfill, "connect", lambda url: FakeConnCtx())
    monkeypatch.setattr(backfill, "backfill_url", lambda: "postgresql://fake")
    monkeypatch.setattr(backfill, "load_yaml", lambda name: {
        "window": {"announcements_from": "2025-09-22", "announcements_to": "2026-09-18"},
        "analysis": {}})


def test_a_gate_violation_exits_2_but_still_prints_the_summary(isolated, monkeypatch, capsys):
    monkeypatch.setattr(backfill.documents, "run",
                        lambda conn, since, until, max_downloads:
                        FakeDocSummary(considered=5, gate_violations=[123]))
    assert backfill.main(["documents"]) == 2
    out = capsys.readouterr().out
    assert "considered: 5" in out and "gate_violations: [123]" in out


def test_no_violation_exits_0(isolated, monkeypatch):
    monkeypatch.setattr(backfill.documents, "run",
                        lambda conn, since, until, max_downloads: FakeDocSummary(considered=5))
    assert backfill.main(["documents"]) == 0
