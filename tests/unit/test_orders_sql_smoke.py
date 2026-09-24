"""Read-only smoke tests for the real SQL in orders/run.py and orders/report.py, against
the real local Postgres (D19's standing dev fixture).

Every other orders/ test uses fakes precisely to avoid depending on a real database (see
test_orders_run.py's module docstring: `raw_announcements` is append-only, so a test that
inserted a row there could never clean it up). That leaves a real gap: nothing confirms the
hand-written SQL in `select_latest_revisions` and the two report queries is even valid
against the actual schema. These tests close that gap without inserting anything - they
only ever read, so there is nothing to clean up and no `raw_announcements` growth. They
skip cleanly wherever no local Postgres is configured (a fresh clone, CI).
"""

from __future__ import annotations

from datetime import date

import pytest

from tradebot.orders import report, run as run_mod


@pytest.fixture
def conn():
    try:
        from tradebot.common.db import connect
    except Exception as exc:
        pytest.skip(f"cannot import db module: {exc}")
    try:
        with connect() as c:
            c.execute("select 1")
            yield c
    except Exception as exc:
        pytest.skip(f"no local Postgres reachable: {exc}")


def test_select_latest_revisions_runs_and_returns_the_expected_shape(conn):
    rows = run_mod.select_latest_revisions(conn)
    assert isinstance(rows, list)
    if rows:
        row = rows[0]
        for key in ("id", "source_id", "symbol", "category_raw", "headline",
                    "attachment_url", "first_seen_at", "revision"):
            assert key in row


def test_select_latest_revisions_respects_a_date_window(conn):
    from datetime import datetime, timedelta, timezone
    far_future_start = datetime.now(timezone.utc) + timedelta(days=3650)
    far_future_end = far_future_start + timedelta(days=1)
    rows = run_mod.select_latest_revisions(conn, since=far_future_start, until=far_future_end)
    assert rows == []   # nothing exists 10 years from now


def test_select_latest_revisions_dedups_to_one_row_per_source_id(conn):
    rows = run_mod.select_latest_revisions(conn)
    source_ids = [r["source_id"] for r in rows]
    assert len(source_ids) == len(set(source_ids))


def test_report_queries_run_for_a_date_with_no_data(conn):
    # 1900-01-01: guaranteed no order_extractions rows, but the SQL must still execute
    # cleanly and return zeroed totals rather than erroring on an empty join.
    rows, totals = report.fetch(conn, date(1900, 1, 1))
    assert rows == []
    assert totals["considered"] == 0
    assert totals["llm_gate_violations"] == 0
    assert totals["ocr_gate_violations"] == 0
