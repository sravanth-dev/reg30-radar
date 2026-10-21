"""Close the gap after live collection was down. `python -m reg30_radar.catchup [--from D] [--to D]`

One date-range request per calendar day, from the day of the last successful live poll
(or `--from`) to today (or `--to`). One request per day, never one for the whole range:
an unsplit range is one large answer with no way to see whether it was cut short, and a
day that fails is then retried on its own (the old `collector --catchup` sent the whole
range as one request; GATE 1 audit).

- Rows are stored with `collected_via = 'catchup'` and `first_seen_at` = now (migration
  0018). A catch-up time is honest but not a real-time observation, and the
  forward-collected sample (D23) can tell the two apart.
- Each request gets its own `source_health` row, so the catch-up is auditable later.
- A day's answer is flagged, never silently trusted, when it holds rows from other days
  or when its size is a round number of at least 1,000 (the shape of a page limit; none
  has been seen, but the endpoint's 20-row live page shows NSE does cut answers).
- Collection only. `python -m reg30_radar.live` then works through the downloaded backlog
  within its per-cycle budget. Run this first and live after, never both at once: the NSE
  lock refuses a second process.

The API gives a partial view of a past day, with the shortfall in SME, debt and funds
(Spike A2), so a caught-up day is less complete than a live one; mainboard order filings
came back 8 of 8 when this was measured.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta

from reg30_radar.collector import nse, store
from reg30_radar.collector.records import SOURCE, to_raw
from reg30_radar.common import calendar as cal
from reg30_radar.common.config import nse as nse_config
from reg30_radar.common.db import connect
from reg30_radar.common.logs import configure as configure_logging

log = logging.getLogger("catchup")

LAST_OK_SQL = "select max(checked_at) from source_health where source = %s and ok"
ROUND_SIZE = 500          # a day's count that is a multiple of this, at 1,000 or more,
SUSPECT_FROM = 1000       # is flagged as possibly cut at a page limit


def days_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def suspect(day: date, rows: list[dict]) -> list[str]:
    """Why one day's answer should not be trusted as whole (empty when nothing is odd)."""
    why = []
    other = sum(1 for r in rows if (r.get("an_dt") or "")[:11]
                and not _on_day(r["an_dt"], day))
    if other:
        why.append(f"{other} rows dated another day")
    if len(rows) >= SUSPECT_FROM and len(rows) % ROUND_SIZE == 0:
        why.append(f"{len(rows)} rows, a round number: possibly cut at a page limit")
    return why


def _on_day(an_dt: str, day: date) -> bool:
    try:
        return datetime.strptime(an_dt[:11], "%d-%b-%Y").date() == day
    except ValueError:
        return False


def run(first: date | None, last: date | None) -> int:
    pacing = nse_config()["pacing"]
    client = nse.NseClient()
    with connect() as conn:
        if first is None:
            last_ok = conn.execute(LAST_OK_SQL, (SOURCE,)).fetchone()[0]
            if last_ok is None:
                log.error("no successful live poll on record; give --from")
                return 1
            first = last_ok.astimezone(cal.IST).date()
        last = last or cal.now_ist().date()
        days = days_between(first, last)
        log.info("catching up %s to %s: %d days, one request each", first, last, len(days))
        totals = {"returned": 0, "new": 0, "failed_days": [], "suspect_days": []}
        for i, day in enumerate(days):
            if i:
                # The live gap is the floor (nse_guard); a catch-up keeps the slower
                # backfill pace, since it is history rather than the live page.
                time.sleep(nse.jittered(float(pacing["backfill_min_gap_seconds"]),
                                        pacing["jitter_seconds"]))
            checked_at = cal.now_ist()
            result = client.fetch_range(day, day)
            if not result.ok:
                store.record_poll(conn, source=SOURCE, checked_at=checked_at, ok=False,
                                  error=result.error, http_status=result.http_status,
                                  latency_ms=result.latency_ms)
                conn.commit()
                log.warning("%s: failed (%s); run again to retry this day", day, result.error)
                totals["failed_days"].append(day)
                continue
            outcome = store.insert_announcements(conn, [to_raw(r) for r in result.rows],
                                                 first_seen_at=checked_at,
                                                 collected_via="catchup")
            store.record_poll(conn, source=SOURCE, checked_at=checked_at, ok=True,
                              http_status=result.http_status, latency_ms=result.latency_ms,
                              records_returned=len(result.rows), new_records=outcome.inserted)
            conn.commit()
            why = suspect(day, result.rows)
            if why:
                totals["suspect_days"].append(day)
                log.warning("%s: answer flagged: %s", day, "; ".join(why))
            totals["returned"] += len(result.rows)
            totals["new"] += outcome.inserted
            log.info("%s: %d returned, %d new (%d revisions, %d already stored)", day,
                     len(result.rows), outcome.inserted, outcome.revisions, outcome.duplicates)
    log.info("catch-up done: %d returned, %d new; failed days %s; flagged days %s",
             totals["returned"], totals["new"], totals["failed_days"] or "none",
             totals["suspect_days"] or "none")
    return 1 if totals["failed_days"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reg30_radar.catchup")
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat,
                        help="first day (default: the day of the last successful live poll)")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat,
                        help="last day, inclusive (default: today)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return run(args.date_from, args.date_to)


if __name__ == "__main__":
    from reg30_radar.common import nse_guard
    sys.exit(nse_guard.run(main))
