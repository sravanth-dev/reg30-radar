"""revenue/xbrl.py: the period comes from an actual start/end date, never a context's
*name*, and the basis is read per context, not globally. Spike C (27 Sep 2026) then found
two real defects in NSE's own filed XBRL that the pure "trust context dates" design (this
file's original version) did not survive - both reproduced below from real BEL filings:

1. A Jan-2025 Q3 filing's cumulative context ("FourD") declares the *same* startDate/endDate
   as the discrete quarter's context ("OneD") - a template copy-paste bug - even though its
   revenue is Rs 146.19bn against the quarter's Rs 57.7bn, plainly nine months' worth.
2. A 2018 Q4 filing's revenue facts reference contextRef="OneD"/"FourD", but no such
   `<context>` element exists in the instance at all.

Both filings correctly tag `DateOfStartOfReportingPeriod`/`DateOfEndOfReportingPeriod`
facts in the same context as the revenue figure, and those are right in both cases - so the
parser reads a fact's period from these declared elements first, falling back to the
context's own dates only when no declared pair exists.

`spikes/spike_c_results_xbrl.py`'s saved files carry the real numbers this file's fixtures
are built from; the end-to-end check (Q4 derived from FY - 9M equals BEL's own reported Q4,
to the rupee) was run there, not here, since it needs real downloaded XBRL.
"""

from datetime import date
from decimal import Decimal

from reg30_radar.revenue.xbrl import months_between, parse

INSTANCE = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/capmkt"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <xbrli:context id="Deliberately_Misleading_Name">
    <xbrli:entity><xbrli:identifier scheme="x">BEL</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-10-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="FourD">
    <xbrli:entity><xbrli:identifier scheme="x">BEL</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="Instant">
    <xbrli:entity><xbrli:identifier scheme="x">BEL</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  <xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="Deliberately_Misleading_Name">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="FourD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
  <in-capmkt:RevenueFromOperations contextRef="Deliberately_Misleading_Name" unitRef="INR" decimals="-5">57924000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-5">161000000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="USD" decimals="0">1</in-capmkt:RevenueFromOperations>
  <in-capmkt:Revenue contextRef="FourD" unitRef="INR" decimals="0">999</in-capmkt:Revenue>
</xbrli:xbrl>"""


def test_periods_come_from_context_dates_not_names():
    facts = sorted(parse(INSTANCE), key=lambda f: f.months)
    assert [(f.months, f.revenue_inr) for f in facts] == [
        (3, Decimal("57924000000")), (9, Decimal("161000000000"))]
    assert facts[0].period_end == date(2025, 12, 31)
    assert {f.basis for f in facts} == {"consolidated"}


def test_the_most_specific_revenue_line_wins_and_foreign_units_are_refused():
    facts = parse(INSTANCE)
    assert {f.element for f in facts} == {"RevenueFromOperations"}   # never mixed with "Revenue"
    assert all(f.revenue_inr != 1 for f in facts)                   # the USD fact


def test_months_between():
    assert months_between(date(2025, 4, 1), date(2025, 6, 30)) == 3
    assert months_between(date(2025, 4, 1), date(2025, 12, 31)) == 9
    assert months_between(date(2025, 4, 1), date(2026, 3, 31)) == 12


def test_basis_is_read_per_context_not_globally():
    # A filing with both standalone and consolidated contexts must never stamp every fact
    # with whichever basis happens to be encountered last.
    instance = b"""<?xml version="1.0" encoding="UTF-8"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/capmkt"
                xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="Cons">
        <xbrli:entity><xbrli:identifier scheme="x">X</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>2025-10-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
      </xbrli:context>
      <xbrli:context id="Stand">
        <xbrli:entity><xbrli:identifier scheme="x">X</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>2025-10-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
      </xbrli:context>
      <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
      <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="Cons">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
      <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="Stand">Standalone</in-capmkt:NatureOfReportStandaloneConsolidated>
      <in-capmkt:RevenueFromOperations contextRef="Cons" unitRef="INR" decimals="0">200</in-capmkt:RevenueFromOperations>
      <in-capmkt:RevenueFromOperations contextRef="Stand" unitRef="INR" decimals="0">150</in-capmkt:RevenueFromOperations>
    </xbrli:xbrl>"""
    by_basis = {f.basis: f.revenue_inr for f in parse(instance)}
    assert by_basis == {"consolidated": Decimal(200), "standalone": Decimal(150)}


# --- Real defects found on real NSE filings (Spike C, 27 Sep 2026) ---

def _fact(context_id: str, value: str, *, declared_start: str | None = None,
         declared_end: str | None = None) -> bytes:
    declared = ""
    if declared_start:
        declared += (f'<in-capmkt:DateOfStartOfReportingPeriod contextRef="{context_id}">'
                    f'{declared_start}</in-capmkt:DateOfStartOfReportingPeriod>')
    if declared_end:
        declared += (f'<in-capmkt:DateOfEndOfReportingPeriod contextRef="{context_id}">'
                    f'{declared_end}</in-capmkt:DateOfEndOfReportingPeriod>')
    return (f'<in-capmkt:RevenueFromOperations contextRef="{context_id}" unitRef="INR" '
            f'decimals="-5">{value}</in-capmkt:RevenueFromOperations>{declared}').encode()


def _wrap(*context_and_fact_xml: bytes) -> bytes:
    header = (b'<?xml version="1.0" encoding="UTF-8"?>'
              b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
              b'xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/capmkt" '
              b'xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
              b'<xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>')
    return header + b"".join(context_and_fact_xml) + b"</xbrli:xbrl>"


def _context(context_id: str, start: str, end: str) -> bytes:
    return (f'<xbrli:context id="{context_id}"><xbrli:entity>'
            f'<xbrli:identifier scheme="x">X</xbrli:identifier></xbrli:entity>'
            f'<xbrli:period><xbrli:startDate>{start}</xbrli:startDate>'
            f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>').encode()


def test_a_context_that_lies_about_its_own_period_is_overridden_by_the_declared_fact():
    # BEL's real Jan-2025 filing: "FourD"'s <context> wrongly repeats OneD's dates, but its
    # own DateOfStartOfReportingPeriod/DateOfEndOfReportingPeriod facts are correct.
    instance = _wrap(
        _context("OneD", "2024-10-01", "2024-12-31"),
        _fact("OneD", "57706900000", declared_start="2024-10-01", declared_end="2024-12-31"),
        _context("FourD", "2024-10-01", "2024-12-31"),      # wrong: copied from OneD
        _fact("FourD", "146191600000", declared_start="2024-04-01", declared_end="2024-12-31"),
    )
    facts = {f.context_id: f for f in parse(instance)}
    assert facts["OneD"].months == 3 and facts["OneD"].revenue_inr == Decimal("57706900000")
    assert facts["FourD"].months == 9 and facts["FourD"].revenue_inr == Decimal("146191600000")
    assert facts["FourD"].period_start == date(2024, 4, 1)   # not 2024-10-01 from the context


def test_a_revenue_fact_with_no_context_element_at_all_is_still_read_from_declared_dates():
    # BEL's real 2018 filing: RevenueFromOperations references contextRef="OneD"/"FourD",
    # but no <context id="OneD"> or <context id="FourD"> exists in the instance.
    instance = _wrap(
        _fact("OneD", "36084600000", declared_start="2018-01-01", declared_end="2018-03-31"),
        _fact("FourD", "104006100000", declared_start="2017-04-01", declared_end="2018-03-31"),
    )
    facts = {f.context_id: f for f in parse(instance)}
    assert facts["OneD"].months == 3 and facts["OneD"].period_end == date(2018, 3, 31)
    assert facts["FourD"].months == 12 and facts["FourD"].revenue_inr == Decimal("104006100000")


def test_a_fact_with_neither_a_context_nor_a_declared_period_is_dropped_not_guessed():
    instance = _wrap(_fact("Nowhere", "999"))
    assert parse(instance) == []
