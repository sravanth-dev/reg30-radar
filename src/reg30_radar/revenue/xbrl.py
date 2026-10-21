"""Revenue from one results XBRL file (ARCHITECTURE §5.8).

§5.8 (Decided): the in-capmkt/in-bse-fin taxonomy carries both discrete-quarter and
cumulative (H1, 9M, FY) contexts, and picking the wrong one double-counts silently. So
nothing here trusts a context's *name*: every revenue fact is read from an actual start and
end date, and the period length is computed from them. The caller keeps only what it needs
(3-, 9- and 12-month periods, for quarters and Q4 = FY - 9M).

**The XBRL `<context>` element's own startDate/endDate cannot be trusted either** (Spike C,
27 Sep 2026, found on real BEL filings, not a synthetic worry). Two real, distinct defects:
- A Jan-2025 Q3 filing's cumulative context ("FourD") declares the *same* startDate/endDate
  as the discrete quarter's context ("OneD") - a template copy-paste bug on NSE's side - even
  though FourD's own revenue is Rs 146.19bn against OneD's Rs 57.7bn, plainly nine months'
  worth, not three. Reading context dates alone would silently collide these two facts under
  one (period_end, months) key.
- A 2018 Q4 filing's `RevenueFromOperations` facts reference contextRef="OneD"/"FourD", but
  no `<context id="OneD">` or `<context id="FourD">` element exists in the instance at all -
  the base contexts were simply never defined.
Both filings correctly tag `DateOfStartOfReportingPeriod`/`DateOfEndOfReportingPeriod` facts
alongside the revenue figure in the same context, and those facts are right in both cases
(3 months for OneD, 9 or 12 for FourD, matching the revenue's real order of magnitude). So
the period a revenue fact belongs to is read from **these declared facts first**, falling
back to the context's own dates only when no declared pair exists for that context.

`NatureOfReportStandaloneConsolidated` is a per-context fact too, not one global flag: a
filing with both standalone and consolidated contexts must not stamp every fact with
whichever value happens to be seen last.

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


def _date(text: str | None) -> date | None:
    if not text or not text.strip():
        return None
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def parse(xml_bytes: bytes) -> list[RevenueFact]:
    root = etree.fromstring(xml_bytes, parser=etree.XMLParser(resolve_entities=False,
                                                              no_network=True, huge_tree=True))
    context_period: dict[str, tuple[date, date]] = {}     # the <context> element's own dates
    declared: dict[str, dict[str, date]] = {}             # per-context DateOfStart/EndOfReportingPeriod
    basis_of: dict[str, str] = {}                         # per-context basis
    units: dict[str, str] = {}
    facts = []
    for el in root.iter():
        name = _local(el.tag)
        ctx = el.get("contextRef")
        if name == "context":
            start = next((c.text for c in el.iter() if _local(c.tag) == "startDate"), None)
            end = next((c.text for c in el.iter() if _local(c.tag) == "endDate"), None)
            if _date(start) and _date(end):
                context_period[el.get("id")] = (_date(start), _date(end))
        elif name == "unit":
            measure = next((c.text for c in el.iter() if _local(c.tag) == "measure"), "")
            units[el.get("id")] = (measure or "").split(":")[-1].strip().upper()
        elif name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod") and ctx:
            key = "start" if name.endswith("StartOfReportingPeriod") else "end"
            d = _date(el.text)
            if d:
                declared.setdefault(ctx, {})[key] = d
        elif name == "NatureOfReportStandaloneConsolidated" and ctx and el.text:
            basis_of[ctx] = el.text.strip().lower()
        elif name in REVENUE_ELEMENTS and ctx:
            facts.append((name, ctx, el.get("unitRef"), (el.text or "").strip()))

    def period_for(ctx: str) -> tuple[date, date] | None:
        """The period a context actually covers: the declared reporting-period facts when
        both are present (they are what the filer asserted the numbers cover), else the
        context's own dates. Never a guess - a context with neither gives None."""
        d = declared.get(ctx) or {}
        if "start" in d and "end" in d:
            return d["start"], d["end"]
        return context_period.get(ctx)

    out = []
    for element in REVENUE_ELEMENTS:
        chosen = [f for f in facts if f[0] == element]
        if not chosen:
            continue
        for _, ctx, unit, text in chosen:
            period = period_for(ctx)
            if period is None or units.get(unit, "INR") != "INR":
                continue
            try:
                value = Decimal(text)
            except InvalidOperation:
                continue
            start, end = period
            basis = basis_of.get(ctx)
            out.append(RevenueFact(start, end, months_between(start, end),
                                   basis if basis in ("consolidated", "standalone") else None,
                                   value, ctx, element))
        break      # the most specific element present wins; never mix two revenue lines
    return out
