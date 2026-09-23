"""The live collector: poll NSE, store every filing, record every poll.

    python -m tradebot.collector --once     one poll, then exit
    python -m tradebot.collector            run until stopped

D23's minimal forward collector: raw store only. No router, no dedup into events, no
document downloads - those are later slices. It exists now because `first_seen_at` cannot
be backfilled, so every day it is not running is a day of forward data that can never be
recovered.

The overflow problem it is built around: the live endpoint returns only the **20 most
recent** filings. If more than 20 arrive between two polls, the ones in between roll off
and are gone. So when a poll comes back full and entirely new, the collector does not
wait - it polls again at the backfill pace until a poll overlaps what it already has,
which is the proof that nothing fell through the gap. Every such event is recorded, so
the risk is measured rather than assumed.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from tradebot.collector import nse, store
from tradebot.collector.records import SOURCE, to_raw
from tradebot.common import calendar as cal
from tradebot.common.config import nse as nse_config
from tradebot.common.db import connect

log = logging.getLogger("collector")

# What the endpoint returns in one response. A full page that is entirely new means the
# page may have rolled over since the last poll (Sect.5.1).
PAGE_SIZE = 20

_stopping = False


def _handle_stop(signum, frame):
    global _stopping
    _stopping = True
    log.info("stop requested; finishing the current poll and exiting")


def poll_once(conn, client: nse.NseClient, seen: set[str]) -> tuple[bool, int, bool]:
    """One poll: store what is new, record the poll, report (ok, new_rows, overflow)."""
    checked_at = cal.now_ist()
    result = client.poll_announcements()

    if not result.ok:
        store.record_poll(
            conn, source=SOURCE, checked_at=checked_at, ok=False, error=result.error,
            http_status=result.http_status, latency_ms=result.latency_ms,
        )
        conn.commit()
        log.warning("poll failed: %s", result.error)
        return False, 0, False

    # Whether we knew anything before this poll decides whether "all new" means anything.
    cold_start = not seen

    raws = [to_raw(r) for r in result.rows]
    fresh = [r for r in raws if r.payload_sha256 not in seen]
    outcome = store.insert_announcements(conn, fresh, first_seen_at=checked_at)
    for r in fresh:
        seen.add(r.payload_sha256)

    # The page was full and nothing on it overlapped what we already had, so we cannot
    # prove filings did not roll off in between.
    #
    # A cold start is excluded: with nothing known, every record is new by definition, so
    # counting it would report a false overflow on the very first poll and trigger a
    # pointless catch-up loop.
    overflow = (
        not cold_start
        and len(result.rows) >= PAGE_SIZE
        and len(fresh) == len(result.rows)
    )

    store.record_poll(
        conn, source=SOURCE, checked_at=checked_at, ok=True,
        http_status=result.http_status, latency_ms=result.latency_ms,
        records_returned=len(result.rows), new_records=outcome.inserted,
        overflow=overflow,
    )
    conn.commit()

    if outcome.inserted or overflow:
        log.info(
            "poll: %d returned, %d new (%d revisions, %d already stored)%s",
            len(result.rows), outcome.inserted, outcome.revisions, outcome.duplicates,
            "  OVERFLOW - re-polling" if overflow else "",
        )
    return True, outcome.inserted, overflow


def run(once: bool = False) -> int:
    cfg = nse_config()
    pacing = cfg["pacing"]
    jitter = pacing["jitter_seconds"]

    today = cal.now_ist().date()
    # Fails loudly, by design: never assume every day trades (D27, Sect.5.1).
    calendar = cal.load(today.year)
    log.info("calendar %d loaded; today is %s", calendar.year, calendar.describe(today))

    warning = cal.next_year_file_warning(today)
    if warning:
        log.warning(warning)

    client = nse.NseClient()

    # An unattended collector must survive a dropped connection. Without this, one
    # transient database blip ends the process quietly at 3am, and D23's whole point is
    # that forward-collected data cannot be recovered afterwards.
    while not _stopping:
        try:
            return _collect(client, calendar, pacing, once=once)
        except Exception:
            if once:
                raise
            log.exception("collector loop failed; reconnecting in 60s")
            time.sleep(nse.jittered(60, jitter))
    return 0


def _collect(client: nse.NseClient, calendar, pacing: dict, *, once: bool) -> int:
    jitter = pacing["jitter_seconds"]
    catch_up_gap = float(pacing["backfill_min_gap_seconds"])
    failures = 0

    with connect() as conn:
        seen = store.known_hashes(conn, SOURCE)
        log.info("resuming with %d known payload hashes", len(seen))

        while True:
            ok, _new_rows, overflow = poll_once(conn, client, seen)
            failures = 0 if ok else failures + 1

            if once:
                return 0 if ok else 1

            # Catch-up loop: keep polling at the backfill pace until a page overlaps what
            # we hold. Bounded, so a permanently-full page cannot spin forever.
            catch_ups = 0
            while overflow and not _stopping and catch_ups < 20:
                time.sleep(nse.jittered(catch_up_gap, jitter))
                _, _, overflow = poll_once(conn, client, seen)
                catch_ups += 1
            if catch_ups:
                log.info("caught up after %d extra polls", catch_ups)

            if _stopping:
                return 0

            now = cal.now_ist()
            if now.year != calendar.year:
                # A collector started in December would otherwise raise CalendarError on
                # 1 January and be retried forever by the outer handler.
                calendar = cal.load(now.year)
                log.info("rolled over to the %d calendar", calendar.year)

            if failures:
                # Back off on repeated failure rather than hammering a source that is
                # already unhappy (CLAUDE.md scraping rules).
                delay = nse.backoff_seconds(failures)
                log.warning("backing off %.0fs after %d consecutive failures",
                            delay, failures)
            else:
                delay = nse.jittered(cal.poll_seconds(cal.now_ist(), calendar, pacing),
                                     jitter)
            time.sleep(delay)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tradebot.collector")
    parser.add_argument("--once", action="store_true", help="one poll, then exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    return run(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
