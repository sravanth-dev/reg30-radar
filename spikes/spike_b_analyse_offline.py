"""Spike B, offline half: re-analyse what is already in spikes/out/. No network.

Two questions left over from the live run:
  - the 16/17 Jul 2026 pair showed no adjustment beyond 10%. Is there any adjustment at
    all in that pair, across every series and at any size?
  - do the three PR bundles already on disk flag a bonus (XB) or split (XS) in CORP_IND,
    so the last of the request budget can be aimed at a day that definitely has one?
"""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def udiff_rows(path: Path) -> dict[tuple[str, str], dict]:
    body = path.read_bytes()
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
        key = (p[idx["TckrSymb"]].strip(), p[idx["SctySrs"]].strip())
        rows[key] = {
            "isin": p[idx["ISIN"]].strip(),
            "close": p[idx["ClsPric"]].strip(),
            "prev": p[idx["PrvsClsgPric"]].strip(),
        }
    return rows


print("=" * 88)
print("A. 16 -> 17 Jul 2026: every series, any size of adjustment")
print("=" * 88)

prior = udiff_rows(OUT / "udiff_20260716.zip")
ex = udiff_rows(OUT / "udiff_20260717.zip")
print(f"  rows: prior={len(prior):,}  ex={len(ex):,}")

diffs = []
for key, e in ex.items():
    p = prior.get(key)
    if not p:
        continue
    try:
        pc, sp, ec = Decimal(p["close"]), Decimal(e["prev"]), Decimal(e["close"])
    except Exception:
        continue
    if pc <= 0 or sp <= 0:
        continue
    if sp != pc:
        diffs.append((sp / pc, key, pc, sp, ec))

diffs.sort()
print(f"  symbols where PrvsClsgPric != prior close: {len(diffs):,}")
print(f"\n  {'SYMBOL':<14} {'SER':<4} {'ratio':>8} {'prior_cl':>10} {'stated_prev':>12} "
      f"{'ex_close':>10} {'naive %':>9} {'chained %':>10}")
for ratio, (sym, ser), pc, sp, ec in diffs[:15]:
    naive = (ec / pc - 1) * 100
    chained = (ec / sp - 1) * 100
    print(f"  {sym:<14} {ser:<4} {ratio:>8.4f} {pc:>10} {sp:>12} {ec:>10} "
          f"{naive:>8.2f}% {chained:>9.2f}%")

print()
print("=" * 88)
print("B. CORP_IND in the three PR bundles already downloaded")
print("=" * 88)

for zip_path in sorted(OUT.glob("pr_*.zip")):
    with zipfile.ZipFile(zip_path) as zf:
        pd_name = next(n for n in zf.namelist() if n.lower().startswith("pd"))
        raw = zf.read(pd_name)
    lines = raw.decode("utf-8", errors="replace").splitlines()
    header = [c.strip() for c in lines[0].split(",")]
    idx = header.index("CORP_IND")
    sym_i, ser_i = header.index("SYMBOL"), header.index("SERIES")
    counts = Counter()
    examples = {}
    for line in lines[1:]:
        p = line.split(",")
        if len(p) <= idx:
            continue
        flag = p[idx].strip()
        if flag:
            counts[flag] += 1
            examples.setdefault(flag, f"{p[sym_i].strip()} ({p[ser_i].strip()})")
    print(f"\n  {zip_path.name} -> {pd_name}")
    for flag, n in counts.most_common():
        print(f"     {flag:<4} {n:>4}   e.g. {examples[flag]}")
    if not counts:
        print("     (no flags that day)")
