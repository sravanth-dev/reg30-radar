"""Order extraction and the §5.6 escalation gate, in two branches sharing one processing
core (`orders/run.py`):

    python -m reg30_radar.orders --date 2026-09-23             one day, already scraped
    python -m reg30_radar.orders --from 2026-09-20 --to 2026-09-24   a date range
    python -m reg30_radar.orders --follow                       live, next to the collector

**Why `--follow` is a separate process rather than something the collector does inline.**
Downloading a PDF, running the per-page quality ladder and possibly calling the LLM can
take tens of seconds per filing. Doing that inside the collector's poll loop would delay
the next poll, and the announcements endpoint only shows the **20 most recent** filings
(§5.1) - a late poll can lose filings for good, and `first_seen_at` cannot be backfilled
(D23). So the collector stays raw-store only, and this worker follows the
`raw_announcements` table instead of hooking into the collector's loop: every saved row
gets processed exactly once, whether `--follow` was running when it arrived or picks it up
on its next cycle after a restart. The collector polls the API host; this polls the archive
host for attachments and the LLM - separate sessions, matching the split
`documents/fetch.py` already made.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import date, datetime, timedelta

from reg30_radar.common.calendar import IST
from reg30_radar.common.logs import configure as configure_logging
from reg30_radar.common.config import documents as documents_config
from reg30_radar.common.db import connect
from reg30_radar.collector.nse import jittered
from reg30_radar.documents.fetch import PdfFetcher
from reg30_radar.llm.client import LlmClient
from reg30_radar.orders import report, run as run_mod, store as orders_store

log = logging.getLogger("orders")


def _work_dir():
    from reg30_radar.common.config import ROOT
    return ROOT / "data" / "orders_work"


_stopping = False


def _handle_stop(signum, frame):
    global _stopping
    _stopping = True
    log.info("stop requested; finishing the current filing and exiting")


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    """One calendar day in IST, as the UTC-aware bounds `first_seen_at` is compared
    against (D17: IST at the edges, timestamptz everywhere in storage).
    """
    start = datetime(d.year, d.month, d.day, tzinfo=IST)
    return start, start + timedelta(days=1)


def run_batch(*, since: date, until: date, max_requests: int) -> int:
    """`--date` / `--from`/`--to`: process everything pending in [since, until), then
    write a report for every date touched, then exit.
    """
    start, _ = _day_bounds(since)
    _, end = _day_bounds(until)
    work_dir = _work_dir()

    with connect() as conn:
        client = LlmClient(conn=conn)
        fetcher = PdfFetcher()
        raw_rows = run_mod.select_latest_revisions(conn, since=start, until=end)
        log.info("%d filings in range; classifying and processing pending ones",
                  len(raw_rows))
        summary = run_mod.process_pending(
            conn, raw_rows, fetcher=fetcher, client=client, work_dir=work_dir,
            max_requests=max_requests,
        )
        for touched in sorted(summary.dates_touched):
            md_path, csv_path = report.write(conn, touched)
            log.info("wrote %s and %s", md_path, csv_path)

        log.info(
            "done: considered=%d downloaded=%d order_related=%d verified=%d "
            "needs_review=%d not_order=%d pending=%d llm_calls=%d llm_cost=$%s "
            "ocr_pages=%d%s",
            summary.considered, summary.downloaded, summary.order_related,
            summary.verified, summary.needs_review, summary.not_order,
            summary.pending_llm + summary.download_failed, summary.llm_calls,
            summary.llm_cost_usd, summary.ocr_pages,
            f"  STOPPED EARLY: {summary.stopped_early}" if summary.stopped_early else "",
        )
        if summary.gate_violations:
            log.error("GATE VIOLATION: LLM/OCR reached a non-order-related filing: %s",
                       summary.gate_violations)
            return 2
    return 0


def follow_cycle(conn, *, fetcher, client, work_dir, lookback_days: float,
                 now: datetime | None = None, limit: int | None = None,
                 stop_when=None) -> run_mod.Summary:
    """One `--follow` pass: process whatever the collector saved recently, then refresh the
    live report for each day touched.

    Only filings first seen in the last `lookback_days` are read. Reading the whole table
    every cycle meant re-reading and re-classifying every out-of-scope filing ever stored,
    because those never get an `order_extractions` row: about 1,200 more rows a day,
    every two minutes, inside a 512 MB container (WORKLOG, 27 Sep). A few days is still
    far longer than any retry takes (three attempts, 15 minutes apart), and a
    `--catchup` after an outage stamps what it recovers with the catch-up time, so it
    lands inside the window too.
    """
    now = now or datetime.now(IST)
    since = now - timedelta(days=lookback_days)
    raw_rows = run_mod.select_latest_revisions(conn, since=since)
    # The retry queue, however old: a filing waiting on a cap must not age out of the
    # lookback window and be dropped (GATE 1 audit, 20 Oct 2026).
    recent = {r["id"] for r in raw_rows}
    older = [i for i in orders_store.pending_ids_any_age(conn) if i not in recent]
    raw_rows += run_mod.select_by_ids(conn, older)
    summary = run_mod.process_pending(
        conn, raw_rows, fetcher=fetcher, client=client, work_dir=work_dir,
        limit=limit, stop_when=stop_when,
    )
    for touched in sorted(summary.dates_touched):
        report.write(conn, touched, reports_dir=report.LIVE_REPORTS_DIR)
    return summary


def run_follow() -> int:
    """`--follow`: a long-running worker, one cycle per interval, until stopped."""
    cfg = documents_config()["orders"]
    interval = float(cfg["follow_interval_seconds"])
    jitter = tuple(float(x) for x in cfg["follow_jitter_seconds"])
    lookback_days = float(cfg["follow_lookback_days"])
    work_dir = _work_dir()

    while not _stopping:
        try:
            with connect() as conn:
                client = LlmClient(conn=conn)
                fetcher = PdfFetcher()
                while not _stopping:
                    summary = follow_cycle(conn, fetcher=fetcher, client=client,
                                           work_dir=work_dir, lookback_days=lookback_days)
                    if summary.considered:
                        log.info(
                            "cycle: considered=%d downloaded=%d order_related=%d "
                            "verified=%d needs_review=%d llm_calls=%d llm_cost=$%s%s",
                            summary.considered, summary.downloaded, summary.order_related,
                            summary.verified, summary.needs_review, summary.llm_calls,
                            summary.llm_cost_usd,
                            f"  STOPPED EARLY: {summary.stopped_early}"
                            if summary.stopped_early else "",
                        )
                        if summary.gate_violations:
                            log.error(
                                "GATE VIOLATION: LLM/OCR reached a non-order-related "
                                "filing: %s", summary.gate_violations,
                            )
                    if _stopping:
                        return 0
                    time.sleep(jittered(interval, jitter))
        except Exception:
            if _stopping:
                return 0
            log.exception("orders --follow loop failed; reconnecting in 60s")
            time.sleep(60)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Not an argparse mutually-exclusive group: exactly one of --date, --from/--to (a
    # pair) or --follow is required, and argparse's own required-group mechanism cannot
    # express "one of these three, where one is actually two flags together" - it can
    # only require one specific argument, which is what silently broke --from/--to as a
    # standalone mode the first time it was used for real (WORKLOG, 25 Sep 2026). The
    # three-way check below is explicit instead.
    parser = argparse.ArgumentParser(prog="python -m reg30_radar.orders")
    parser.add_argument("--date", type=date.fromisoformat,
                         help="process one day already in raw_announcements (YYYY-MM-DD)")
    parser.add_argument("--follow", action="store_true",
                         help="run continuously, processing new filings as the collector saves them")
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat,
                         help="range start (YYYY-MM-DD), with --to; an alternative to --date")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat,
                         help="range end, inclusive (YYYY-MM-DD)")
    parser.add_argument("--max-requests", type=int, default=200,
                         help="refuse to start a batch run needing more downloads than this")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    if args.follow:
        if args.date or args.date_from or args.date_to:
            parser.error("--follow cannot be combined with --date/--from/--to")
        return run_follow()

    if bool(args.date_from) != bool(args.date_to):
        parser.error("--from and --to must be given together")
    if args.date and (args.date_from or args.date_to):
        parser.error("--date cannot be combined with --from/--to")
    if not args.date and not args.date_from:
        parser.error("one of --date, --from/--to, or --follow is required")

    since = args.date_from or args.date
    until = args.date_to or args.date
    return run_batch(since=since, until=until, max_requests=args.max_requests)


if __name__ == "__main__":
    from reg30_radar.common import nse_guard
    sys.exit(nse_guard.run(main))
