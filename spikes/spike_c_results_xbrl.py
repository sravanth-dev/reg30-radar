"""Spike C - results XBRL (ARCHITECTURE §5.8, §10). Throwaway probe, not production code.

Question: where does NSE publish each company's quarterly results as XBRL, for both the
"Integrated Filing - Financial" era (from April 2025) and the older "Financial Results"
filings, and does one parser read both? Must show a discrete-quarter context and a
cumulative one, and enough to derive Q4 = FY - 9M.

Budget: 14 requests, counted in one persisted file with warm-ups included (the Spike A
lesson). Saves raw responses to spikes/out/spike_c/ for offline analysis. Run on the laptop
over the phone hotspot only (D19), with nothing else sending to NSE.

    python spikes/spike_c_results_xbrl.py listing BEL      # 1-2 requests
    python spikes/spike_c_results_xbrl.py file <url>       # 1 request
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

OUT = ROOT / "spikes" / "out" / "spike_c"
BUDGET_FILE = OUT / "budget.json"
BUDGET = 14

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


def warm() -> None:
    get(CFG["warmup_url"], label="warm-up")


def listing(symbol: str) -> None:
    warm()
    url = "https://www.nseindia.com/api/corporates-financial-results"
    r = get(url, {"index": "equities", "period": "Quarterly", "symbol": symbol},
            label=f"results listing {symbol}")
    path = OUT / f"listing_{symbol}.json"
    path.write_bytes(r.content)
    print(r.status_code, r.headers.get("content-type"), len(r.content), "bytes ->", path)


def files(urls: list[str]) -> None:
    """Several files behind one warm-up."""
    warm()
    for url in urls:
        r = get(url, label=f"file {url.rsplit('/', 1)[-1]}")
        path = OUT / url.rsplit("/", 1)[-1].split("?")[0]
        path.write_bytes(r.content)
        print(r.status_code, r.headers.get("content-type"), len(r.content), "bytes ->", path)


def api(path_and_query: str) -> None:
    """One arbitrary www.nseindia.com/api GET, e.g. 'integrated-filing-results?...'."""
    warm()
    r = get("https://www.nseindia.com/api/" + path_and_query, label=f"api {path_and_query}")
    out = OUT / ("api_" + path_and_query.split("?")[0].replace("/", "_") + ".json")
    out.write_bytes(r.content)
    print(r.status_code, r.headers.get("content-type"), len(r.content), "bytes ->", out)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "listing":
        listing(args[0])
    elif cmd == "files":
        files(args)
    elif cmd == "api":
        api(args[0])
