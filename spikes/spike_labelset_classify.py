"""Classify the candidate PDFs into edge cases WITHOUT disclosing any extracted value.

Sravanth labels ten of these blind. So this prints only: the filename, structural facts
(pages, whether a text layer exists), and which edge-case category the file exercises.
It never prints a monetary amount, a counterparty, a date from inside the document, or any
span of document text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tests" / "labelled"
MANIFEST = json.loads((ROOT / "spikes" / "out" / "labelset_manifest.json").read_text(encoding="utf-8"))

# Signals. Each maps to a category name; the matched text is never printed.
SIGNALS = {
    "foreign currency": re.compile(r"\b(USD|EUR|GBP|JPY|AED|SGD|CHF)\b|US\s?\$|€|£", re.I),
    "value not disclosed": re.compile(
        r"not\s+(been\s+)?disclos|cannot\s+be\s+disclos|confidential|withheld|"
        r"not\s+quantifiab|yet\s+to\s+be\s+(determined|ascertain)", re.I),
    "several orders in one filing": re.compile(
        r"\b(aggregate|aggregating|cumulative|total\s+of)\b.{0,40}\border", re.I),
    "LoI / letter of intent": re.compile(r"letter\s+of\s+intent|\bLoI\b", re.I),
    "LoA / letter of award": re.compile(r"letter\s+of\s+award|\bLoA\b", re.I),
    "L1 / lowest bidder": re.compile(r"\bL-?1\b|lowest\s+bidder|lowest\s+evaluated", re.I),
    "amendment or revision": re.compile(r"\bamend|\brevis|\bterminat|\bcancell|\bwithdraw", re.I),
    "GST treatment stated": re.compile(r"incl.{0,6}\s*GST|including\s+GST|excluding\s+GST|plus\s+GST", re.I),
    "company may be placing, not winning": re.compile(
        r"\bawarded\s+(a\s+)?(work\s+)?order\s+to\b|\bplaced\s+(an\s+)?order\s+(on|with)\b", re.I),
    "approximate value": re.compile(r"\bapprox|\babout\s+(Rs|INR|₹)", re.I),
    "execution period stated": re.compile(
        r"\b(\d+\s*(months?|years?|days?|weeks?))\b|completion\s+period|execution\s+period", re.I),
}


def classify(path: Path) -> dict:
    out = {"pages": 0, "chars": 0, "is_scanned": True, "signals": []}
    try:
        with pdfplumber.open(path) as pdf:
            out["pages"] = len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:12])
    except Exception as exc:
        out["error"] = type(exc).__name__
        return out
    out["chars"] = len(text.strip())
    # A filing with a real text layer yields well over a few hundred characters a page.
    out["is_scanned"] = out["chars"] < max(200, 80 * min(out["pages"], 12))
    for name, rx in SIGNALS.items():
        if rx.search(text):
            out["signals"].append(name)
    return out


rows = []
for entry in MANIFEST:
    p = DEST / entry["file"]
    if not p.exists():
        continue
    info = classify(p)
    rows.append({**entry, **info})

print(f"{'FILE':<26}{'pages':>6}{'text?':>7}  signals")
print("-" * 104)
for r in sorted(rows, key=lambda x: x["file"]):
    text_flag = "scanned" if r["is_scanned"] else "yes"
    sig = ", ".join(r["signals"]) or "(plain order, no special signal)"
    print(f"{r['file']:<26}{r['pages']:>6}{text_flag:>7}  {sig[:70]}")

scanned = [r for r in rows if r["is_scanned"]]
print(f"\nscanned (no usable text layer): {len(scanned)} of {len(rows)}")
for r in scanned:
    print(f"   {r['file']}")

print("\ncoverage of the edge cases you asked for:")
for name in SIGNALS:
    hits = [r["file"] for r in rows if name in r["signals"]]
    mark = "ok " if hits else "GAP"
    print(f"  {mark} {name:<38} {len(hits):>2}  {', '.join(h.split('_')[0] for h in hits[:6])}")

(ROOT / "spikes" / "out" / "labelset_classified.json").write_text(
    json.dumps(rows, indent=1), encoding="utf-8")
