"""How big an order is next to the company that won it (ARCHITECTURE §5.10).

Pure functions: the caller supplies the order value, the point-in-time TTM revenue and the
market cap at the valuation date, all already chosen as of the filing (Sravanth's rule 1 in
config/backfill.yaml: nothing from after the announcement). Nothing here reads a clock or
a database.

Ratios are NUMERIC(12,6) in Postgres, not money (§7): two decimal places would round a 0.4%
ratio to zero.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from tradebot.units.money import parse_execution_months

RATIO_PLACES = Decimal("0.000001")
ONE_LAKH = Decimal(10) ** 5


@dataclass
class Materiality:
    value_to_ttm: Decimal | None = None
    next12m_to_ttm: Decimal | None = None
    value_to_mcap: Decimal | None = None
    flags: set[str] = field(default_factory=set)


def _ratio(numerator: Decimal, denominator: Decimal | None) -> Decimal | None:
    if denominator is None or denominator <= 0:
        return None
    return (numerator / denominator).quantize(RATIO_PLACES)


def compute(value_inr: Decimal | None, *, ttm_revenue_inr: Decimal | None,
            mcap_inr: Decimal | None, execution_months: Decimal | None) -> Materiality:
    """§5.10's three ratios and flags. A missing input gives a null ratio, never a guess."""
    out = Materiality()
    if value_inr is None:
        out.flags.add("no_value")
        return out
    if value_inr < ONE_LAKH:
        out.flags.add("suspect_parse")
    if ttm_revenue_inr is None or ttm_revenue_inr <= 0:
        out.flags.add("missing_ttm")
    if mcap_inr is None or mcap_inr <= 0:
        out.flags.add("missing_mcap")

    out.value_to_ttm = _ratio(value_inr, ttm_revenue_inr)
    out.value_to_mcap = _ratio(value_inr, mcap_inr)
    if execution_months is not None and execution_months > 0 and out.value_to_ttm is not None:
        # Revenue the order can add in the next 12 months: a 6-month order is not doubled,
        # a 24-month one counts half (§5.10).
        share = min(Decimal(1), Decimal(12) / execution_months)
        out.next12m_to_ttm = _ratio(value_inr * share, ttm_revenue_inr)
    if out.value_to_ttm is not None and out.value_to_ttm > 1:
        # Either the trade of the year or a lakh/crore error (§5.10).
        out.flags.add("manual_review")
    return out


_MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): n for n, name in enumerate(calendar.month_abbr) if name})
_BY_DATE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) +
                      r")\b[\s,.'-]*(\d{4})\b", re.I)


def execution_months(raw: str | None, filed_on: date) -> Decimal | None:
    """Execution period in months (§5.7). A duration ("10 Months from Work Order", "2
    Years") is read directly. A completion month ("Delivery Completion is November, 2026")
    is counted from the filing date to the end of that month. Anything else is None,
    never a guess."""
    months = parse_execution_months(raw)
    if months is not None:
        return months
    if not raw:
        return None
    m = _BY_DATE.search(raw)
    if not m:
        return None
    month, year = _MONTHS[m.group(1).lower()], int(m.group(2))
    span = (year - filed_on.year) * 12 + (month - filed_on.month)
    if span < 0:
        return None     # a completion date before the filing is not an execution period
    return Decimal(max(span, 1))
