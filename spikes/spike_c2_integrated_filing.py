"""Spike C2 - the post-April-2025 "Integrated Filing - Financials" results (ARCHITECTURE §5.8).
Throwaway probe, not production code.

Sravanth captured the endpoint from NSE's Integrated Filing page (27 Sep 2026):
    GET https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=BEL
        &issuer=Bharat%20Electronics%20Limited&period_ended=all
        &type=Integrated%20Filing-%20Financials&page=1&size=20
Questions: does it answer a script (not just a browser)? Is the exact `issuer` name
required? Does it reach back to the first integrated quarter (Jan-Mar 2025)? And do its
XBRL files parse with revenue/xbrl.py, including what Q4 = FY - 9M needs?

Budget: 8 requests in one persisted counter, warm-up included (the Spike A lesson). Run on
the laptop over the phone hotspot (D19) with nothing else sending to NSE.

    python spikes/spike_c2_integrated_filing.py run
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tradebot.common.config import nse  # noqa: E402

OUT = ROOT / "spikes" / "out" / "spike_c2"
BUDGET_FILE = OUT / "budget.json"
BUDGET = 8
LISTING = "https://www.nseindia.com/api/integrated-filing-results"

CFG = nse()
session = requests.Session()
session.headers.update({k: str(v) for k, v in CFG["headers"].items()})


def spend(label: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    used = json.loads(BUDGET_FILE.read_text())["used"] if BUDGET_FILE.exists() else 0
    if used >= BUDGET:
        raise SystemExit(f"budget of {BUDGET} requests spent; not sending {label}")
    BUDGET_FILE.write_text(json.dumps({"used": used + 1, "last": label}))
    print(f"[request {used + 1}/{BUDGET}] {label}")
    time.sleep(3.5)


def get(url: str, params: dict | None = None, label: str = "") -> requests.Response:
    spend(label or url)
    return session.get(url, params=params, timeout=60)


def listing(symbol: str, issuer: str | None, tag: str) -> list[dict]:
    params = {"index": "equities", "symbol": symbol, "period_ended": "all",
              "type": "Integrated Filing- Financials", "page": 1, "size": 20}
    if issuer:
        params["issuer"] = issuer
    r = get(LISTING, params, label=f"listing {symbol} ({tag})")
    path = OUT / f"listing_{symbol}_{tag}.json"
    path.write_bytes(r.content)
    print(r.status_code, r.headers.get("content-type"), len(r.content), "bytes ->", path.name)
    try:
        body = r.json()
    except ValueError:
        return []
    rows = body.get("data", []) if isinstance(body, dict) else []
    print("   totalCount:", body.get("totalCount") if isinstance(body, dict) else None,
          "rows:", len(rows))
    return rows


def run() -> None:
    get(CFG["warmup_url"], label="warm-up")
    rows = listing("BEL", "Bharat Electronics Limited", "with_issuer")
    listing("BEL", None, "no_issuer")
    for r in sorted(rows, key=lambda r: r.get("broadcast_Date") or ""):
        print("  ", r.get("qe_Date"), r.get("consolidated"), r.get("audited"),
              r.get("type_Sub"), r.get("broadcast_Date"), (r.get("xbrl") or "")[-60:])
    wanted = {"30-JUN-2026", "31-MAR-2026", "31-DEC-2025"}
    for r in rows:
        if r.get("qe_Date", "").upper() in wanted and r.get("consolidated") == "Consolidated" \
                and r.get("xbrl"):
            fr = get(r["xbrl"], label=f"xbrl {r['qe_Date']} consolidated")
            path = OUT / r["xbrl"].rsplit("/", 1)[-1]
            path.write_bytes(fr.content)
            print(fr.status_code, fr.headers.get("content-type"), len(fr.content), "bytes ->",
                  path.name)
            wanted.discard(r["qe_Date"].upper())


if __name__ == "__main__":
    if sys.argv[1:] == ["run"]:
        run()
    else:
        print(__doc__)
