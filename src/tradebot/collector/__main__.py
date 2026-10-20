"""The live collector: poll NSE, store every filing, record every poll.

    python -m tradebot.collector --once     one poll, then exit
    python -m tradebot.collector            run until stopped

D23's minimal forward collector: raw store only. No router, no dedup into events, no
document downloads - those are later slices. It exists now because `first_seen_at` cannot
be backfilled, so every day it is not running is a day of forward data that can never be
recovered.

The overflow problem it is built around: the live endpoint returns only the **20 most
recent** filings. If more than 20 arrive between two polls, the ones in between roll off
the live page. So when a poll comes back full and entirely new, the collector closes the
gap with one date-range query for yesterday and today (`close_gap`), which returns every
filing in that range rather than only the newest 20. Every overflow is recorded in
`source_health`, so the risk is measured rather than assumed.

Re-polling the live endpoint cannot close the gap, and an earlier version of this module
did exactly that: it re-polled until a page overlapped what was stored. The live page is
always the newest 20, so the very next poll overlaps the 20 just stored and the loop
stops after one extra poll, having recovered only what arrived in those few seconds.
Filings that had already rolled off were never fetched (26 Sep 2026: all 8 recorded
overflows ended after exactly one extra poll).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import date, timedelta

from tradebot.collector import nse, store
from tradebot.collector.records import SOURCE, to_raw
from tradebot.common import calendar as cal
from tradebot.common.logs import configure as configure_logging
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

    fresh, outcome = _store_new(conn, result.rows, seen, checked_at)

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
            "  OVERFLOW - closing the gap with a date-range query" if overflow else "",
        )
    return True, outcome.inserted, overflow


def close_gap(conn, client: nse.NseClient, seen: set[str]) -> bool:
    """After an overflow, fetch yesterday and today in one date-range query and store
    whatever the live page let roll off. Returns whether the query succeeded.

    Yesterday as well as today, because the gap can straddle midnight: a collector
    restarted in the morning has last evening's post-close filings to recover, and those
    carry yesterday's date. An outage longer than that is `--catchup`'s job.

    One request, not a loop. If it fails, the caller tries again on its next ordinary
    poll cycle, at the normal pace, rather than retrying here.
    """
    checked_at = cal.now_ist()
    today = checked_at.date()
    result = client.fetch_range(today - timedelta(days=1), today)

    if not result.ok:
        store.record_poll(
            conn, source=SOURCE, checked_at=checked_at, ok=False, error=result.error,
            http_status=result.http_status, latency_ms=result.latency_ms,
        )
        conn.commit()
        log.warning("gap query failed, will retry next cycle: %s", result.error)
        return False

    _fresh, outcome = _store_new(conn, result.rows, seen, checked_at)
    # Recorded as an ordinary poll row. records_returned well above 20 is what marks it
    # as a gap query rather than a live poll.
    store.record_poll(
        conn, source=SOURCE, checked_at=checked_at, ok=True,
        http_status=result.http_status, latency_ms=result.latency_ms,
        records_returned=len(result.rows), new_records=outcome.inserted,
    )
    conn.commit()
    log.info(
        "gap closed: %s to %s returned %d, %d new (%d revisions, %d already stored)",
        today - timedelta(days=1), today, len(result.rows), outcome.inserted,
        outcome.revisions, outcome.duplicates,
    )
    return True


def _store_new(conn, rows: list[dict], seen: set[str], checked_at):
    """Insert the rows whose payload hash we have not seen, and remember them."""
    raws = [to_raw(r) for r in rows]
    fresh = [r for r in raws if r.payload_sha256 not in seen]
    outcome = store.insert_announcements(conn, fresh, first_seen_at=checked_at)
    for r in fresh:
        seen.add(r.payload_sha256)
    return fresh, outcome


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
    # Set by an overflow, cleared only once the gap query succeeds, so a failed gap
    # query is retried on the next cycle instead of being forgotten.
    gap_open = False

    with connect() as conn:
        seen = store.known_hashes(conn, SOURCE)
        log.info("resuming with %d known payload hashes", len(seen))

        while True:
            ok, _new_rows, overflow = poll_once(conn, client, seen)
            failures = 0 if ok else failures + 1
            gap_open = gap_open or overflow

            if once:
                return 0 if ok else 1

            if gap_open and ok and not _stopping:
                time.sleep(nse.jittered(catch_up_gap, jitter))
                gap_open = not close_gap(conn, client, seen)
                if gap_open:
                    failures += 1

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


def catchup(date_from: date, date_to: date) -> int:
    """Close a gap after the live collector was down, with one date-range query
    (Spike A's `from_date`/`to_date` params) instead of waiting for the next live poll.

    `first_seen_at` is set to *now*, not to each filing's own timestamp. D23's rule is
    that a forward-collected `first_seen_at` can never be fabricated to look like it was
    observed in real time - it is never about refusing to record a late observation, only
    about never pretending a late one was on time. Recording the true catch-up time is the
    honest thing this function can do, and is exactly what a delayed live poll would also
    have recorded.
    """
    client = nse.NseClient()
    checked_at = cal.now_ist()
    result = client.fetch_range(date_from, date_to)
    if not result.ok:
        log.error("catch-up query failed: %s", result.error)
        return 1

    with connect() as conn:
        raws = [to_raw(r) for r in result.rows]
        outcome = store.insert_announcements(conn, raws, first_seen_at=checked_at)
        conn.commit()

    log.info(
        "catch-up %s to %s: %d returned, %d new (%d revisions, %d already stored)",
        date_from, date_to, len(result.rows), outcome.inserted, outcome.revisions,
        outcome.duplicates,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tradebot.collector")
    parser.add_argument("--once", action="store_true", help="one poll, then exit")
    parser.add_argument("--catchup", action="store_true",
                         help="one date-range query to close a gap after downtime, then exit")
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat,
                         help="with --catchup: range start (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat,
                         help="with --catchup: range end, inclusive (YYYY-MM-DD)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    if args.catchup:
        if not (args.date_from and args.date_to):
            parser.error("--catchup needs --from and --to")
        return catchup(args.date_from, args.date_to)

    return run(once=args.once)


if __name__ == "__main__":
    from tradebot.common import nse_guard
    sys.exit(nse_guard.run(main))
