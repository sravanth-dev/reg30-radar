"""Bundle-versus-API reconciliation, run for every day of the backfill window.

Spike A2 established mainboard order coverage of 8/8 on a single day, and that the
`an<date>.txt` bundle is a *report* covering filings disseminated since the previous
report — so a bundle entry dated D usually corresponds to an API record timestamped D or
D-1. Both of those are observations from one day. Neither is a rate.

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


@dataclass
class Coverage:
    """What one report-date's reconciliation found."""

    report_date: date
    window_days: int
    bundle_total: int = 0
    bundle_orders: int = 0
    bundle_order_symbols: set[str] = field(default_factory=set)
    matched_order_symbols: set[str] = field(default_factory=set)
    unmatched_order_symbols: set[str] = field(default_factory=set)
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
    window_days: int = 1,
    universe: set[str] | None = None,
) -> Coverage:
    """Match a report-date bundle against API records over a +/- window.

    `window_days=1` is the default because a filing disseminated after the close on D-1
    appears in the bundle reported on D. `universe` restricts to NSE mainboard (D9) when
    supplied; SME and debt are outside the study and would otherwise depress the number
    for no reason.
    """
    if universe is not None:
        bundle = [b for b in bundle if b.symbol in universe]
        api = [a for a in api if a.symbol in universe]

    lo = report_date - timedelta(days=window_days)
    hi = report_date + timedelta(days=window_days)
    in_window = [a for a in api if lo <= a.filed_on <= hi]

    cov = Coverage(report_date=report_date, window_days=window_days)
    cov.bundle_total = len(bundle)

    order_entries = [b for b in bundle if b.is_order]
    cov.bundle_orders = len(order_entries)
    cov.bundle_order_symbols = {b.symbol for b in order_entries}

    api_order_symbols = {a.symbol for a in in_window if a.is_order}
    cov.matched_order_symbols = cov.bundle_order_symbols & api_order_symbols
    cov.unmatched_order_symbols = cov.bundle_order_symbols - api_order_symbols

    # How far ahead of the report date the matched filings actually sit. A histogram
    # concentrated on 0 and -1 confirms the report-window model; anything else means the
    # window is wrong and the backfill should widen it rather than silently lose filings.
    for a in in_window:
        if a.is_order and a.symbol in cov.matched_order_symbols:
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
