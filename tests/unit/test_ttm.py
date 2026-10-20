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


# --- Q2 = H1 - Q1 (Proposed, 20 Oct 2026) -------------------------------------------------
# 47 Integrated-Filing Q2 files (Nov 2025) carry only the half-year: their quarter context
# holds the Apr-Sep figure. DBL re-filed in Jun 2026 with the quarter, and H1 - Q1 matched it
# to the rupee (4,546.23 - 2,620.34 = 1,925.89 cr); 30 of 45 such checks matched exactly and
# 10 more within the filers' own rounding.

def _half_year_book(h1):
    return [q(date(2025, 3, 31), 90, filed(2025, 5, 20)),
            q(date(2025, 6, 30), 100, filed(2025, 8, 10)),
            q(date(2025, 9, 30), h1, filed(2025, 11, 13), months=6),
            q(date(2025, 12, 31), 120, filed(2026, 2, 10)),
            q(date(2024, 12, 31), 80, filed(2025, 2, 10))]


def test_q2_is_derived_from_the_half_year_minus_q1():
    ttm, basis = ttm_as_of(_half_year_book(210), filed(2026, 3, 1))
    assert ttm == Decimal(90 + 100 + 110 + 120)


def test_a_half_year_that_is_really_a_quarter_derives_nothing():
    # INE0BYP01024's "half-year" was 1.05x Q1 and its later revision changed it: the figure
    # was the quarter, mislabelled. A derived Q2 below 0.4 x Q1 is refused, not used.
    assert ttm_as_of(_half_year_book(105), filed(2026, 3, 1)) == (None, None)


def test_the_derived_q2_is_only_known_once_the_half_year_is_filed():
    assert ttm_as_of(_half_year_book(210), filed(2025, 11, 1)) == (None, None)


def test_a_non_positive_q4_is_never_used():
    book = [q(date(2025, 12, 31), 400, filed(2026, 2, 10), months=9),
            q(date(2026, 3, 31), 380, filed(2026, 5, 20), months=12),   # FY below 9M
            q(date(2025, 6, 30), 100, filed(2025, 8, 10)),
            q(date(2025, 9, 30), 110, filed(2025, 11, 10)),
            q(date(2025, 12, 31), 120, filed(2026, 2, 10))]
    assert ttm_as_of(book, filed(2026, 6, 1)) == (None, None)


def test_a_year_whose_quarters_do_not_add_up_is_reported_not_changed():
    from tradebot.revenue.ttm import fy_mismatches
    good = [q(date(2025, 6, 30), 100, filed(2025, 8, 1)), q(date(2025, 9, 30), 100, filed(2025, 11, 1)),
            q(date(2025, 12, 31), 100, filed(2026, 2, 1)), q(date(2026, 3, 31), 100, filed(2026, 5, 1)),
            q(date(2026, 3, 31), 401, filed(2026, 5, 1), months=12)]
    assert fy_mismatches(good) == []                       # within 2%
    bad = good[:-1] + [q(date(2026, 3, 31), 500, filed(2026, 5, 1), months=12)]
    assert fy_mismatches(bad) == [(date(2026, 3, 31), "consolidated", Decimal(500), Decimal(400))]
