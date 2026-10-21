"""Keep a Google Sheet in sync with `raw_announcements` and `order_extractions`, for
browsing only - two tabs in one spreadsheet, one shared authenticated session.

    python -m reg30_radar.sheets --once       one sync of both tabs, then exit
    python -m reg30_radar.sheets --rebuild    clear the raw tab and resync it, then run as above
    python -m reg30_radar.sheets              run until stopped, syncing every interval

A separate process from the collector, on purpose: a Sheets outage, a quota error or a
dropped connection here must never stop collection, because first_seen_at cannot be
backfilled (D23). This process only ever reads raw_announcements and order_extractions -
see sheets/sync.py for how the raw tab avoids ever writing a duplicate row, and
sheets/orders.py for why the orders tab is rewritten whole each cycle instead.

The two tabs sync independently within a cycle - each has its own try/except, so a
failure on one (a bad range, a quota error) never stops the other from updating.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from reg30_radar.collector.nse import backoff_seconds, jittered
from reg30_radar.common.logs import configure as configure_logging
from reg30_radar.common.config import env
from reg30_radar.common.config import sheets as sheets_config
from reg30_radar.common.db import connect
from reg30_radar.sheets.client import SheetsClient, authorized_session
from reg30_radar.sheets.backfill import sync_backfill
from reg30_radar.sheets.orders import sync_orders
from reg30_radar.sheets.sync import rebuild, sync_once

log = logging.getLogger("sheets")

_stopping = False


def _handle_stop(signum, frame):
    global _stopping
    _stopping = True
    log.info("stop requested; finishing the current sync and exiting")


def _backfill_url() -> str | None:
    """The backfill database, where this machine has one (the laptop); else None."""
    url = env("BACKFILL_DATABASE_URL", required=False)
    return url if url and url != "CHANGEME" else None


def _build_client(cfg: dict, session, tab_name: str) -> SheetsClient:
    return SheetsClient(
        session=session,
        spreadsheet_id=env("GOOGLE_SHEET_ID"),
        tab_name=tab_name,
        api_base=cfg["api_base"],
    )


def run(once: bool = False, do_rebuild: bool = False) -> int:
    cfg = sheets_config()
    jitter = tuple(cfg["jitter_seconds"])
    chunk_size = int(cfg["chunk_size"])
    interval = int(cfg["interval_seconds"])

    # One authenticated session, two tabs - a second service-account login every cycle
    # would just be wasted latency, and AuthorizedSession already refreshes its own token.
    session = authorized_session(env("GOOGLE_SERVICE_ACCOUNT_FILE"))
    raw_sheet = _build_client(cfg, session, cfg["tab_name"])
    orders_sheet = _build_client(cfg, session, cfg["orders_tab_name"])
    backfill_url = _backfill_url()
    backfill_sheet = (_build_client(cfg, session, cfg["backfill_tab_name"])
                      if backfill_url and cfg.get("backfill_tab_name") else None)

    failures = 0
    # order_extractions has no watermark to resume from (sheets/orders.py) - this carries
    # the "did anything change" hash across cycles instead, so an unchanged day costs one
    # cheap read, not a rewrite.
    orders_fingerprint: str | None = None
    backfill_fingerprint: str | None = None

    while not _stopping:
        cycle_ok = True

        try:
            with connect() as conn:
                if do_rebuild:
                    result = rebuild(conn, raw_sheet, chunk_size=chunk_size)
                else:
                    result = sync_once(conn, raw_sheet, chunk_size=chunk_size)
            if result.rows_written:
                log.info("raw: synced %d new row(s), up to raw_announcements.id=%s",
                          result.rows_written, result.last_raw_id)
        except Exception:
            cycle_ok = False
            log.exception("raw tab sync failed")

        # --rebuild only ever applies to the raw tab's watermark; the orders tab is
        # rewritten from scratch every cycle regardless, so it needs no rebuild of its own.
        try:
            with connect() as conn:
                orders_fingerprint, rows_written = sync_orders(
                    conn, orders_sheet, orders_fingerprint)
            if rows_written:
                log.info("orders: rewrote %d order-related row(s)", rows_written)
        except Exception:
            cycle_ok = False
            log.exception("orders tab sync failed")

        if backfill_sheet is not None:
            try:
                with connect(backfill_url) as conn:
                    backfill_fingerprint, rows_written = sync_backfill(
                        conn, backfill_sheet, backfill_fingerprint)
                if rows_written:
                    log.info("backfill: rewrote %d event row(s)", rows_written)
            except Exception:
                cycle_ok = False
                log.exception("backfill tab sync failed")

        do_rebuild = False  # only the first cycle wipes the raw tab
        failures = 0 if cycle_ok else failures + 1

        if once:
            return 0 if cycle_ok else 1

        delay = backoff_seconds(failures) if failures else jittered(interval, jitter)
        time.sleep(delay)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reg30_radar.sheets")
    parser.add_argument("--once", action="store_true", help="one sync, then exit")
    parser.add_argument("--rebuild", action="store_true",
                         help="clear the sheet and resync everything from scratch")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    return run(once=args.once, do_rebuild=args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
