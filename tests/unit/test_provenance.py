"""extractor/provenance.py (§5.6): a value is trusted only if its span is really in the
document AND parses back to the same number - substring presence alone is not enough.
"""

from __future__ import annotations

from decimal import Decimal

from tradebot.extractor.provenance import verify

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
