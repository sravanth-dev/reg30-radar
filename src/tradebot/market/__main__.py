"""Load NSE's daily archives into the backfill database (ARCHITECTURE §5.2, §5.9, D10, D27).

    python -m tradebot.market --from 2025-08-01 --to 2026-09-26

Per calendar day: the UDiFF bhavcopy first. A clean 404 means no trading that day (D27's
past-date calendar), and nothing more is fetched for it. A 200 means a trading day, so the
PR bundle follows (Nifty 50, CORP_IND, market caps, band hitters, the announcement report).
Weekends are tried too, because a Muhurat or other special session can fall on one and
leaves a bhavcopy behind (D27); that costs one request per weekend day.

Resumable: days already settled in `archive_days` are skipped, and a day that ended in an
error rather than an answer is retried on the next run. Runs on the laptop over the phone
hotspot, never the campus network (D19). Writes only to BACKFILL_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from tradebot.common.config import nse as nse_config
from tradebot.common.db import backfill_url, connect
from tradebot.common.logs import configure as configure_logging
from tradebot.market import parse, store
from tradebot.market.fetch import ArchiveFetcher

log = logging.getLogger("market")

# Two 401/403 answers in a row mean the session itself has gone bad; stop rather than
# keep asking (same breaker as orders/run.py).
STOP_AFTER_AUTH_FAILURES = 2


def udiff_url(cfg: dict, day: date) -> str:
    return cfg["archives"]["udiff_cm"].format(yyyymmdd=day.strftime("%Y%m%d"))


def pr_url(cfg: dict, day: date) -> str:
    # Two-digit year in the URL, four digits inside the zip (Spike B).
    return cfg["archives"]["pr_bundle"].format(ddmmyy=day.strftime("%d%m%y"))


def load_day(conn, fetcher, cfg: dict, day: date) -> str:
    """Fetch and store one day. Returns a one-line outcome for the log."""
    udiff = fetcher.get(udiff_url(cfg, day))
    if udiff.status == 404:
        store.mark_day(conn, day, udiff_status=404, pr_status=None, trading_day=False)
        return "no trading"
    if not udiff.ok:
        store.mark_day(conn, day, udiff_status=udiff.status, pr_status=None,
                       trading_day=None, note=udiff.error)
        return f"error (bhavcopy): {udiff.error}"

    try:
        prices = parse.parse_udiff(parse.udiff_csv_from_zip(udiff.content))
    except Exception as exc:
        store.mark_day(conn, day, udiff_status=200, pr_status=None, trading_day=None,
                       note=f"bhavcopy unreadable: {exc}")
        return f"error (bhavcopy unreadable): {exc}"
    wrong_dates = {p.trade_date for p in prices} - {day}
    if wrong_dates:
        store.mark_day(conn, day, udiff_status=200, pr_status=None, trading_day=None,
                       note=f"bhavcopy dated {sorted(wrong_dates)}")
        return f"error: bhavcopy is dated {sorted(wrong_dates)}"

    bundle = fetcher.get(pr_url(cfg, day))
    members: dict[str, str] = {}
    note = None
    if bundle.ok:
        try:
            members = parse.pr_members(bundle.content, cfg["archives"]["pr_members"])
        except Exception as exc:
            note = f"PR bundle unreadable: {exc}"
    else:
        note = f"PR bundle: {bundle.error}"

    indices, actions = parse.parse_pd(members["price_data"]) if "price_data" in members else ([], [])
    counts = store.save_day(
        conn, day, prices=prices, indices=indices, actions=actions,
        caps=parse.parse_mcap(members["market_cap"]) if "market_cap" in members else None,
        hits=parse.parse_bh(members["band_hitters"]) if "band_hitters" in members else None,
        entries=parse.parse_an(members["announcements"]) if "announcements" in members else None,
    )
    missing = [k for k in cfg["archives"]["pr_members"] if k not in members]
    if bundle.ok and missing:
        # Noted, not retried: a member absent from the published zip will not appear later.
        note = f"PR bundle missing members: {missing}"
    # A trading day whose bundle could not be fetched stays retryable: decided_days()
    # treats only pr_status 200 as settled.
    store.mark_day(conn, day, udiff_status=200, pr_status=bundle.status, trading_day=True,
                   note=note)
    return (f"trading: {counts.prices} prices, {counts.market_caps} caps "
            f"({counts.unmapped_market_caps} unmapped), {counts.index_closes} indices, "
            f"{counts.corp_actions} corp actions, {counts.band_hits} band hits, "
            f"{counts.announcements} announcements" + (f" [{note}]" if note else ""))


def run(date_from: date, date_to: date, max_requests: int) -> int:
    cfg = nse_config()
    fetcher = ArchiveFetcher()
    auth_failures = 0
    with connect(backfill_url()) as conn:
        done = store.decided_days(conn, date_from, date_to)
        days = [date_from + timedelta(n) for n in range((date_to - date_from).days + 1)]
        todo = [d for d in days if d not in done]
        log.info("%d days in range, %d already settled, %d to load", len(days),
                 len(days) - len(todo), len(todo))
        for day in todo:
            # Each day costs at most two requests (plus a warm-up); stop before, not after.
            if fetcher.requests + 3 > max_requests:
                log.warning("stopping: %d requests used of --max-requests %d",
                            fetcher.requests, max_requests)
                break
            outcome = load_day(conn, fetcher, cfg, day)
            log.info("%s %s", day.isoformat(), outcome)
            if "HTTP 401" in outcome or "HTTP 403" in outcome:
                auth_failures += 1
                if auth_failures >= STOP_AFTER_AUTH_FAILURES:
                    log.error("stopping: %d consecutive 401/403 answers", auth_failures)
                    break
            else:
                auth_failures = 0
    log.info("requests sent (warm-ups included): %d", fetcher.requests)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tradebot.market")
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--max-requests", type=int, default=1000,
                        help="stop before sending more than this many requests")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return run(args.date_from, args.date_to, args.max_requests)


if __name__ == "__main__":
    from tradebot.common import nse_guard
    sys.exit(nse_guard.run(main))
