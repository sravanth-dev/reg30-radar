"""revenue/xbrl.py on a synthetic in-capmkt-style instance: the period comes from each
context's dates, never its name; discrete and cumulative facts are told apart; a foreign
unit is refused. Spike C checks the same parser against real NSE files."""

from datetime import date
from decimal import Decimal

from tradebot.revenue.xbrl import months_between, parse

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
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="Instant">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
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
