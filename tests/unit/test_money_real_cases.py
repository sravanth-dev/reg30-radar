"""Value-reading rules settled at GATE 1 (20 Oct 2026), each pinned by a string that was
really stored as a *verified* value in the backfill database. See AUDIT.md §3.

- D32 (Sravanth): "over Rs X" counts as X, flagged `lower_bound`; a range counts as its low
  end, flagged `range`; a size legend has no figure (`band_only`).
- Proposed with it: a ceiling ("up to") is never verified; nothing that does not say it is
  money is verified; a foreign currency without a configured rate is never converted.
"""

from decimal import Decimal

import pytest

from tradebot.extractor.provenance import verify
from tradebot.units.money import has_currency_marker, is_suspect, parse_money

CRORE = Decimal(10) ** 7


# --- ranges and legends ----------------------------------------------------------------

def test_a_band_with_no_scale_is_never_verified():
    # L&T: "2,500 to 5,000" was stored as a verified Rs 2,500. The crore is only in a table
    # header elsewhere, so the quote cannot show the scale.
    got = parse_money("2,500 to 5,000")
    assert "range" in got.flags and got.value_inr == Decimal("2500")
    assert is_suspect(got)


def test_a_scale_printed_before_the_band_is_read():
    got = parse_money("₹ Cr 1,000 to 2,500")
    assert got.low_inr == 1000 * CRORE and got.high_inr == 2500 * CRORE
    assert got.value_inr == got.low_inr and "range" in got.flags
    assert not is_suspect(got)


@pytest.mark.parametrize("legend", [
    "in Rs. Crore 100 to 250 250 to 500 500 to 1000 1000 to 2000 Above 2000",   # COCHINSHIP
    "in Rs. 0 to 250 251 to 750 751 to 1500 1501 to 3000 Above 3000",           # SWANDEF
])
def test_a_size_legend_has_no_figure(legend):
    got = parse_money(legend)
    assert got.value_inr is None and "band_only" in got.flags
    assert is_suspect(got)


def test_a_date_is_not_a_range():
    got = parse_money("Rs. 13.51 Crs dated 01-02-2026")
    assert "range" not in got.flags and got.value_inr == Decimal("135100000")


def test_a_span_of_years_is_not_a_range():
    got = parse_money("Rs 50 crore for FY 2024-2025")
    assert "range" not in got.flags and got.value_inr == 50 * CRORE


def test_a_spec_range_still_reads():
    got = parse_money("₹10-12 crore")
    assert got.value_inr == 10 * CRORE and got.high_inr == 12 * CRORE


# --- bounds (D32) -----------------------------------------------------------------------

def test_over_is_a_flagged_lower_bound_that_still_counts():
    got = parse_money("over ₹ 5,400/-\nCrores")                         # BEML, 18 Sep 2026
    assert got.value_inr == 5400 * CRORE and "lower_bound" in got.flags
    assert not is_suspect(got)


def test_more_than_and_in_excess_of_are_lower_bounds():
    for raw in ("worth more than Rs. 100 crore", "in excess of INR 250 Crores"):
        assert "lower_bound" in parse_money(raw).flags, raw


def test_a_ceiling_is_never_verified():
    got = parse_money("or size of Not exceeding Rs. 12 crores (approx.)")
    assert "upper_bound" in got.flags and "lower_bound" not in got.flags
    assert is_suspect(got)


# --- currency ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,code", [
    ("or size of the : RM 6,465,400.80 (Ringgit Malaysia Six", "MYR"),
    ("or size of the : KWD 875,000 (Eight hundred", "KWD"),
    ("SAR 12,50,000", "SAR"),
])
def test_foreign_currencies_without_a_rate_are_never_rupees(raw, code):
    got = parse_money(raw)
    assert got.currency == code and got.value_inr is None
    assert "foreign_currency_not_converted" in got.flags


def test_us_dollars_written_out_still_convert():
    got = parse_money("US Dollars 1,495,000")
    assert got.currency == "USD" and got.value_inr == Decimal("140530000.00")
    assert not is_suspect(got)


def test_a_quantity_with_no_currency_is_never_verified():
    got = parse_money("or size of Approximately 2,00,000 Numbers of")
    assert "no_currency_marker" in got.flags and is_suspect(got)
    # also a bare Indian-grouped number: plausible rupees, but nothing says so
    assert is_suspect(parse_money("or size of order(s)/contract(s) 48,77,92,166"))


def test_markers_are_whole_words_not_fragments():
    assert not has_currency_marker("Supply of 500 MT for the term of the platform orders")
    assert has_currency_marker("Rs. 5 Crore") and has_currency_marker("65,02,160.50/-")
    assert has_currency_marker("13.51 Crores")
    assert parse_money("USD 5 million").currency == "USD"


def test_below_one_lakh_is_never_verified_even_when_words_agree():
    got = parse_money("Rs. 50,000/- (Rupees Fifty Thousand only)")
    assert got.value_inr == Decimal("50000") and is_suspect(got)


# --- provenance ---------------------------------------------------------------------------

def test_provenance_rejects_a_dropped_digit():
    assert not verify("Order value Rs. 113.51 Crs.", "Rs. 13.51 Crs", Decimal("135100000"))
    assert not verify("Order value Rs. 13.515 Crs.", "13.51 Crs", Decimal("135100000"))


def test_provenance_still_accepts_the_real_quote():
    assert verify("Order value Rs. 13.51 Crs.", "Rs. 13.51 Crs", Decimal("135100000"))
    # RAILTEL: the label column lands inside the value; a verbatim part still verifies
    doc = "Broad consideration Rs.\n(in INR); 38,59,27,045/-"
    assert verify(doc, "Rs. 38,59,27,045/-", Decimal("385927045"))


# --- formats found reading the review queue (20 Oct 2026) -------------------------------

def test_international_number_words_confirm_a_foreign_numeral():
    got = parse_money("USD 3,600,000.00 (USD Three Million Six Hundred Thousand only)")  # RITES
    assert got.value_inr == Decimal("338400000.00") and "words_confirm" in got.flags
    assert not is_suspect(got)


def test_a_plus_after_the_number_is_a_lower_bound_and_keeps_the_scale():
    got = parse_money("₹400+ Crores")                                       # BAJEL
    assert got.value_inr == 400 * CRORE and "lower_bound" in got.flags
    assert not is_suspect(got)


def test_a_scale_in_a_parenthetical_after_the_number_is_read():
    got = parse_money("12.185 (Rs. In crore)")                              # CEIGALL
    assert got.value_inr == Decimal("121850000") and not is_suspect(got)


def test_a_cut_off_spelled_amount_still_cannot_confirm():
    # ABINFRA: the quote stops mid-words, so the words disagree with the numeral and the
    # value stays out of verified, as before.
    got = parse_money("Rs. 42,68,20,821.94 (Rupees Forty-Two Crore Sixty-Eight Lakh")
    assert is_suspect(got)


# --- found by the gated T0 eval (20 Oct 2026) --------------------------------------------

def test_an_exact_restatement_of_the_rounded_figure_wins():
    got = parse_money("₹44.60 Lakh (Rs. 44,60,400/-)")                      # MCLOUD
    assert got.value_inr == Decimal("4460400")
    assert parse_money("Rs. 44,60,400/- (₹44.60 Lakh)").value_inr == Decimal("4460400")


def test_a_second_amount_that_is_not_a_restatement_is_ignored():
    # Outside half a unit of the rounded figure's last digit: a different amount.
    assert parse_money("Rs. 13.51 Crore (Rs. 1,35,12,345/-)").value_inr == 135100000
    assert parse_money("₹ 10.5 Crore (Rs 2,50,000 advance)").value_inr == Decimal("105000000")
    # A different currency is never a restatement.
    assert parse_money("INR 651 Crores (USD 73.47 million)").value_inr == 651 * CRORE


def test_a_numeral_with_two_dots_gives_no_value():
    # HCC: "~2.917.6 crore" (dots as thousands separators) was read as Rs 6 crore.
    got = parse_money("d at approximately ~2.917.6 crore from City and")
    assert got.value_inr is None and "malformed_number" in got.flags
    # A dotted date beside a real amount is not the chosen numeral, and still reads.
    assert parse_money("LoA dated 24.04.2026 for Rs. 50 Crore").value_inr == 50 * CRORE
