"""extractor/provenance.py (§5.6): a value is trusted only if its span is really in the
document AND parses back to the same number - substring presence alone is not enough.
"""

from __future__ import annotations

from decimal import Decimal

from reg30_radar.extractor.provenance import verify

DOC = (
    "Sub: Bagging of orders.\n"
    "We wish to inform that the Company has received a work order worth Rs. 13.51 Crs "
    "from ABC Ltd, dated 01.01.2026, for supply of components."
)


def test_span_present_and_value_matches_verifies():
    assert verify(DOC, "Rs. 13.51 Crs", Decimal("135100000")) is True


def test_span_absent_fails_even_if_the_value_is_correct():
    assert verify(DOC, "Rs. 99.00 Crs", Decimal("990000000")) is False


def test_span_present_but_wrong_value_fails():
    # The exact failure mode this check exists to catch: a real quote, a hallucinated
    # number.
    assert verify(DOC, "Rs. 13.51 Crs", Decimal("1")) is False


def test_substring_only_would_have_been_fooled_by_this_but_verify_is_not():
    # "13.51" alone is a substring of the document, but on its own it parses to 13.51
    # rupees, not 13.51 crore - the second check (parse the span, compare the value) is
    # what a naive `span in doc_text` check would miss entirely.
    assert verify(DOC, "13.51", Decimal("135100000")) is False


def test_none_span_fails():
    assert verify(DOC, None, Decimal("135100000")) is False


def test_none_value_fails():
    assert verify(DOC, "Rs. 13.51 Crs", None) is False


def test_whitespace_differences_are_tolerated():
    # pdfplumber can render the same text with different internal spacing between reads;
    # the check collapses whitespace runs on both sides, but corrects nothing else.
    messy_doc = "Rs.\n   13.51   Crs   was the order value"
    assert verify(messy_doc, "Rs. 13.51 Crs", Decimal("135100000")) is True


def test_reworded_span_is_not_verbatim_and_fails():
    # The span must be an exact quote, not a paraphrase - "verbatim" is enforced, not
    # just "the same number appears somewhere".
    assert verify(DOC, "Rs 13.51 crore", Decimal("135100000")) is False


# RAILTEL, 2026: the PDF table's label column lands inside the value in the extracted text.
TABLE_DOC = ("h) Value of order as per Work Order is Rs.\n(in INR); 38,59,27,045/-(ExcludingTax)\n"
             "i) Whether the promoter has any interest: No")


def test_a_quote_split_by_an_interleaved_table_column_verifies_on_its_verbatim_part():
    # The model quotes "Rs. 38,59,27,045/-(ExcludingTax)" as a reader sees it; that is not
    # one piece of the text, but "38,59,27,045/-(ExcludingTax)" is, and gives the same
    # value (Sravanth, 29 Sep 2026: 51 of 54 such answers in the first batch).
    assert verify(TABLE_DOC, "Rs.\n38,59,27,045/-(ExcludingTax)", Decimal("385927045")) is True


def test_a_verbatim_part_that_gives_a_different_number_still_fails():
    # Allowing a part must not let a real passage vouch for a number it doesn't state.
    assert verify(TABLE_DOC, "Rs.\n38,59,27,045/-(ExcludingTax)", Decimal("3859270450")) is False
    assert verify(DOC, "worth Rs. 13.51 Crs from ABC", Decimal("1351")) is False
