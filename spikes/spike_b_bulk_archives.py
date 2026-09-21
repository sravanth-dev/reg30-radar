"""Spike B: NSE bulk archives.

Throwaway probe code (CLAUDE.md: spikes/ only, never src/). Answers:

1. The URL patterns for the UDiFF CM bhavcopy and the daily PR bundle.
2. Archive depth: do both exist for early Aug 2025, Mar 2026 and 18 Sep 2026, and does
   each PR zip carry an*, pd*, mcap* and bh* with the same columns as tests/fixtures/?
3. Does a return chained through PrvsClsgPric stay continuous across a split/bonus ex-date?
4. What robots.txt and the terms of use say about automated access.

Budget discipline, because the VPS IP is whitelisted with the broker and this laptop
shares a household with nothing worth risking either: a hard cap of 12 requests, at least
3 s apart with jitter, session warm-up first, and an immediate stop on 401/403.

Endpoints live here only because this spike exists to discover them. Once confirmed they
belong in config/sources.yaml (CLAUDE.md scraping rules), never in code.
"""

from __future__ import annotations

import io
import random
import sys
import time
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "out"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

MAX_REQUESTS = 12
MIN_GAP_SECONDS = 3.0

BASE = "https://www.nseindia.com"
ARCHIVES = "https://nsearchives.nseindia.com"

# NSE serves 401/403 to bare clients, so the session needs browser-like headers and the
# cookies handed out by the homepage. This is not disguise for its own sake: the UA still
# has to be consistent and traceable, which is a decision for Sravanth (see the report).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class Budget:
    """Refuses to exceed the request cap, and paces every call."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._last = 0.0
        self.log: list[tuple[int, str, str]] = []

    def spend(self, label: str) -> None:
        if self.used >= self.limit:
            raise RuntimeError(f"request budget exhausted at {self.limit}; refusing: {label}")
        gap = time.monotonic() - self._last
        wait = MIN_GAP_SECONDS + random.uniform(0.4, 1.6) - gap
        if self._last and wait > 0:
            time.sleep(wait)
        self.used += 1
        self._last = time.monotonic()


budget = Budget(MAX_REQUESTS)
session = requests.Session()
session.headers.update(HEADERS)


def get(url: str, label: str, referer: str | None = None) -> requests.Response:
    budget.spend(label)
    headers = {"Referer": referer} if referer else {}
    resp = session.get(url, headers=headers, timeout=40)
    budget.log.append((budget.used, resp.status_code, url))
    print(f"  [{budget.used:>2}/{MAX_REQUESTS}] {resp.status_code} {len(resp.content):>9,}b  {url}")
    if resp.status_code in (401, 403):
        print("\nSTOP: NSE returned an auth/forbidden status. Not retrying.")
        report_budget()
        sys.exit(2)
    return resp


def report_budget() -> None:
    print(f"\n--- requests used: {budget.used}/{MAX_REQUESTS} ---")
    for n, status, url in budget.log:
        print(f"  {n:>2}. {status}  {url}")


def udiff_url(d: date) -> str:
    return f"{ARCHIVES}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def pr_url(d: date) -> str:
    return f"{ARCHIVES}/archives/equities/bhavcopy/pr/PR{d:%d%m%y}.zip"


def save(name: str, body: bytes) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_bytes(body)
    return path


def read_zip_member(body: bytes, predicate) -> tuple[str, bytes] | None:
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        for name in zf.namelist():
            if predicate(name.lower()):
                return name, zf.read(name)
    return None


def csv_header(raw: bytes) -> list[str]:
    text = raw.decode("utf-8", errors="replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    return [c.strip() for c in first.split(",")]


def parse_udiff(body: bytes) -> tuple[str, dict[str, dict]]:
    """Return (member name, {symbol: row}) for EQ-series rows keyed by symbol."""
    got = read_zip_member(body, lambda n: n.endswith(".csv"))
    assert got, "no csv inside the UDiFF zip"
    name, raw = got
    lines = raw.decode("utf-8", errors="replace").splitlines()
    header = [c.strip() for c in lines[0].split(",")]
    idx = {c: i for i, c in enumerate(header)}
    rows: dict[str, dict] = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < len(header):
            continue
        if parts[idx["SctySrs"]].strip() != "EQ":
            continue
        rows[parts[idx["TckrSymb"]].strip()] = {
            "isin": parts[idx["ISIN"]].strip(),
            "close": parts[idx["ClsPric"]].strip(),
            "prev_close": parts[idx["PrvsClsgPric"]].strip(),
        }
    return name, rows


# ---------------------------------------------------------------------------------------
# 1 + 4. Warm up the session and read robots.txt
# ---------------------------------------------------------------------------------------
print("=" * 88)
print("STEP 1/4  session warm-up and robots.txt")
print("=" * 88)

get(BASE + "/", "warm-up")
print(f"  cookies held: {sorted(session.cookies.keys())}")

robots = get(BASE + "/robots.txt", "robots.txt", referer=BASE + "/")
robots_text = robots.text if robots.status_code == 200 else ""
save("robots.txt", robots.content)
print("\n--- robots.txt (verbatim) ---")
print(robots_text.strip()[:2000] or "(empty or non-200)")

# ---------------------------------------------------------------------------------------
# 2. Archive depth across three periods
# ---------------------------------------------------------------------------------------
print()
print("=" * 88)
print("STEP 2  archive depth: UDiFF bhavcopy + PR bundle at three dates")
print("=" * 88)

TARGETS = [
    ("early Aug 2025", date(2025, 8, 6)),
    ("Mar 2026", date(2026, 3, 11)),
    ("18 Sep 2026", date(2026, 9, 18)),
]

pr_payloads: dict[str, bytes] = {}
udiff_payloads: dict[str, bytes] = {}

for label, d in TARGETS:
    print(f"\n-- {label}: {d:%Y-%m-%d} ({d:%A}) --")
    r = get(udiff_url(d), f"udiff {d}", referer=BASE + "/all-reports")
    if r.status_code == 200 and r.content[:2] == b"PK":
        udiff_payloads[label] = r.content
        save(f"udiff_{d:%Y%m%d}.zip", r.content)
    else:
        print(f"     -> UDiFF not available ({r.status_code}); likely a holiday or a moved path")

    r = get(pr_url(d), f"pr {d}", referer=BASE + "/all-reports")
    if r.status_code == 200 and r.content[:2] == b"PK":
        pr_payloads[label] = r.content
        save(f"pr_{d:%Y%m%d}.zip", r.content)
    else:
        print(f"     -> PR bundle not available ({r.status_code})")

# --- what is inside each PR bundle, and do the columns match the fixtures? --------------
print()
print("=" * 88)
print("STEP 2b  PR bundle contents vs tests/fixtures/")
print("=" * 88)

WANTED = {
    "an": (lambda n: n.startswith("an") and n.endswith(".txt"), FIXTURES / "an18092026.txt"),
    "pd": (lambda n: n.startswith("pd") and n.endswith(".csv"), FIXTURES / "pd18092026.csv"),
    "mcap": (lambda n: n.startswith("mcap") and n.endswith(".csv"), FIXTURES / "mcap18092026.csv"),
    "bh": (lambda n: n.startswith("bh") and n.endswith(".csv"), None),
}

for label, body in pr_payloads.items():
    print(f"\n-- {label} --")
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = sorted(zf.namelist())
    print(f"  {len(names)} members: {', '.join(names)}")
    for key, (pred, fixture) in WANTED.items():
        got = read_zip_member(body, pred)
        if not got:
            print(f"  {key:<5} MISSING")
            continue
        name, raw = got
        if key == "an":
            line_count = raw.decode("utf-8", errors="replace").count("\n")
            print(f"  {key:<5} {name}  ({line_count} lines)")
            continue
        header = csv_header(raw)
        note = ""
        if fixture and fixture.exists():
            same = header == csv_header(fixture.read_bytes())
            note = "  columns MATCH fixture" if same else f"  columns DIFFER: {header}"
        print(f"  {key:<5} {name}  {len(header)} cols{note}")
        if key == "bh":
            print(f"        bh columns: {header}")
            body_lines = raw.decode("utf-8", errors="replace").splitlines()[1:4]
            for bl in body_lines:
                print(f"        sample: {bl.strip()}")

# --- UDiFF: ISIN and PrvsClsgPric present? ---------------------------------------------
print()
print("=" * 88)
print("STEP 2c  UDiFF columns: ISIN and PrvsClsgPric")
print("=" * 88)

for label, body in udiff_payloads.items():
    got = read_zip_member(body, lambda n: n.endswith(".csv"))
    name, raw = got
    header = csv_header(raw)
    print(f"\n-- {label}: {name}, {len(header)} cols --")
    for need in ("ISIN", "TckrSymb", "SctySrs", "ClsPric", "PrvsClsgPric"):
        print(f"  {need:<14} {'present' if need in header else 'MISSING'}")
    bse_header = csv_header((FIXTURES / "BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV").read_bytes())
    print(f"  same columns as the BSE UDiFF fixture: {header == bse_header}")

# ---------------------------------------------------------------------------------------
# 3. Corporate action: is a PrvsClsgPric-chained return continuous across an ex-date?
# ---------------------------------------------------------------------------------------
print()
print("=" * 88)
print("STEP 3  return chaining across a split/bonus ex-date")
print("=" * 88)

# Candidates found off-network: Indian Toners 1:5 split (record 17 Jul 2026) and
# Divine Hira Jewellers 2:1 bonus (record 2 Jul 2026). The symbol does not need to be
# known in advance: any corporate action shows up as close[D-1] != PrvsClsgPric[D].
EX_DATE = date(2026, 7, 17)
PRIOR = date(2026, 7, 16)

print(f"  ex-date   {EX_DATE:%Y-%m-%d} ({EX_DATE:%A})")
print(f"  prior day {PRIOR:%Y-%m-%d} ({PRIOR:%A})")

r_prior = get(udiff_url(PRIOR), f"udiff {PRIOR}", referer=BASE + "/all-reports")
r_ex = get(udiff_url(EX_DATE), f"udiff {EX_DATE}", referer=BASE + "/all-reports")

if r_prior.content[:2] == b"PK" and r_ex.content[:2] == b"PK":
    save(f"udiff_{PRIOR:%Y%m%d}.zip", r_prior.content)
    save(f"udiff_{EX_DATE:%Y%m%d}.zip", r_ex.content)
    _, prior_rows = parse_udiff(r_prior.content)
    _, ex_rows = parse_udiff(r_ex.content)
    print(f"  EQ rows: prior={len(prior_rows):,}  ex={len(ex_rows):,}")

    adjustments = []
    for sym, ex in ex_rows.items():
        pr = prior_rows.get(sym)
        if not pr:
            continue
        try:
            prior_close = Decimal(pr["close"])
            stated_prev = Decimal(ex["prev_close"])
            ex_close = Decimal(ex["close"])
        except Exception:
            continue
        if prior_close <= 0 or stated_prev <= 0:
            continue
        ratio = stated_prev / prior_close
        if ratio < Decimal("0.9"):  # a real adjustment, not a rounding wobble
            naive = (ex_close / prior_close - 1) * 100
            chained = (ex_close / stated_prev - 1) * 100
            adjustments.append((ratio, sym, ex["isin"], prior_close, stated_prev, ex_close, naive, chained))

    adjustments.sort()
    print(f"\n  {len(adjustments)} symbols where PrvsClsgPric is below the prior close by >10%")
    print(f"  (each is a corporate action the unadjusted series would get wrong)\n")
    print(f"  {'SYMBOL':<12} {'ratio':>7} {'prior_cl':>10} {'stated_prev':>12} {'ex_close':>10} "
          f"{'naive %':>10} {'chained %':>10}")
    for ratio, sym, isin, pc, sp, ec, naive, chained in adjustments[:12]:
        print(f"  {sym:<12} {ratio:>7.4f} {pc:>10} {sp:>12} {ec:>10} {naive:>9.1f}% {chained:>9.1f}%")
    if not adjustments:
        print("  none found on this pair; pick another ex-date")
else:
    print(f"  one of the two days is not a trading day "
          f"(prior={r_prior.status_code}, ex={r_ex.status_code}); pick another pair")

report_budget()
