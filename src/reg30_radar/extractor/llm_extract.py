"""LLM field extraction for one order filing (§6 T1) - the fallback the router only offers
when T0 (the annexure parser) couldn't produce a provenance-verified value.

The model returns raw strings and an exact quoted span only, never a number (§5.6: "The
model never normalizes"). Every conversion runs through `units.money.parse_money`, the same
function T0 uses, and the result is checked by the same `extractor.provenance.verify` - so
an LLM-sourced value and a parser-sourced value are held to one identical standard, not two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ValidationError

from reg30_radar.extractor.provenance import verify as verify_provenance
from reg30_radar.llm.client import LlmClient, LlmProviderError, LlmRefused, LlmResult
from reg30_radar.units.money import is_suspect, parse_money

PROMPT_VERSION = "order_extract_v1"
SCHEMA_NAME = "order_fields"

# Hand-written, not generated from the Pydantic model below: OpenAI's strict structured
# output mode requires every property in `required` and forbids a bare default, which the
# model's `null`-means-"not stated" fields don't naturally express through
# `model_json_schema()`. Keeping the two in one file, next to each other, is what keeps
# them from drifting apart - a field added to one and not the other fails loudly in
# `test_llm_extract.py`, not silently in production.
ORDER_FIELDS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "is_order_announcement": {"type": "boolean"},
        "company_is_recipient": {"type": "string", "enum": ["true", "false", "unknown"]},
        "consideration_raw": {"type": ["string", "null"]},
        "value_span": {"type": ["string", "null"]},
        "awarding_entity": {"type": ["string", "null"]},
        "nature_of_order": {"type": ["string", "null"]},
        "execution_period_raw": {"type": ["string", "null"]},
        "domestic_or_international": {"type": ["string", "null"]},
        "stage": {
            "type": "string",
            "enum": ["L1", "LoI", "LoA", "PO", "contract", "amendment", "unknown"],
        },
    },
    "required": [
        "is_order_announcement", "company_is_recipient", "consideration_raw", "value_span",
        "awarding_entity", "nature_of_order", "execution_period_raw",
        "domestic_or_international", "stage",
    ],
    "additionalProperties": False,
}


class OrderFields(BaseModel):
    is_order_announcement: bool
    company_is_recipient: Literal["true", "false", "unknown"]
    consideration_raw: str | None
    value_span: str | None
    awarding_entity: str | None
    nature_of_order: str | None
    execution_period_raw: str | None
    domestic_or_international: str | None
    stage: Literal["L1", "LoI", "LoA", "PO", "contract", "amendment", "unknown"]

    @property
    def company_is_recipient_bool(self) -> bool | None:
        return {"true": True, "false": False, "unknown": None}[self.company_is_recipient]


@dataclass
class ExtractResult:
    review_status: str            # "verified" | "needs_review" | "not_order" | "pending_llm"
    fields: OrderFields | None = None
    value_inr: Decimal | None = None
    provenance_ok: bool = False
    currency: str | None = None   # as stated; non-INR with a value_inr means converted
    value_flags: list[str] | None = None    # units/money.py's flags, e.g. lower_bound (D32)
    value_high_inr: Decimal | None = None   # the high end of a range
    gst_inclusive: bool | None = None
    cost_usd: Decimal = Decimal("0")
    attempts: int = 0
    error: str | None = None


def _parse_and_validate(raw_text: str) -> OrderFields:
    """Raises ValueError (JSON) or pydantic.ValidationError (schema) - both are what
    `extract_order_fields` retries once on, per §6.
    """
    data = json.loads(raw_text)
    return OrderFields(**data)


def interpret(document_text: str, raw_text: str) -> ExtractResult:
    """What one model response means for one filing. Shared by the live call below and the
    backfill's Batch results (backfill/batch.py), so both are judged by identical rules.

    Raises json.JSONDecodeError or pydantic.ValidationError on an invalid response; the
    caller decides whether that earns the one retry §6 allows.
    """
    return judge(document_text, _parse_and_validate(raw_text))


def gst_of(money) -> bool | None:
    """True/False when the consideration says GST is in or out, None when it is silent."""
    if "gst_inclusive" in money.flags:
        return True
    if "gst_exclusive" in money.flags:
        return False
    return None


def judge(document_text: str, fields: OrderFields) -> ExtractResult:
    """The verification rules for one set of extracted fields. Separate from `interpret`
    so `backfill.batch.rejudge` can re-apply them to answers already stored, when a rule
    changes after the answers came back, without asking the model again."""
    if not fields.is_order_announcement:
        return ExtractResult(review_status="not_order", fields=fields)

    money = parse_money(fields.consideration_raw)
    provenance_ok = verify_provenance(document_text, fields.value_span, money.value_inr)
    # A suspect scale (units/money.py) is never verified, whatever provenance says.
    status = "verified" if provenance_ok and not is_suspect(money) else "needs_review"
    # §6 trigger 3, narrowed by Sravanth on 29 Sep 2026: an unknown recipient still sends
    # the order to review (the verdict needs the company to have won it), but an unknown
    # stage no longer does. Stage is not used by the verdict, and it alone had sent 112 of
    # the first batch's 369 reviews there with a verified value.
    if fields.company_is_recipient == "unknown":
        status = "needs_review"
    return ExtractResult(review_status=status, fields=fields, value_inr=money.value_inr,
                         provenance_ok=provenance_ok,
                         currency=money.currency if fields.consideration_raw else None,
                         value_flags=sorted(money.flags) or None,
                         value_high_inr=money.high_inr, gst_inclusive=gst_of(money))


RETRY_NOTE = ("Your previous response was invalid and could not be used: {error}. Return a "
              "single JSON object that matches the schema exactly, with every field present.")


def build_request(document_text: str, *, client: LlmClient, retry_error: str | None = None,
                  tier: str = "t1") -> dict:
    """The request body for one filing, for a Batch file (backfill/batch.py)."""
    return client.extraction_body(
        document_text, prompt_version=PROMPT_VERSION, schema_name=SCHEMA_NAME,
        json_schema=ORDER_FIELDS_SCHEMA, tier=tier,
        retry_note=RETRY_NOTE.format(error=retry_error) if retry_error else None,
    )


def extract_order_fields(document_text: str, *, client: LlmClient) -> ExtractResult:
    """One order filing, T1. Retries once on an invalid response with the error fed back
    (§6), then gives up to `needs_review` rather than looping. A cap refusal or any other
    `LlmRefused` comes back as `pending_llm`, never as a review item - nothing was spent
    and nothing failed, the call simply could not be made yet (§6: "at a cap, items wait").
    """
    total_cost = Decimal("0")
    retry_note: str | None = None

    for attempt in (1, 2):
        try:
            result: LlmResult = client.extract_json(
                document_text, prompt_version=PROMPT_VERSION, schema_name=SCHEMA_NAME,
                json_schema=ORDER_FIELDS_SCHEMA, retry_note=retry_note,
            )
        except LlmRefused as exc:
            return ExtractResult(review_status="pending_llm", cost_usd=total_cost,
                                  attempts=attempt - 1, error=str(exc))
        except LlmProviderError as exc:
            # The provider failed, not the document: wait and retry later (GATE 1 audit).
            return ExtractResult(review_status="pending_llm", cost_usd=total_cost,
                                  attempts=attempt - 1, error=f"provider error: {exc}")

        total_cost += result.cost_usd
        try:
            outcome = interpret(document_text, result.text)
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 1:
                retry_note = RETRY_NOTE.format(error=exc)
                continue
            return ExtractResult(review_status="needs_review", cost_usd=total_cost,
                                  attempts=attempt, error=f"invalid response twice: {exc}")

        outcome.cost_usd = total_cost
        outcome.attempts = attempt
        return outcome

    # Unreachable (the loop always returns), but keeps the function's return type honest.
    return ExtractResult(review_status="needs_review", cost_usd=total_cost, attempts=2,
                          error="exhausted retries")
