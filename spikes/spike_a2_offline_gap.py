"""Spike A2, offline half: is the API's gap inside the study universe or outside it?

Sravanth's framing, and it is the right one: Spike A compared 563 API records against all
1,229 bundle bodies, but the study only cares about NSE mainboard. If the 666 missing are
mostly SME and debt, the backfill may survive as specified.

Costs nothing: everything is already on disk.
  tests/fixtures/an18092026.txt   the complete record of what was filed
  spikes/out/spike_a_18sep.json   the API's 563 records for the same day
  spikes/out/udiff_20260918.zip   symbol -> series, to segment them
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"

ORDER_WIN = "Bagging/Receiving of orders/contracts"
ORDER_CAND = "Awarding of order(s)/contract(s)"

# D9: mainboard is anything that is not the SME platform. Debt and the rest are not equity
# announcements we would ever act on, so they are split out to see where the gap really is.
SME_SERIES = {"SM", "ST", "SZ"}
MAINBOARD_SERIES = {"EQ", "BE", "BZ", "BT", "IL"}


def series_by_symbol() -> dict[str, set[str]]:
    with zipfile.ZipFile(OUT / "udiff_20260918.zip") as zf:
        raw = zf.read(next(n for n in zf.namelist() if n.lower().endswith(".csv")))
    lines = raw.decode("utf-8", "replace").splitlines()
    head = [c.strip() for c in lines[0].split(",")]
    si, ri = head.index("TckrSymb"), head.index("SctySrs")
    out: dict[str, set[str]] = defaultdict(set)
    for ln in lines[1:]:
        p = ln.split(",")
        if len(p) > max(si, ri):
            out[p[si].strip()].add(p[ri].strip())
    return out


def segment(symbol: str, smap: dict[str, set[str]]) -> str:
    ser = smap.get(symbol)
    if not ser:
        return "not in bhavcopy"
    if ser & MAINBOARD_SERIES:
        return "mainboard"
    if ser & SME_SERIES:
        return "SME"
    return "debt/other"


def bundle_rows() -> list[tuple[str, str]]:
    """(symbol, body) for every line of the announcements file."""
    txt = (ROOT / "tests" / "fixtures" / "an18092026.txt").read_text(encoding="utf-8", errors="replace")
    rows = []
    for ln in txt.splitlines()[1:]:
        if not ln.strip():
            continue
        m = re.match(r"^(.*?)\s+([A-Z0-9&\-]+)\s*:\s*(.*)$", ln)
        if m:
            rows.append((m.group(2), m.group(3)))
    return rows


smap = series_by_symbol()
bundle = bundle_rows()
api = json.loads((OUT / "spike_a_18sep.json").read_text(encoding="utf-8"))

print("=" * 90)
print("A. THE HEADLINE: do the 22+1 order filings appear in the API's 563?")
print("=" * 90)

bundle_orders = [(s, b) for s, b in bundle if b.startswith(ORDER_WIN) or b.startswith(ORDER_CAND)]
api_orders = [r for r in api if r["desc"].startswith(ORDER_WIN) or r["desc"].startswith(ORDER_CAND)]
api_order_syms = Counter(r["symbol"] for r in api_orders)
bundle_order_syms = Counter(s for s, _ in bundle_orders)

print(f"  bundle order filings: {len(bundle_orders)}  from {len(bundle_order_syms)} companies")
print(f"  API    order filings: {len(api_orders)}  from {len(api_order_syms)} companies")
print()
print(f"  {'SYMBOL':<14}{'SEGMENT':<16}{'bundle':>7}{'API':>5}   status")
present = absent = 0
for sym, n in sorted(bundle_order_syms.items(), key=lambda kv: (-kv[1], kv[0])):
    got = api_order_syms.get(sym, 0)
    seg = segment(sym, smap)
    status = "present" if got else "MISSING FROM API"
    present += got
    absent += n if not got else 0
    print(f"  {sym:<14}{seg:<16}{n:>7}{got:>5}   {status}")
print(f"\n  order filings the API carries: {present} of {len(bundle_orders)}")
print(f"  order filings with no API record at all: {absent}")

print()
print("=" * 90)
print("B. THE GAP BY SEGMENT: where do the missing bodies actually live?")
print("=" * 90)

# Reconcile per (symbol, category-prefix). The bundle has no ids, so symbol is the unit.
api_by_sym = Counter(r["symbol"] for r in api)
bundle_by_sym = Counter(s for s, _ in bundle)

seg_tot = Counter()
seg_missing = Counter()
seg_syms_missing = defaultdict(set)
for sym, n in bundle_by_sym.items():
    seg = segment(sym, smap)
    seg_tot[seg] += n
    miss = max(0, n - api_by_sym.get(sym, 0))
    if miss:
        seg_missing[seg] += miss
        seg_syms_missing[seg].add(sym)

print(f"  {'SEGMENT':<18}{'bundle':>9}{'missing':>9}{'% missing':>11}   companies affected")
for seg in ("mainboard", "SME", "debt/other", "not in bhavcopy"):
    t, m = seg_tot.get(seg, 0), seg_missing.get(seg, 0)
    if t:
        print(f"  {seg:<18}{t:>9}{m:>9}{m/t:>10.0%}   {len(seg_syms_missing[seg])}")
print(f"  {'TOTAL':<18}{sum(seg_tot.values()):>9}{sum(seg_missing.values()):>9}")

print()
print("=" * 90)
print("C. MAINBOARD ONLY: the number that decides whether the backfill survives")
print("=" * 90)
mb_bundle = [(s, b) for s, b in bundle if segment(s, smap) == "mainboard"]
mb_syms = {s for s, _ in mb_bundle}
mb_in_api = {s for s in mb_syms if api_by_sym.get(s)}
print(f"  mainboard bodies in the bundle:        {len(mb_bundle):>6}")
print(f"  mainboard companies in the bundle:     {len(mb_syms):>6}")
print(f"  of those, companies the API returns:   {len(mb_in_api):>6}  ({len(mb_in_api)/len(mb_syms):.0%})")
print(f"  mainboard companies wholly absent:     {len(mb_syms - mb_in_api):>6}")
missing_mb = sorted(mb_syms - mb_in_api)
print(f"\n  first 20 wholly-absent mainboard companies: {missing_mb[:20]}")
