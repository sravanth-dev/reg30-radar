"""Assemble the candidate label set: download the PDFs, then classify without disclosing.

Sravanth labels ten of these blind, so this script must never print an extracted value.
It prints the filename and the reason the file was picked, nothing else. The classifier
below deliberately returns booleans and categories, never numbers lifted from the text.

PDFs land directly in tests/labelled/, which is the one place D8's delete-after-extraction
rule does not apply.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"
DEST = ROOT / "tests" / "labelled"
CFG = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["nse"]
LEDGER = OUT / "labelset_budget.json"
BUDGET = 20

# One per company, chosen for spread across the D22 market-cap bands and across the
# extraction edge cases. Reasons are written for Sravanth and carry no values.
WANTED = [
    "BEL", "WAAREEENER", "BEML", "RAILTEL", "NEWGEN", "DBL", "GKENERGY", "ZAGGLE",
    "GPTINFRA", "MCLOUD", "CEINSYS", "GREENPOWER", "VIVIANA", "HEG", "CPL",
    "HILINFRA", "HECPROJECT", "AFFORDABLE", "JISLDVREQS",
]

ORDER = re.compile(
    r"bagging|receiving of order|awarding of order|work order|purchase order|"
    r"letter of (award|intent)|\bLo[AI]\b|\bL1\b|lowest bidder|contract", re.I)


def spent() -> int:
    return json.loads(LEDGER.read_text())["used"] if LEDGER.exists() else 0


def charge(url: str, status: int) -> int:
    log = json.loads(LEDGER.read_text()) if LEDGER.exists() else {"used": 0, "calls": []}
    log["used"] += 1
    log["calls"].append({"n": log["used"], "status": status, "url": url})
    LEDGER.write_text(json.dumps(log, indent=1))
    return log["used"]


def load_records() -> dict:
    recs = {}
    for f in OUT.glob("*.json"):
        if f.name.endswith("budget.json"):
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = j if isinstance(j, list) else j.get("data", [])
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and str(r.get("attchmntFile", "")).lower().endswith(".pdf"):
                    recs[r["attchmntFile"]] = r
    return recs


recs = load_records()
cands = [r for r in recs.values()
         if ORDER.search(r.get("desc", "") + " " + str(r.get("attchmntText", "")))]
by_sym: dict[str, list] = {}
for r in cands:
    by_sym.setdefault(r["symbol"], []).append(r)

picked = []
for sym in WANTED:
    if sym in by_sym:
        picked.append(max(by_sym[sym], key=lambda r: r.get("an_dt", "")))
print(f"selected {len(picked)} candidates from {len(cands)} order-shaped records on disk\n")

DEST.mkdir(parents=True, exist_ok=True)
session = requests.Session()
session.headers.update({k: str(v) for k, v in CFG["headers"].items()})
session.get(CFG["warmup_url"], timeout=60)
charge("warm-up", 200)
_last = time.monotonic()

manifest = []
for r in picked:
    if spent() >= BUDGET:
        print("budget exhausted")
        break
    dt = r.get("an_dt", "")[:11].replace("-", "")
    try:
        from datetime import datetime
        stamp = datetime.strptime(r["an_dt"][:11], "%d-%b-%Y").strftime("%Y%m%d")
    except Exception:
        stamp = "unknown"
    name = f"{r['symbol']}_{stamp}_1.pdf"
    wait = CFG["pacing"]["backfill_min_gap_seconds"] + random.uniform(*CFG["pacing"]["jitter_seconds"])
    time.sleep(max(0, wait - (time.monotonic() - _last)))
    resp = session.get(r["attchmntFile"], timeout=90)
    _last = time.monotonic()
    n = charge(r["attchmntFile"], resp.status_code)
    ok = resp.status_code == 200 and resp.content[:4] == b"%PDF"
    print(f"  [{n:>2}/{BUDGET}] {resp.status_code} {len(resp.content):>8,}b  {name}"
          f"{'' if ok else '   <-- not a PDF, skipped'}")
    if resp.status_code in (401, 403):
        print("STOP: forbidden")
        sys.exit(2)
    if ok:
        (DEST / name).write_bytes(resp.content)
        manifest.append({
            "file": name,
            "symbol": r["symbol"],
            "isin": r.get("sm_isin"),
            "filing_datetime": r.get("an_dt"),
            "category_raw": r.get("desc"),
            "pdf_url": r["attchmntFile"],
        })

(OUT / "labelset_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
print(f"\nsaved {len(manifest)} PDFs to tests/labelled/ ; manifest in spikes/out/")
