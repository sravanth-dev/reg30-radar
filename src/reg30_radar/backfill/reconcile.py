"""Bundle-versus-API reconciliation, run for every day of the backfill window.

Spike A2 established mainboard order coverage of 8/8 on a single day, and that the
`an<date>.txt` bundle is a *report* covering filings disseminated since the previous
report. So an entry in the report for D corresponds to an API record dated anywhere from
the previous report date to D - which after a weekend or holiday reaches back three or
four days, not one (found 27 Sep 2026: RVNL's order disseminated Saturday 20 Jun 2026 sits
in Monday 22 Jun's report; a ±1-day window matched 0 of that day's 13 order filers).

This module turns that check into a permanent part of the backfill rather than a spike
finding, so coverage and the report-window offset are measured on every day processed. If
coverage degrades mid-window, the backfill says so at the time instead of producing a
quietly thin sample that nobody notices until the verdict.

Pure functions only: no network, no database. The backfill feeds it parsed inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from reg30_radar.router.orders import bucket_of

# §5.4: these two categories are the study's subject. They are distinctive prefixes, which
# is why they survive the bundle's missing category/description delimiter.
ORDER_WIN = "Bagging/Receiving of orders/contracts"
ORDER_CANDIDATE = "Awarding of order(s)/contract(s)"

_SYMBOL_LINE = re.compile(r"^(?P<company>.*?)\s+(?P<symbol>[A-Z0-9&\-]+)\s*:\s*(?P<body>.*)$")


@dataclass(frozen=True)
class BundleEntry:
    symbol: str
    body: str

    @property
    def is_order(self) -> bool:
        return self.body.startswith(ORDER_WIN) or self.body.startswith(ORDER_CANDIDATE)


@dataclass(frozen=True)
class ApiRecord:
    symbol: str
    filed_on: date
    desc: str

    @property
    def is_order(self) -> bool:
        return self.desc.startswith(ORDER_WIN) or self.desc.startswith(ORDER_CANDIDATE)

    @property
    def is_catch_all(self) -> bool:
        return bucket_of(self.desc) == "catch_all"


@dataclass
class Coverage:
    """What one report-date's reconciliation found."""

    report_date: date
    window_from: date
    bundle_total: int = 0
    bundle_orders: int = 0
    bundle_order_symbols: set[str] = field(default_factory=set)
    matched_order_symbols: set[str] = field(default_factory=set)
    unmatched_order_symbols: set[str] = field(default_factory=set)
    # Unmatched order filers that do have a catch-all filing (General Updates, Updates,
    # Press Release) in the window: NSE's two sources can label one filing differently
    # (the bundle's "Bagging/Receiving ... (Sub-para 4-Para B)" is the API's "Updates"),
    # and D7 downloads catch-all filings, so these are likely reachable - but a category
    # match is not proof, so they stay out of the coverage figure.
    catch_all_only_symbols: set[str] = field(default_factory=set)
    offset_histogram: dict[int, int] = field(default_factory=dict)

    @property
    def order_symbol_coverage(self) -> float | None:
        """The number that matters: share of order-filing companies the API can serve."""
        n = len(self.bundle_order_symbols)
        return None if not n else len(self.matched_order_symbols) / n


def parse_bundle_line(line: str) -> BundleEntry | None:
    """One `an<date>.txt` line into (symbol, body).

    The file has no delimiter between category and description (§5.4), so `body` keeps
    both; callers match on a category prefix rather than trying to split it.
    """
    if not line.strip():
        return None
    m = _SYMBOL_LINE.match(line)
    if not m:
        return None
    return BundleEntry(symbol=m.group("symbol").strip(), body=m.group("body").strip())


def reconcile(
    report_date: date,
    bundle: list[BundleEntry],
    api: list[ApiRecord],
    window_from: date | None = None,
    universe: set[str] | None = None,
    company_of: dict[str, str] | None = None,
) -> Coverage:
    """Match a report-date bundle against API records dated [window_from, report_date].

    `window_from` is the previous report date: the report covers everything disseminated
    since that report, and nothing after its own date. It defaults to the day before,
    which is right only when the previous day was a trading day. `universe` restricts to
    NSE mainboard (D9) when supplied; SME and debt are outside the study and would
    otherwise depress the number for no reason. `company_of` maps a symbol to its company
    (the universe ISIN), because the API files a company's whole history under its current
    symbol (LTIMindtree's under LTM) while older reports carry the old one (LTIM).
    """
    if universe is not None:
        bundle = [b for b in bundle if b.symbol in universe]
        api = [a for a in api if a.symbol in universe]
    company = (lambda s: company_of.get(s, s)) if company_of else (lambda s: s)
    lo = window_from or report_date - timedelta(days=1)
    in_window = [a for a in api if lo <= a.filed_on <= report_date]

    cov = Coverage(report_date=report_date, window_from=lo)
    cov.bundle_total = len(bundle)

    order_entries = [b for b in bundle if b.is_order]
    cov.bundle_orders = len(order_entries)
    cov.bundle_order_symbols = {b.symbol for b in order_entries}

    api_order_companies = {company(a.symbol) for a in in_window if a.is_order}
    api_catch_all_companies = {company(a.symbol) for a in in_window if a.is_catch_all}
    cov.matched_order_symbols = {s for s in cov.bundle_order_symbols
                                 if company(s) in api_order_companies}
    cov.unmatched_order_symbols = cov.bundle_order_symbols - cov.matched_order_symbols
    cov.catch_all_only_symbols = {s for s in cov.unmatched_order_symbols
                                  if company(s) in api_catch_all_companies}

    # Where in the window the matched filings sit, relative to the report date. It counts
    # every order filing of a matched company in the window, so a company that filed on
    # two days shows twice; read it as a shape, not a count of matches.
    matched = {company(s) for s in cov.matched_order_symbols}
    for a in in_window:
        if a.is_order and company(a.symbol) in matched:
            offset = (a.filed_on - report_date).days
            cov.offset_histogram[offset] = cov.offset_histogram.get(offset, 0) + 1

    return cov


def coverage_is_acceptable(cov: Coverage, floor: float = 0.95) -> bool:
    """Backfill gate. Below the floor the day is suspect and must be reported, not dropped.

    A day where the API cannot serve the order filings the bundle proves exist is a day
    whose events would be missing from the study through no fault of the companies. That
    has to surface as a number, because a quietly thin sample changes the verdict without
    anyone seeing it (§5.11).
    """
    share = cov.order_symbol_coverage
    return True if share is None else share >= floor
