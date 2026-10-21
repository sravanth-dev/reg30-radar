"""Spike - price bands and ASM/GSM history (Sravanth's rule 3; §11's open "source of
circuit-band membership"). Throwaway probe, not production code.

Question: can each stock's price band (2/5/10/20%) and its ASM/GSM stage be known **as of a
past date**? The live lists answer "today" only, which would be look-ahead if used for a
2025 event. Candidates, each one request:
  1. the current security list (has a price-band column) - format check only
  2. a dated band-changes file for a past day - if it exists, bands can be rebuilt
     forward from a starting list
  3. the current ASM and GSM lists from the API - format, and whether they carry dates

Budget 8, one persisted counter, warm-ups counted. Saves to spikes/out/spike_band_asm/.
Laptop over the hotspot only (D19), with nothing else sending to NSE.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reg30_radar.common.config import nse  # noqa: E402

OUT = ROOT / "spikes" / "out" / "spike_band_asm"
BUDGET_FILE = OUT / "budget.json"
BUDGET = 8
CFG = nse()

PROBES = [
    ("sec_list_current", "https://nsearchives.nseindia.com/content/equities/sec_list.csv"),
    ("band_changes_19092025",
     "https://nsearchives.nseindia.com/content/equities/eq_band_changes_19092025.csv"),
    ("asm_current", "https://www.nseindia.com/api/reportASM"),
    ("gsm_current", "https://www.nseindia.com/api/reportGSM"),
]


def spend(label: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    used = json.loads(BUDGET_FILE.read_text())["used"] if BUDGET_FILE.exists() else 0
    if used >= BUDGET:
        raise SystemExit(f"budget of {BUDGET} spent; not sending {label}")
    BUDGET_FILE.write_text(json.dumps({"used": used + 1, "last": label}))
    print(f"[request {used + 1}/{BUDGET}] {label}")
    time.sleep(3.5)


def main() -> None:
    s = requests.Session()
    s.headers.update({k: str(v) for k, v in CFG["headers"].items()})
    spend("warm-up")
    s.get(CFG["warmup_url"], timeout=60)
    for name, url in PROBES:
        spend(name)
        r = s.get(url, timeout=60)
        suffix = ".json" if "api" in url else ".csv"
        (OUT / f"{name}{suffix}").write_bytes(r.content)
        head = r.content[:300].decode("utf-8", "replace").replace("\n", " | ")
        print(f"  {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes: {head}")


if __name__ == "__main__":
    main()
