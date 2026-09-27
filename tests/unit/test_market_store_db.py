"""market/store.py's SQL against the real backfill database, inside a transaction that is
always rolled back, so nothing persists. Skips wherever BACKFILL_DATABASE_URL is not set or
not reachable (a fresh clone, CI, the VPS). The backfill database holds no append-only
table that this touches, but the rollback keeps the test from leaving rows anyway."""

from datetime import date
from pathlib import Path

import pytest

from tradebot.market import parse, store

F = Path(__file__).resolve().parents[1] / "fixtures"
DAY = date(2026, 9, 18)


@pytest.fixture
def conn():
    try:
        import psycopg

        from tradebot.common.config import env
        url = env("BACKFILL_DATABASE_URL", required=False)
        if not url or url == "CHANGEME":
            pytest.skip("BACKFILL_DATABASE_URL not set")
        c = psycopg.connect(url)
    except Exception as exc:
        pytest.skip(f"backfill database not reachable: {exc}")
    exists = c.execute("select to_regclass('public.prices') is not null").fetchone()[0]
    if not exists:
        c.close()
        pytest.skip("backfill database not migrated (python -m tradebot.common.migrate --backfill)")
    with c.transaction(force_rollback=True):
        yield c
    c.close()


def _read(name):
    return (F / name).read_text(encoding="utf-8", errors="replace")


def test_a_day_round_trips_and_maps_every_file_to_isins(conn):
    prices = parse.parse_udiff(_read("BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV"))
    indices, actions = parse.parse_pd(_read("pd18092026.csv"))
    counts = store.save_day(conn, DAY, prices=prices, indices=indices, actions=actions,
                            caps=parse.parse_mcap(_read("mcap18092026.csv")),
                            hits=parse.parse_bh(_read("bh18092026.csv")),
                            entries=parse.parse_an(_read("an18092026.txt")))

    stored = conn.execute("select count(*) from prices where trade_date = %s", (DAY,)).fetchone()[0]
    assert stored == counts.prices > 0
    nifty = conn.execute("select close from index_prices where trade_date = %s and "
                         "index_name = 'Nifty 50'", (DAY,)).fetchone()[0]
    assert str(nifty) == "23346.40"
    assert conn.execute("select count(*) from bundle_announcements where report_date = %s",
                        (DAY,)).fetchone()[0] == 1229

    # Saving the same day again replaces it rather than duplicating.
    store.save_day(conn, DAY, prices=prices, indices=indices)
    again = conn.execute("select count(*) from prices where trade_date = %s", (DAY,)).fetchone()[0]
    assert again == stored
