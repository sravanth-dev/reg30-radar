"""The one live process (D30). `python -m tradebot.live [--once]`

Polls NSE's announcements on D6's schedule and, after each poll, runs the order pipeline
on whatever is pending, in one loop. The brief allows one process on this machine to talk
to NSE at a time, so the collector and `orders --follow` no longer run side by side: both
the poll and the PDF downloads go through the NSE lock and the one request gap
(`common/nse_guard.py`).

What keeps the poll on time. The live endpoint shows only the 20 newest filings (§5.1),
so a late poll can lose filings. Each cycle therefore gives the order pipeline a budget:
at most `live_filings_per_cycle` filings, and none started within
`live_poll_margin_seconds` of the next poll (`config/documents.yaml`). The rest stay
pending and are taken next cycle. If more than 20 filings still arrive between two polls,
the overflow gap query recovers them, as before.

Stops, by design, rather than running on wrongly:
- a missing or unusable holidays file for the current year (D27): exit code 2;
- 5 consecutive failed NSE requests (`NseHardStop`): exit code 3, via `nse_guard.run`.
Restarting after either is the hosting layer's job (GATE 2). A database error reconnects
after 60 s, as the old collector did. From 1 December it warns once a day until next
year's holidays file exists, and inside the trading window it warns once when no poll has
succeeded for 10 minutes (§5.1 health).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta

from tradebot.collector import __main__ as collector
from tradebot.collector import nse, store
from tradebot.collector.records import SOURCE
from tradebot.common import calendar as cal
from tradebot.common.config import documents as documents_config, nse as nse_config
from tradebot.common.db import connect
from tradebot.common.logs import configure as configure_logging

log = logging.getLogger("live")

# §5.1: warn when a source has had no successful poll for this long inside the window.
STALE_AFTER = timedelta(minutes=10)
EXIT_CALENDAR = 2

_stopping = False


def _handle_stop(signum, frame):
    global _stopping
    _stopping = True
    log.info("stop requested; finishing the current step and exiting")


class Watch:
    """The two warnings this loop owes, each said once rather than every cycle."""

    def __init__(self):
        self.last_ok: datetime | None = None
        self.stale_warned = False
        self.year_warned_on = None

    def poll_result(self, ok: bool, now: datetime, calendar) -> str | None:
        if ok:
            self.last_ok, self.stale_warned = now, False
            return None
        in_window = (calendar.is_trading_day(now.date())
                     and cal.band_for(now, nse_config()["pacing"]) is not None)
        if (in_window and not self.stale_warned and self.last_ok is not None
                and now - self.last_ok > STALE_AFTER):
            self.stale_warned = True
            return (f"no successful poll since {self.last_ok:%H:%M} "
                    f"({(now - self.last_ok).seconds // 60} min) inside the trading window")
        return None

    def next_year(self, now: datetime) -> str | None:
        if self.year_warned_on == now.date():
            return None
        warning = cal.next_year_file_warning(now.date())
        if warning:
            self.year_warned_on = now.date()
        return warning


def run(once: bool = False) -> int:
    pacing = nse_config()["pacing"]
    ocfg = documents_config()["orders"]
    try:
        calendar = cal.load(cal.now_ist().year)
    except cal.CalendarError as exc:
        log.error("stopping: %s", exc)
        return EXIT_CALENDAR
    log.info("calendar %d loaded; today is %s", calendar.year,
             calendar.describe(cal.now_ist().date()))
    client = nse.NseClient()          # the live gap (2 s), warm-up included
    watch = Watch()

    while not _stopping:
        try:
            return _loop(client, calendar, pacing, ocfg, watch, once=once)
        except cal.CalendarError as exc:
            log.error("stopping: %s", exc)
            return EXIT_CALENDAR
        except Exception:
            if once:
                raise
            log.exception("live loop failed; reconnecting in 60s")
            time.sleep(nse.jittered(60, pacing["jitter_seconds"]))
    return 0


def _loop(client, calendar, pacing: dict, ocfg: dict, watch: Watch, *, once: bool) -> int:
    from tradebot.documents.fetch import PdfFetcher
    from tradebot.llm.client import LlmClient
    from tradebot.orders.__main__ import _work_dir, follow_cycle

    jitter = pacing["jitter_seconds"]
    gap_wait = float(pacing["backfill_min_gap_seconds"])
    per_cycle = int(ocfg["live_filings_per_cycle"])
    margin = float(ocfg["live_poll_margin_seconds"])
    lookback = float(ocfg["live_lookback_days"])
    fetcher = PdfFetcher()
    failures, gap_open = 0, False

    with connect() as conn:
        llm = LlmClient(conn=conn)
        seen = store.known_hashes(conn, SOURCE)
        log.info("resuming with %d known payload hashes", len(seen))
        while True:
            started = time.monotonic()
            now = cal.now_ist()
            if now.year != calendar.year:
                calendar = cal.load(now.year)          # CalendarError stops the process
                log.info("rolled over to the %d calendar", calendar.year)
            warning = watch.next_year(now)
            if warning:
                log.warning(warning)

            ok, _new, overflow = collector.poll_once(conn, client, seen)
            failures = 0 if ok else failures + 1
            stale = watch.poll_result(ok, now, calendar)
            if stale:
                log.warning(stale)
            gap_open = gap_open or overflow
            if gap_open and ok and not _stopping:
                time.sleep(nse.jittered(gap_wait, jitter))
                gap_open = not collector.close_gap(conn, client, seen)

            if failures:
                # NseGuard already keeps a backoff gap before the next request; this only
                # spaces the polls themselves (CLAUDE.md scraping rules).
                delay = nse.backoff_seconds(failures)
            else:
                delay = nse.jittered(cal.poll_seconds(cal.now_ist(), calendar, pacing), jitter)
            deadline = started + delay

            if ok and not _stopping:
                summary = follow_cycle(
                    conn, fetcher=fetcher, client=llm, work_dir=_work_dir(),
                    lookback_days=lookback, limit=per_cycle,
                    stop_when=lambda: _stopping or time.monotonic() > deadline - margin)
                if summary.considered or summary.deferred:
                    log.info("orders: considered=%d downloaded=%d verified=%d needs_review=%d"
                             " pending=%d deferred=%d llm_cost=$%s%s",
                             summary.considered, summary.downloaded, summary.verified,
                             summary.needs_review, summary.pending_llm + summary.download_failed,
                             summary.deferred, summary.llm_cost_usd,
                             f"  STOPPED: {summary.stopped_early}" if summary.stopped_early
                             else "")
                if summary.gate_violations:
                    log.error("GATE VIOLATION: LLM/OCR reached a non-order-related filing: %s",
                              summary.gate_violations)

            if once or _stopping:
                return 0 if ok else 1
            time.sleep(max(0.0, deadline - time.monotonic()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tradebot.live")
    parser.add_argument("--once", action="store_true",
                        help="one poll and one order cycle, then exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    return run(once=args.once)


if __name__ == "__main__":
    from tradebot.common import nse_guard
    sys.exit(nse_guard.run(main))
