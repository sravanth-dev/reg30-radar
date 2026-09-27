"""Point-in-time trailing-twelve-month revenue (ARCHITECTURE §5.8; Sravanth's rule 1).

Pure: the caller supplies every `financials` row known for one company, and this decides
what was knowable at one moment.

- Only results **filed before** the announcement count: the last four quarters whose
  results were FILED before it, not the last four that ENDED before it (rule 1).
- One basis throughout: consolidated when four consolidated quarters are available,
  otherwise standalone (§5.8 Default), never a mix.
- **Q4 = FY − 9M** (Decided): most companies file an audited full year and never a discrete
  fourth quarter, so without this rule TTM would be null for them exactly when it is needed.
- The four quarters must be consecutive. A gap gives None, never a guess.
- A period restated by a later filing uses the latest version filed before the moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Period:
    period_end: date
    months: int                  # 3 (quarter), 6 (half year), 9 (nine months), 12 (year)
    basis: str                   # "consolidated" | "standalone"
    revenue_inr: Decimal
    filed_at: datetime


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def quarters_known(periods: list[Period], moment: datetime, basis: str) -> dict[date, Decimal]:
    """Discrete quarterly revenue by quarter end, as known at `moment` on one basis."""
    latest: dict[tuple[date, int], Period] = {}
    for p in periods:
        if p.basis != basis or p.filed_at >= moment:
            continue
        key = (p.period_end, p.months)
        if key not in latest or p.filed_at > latest[key].filed_at:
            latest[key] = p

    quarters = {end: p.revenue_inr for (end, months), p in latest.items() if months == 3}
    for (end, months), year in latest.items():
        if months != 12 or end in quarters:
            continue
        nine = next((p for (e9, m9), p in latest.items()
                     if m9 == 9 and _months_between(e9, end) == 3), None)
        if nine is not None:
            quarters[end] = year.revenue_inr - nine.revenue_inr    # Q4 = FY - 9M
    return quarters


def ttm_as_of(periods: list[Period], moment: datetime) -> tuple[Decimal | None, str | None]:
    """(TTM revenue, basis) knowable at `moment`, or (None, None)."""
    for basis in ("consolidated", "standalone"):
        quarters = quarters_known(periods, moment, basis)
        if not quarters:
            continue
        ends = sorted(quarters, reverse=True)[:4]
        consecutive = len(ends) == 4 and all(
            _months_between(ends[i + 1], ends[i]) == 3 for i in range(3))
        if consecutive:
            return sum(quarters[e] for e in ends), basis
    return None, None
