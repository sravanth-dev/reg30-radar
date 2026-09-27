"""Revenue from one results XBRL file (ARCHITECTURE §5.8).

§5.8 (Decided): the in-capmkt taxonomy carries both discrete-quarter and cumulative (H1, 9M,
FY) contexts, and picking the wrong one double-counts silently. So nothing here trusts a
context's *name*: every revenue fact is read with its context's actual start and end dates,
and the period length is computed from them. The caller keeps only what it needs (3-, 9-
and 12-month periods, for quarters and Q4 = FY - 9M).

Namespace prefixes vary between filings, so elements are matched on their local name.
Values in an XBRL instance are in the unit's base currency (the `decimals` attribute says
how they were rounded, not how they are scaled); a unit other than INR is refused rather
than converted, because FX is still Open (§11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

# The revenue line, most specific first. "RevenueFromOperations" is the Ind AS
# "Revenue from operations" line; the others are fallbacks for older formats, recorded in
# `element` so a row always says which line it came from.
REVENUE_ELEMENTS = ("RevenueFromOperations", "RevenueFromOperationsNet", "Revenue")


@dataclass(frozen=True)
class RevenueFact:
    period_start: date
    period_end: date
    months: int
    basis: str | None             # "consolidated" | "standalone" | None if not stated
    revenue_inr: Decimal
    context_id: str
    element: str


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def months_between(start: date, end: date) -> int:
    """Months covered by [start, end], from the day count: a quarter is 90-92 days, nine
    months 273-275, a year 365-366, so rounding days / 30.44 is exact for every period a
    results filing uses."""
    return round(((end - start).days + 1) / 30.44)


def parse(xml_bytes: bytes) -> list[RevenueFact]:
    root = etree.fromstring(xml_bytes, parser=etree.XMLParser(resolve_entities=False,
                                                              no_network=True, huge_tree=True))
    contexts: dict[str, tuple[date, date]] = {}
    units: dict[str, str] = {}
    basis = None
    facts = []
    for el in root.iter():
        name = _local(el.tag)
        if name == "context":
            start = next((c.text for c in el.iter() if _local(c.tag) == "startDate"), None)
            end = next((c.text for c in el.iter() if _local(c.tag) == "endDate"), None)
            if start and end:
                contexts[el.get("id")] = (date.fromisoformat(start.strip()[:10]),
                                          date.fromisoformat(end.strip()[:10]))
        elif name == "unit":
            measure = next((c.text for c in el.iter() if _local(c.tag) == "measure"), "")
            units[el.get("id")] = (measure or "").split(":")[-1].strip().upper()
        elif name == "NatureOfReportStandaloneConsolidated" and el.text:
            basis = el.text.strip().lower()
        elif name in REVENUE_ELEMENTS and el.get("contextRef"):
            facts.append((name, el.get("contextRef"), el.get("unitRef"), (el.text or "").strip()))

    out = []
    for element in REVENUE_ELEMENTS:
        chosen = [f for f in facts if f[0] == element]
        if not chosen:
            continue
        for _, ctx, unit, text in chosen:
            if ctx not in contexts or units.get(unit, "INR") != "INR":
                continue
            try:
                value = Decimal(text)
            except InvalidOperation:
                continue
            start, end = contexts[ctx]
            out.append(RevenueFact(start, end, months_between(start, end),
                                   basis if basis in ("consolidated", "standalone") else None,
                                   value, ctx, element))
        break      # the most specific element present wins; never mix two revenue lines
    return out
