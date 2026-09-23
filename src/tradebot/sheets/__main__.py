"""Keep a Google Sheet in sync with `raw_announcements`, for browsing only.

    python -m tradebot.sheets --once       one sync, then exit
    python -m tradebot.sheets --rebuild    clear the sheet and resync everything, then exit
    python -m tradebot.sheets              run until stopped, syncing every interval

A separate process from the collector, on purpose: a Sheets outage, a quota error or a
dropped connection here must never stop collection, because first_seen_at cannot be
backfilled (D23). This process only ever reads raw_announcements - see sheets/sync.py for
how it avoids ever writing a duplicate row.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from tradebot.collector.nse import backoff_seconds, jittered
from tradebot.common.config import env
from tradebot.common.config import sheets as sheets_config
from tradebot.common.db import connect
from tradebot.sheets.client import SheetsClient, authorized_session
from tradebot.sheets.sync import rebuild, sync_once

log = logging.getLogger("sheets")

_stopping = False


def _handle_stop(signum, frame):
    global _stopping
    _stopping = True
    log.info("stop requested; finishing the current sync and exiting")


def _build_sheet(cfg: dict) -> SheetsClient:
    session = authorized_session(env("GOOGLE_SERVICE_ACCOUNT_FILE"))
    return SheetsClient(
        session=session,
        spreadsheet_id=env("GOOGLE_SHEET_ID"),
        tab_name=cfg["tab_name"],
        api_base=cfg["api_base"],
    )


def run(once: bool = False, do_rebuild: bool = False) -> int:
    cfg = sheets_config()
    jitter = tuple(cfg["jitter_seconds"])
    chunk_size = int(cfg["chunk_size"])
    interval = int(cfg["interval_seconds"])

    sheet = _build_sheet(cfg)
    failures = 0

    while not _stopping:
        try:
            with connect() as conn:
                if do_rebuild:
                    result = rebuild(conn, sheet, chunk_size=chunk_size)
                    do_rebuild = False  # only the first pass in this run wipes the sheet
                else:
                    result = sync_once(conn, sheet, chunk_size=chunk_size)
            failures = 0
            if result.rows_written:
                log.info("synced %d new row(s), up to raw_announcements.id=%s",
                          result.rows_written, result.last_raw_id)
        except Exception:
            failures += 1
            log.exception("sync failed (%d consecutive)", failures)

        if once:
            return 0 if failures == 0 else 1

        delay = backoff_seconds(failures) if failures else jittered(interval, jitter)
        time.sleep(delay)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tradebot.sheets")
    parser.add_argument("--once", action="store_true", help="one sync, then exit")
    parser.add_argument("--rebuild", action="store_true",
                         help="clear the sheet and resync everything from scratch")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    return run(once=args.once, do_rebuild=args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
