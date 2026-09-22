"""Spike A2: can the announcements API be made to return a whole past day?

The offline half already killed the hopeful hypothesis: the gap is inside the study
universe, not outside it. 700 of 976 operating-company bodies are missing for 18 Sep 2026,
462 of 680 companies wholly absent, and only 2 of the 23 order filings are present.

So this asks the remaining question: is there a parameter that reaches the full day, and is
the API at least complete for the *current* day (which decides whether D23's forward
collection can start now).

Budget is 14 requests, held in a file on disk and shared by every script in this spike, so
warm-ups cannot be forgotten the way they were in Spike A.
"""

from __future__ import annotations

import json
import random
import sys
import time
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"
OUT.mkdir(parents=True, exist_ok=True)
LEDGER = OUT / "a2_budget.json"
CFG = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["nse"]

BUDGET = 14
MIN_GAP = CFG["pacing"]["backfill_min_gap_seconds"]
JIT_LO, JIT_HI = CFG["pacing"]["jitter_seconds"]

API = CFG["announcements"]["url"]
session = requests.Session()
session.headers.update({k: str(v) for k, v in CFG["headers"].items()})
_last = 0.0


def spent() -> int:
    return json.loads(LEDGER.read_text())["used"] if LEDGER.exists() else 0


def charge(url: str, status: int) -> int:
    log = json.loads(LEDGER.read_text()) if LEDGER.exists() else {"used": 0, "calls": []}
    log["used"] += 1
    log["calls"].append({"n": log["used"], "status": status, "url": url})
    LEDGER.write_text(json.dumps(log, indent=1))
    return log["used"]


def get(url: str, params: dict | None = None, label: str = "") -> requests.Response:
    global _last
    if spent() >= BUDGET:
        raise RuntimeError(f"budget exhausted at {BUDGET}; refusing: {label or url}")
    wait = MIN_GAP + random.uniform(JIT_LO, JIT_HI) - (time.monotonic() - _last)
    if _last and wait > 0:
        time.sleep(wait)
    r = session.get(url, params=params, timeout=60)
    _last = time.monotonic()
    n = charge(r.url, r.status_code)
    print(f"  [{n:>2}/{BUDGET}] {r.status_code} {len(r.content):>9,}b  {r.url[:118]}")
    if r.status_code in (401, 403):
        print("\nSTOP: auth/forbidden. Not retrying.")
        sys.exit(2)
    return r


def rows(r: requests.Response):
    try:
        j = r.json()
    except Exception:
        return None
    return j if isinstance(j, list) else j.get("data") if isinstance(j, dict) else None


BASE = {"index": "equities"}
D18 = {"from_date": "18-09-2026", "to_date": "18-09-2026"}

print("=" * 92)
print("WARM-UP")
print("=" * 92)
get(CFG["warmup_url"], label="warm-up")
print(f"  cookies: {sorted(session.cookies.keys())}")

# ---------------------------------------------------------------------------------------
print()
print("=" * 92)
print("1. CAN ANY PARAMETER REACH THE WHOLE DAY? (baseline for 18 Sep was 563 of ~1,229)")
print("=" * 92)

# The record carries a null `csvName`, which implies the page offers a CSV export. That is
# the most likely route to an unpaginated full day, so it goes first.
probes = [
    ("csv=true", {**BASE, **D18, "csv": "true"}),
    ("pagination: page=2", {**BASE, **D18, "page": "2"}),
    ("no index filter", {**D18}),
]
for label, params in probes:
    print(f"\n-- {label} --")
    r = get(API, params, label)
    body = rows(r)
    if body is None:
        head = r.content[:160].decode("utf-8", "replace").replace("\n", " ")
        print(f"   non-JSON ({r.headers.get('content-type','?')}): {head!r}")
        if "csv" in r.headers.get("content-type", "").lower() or r.content[:1] not in (b"[", b"{"):
            lines = r.content.decode("utf-8", "replace").splitlines()
            print(f"   >>> {len(lines)-1} data lines. header: {lines[0][:150] if lines else '(empty)'}")
            (OUT / "a2_csv_probe.csv").write_bytes(r.content)
    else:
        print(f"   records: {len(body)}   distinct symbols: {len({x.get('symbol') for x in body})}")

# ---------------------------------------------------------------------------------------
print()
print("=" * 92)
print("2. IS THE API COMPLETE FOR A RECENT DAY? (decides whether D23 can start now)")
print("=" * 92)

RECENT = date(2026, 9, 21)  # Monday
print(f"\n-- PR bundle for {RECENT:%d %b %Y}, as ground truth --")
r = get(f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{RECENT:%d%m%y}.zip",
        label="pr recent")
bundle_n = None
if r.content[:2] == b"PK":
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        an = next((n for n in zf.namelist() if n.lower().startswith("an")), None)
        if an:
            body = zf.read(an).decode("utf-8", "replace").splitlines()
            bundle_n = len([l for l in body[1:] if l.strip()])
            (OUT / f"an_{RECENT:%d%m%Y}.txt").write_bytes(zf.read(an))
            print(f"   bundle announcement lines: {bundle_n}")
else:
    print(f"   no bundle ({r.status_code}) - holiday, or not published yet")

print(f"\n-- API date query for {RECENT:%d %b %Y} --")
r = get(API, {**BASE, "from_date": f"{RECENT:%d-%m-%Y}", "to_date": f"{RECENT:%d-%m-%Y}"}, "api recent")
body = rows(r) or []
print(f"   API records: {len(body)}   distinct symbols: {len({x.get('symbol') for x in body})}")
if bundle_n:
    print(f"   >>> API covers {len(body)/bundle_n:.0%} of the bundle for that day")
if body:
    (OUT / f"api_{RECENT:%d%m%Y}.json").write_text(json.dumps(body), encoding="utf-8")

print("\n-- API with no date parameters (what the live page shows) --")
r = get(API, BASE, "api today")
body = rows(r) or []
print(f"   records: {len(body)}")
if body:
    ts = sorted(x.get("an_dt", "") for x in body)
    print(f"   oldest: {ts[0]}   newest: {ts[-1]}")
    (OUT / "a2_live_now.json").write_text(json.dumps(body), encoding="utf-8")

print(f"\n--- budget: {spent()}/{BUDGET} used ---")
