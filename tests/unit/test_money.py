"""Unit normalizer against ARCHITECTURE.md §5.7's published test vectors.

These vectors come from the spec, which drew them from real filings before the labelled set
existed. They are the contract the normalizer is built to, and they are deliberately the
*only* thing it is tuned against — tuning it on `tests/labelled/` would make the first score
there a fit rather than a measurement.
"""

from decimal import Decimal

import pytest

from tradebot.units.money import Money, parse_execution_months, parse_money

# (raw string, expected rupees, expected flags) — §5.7's table, verbatim.
VECTORS = [
    ("₹ 13.51 Crs", Decimal("135100000"), set()),
    ("Approx. ₹2.89 Crores", Decimal("28900000"), {"approx"}),
    ("INR 72226994.2/- incl. of GST", Decimal("72226994.20"), {"gst_inclusive"}),
    ("INR 65,02,160.50/-", Decimal("6502160.50"), set()),
    ("INR 17.79 Crores (including GST)", Decimal("177900000"), {"gst_inclusive"}),
    ("Rs. 10.18 Crores New Order (approx.)", Decimal("101800000"), {"approx"}),
    ("Rs. 220.66 Crore", Decimal("2206600000"), set()),
]


@pytest.mark.parametrize("raw,expected,flags", VECTORS)
def test_spec_vectors(raw, expected, flags):
    got = parse_money(raw)
    assert got.value_inr == expected, f"{raw!r} -> {got.value_inr} (flags {got.flags})"
    assert got.currency == "INR"
    # The expected flags must all be present. Extra informational flags are allowed, since
    # the spec lists what must be detected, not what must not be.
    assert flags <= got.flags, f"{raw!r} missing {flags - got.flags}"


def test_value_is_decimal_not_float():
    # 13.51 crore as a float is 135099999.99999999, which would fail the provenance check
    # in §5.6 against a document that prints 13.51.
    got = parse_money("₹ 13.51 Crs")
    assert isinstance(got.value_inr, Decimal)
    assert got.value_inr == Decimal("135100000")


def test_indian_number_words():
    got = parse_money("Rupees Thirteen Crore Fifty One Lakh only")
    assert got.value_inr == Decimal("135100000")
    assert "number_in_words" in got.flags


def test_foreign_currency_is_flagged_and_not_converted():
    got = parse_money("USD 5 million")
    assert got.currency == "USD"
    assert got.value_inr is None, "FX is Open (§11); converting would be guessing a number"
    assert "foreign_currency_not_converted" in got.flags


def test_range_takes_the_low_end_and_flags_it():
    got = parse_money("₹10-12 crore")
    assert "range" in got.flags
    assert got.low_inr == Decimal("100000000")
    assert got.high_inr == Decimal("120000000")
    assert got.value_inr == got.low_inr


def test_undisclosed_value_returns_none_not_zero():
    for raw in ("", None, "Not disclosed", "Confidential"):
        got = parse_money(raw)
        assert got.value_inr is None, f"{raw!r} should not produce a number"


def test_gst_exclusive_is_distinguished_from_inclusive():
    assert "gst_exclusive" in parse_money("Rs. 5 Crore plus GST").flags
    assert "gst_inclusive" in parse_money("Rs. 5 Crore including GST").flags


@pytest.mark.parametrize("raw,months", [
    ("10 Months from Work Order", Decimal("10")),
    ("2 Years", Decimal("24")),
    ("Within 6 months", Decimal("6")),
    ("60 days", Decimal("2")),
    ("18 calendar months", Decimal("18")),
    ("as per the agreement", None),
    ("", None),
])
def test_execution_months(raw, months):
    assert parse_execution_months(raw) == months


def test_absolute_date_is_not_guessed():
    # §5.7 puts absolute dates on the caller, which has the filing date as reference.
    assert parse_execution_months("Delivery Completion is November, 2026") is None


# --- Scale cross-checked against the spelled-out amount (WORKLOG, 25 and 27 Sep 2026) ---

from tradebot.units.money import is_suspect  # noqa: E402


def test_scale_is_taken_from_the_words_when_they_match_exactly():
    # VASCONEQ, 25 Sep 2026: stored as ₹660.79 and marked verified.
    got = parse_money("Rs. 660.79/- (Rupees Six Hundred & Sixty Crore and "
                      "Seventy-Nine Lakhs only)")
    assert got.value_inr == Decimal("6607900000")
    assert "scale_from_words" in got.flags
    assert not is_suspect(got)


def test_a_cut_off_span_with_no_confirmable_scale_is_suspect():
    # The span T0 actually stored for VASCONEQ: the words run onto the next line.
    got = parse_money("or size of the Rs. 660.79/- (Rupees Six Hundred &")
    assert got.value_inr == Decimal("660.79")
    assert is_suspect(got)


def test_a_physical_quantity_is_never_a_trustworthy_rupee_value():
    # WAAREEENER in the labelled set: "2 GW" read as ₹2.
    assert is_suspect(parse_money("Supply of 2 GW Solar modules"))


def test_large_bare_rupee_amounts_stay_trusted():
    for raw in ("INR 72226994.2/- incl. of GST", "INR 65,02,160.50/-"):
        assert not is_suspect(parse_money(raw)), raw


def test_words_that_agree_with_a_rupee_numeral_confirm_it():
    got = parse_money("Rs. 5,00,00,000/- (Rupees Five Crore only)")
    assert got.value_inr == Decimal("50000000")
    assert "words_confirm" in got.flags
    assert not is_suspect(got)


def test_words_that_contradict_the_numeral_make_it_suspect():
    got = parse_money("Rs. 12,00,000/- (Rupees Five Crore only)")
    assert "words_mismatch" in got.flags
    assert is_suspect(got)


def test_scale_word_after_slash_dash_is_read():
    # LCCPROJECT, 25 Sep 2026: stored as ₹58.53 and marked verified.
    got = parse_money("basic order value ₹58.53/- Crore")
    assert got.value_inr == Decimal("585300000")
    assert not is_suspect(got)


def test_a_bare_unit_word_is_not_a_spelled_out_amount():
    got = parse_money("or size of the ₹653.34 crore (including GST)")
    assert got.value_inr == Decimal("6533400000")
    assert "words_mismatch" not in got.flags
