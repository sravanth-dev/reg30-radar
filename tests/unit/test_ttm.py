"""revenue/ttm.py: point-in-time TTM, Q4 = FY - 9M, one basis, consecutive quarters."""

from datetime import date, datetime, timezone
from decimal import Decimal

from tradebot.revenue.ttm import Period, ttm_as_of


def filed(y, m, d):
    return datetime(y, m, d, 18, 0, tzinfo=timezone.utc)


def q(end, value, when, months=3, basis="consolidated"):
    return Period(end, months, basis, Decimal(value), when)


# FY ends 31 Mar. Q1 Jun, Q2 Sep, Q3 Dec filed ~6 weeks after; FY (and so Q4) in May.
BOOK = [
    q(date(2025, 6, 30), 100, filed(2025, 8, 10)),
    q(date(2025, 9, 30), 110, filed(2025, 11, 10)),
    q(date(2025, 12, 31), 120, filed(2026, 2, 10)),
    q(date(2025, 12, 31), 330, filed(2026, 2, 10), months=9),
    q(date(2026, 3, 31), 460, filed(2026, 5, 20), months=12),   # Q4 = 460 - 330 = 130
    q(date(2026, 6, 30), 140, filed(2026, 8, 10)),
    q(date(2025, 3, 31), 90, filed(2025, 5, 20)),               # the previous year's Q4
]


def test_q4_is_derived_from_the_full_year_minus_nine_months():
    assert ttm_as_of(BOOK, filed(2026, 6, 1)) == (Decimal(100 + 110 + 120 + 130), "consolidated")


def test_only_results_filed_before_the_moment_count():
    # On 15 Aug 2026 the June 2026 quarter (filed 10 Aug) is known: 110+120+130+140.
    assert ttm_as_of(BOOK, filed(2026, 8, 15))[0] == Decimal(500)
    # On 9 Aug it is not, even though the quarter had already ENDED (rule 1).
    assert ttm_as_of(BOOK, filed(2026, 8, 9))[0] == Decimal(460)


def test_a_missing_quarter_gives_none_not_a_guess():
    gappy = [p for p in BOOK if p.period_end != date(2025, 9, 30)]
    assert ttm_as_of(gappy, filed(2026, 6, 1)) == (None, None)


def test_bases_are_never_mixed_and_standalone_is_the_fallback():
    standalone = [Period(p.period_end, p.months, "standalone", p.revenue_inr * 2, p.filed_at)
                  for p in BOOK]
    mixed = [p for p in BOOK if p.period_end != date(2025, 12, 31)] + standalone
    value, basis = ttm_as_of(mixed, filed(2026, 6, 1))
    assert basis == "standalone" and value == Decimal(2 * (100 + 110 + 120 + 130))


def test_a_restatement_filed_later_replaces_the_original_only_from_then_on():
    restated = BOOK + [q(date(2025, 9, 30), 150, filed(2026, 7, 1))]
    assert ttm_as_of(restated, filed(2026, 6, 1))[0] == Decimal(460)
    assert ttm_as_of(restated, filed(2026, 7, 2))[0] == Decimal(500)
