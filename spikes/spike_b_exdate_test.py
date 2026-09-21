"""Spike B, step 3 retry: is PrvsClsgPric actually corporate-action adjusted?

The 16/17 Jul 2026 pair showed zero adjustments, but that day had no corporate action,
so it proved nothing either way. 6 Aug 2025 does: the PR bundle for that day flags
16 ex-dividends (COALINDIA among them) and one ex-rights (DAVANGERE).

This costs one request: the 5 Aug 2025 UDiFF. The 6 Aug UDiFF and PR bundle are already
on disk from the live run.

Why it matters: Sect.5.9 plans to chain every event-study return through PrvsClsgPric so
splits and bonuses do not read as huge fake losses. If NSE does not actually adjust that
field, the whole approach has to change before Slice 7 is built on it.
"""

from __future__ import annotations

import io
import random
import sys
import time
import zipfile
from decimal import Decimal
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "out"
ARCHIVES = "https://nsearchives.nseindia.com"
BASE = "https://www.nseindia.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REMAINING_BUDGET = 2
used = 0


def udiff_rows(body: bytes) -> dict[tuple[str, str], dict]:
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        raw = zf.read(name)
    lines = raw.decode("utf-8", errors="replace").splitlines()
    header = [c.strip() for c in lines[0].split(",")]
    idx = {c: i for i, c in enumerate(header)}
    rows = {}
    for line in lines[1:]:
        p = line.split(",")
        if len(p) < len(header):
            continue
        rows[(p[idx["TckrSymb"]].strip(), p[idx["SctySrs"]].strip())] = {
            "close": p[idx["ClsPric"]].strip(),
            "prev": p[idx["PrvsClsgPric"]].strip(),
            "open": p[idx["OpnPric"]].strip(),
        }
    return rows


target = OUT / "udiff_20250805.zip"
if not target.exists():
    session = requests.Session()
    session.headers.update(HEADERS)
    print("  warm-up cookies are already spent; reusing a fresh session")
    time.sleep(3 + random.uniform(0.4, 1.6))
    url = f"{ARCHIVES}/content/cm/BhavCopy_NSE_CM_0_0_0_20250805_F_0000.csv.zip"
    resp = session.get(url, headers={"Referer": BASE + "/all-reports"}, timeout=40)
    used += 1
    print(f"  [{used}/{REMAINING_BUDGET}] {resp.status_code} {len(resp.content):,}b  {url}")
    if resp.status_code in (401, 403):
        print("STOP: auth/forbidden. Not retrying.")
        sys.exit(2)
    if resp.content[:2] != b"PK":
        print("  not a zip; 5 Aug 2025 may be a holiday")
        sys.exit(1)
    target.write_bytes(resp.content)

prior = udiff_rows(target.read_bytes())
ex = udiff_rows((OUT / "udiff_20250806.zip").read_bytes())
print(f"\n  rows: 2025-08-05={len(prior):,}  2025-08-06={len(ex):,}")

# The names the PR bundle flagged for 6 Aug 2025.
with zipfile.ZipFile(OUT / "pr_20250806.zip") as zf:
    pd_raw = zf.read(next(n for n in zf.namelist() if n.lower().startswith("pd")))
lines = pd_raw.decode("utf-8", errors="replace").splitlines()
head = [c.strip() for c in lines[0].split(",")]
si, ri, ci = head.index("SYMBOL"), head.index("SERIES"), head.index("CORP_IND")
flagged = []
for line in lines[1:]:
    p = line.split(",")
    if len(p) > ci and p[ci].strip():
        flagged.append((p[si].strip(), p[ri].strip(), p[ci].strip()))

print(f"  PR bundle flags {len(flagged)} corporate actions on 2025-08-06\n")
print(f"  {'SYMBOL':<14} {'SER':<4} {'IND':<4} {'prior_close':>12} {'stated_prev':>12} "
      f"{'ex_open':>10} {'ex_close':>10} {'adjusted?':>10}")

adjusted_count = 0
for sym, ser, ind in flagged:
    p, e = prior.get((sym, ser)), ex.get((sym, ser))
    if not p or not e:
        continue
    try:
        pc, sp = Decimal(p["close"]), Decimal(e["prev"])
    except Exception:
        continue
    is_adj = sp != pc
    adjusted_count += is_adj
    print(f"  {sym:<14} {ser:<4} {ind:<4} {pc:>12} {sp:>12} {e['open']:>10} "
          f"{e['close']:>10} {'YES' if is_adj else 'no':>10}")

print(f"\n  adjusted: {adjusted_count} of {len(flagged)} flagged names")

# And the whole-file view: does PrvsClsgPric ever differ from the prior close?
total_diff = 0
for key, e in ex.items():
    p = prior.get(key)
    if not p:
        continue
    try:
        if Decimal(e["prev"]) != Decimal(p["close"]):
            total_diff += 1
    except Exception:
        continue
print(f"  across the whole file, PrvsClsgPric differs from the prior close for "
      f"{total_diff} of {len(ex):,} symbols")
