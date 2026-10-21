"""extractor/llm_extract.py: the T1 fallback, offline with a fake LlmClient.

Covers the retry-once-then-review rule (§6), the provenance gate applying identically to
an LLM answer as to the parser's, and that document text is never echoed back as an
instruction - only ever wrapped as data (CLAUDE.md).
"""

from __future__ import annotations

import json
from decimal import Decimal

from reg30_radar.extractor.llm_extract import ORDER_FIELDS_SCHEMA, extract_order_fields
from reg30_radar.llm.client import LlmRefused, LlmResult

DOC = (
    "We wish to inform that the Company has received a work order worth Rs. 13.51 Crs "
    "from ABC Ltd for supply of components, to be executed domestically within 18 months."
)

GOOD_FIELDS = {
    "is_order_announcement": True,
    "company_is_recipient": "true",
    "consideration_raw": "Rs. 13.51 Crs",
    "value_span": "Rs. 13.51 Crs",
    "awarding_entity": "ABC Ltd",
    "nature_of_order": "supply of components",
    "execution_period_raw": "18 months",
    "domestic_or_international": "domestic",
    "stage": "PO",
}


class FakeClient:
    """Returns each entry in `responses` in order, one per call; raises `refuse` instead
    if given.
    """

    def __init__(self, responses: list[str] | None = None, refuse: Exception | None = None):
        self.responses = list(responses or [])
        self.refuse = refuse
        self.calls: list[dict] = []

    def extract_json(self, document_text, **kwargs):
        self.calls.append({"document_text": document_text, **kwargs})
        if self.refuse:
            raise self.refuse
        text = self.responses.pop(0)
        return LlmResult(text=text, model="fake", in_tokens=10, out_tokens=10,
                          cached_tokens=0, cost_usd=Decimal("0.0001"))


def test_valid_response_first_try_is_verified():
    client = FakeClient([json.dumps(GOOD_FIELDS)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "verified"
    assert result.value_inr == Decimal("135100000")
    assert result.provenance_ok is True
    assert result.attempts == 1
    assert len(client.calls) == 1


def test_span_that_does_not_match_the_document_needs_review():
    bad = dict(GOOD_FIELDS, value_span="Rs. 99.00 Crs")   # not in DOC
    client = FakeClient([json.dumps(bad)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "needs_review"
    assert result.provenance_ok is False


def test_not_an_order_announcement_is_reported_as_such_with_no_provenance_check():
    fields = dict(GOOD_FIELDS, is_order_announcement=False)
    client = FakeClient([json.dumps(fields)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "not_order"
    assert result.value_inr is None


def test_unknown_recipient_forces_review_even_with_good_provenance():
    fields = dict(GOOD_FIELDS, company_is_recipient="unknown")
    client = FakeClient([json.dumps(fields)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "needs_review"
    # §6 trigger 3 fired; the value itself may still be right (provenance_ok can be true),
    # but the escalation is what gates `verified`, not the number alone.
    assert result.provenance_ok is True


def test_unknown_stage_no_longer_forces_review():
    # Sravanth, 29 Sep 2026: stage is not used by the verdict, and an unknown stage alone
    # had sent 112 verified values to review. An unknown recipient still does (above).
    fields = dict(GOOD_FIELDS, stage="unknown")
    client = FakeClient([json.dumps(fields)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "verified"
    assert result.currency == "INR"


# --------------------------------------------------------------------- retry-once rule

def test_invalid_json_retries_once_then_succeeds():
    client = FakeClient(["not json at all", json.dumps(GOOD_FIELDS)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "verified"
    assert result.attempts == 2
    assert len(client.calls) == 2
    # The retry call must carry feedback about the failure, and it must not be silent.
    assert client.calls[1]["retry_note"]
    assert client.calls[0].get("retry_note") is None


def test_invalid_json_twice_gives_up_to_needs_review():
    client = FakeClient(["not json", "still not json"])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "needs_review"
    assert result.attempts == 2
    assert len(client.calls) == 2


def test_schema_violation_also_triggers_one_retry():
    # Missing a required field - valid JSON, invalid against OrderFields.
    incomplete = {k: v for k, v in GOOD_FIELDS.items() if k != "stage"}
    client = FakeClient([json.dumps(incomplete), json.dumps(GOOD_FIELDS)])
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "verified"
    assert result.attempts == 2


# --------------------------------------------------------------------- cap / refusal

def test_llm_refused_comes_back_pending_not_needs_review():
    client = FakeClient(refuse=LlmRefused("cap reached"))
    result = extract_order_fields(DOC, client=client)
    assert result.review_status == "pending_llm"
    assert result.cost_usd == Decimal("0")


# --------------------------------------------------------------------- prompt safety

def test_document_text_is_passed_as_data_not_merged_into_instructions():
    client = FakeClient([json.dumps(GOOD_FIELDS)])
    extract_order_fields(DOC, client=client)
    call = client.calls[0]
    assert call["document_text"] == DOC
    assert call["prompt_version"] == "order_extract_v1"
    assert call["schema_name"] == "order_fields"
    assert call["json_schema"] is ORDER_FIELDS_SCHEMA


def test_cost_accumulates_across_a_retry():
    client = FakeClient(["bad", json.dumps(GOOD_FIELDS)])
    result = extract_order_fields(DOC, client=client)
    assert result.cost_usd == Decimal("0.0002")   # two calls, 0.0001 each
