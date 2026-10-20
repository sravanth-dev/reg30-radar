"""Shared fixtures.

`scratch_conn`: a real Postgres connection whose search_path is a throwaway schema in the
**backfill** database, with every migration applied, dropped again after the test. It lets
code that commits, as the backfill stages do on purpose, be tested against real SQL, which
a rollback-only transaction cannot do. It never touches the live `tradebot` database, which
moves to the VPS by pg_dump, and it skips wherever BACKFILL_DATABASE_URL is not set.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def scratch_conn():
    try:
        import psycopg

        from tradebot.common.config import env
        url = env("BACKFILL_DATABASE_URL", required=False)
        if not url or url == "CHANGEME":
            pytest.skip("BACKFILL_DATABASE_URL not set")
        conn = psycopg.connect(url)
    except Exception as exc:
        pytest.skip(f"backfill database not reachable: {exc}")

    schema = f"test_{uuid.uuid4().hex[:12]}"
    conn.execute(f"create schema {schema}")
    conn.execute(f"set search_path to {schema}")
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute(f"drop schema {schema} cascade")
        conn.commit()
        conn.close()


@pytest.fixture(autouse=True)
def nse_guard_for_tests(tmp_path_factory, monkeypatch):
    """Every test gets its own NSE guard: a lock file in a temporary directory of its own
    (not the test's tmp_path, which some tests inspect) and a sleep that returns at once, so
    no test ever waits on pacing or touches data/nse.lock."""
    from tradebot.common import nse_guard

    lock = tmp_path_factory.mktemp("nse_guard") / "nse.lock"
    guard = nse_guard.NseGuard(lock, sleep=lambda seconds: None)
    monkeypatch.setattr(nse_guard, "GUARD", guard)
    yield guard
    guard.release()
