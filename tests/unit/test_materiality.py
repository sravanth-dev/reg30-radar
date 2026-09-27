"""calculator/materiality.py: §5.10's ratios and flags, and §5.7's execution periods."""

from datetime import date
from decimal import Decimal

from tradebot.calculator.materiality import compute, execution_months

CR = Decimal(10) ** 7


def test_the_three_ratios():
    m = compute(Decimal(50) * CR, ttm_revenue_inr=Decimal(200) * CR,
                mcap_inr=Decimal(1000) * CR, execution_months=Decimal(24))
    assert m.value_to_ttm == Decimal("0.250000")
    assert m.value_to_mcap == Decimal("0.050000")
    assert m.next12m_to_ttm == Decimal("0.125000")      # a 24-month order counts half
    assert m.flags == set()


def test_a_short_order_is_not_scaled_up():
    m = compute(Decimal(50) * CR, ttm_revenue_inr=Decimal(200) * CR,
                mcap_inr=Decimal(1000) * CR, execution_months=Decimal(6))
    assert m.next12m_to_ttm == m.value_to_ttm


def test_small_ratios_keep_their_precision():
    # 0.4% must not round to zero (§7: ratios are NUMERIC(12,6), not money).
    m = compute(Decimal(4) * CR, ttm_revenue_inr=Decimal(1000) * CR, mcap_inr=None,
                execution_months=None)
    assert m.value_to_ttm == Decimal("0.004000")


def test_missing_inputs_give_null_ratios_and_flags_never_guesses():
    m = compute(Decimal(10) * CR, ttm_revenue_inr=None, mcap_inr=None, execution_months=None)
    assert (m.value_to_ttm, m.value_to_mcap, m.next12m_to_ttm) == (None, None, None)
    assert {"missing_ttm", "missing_mcap"} <= m.flags


def test_flags_for_an_order_bigger_than_revenue_and_a_tiny_value():
    assert "manual_review" in compute(Decimal(300) * CR, ttm_revenue_inr=Decimal(200) * CR,
                                      mcap_inr=None, execution_months=None).flags
    assert "suspect_parse" in compute(Decimal("660.79"), ttm_revenue_inr=Decimal(200) * CR,
                                      mcap_inr=None, execution_months=None).flags


def test_execution_periods_from_section_5_7():
    filed = date(2026, 9, 18)
    assert execution_months("10 Months from Work Order", filed) == Decimal(10)
    assert execution_months("2 Years", filed) == Decimal(24)
    assert execution_months("Within 6 months", filed) == Decimal(6)
    assert execution_months("60 days", filed) == Decimal(2)
    assert execution_months("Delivery Completion is November, 2026", filed) == Decimal(2)
    assert execution_months("as per the contract terms", filed) is None
    assert execution_months("completed by March 2020", filed) is None   # before the filing
