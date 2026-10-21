"""Point-in-time trailing-twelve-month revenue (ARCHITECTURE §5.8; Sravanth's rule 1).

Pure: the caller supplies every `financials` row known for one company, and this decides
what was knowable at one moment.

- Only results **filed before** the announcement count: the last four quarters whose
  results were FILED before it, not the last four that ENDED before it (rule 1).
- One basis throughout: consolidated when four consolidated quarters are available,
  otherwise standalone (§5.8 Default), never a mix.
- **Q4 = FY − 9M** (Decided): most companies file an audited full year and never a discrete
  fourth quarter, so without this rule TTM would be null for them exactly when it is needed.
  A derived quarter that is not positive is never used.
- **Q2 = H1 − Q1** (Proposed, 20 Oct 2026): 47 Integrated-Filing Q2 files (Nov 2025) carry
  only the half-year, their quarter context holding the Apr-Sep figure. Derived only when
  the result is at least `Q2_MIN_SHARE` of Q1: where the "half-year" is really the quarter
  mislabelled (two companies; their later revisions changed it), the difference is a
  fraction of Q1, and TTM stays null rather than wrong.
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


# Below this share of Q1, an H1 - Q1 difference means the "half-year" was the quarter.
# Measured on the 47 affected filings: good cases 0.53-3.26, the two bad ones 0.05-0.28.
Q2_MIN_SHARE = Decimal("0.4")


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
        if nine is not None and year.revenue_inr - nine.revenue_inr > 0:
            quarters[end] = year.revenue_inr - nine.revenue_inr    # Q4 = FY - 9M
    for (end, months), half in latest.items():
        if months != 6 or end.month != 9 or end in quarters:
            continue
        q1 = next((v for e, v in quarters.items() if _months_between(e, end) == 3), None)
        if q1 is not None and q1 > 0 and half.revenue_inr - q1 >= Q2_MIN_SHARE * q1:
            quarters[end] = half.revenue_inr - q1                   # Q2 = H1 - Q1
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


def fy_mismatches(periods: list[Period], tolerance: Decimal = Decimal("0.02")):
    """§5.8's sanity check: where a full year and its four discrete quarters were all filed
    (latest versions), they should add up. Returns (year end, basis, FY, sum of quarters)
    for each year off by more than `tolerance`. Logged for review, never used to change a
    number: a mismatch is a question about a filing, not an answer."""
    out = []
    for basis in ("consolidated", "standalone"):
        latest: dict[tuple[date, int], Period] = {}
        for p in periods:
            if p.basis == basis and ((p.period_end, p.months) not in latest
                                     or p.filed_at > latest[(p.period_end, p.months)].filed_at):
                latest[(p.period_end, p.months)] = p
        for (end, months), year in latest.items():
            if months != 12:
                continue
            qs = [v for (e, m), v in latest.items()
                  if m == 3 and 0 <= _months_between(e, end) <= 9 and _months_between(e, end) % 3 == 0]
            if len(qs) == 4 and year.revenue_inr:
                total = sum(q.revenue_inr for q in qs)
                if abs(total - year.revenue_inr) > tolerance * abs(year.revenue_inr):
                    out.append((end, basis, year.revenue_inr, total))
    return out
