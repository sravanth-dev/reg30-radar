"""One-day live-feed reconciliation (D23's precondition).

The question: does polling the no-date endpoint actually capture every filing, or does it
inherit whatever filter makes the date-range query incomplete? D23 commits to forward
collection, and forward-collected data cannot be re-fetched, so this has to be answered
before the collector is trusted rather than after.

Method: poll every ~60 s with jitter for the rest of today's window, keep every distinct
record, and tomorrow reconcile the union against today's PR bundle.

The endpoint returns only the 20 most recent records. So the poll also watches for the
failure that would matter: if a single poll ever returns 20 records that are ALL new, the
window overflowed between polls and filings were missed. That count is the headline result.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"
OUT.mkdir(parents=True, exist_ok=True)
CFG = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["nse"]

IST = ZoneInfo("Asia/Kolkata")
STOP_HOUR = 22          # D6's window closes at 22:00 IST
POLL_SECONDS = 60
RECORDS_PER_PAGE = 20   # what the endpoint returns; overflow above this means loss

SEEN = OUT / "live_feed_seen.jsonl"
STATS = OUT / "live_feed_stats.json"

session = requests.Session()
session.headers.update({k: str(v) for k, v in CFG["headers"].items()})


def warm_up() -> None:
    session.get(CFG["warmup_url"], timeout=60)


def key(rec: dict) -> str:
    # seq_id is null on older records (§5.1), so pair it with the timestamp.
    return f"{rec.get('seq_id')}|{rec.get('an_dt')}|{rec.get('symbol')}"


seen: set[str] = set()
if SEEN.exists():
    for line in SEEN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                seen.add(key(json.loads(line)))
            except Exception:
                pass

stats = {
    "started_ist": datetime.now(IST).isoformat(),
    "polls": 0, "errors": 0, "new_records": 0,
    "full_page_all_new": 0,      # the overflow signal
    "max_new_in_one_poll": 0,
    "resumed_with": len(seen),
}
print(f"start {stats['started_ist']}  already seen: {len(seen)}")

warm_up()
backoff = 0.0
fh = SEEN.open("a", encoding="utf-8")

while datetime.now(IST).hour < STOP_HOUR:
    try:
        r = session.get(CFG["announcements"]["url"],
                        params=CFG["announcements"]["params"], timeout=45)
        stats["polls"] += 1
        if r.status_code in (401, 403):
            stats["errors"] += 1
            backoff = min(600, max(60, backoff * 2 or 60))
            warm_up()
        elif r.status_code == 200:
            backoff = 0.0
            rows = r.json()
            rows = rows if isinstance(rows, list) else rows.get("data", [])
            fresh = [x for x in rows if key(x) not in seen]
            for x in fresh:
                seen.add(key(x))
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
            fh.flush()
            stats["new_records"] += len(fresh)
            stats["max_new_in_one_poll"] = max(stats["max_new_in_one_poll"], len(fresh))
            if (stats["polls"] > 1 and len(rows) >= RECORDS_PER_PAGE
                    and len(fresh) == len(rows)):
                # Every record on the page was new, so the page may have rolled over
                # between polls and we cannot prove nothing was lost.
                # The first poll is excluded: starting from an empty set, everything is
                # new by definition, and counting it would report a false overflow.
                stats["full_page_all_new"] += 1
        else:
            stats["errors"] += 1
            backoff = min(600, max(30, backoff * 2 or 30))
    except Exception:
        stats["errors"] += 1
        backoff = min(600, max(30, backoff * 2 or 30))

    stats["last_ist"] = datetime.now(IST).isoformat()
    stats["distinct_records"] = len(seen)
    STATS.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    time.sleep(backoff or (POLL_SECONDS + random.uniform(-8, 8)))

fh.close()
stats["finished_ist"] = datetime.now(IST).isoformat()
STATS.write_text(json.dumps(stats, indent=1), encoding="utf-8")
print(json.dumps(stats, indent=1))
