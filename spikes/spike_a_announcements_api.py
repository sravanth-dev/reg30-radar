"""Spike A: the NSE corporate-announcements API, for targeted lookups only.

Throwaway probe (CLAUDE.md: spikes/ only). Answers:

1. Field names and one full sample record from today's list.
2. Can it be filtered by symbol and by date? Pull 18 Sep 2026 for BEL, HILINFRA, MASON
   and show each filing's ID, timestamp (with time of day?), category and attachment URL.
3. Is the ID stable? Is there an ISIN field? An industry/sector field? Any revision or
   "modified" field?
4. How far back do date queries reach (test ~13 months)?

Budget: 12 requests, >=3 s apart with jitter, warm-up first, hard stop on 401/403.
Endpoints and headers come from config/sources.yaml, never from this file (CLAUDE.md).
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "out"
CFG = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["nse"]

MAX_REQUESTS = 12
MIN_GAP = CFG["pacing"]["backfill_min_gap_seconds"]
JIT_LO, JIT_HI = CFG["pacing"]["jitter_seconds"]

used = 0
last = 0.0
log: list[tuple[int, int, str]] = []
session = requests.Session()
session.headers.update({k: str(v) for k, v in CFG["headers"].items()})


def get(url: str, params: dict | None = None, label: str = "") -> requests.Response:
    global used, last
    if used >= MAX_REQUESTS:
        raise RuntimeError(f"budget exhausted at {MAX_REQUESTS}; refusing: {label or url}")
    gap = time.monotonic() - last
    wait = MIN_GAP + random.uniform(JIT_LO, JIT_HI) - gap
    if last and wait > 0:
        time.sleep(wait)
    resp = session.get(url, params=params, timeout=40)
    used += 1
    last = time.monotonic()
    log.append((used, resp.status_code, resp.url))
    print(f"  [{used:>2}/{MAX_REQUESTS}] {resp.status_code} {len(resp.content):>8,}b  {resp.url}")
    if resp.status_code in (401, 403):
        print("\nSTOP: NSE returned an auth/forbidden status. Not retrying.")
        summary()
        sys.exit(2)
    return resp


def summary() -> None:
    print(f"\n--- requests used: {used}/{MAX_REQUESTS} ---")
    for n, st, u in log:
        print(f"  {n:>2}. {st}  {u}")


def as_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        print(f"     -> not JSON; first 200 bytes: {resp.content[:200]!r}")
        return None


def records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "records"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


API = CFG["announcements"]["url"]
BASE_PARAMS = dict(CFG["announcements"]["params"])

print("=" * 90)
print("WARM-UP")
print("=" * 90)
get(CFG["warmup_url"], label="warm-up")
print(f"  cookies: {sorted(session.cookies.keys())}")

# --------------------------------------------------------------------------- 1. today
print()
print("=" * 90)
print("1. TODAY'S LIST: field names and one full record")
print("=" * 90)
today = as_json(get(API, BASE_PARAMS, "today"))
rows = records(today)
print(f"  container type: {type(today).__name__}; records: {len(rows)}")
if isinstance(today, dict):
    print(f"  top-level keys: {list(today.keys())}")
if rows:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spike_a_today.json").write_text(json.dumps(today, indent=2)[:400000], encoding="utf-8")
    keys = sorted({k for r in rows[:200] for k in r})
    print(f"\n  {len(keys)} field names across the first 200 records:")
    for k in keys:
        filled = sum(1 for r in rows[:200] if str(r.get(k, "")).strip())
        print(f"    {k:<28} filled in {filled:>3}/{min(200, len(rows))}")
    print("\n  --- one full sample record ---")
    print(json.dumps(rows[0], indent=4, ensure_ascii=False)[:2500])

# --------------------------------------------------------- 2. symbol and date filtering
print()
print("=" * 90)
print("2. FILTERING by symbol and by date (18 Sep 2026)")
print("=" * 90)

DATE = "18-09-2026"
attempts = [
    ("symbol only", {**BASE_PARAMS, "symbol": "BEL"}),
    ("date range only", {**BASE_PARAMS, "from_date": DATE, "to_date": DATE}),
    ("symbol + date range", {**BASE_PARAMS, "symbol": "BEL", "from_date": DATE, "to_date": DATE}),
]
working = None
for label, params in attempts:
    print(f"\n-- {label} --")
    payload = as_json(get(API, params, label))
    rs = records(payload)
    print(f"   records: {len(rs)}")
    if rs:
        syms = {str(r.get("symbol", "")) for r in rs}
        print(f"   symbols present: {sorted(syms)[:8]}{' ...' if len(syms) > 8 else ''}")
        if label == "symbol + date range" and len(rs) < 50:
            working = params


def show(sym: str, payload) -> list[dict]:
    rs = records(payload)
    print(f"   {sym}: {len(rs)} filing(s)")
    for r in rs:
        ident = r.get("seqId") or r.get("seq_id") or r.get("id") or r.get("sr_no") or "-"
        ts = r.get("an_dt") or r.get("sort_date") or r.get("exchdisstime") or r.get("dt") or "-"
        cat = (r.get("desc") or r.get("subject") or r.get("category") or "-")[:52]
        att = r.get("attchmntFile") or r.get("attachmentFile") or r.get("attchmntText") or "-"
        print(f"     id={ident}  ts={ts}")
        print(f"       cat={cat}")
        print(f"       att={str(att)[:110]}")
    return rs


collected: dict[str, list[dict]] = {}
for sym in ("BEL", "HILINFRA", "MASON"):
    print(f"\n-- {sym} on {DATE} --")
    params = {**BASE_PARAMS, "symbol": sym, "from_date": DATE, "to_date": DATE}
    collected[sym] = show(sym, as_json(get(API, params, f"{sym} {DATE}")))

# ----------------------------------------------------------------- 3. field questions
print()
print("=" * 90)
print("3. ID stability, ISIN, industry, revision fields")
print("=" * 90)
pool = [r for rs in collected.values() for r in rs] or rows
if pool:
    keys = sorted({k for r in pool for k in r})
    print(f"  fields seen: {keys}")
    for want, names in {
        "ISIN": ("isin", "isinNumber", "isin_number"),
        "industry/sector": ("industry", "sector", "indus", "macro", "sectorName"),
        "revision/modified": ("modified", "modifiedDate", "revision", "updated", "rev"),
        "identifier": ("seqId", "seq_id", "id", "sr_no", "csvId"),
    }.items():
        found = [k for k in keys if k.lower() in {n.lower() for n in names}]
        print(f"  {want:<18} {found if found else 'NOT PRESENT under the expected names'}")
    mason = collected.get("MASON", [])
    if len(mason) > 1:
        ids = [r.get("seqId") or r.get("id") or r.get("sr_no") for r in mason]
        print(f"\n  MASON filed {len(mason)} times that day; ids: {ids}")
        print(f"  ids unique: {len(set(map(str, ids))) == len(ids)}")

# --------------------------------------------------------------- 4. how far back?
print()
print("=" * 90)
print("4. DATE REACH: about 13 months back (19-08-2025)")
print("=" * 90)
OLD = "19-08-2025"
old = as_json(get(API, {**BASE_PARAMS, "symbol": "BEL", "from_date": OLD, "to_date": OLD}, "13mo"))
old_rows = records(old)
print(f"  records for BEL on {OLD}: {len(old_rows)}")
for r in old_rows[:4]:
    print(f"    {r.get('an_dt') or r.get('sort_date') or '-'}  "
          f"{(r.get('desc') or r.get('subject') or '-')[:60]}")

summary()
