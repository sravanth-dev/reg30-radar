"""The backfill's LLM extraction through OpenAI's Batch API (CLAUDE.md, §6).

    submit   every `pending_llm` order filing with extracted text becomes one request in
             a Batch, after the worst-case cost is checked against the $3 backfill cap
    collect  finished Batches are read back; each result is judged by
             `llm_extract.interpret`, the same rules as a live call, and written to its
             `order_extractions` row, with its real cost logged to `llm_calls`

§6's retry rule holds: an invalid response is sent once more, with the error fed back, in
a later Batch; a second invalid response goes to `needs_review`. A request that failed or
expired inside a Batch is resubmitted, at most three times in all, then left for review.
A batch OpenAI rejected whole (status `failed`) ran no request, so it does not count
toward those three. Nothing loops: each run of `submit` or `collect` does one pass.

One batch per model is in OpenAI's queue at a time, filled to the organisation's
enqueued-token limit (`LlmClient.batch_token_room`): the first backfill batch, 1,415
requests in one file, was rejected whole for passing it. So a large pending set goes out
over several `collect` + `submit` rounds.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import ValidationError

from tradebot.extractor.llm_extract import (PROMPT_VERSION, OrderFields, build_request,
                                            interpret, judge)
from tradebot.llm.client import LlmClient

log = logging.getLogger("backfill")

PURPOSE = "order_extract"
MAX_SUBMISSIONS = 3
TERMINAL = ("completed", "failed", "expired", "cancelled")
INVALID = "invalid batch response: "

PENDING_SQL = """
select oe.raw_announcement_id, d.text, oe.last_error,
       -- submissions so far; a batch rejected whole ('failed') never ran, so not counted
       (select count(*) from llm_batch_items i join llm_batches b using (batch_id)
        where i.raw_announcement_id = oe.raw_announcement_id and b.status <> 'failed')
from order_extractions oe
join documents d on d.id = oe.document_id
where oe.review_status = 'pending_llm'
  and oe.order_related
  and not exists (select 1 from llm_batch_items i join llm_batches b using (batch_id)
                  where i.raw_announcement_id = oe.raw_announcement_id
                    and b.collected_at is null)
order by oe.raw_announcement_id
"""


def submit(conn, client: LlmClient) -> dict:
    rows = conn.execute(PENDING_SQL).fetchall()
    items, exhausted = [], 0
    for raw_id, text, last_error, submissions in rows:
        if submissions >= MAX_SUBMISSIONS:
            _set_review(conn, raw_id, f"batch gave no usable answer in {submissions} tries")
            exhausted += 1
            continue
        retry_error = last_error[len(INVALID):] if (last_error or "").startswith(INVALID) else None
        custom_id = f"oe-{raw_id}-{submissions + 1}"
        items.append((custom_id, raw_id, submissions + 1,
                      build_request(text, client=client, retry_error=retry_error)))
    conn.commit()
    if not items:
        return {"submitted": [], "waiting": 0, "left_for_review": exhausted}

    bodies = [body for _, _, _, body in items]
    room = client.batch_token_room(bodies[0]["model"])
    chunk = items[:client.batch_fit(bodies, room)]
    if not chunk:
        log.info("an earlier %s batch is not collected yet; run batch-collect first",
                 bodies[0]["model"])
        return {"submitted": [], "waiting": len(items), "left_for_review": exhausted}

    batch_id, estimate = client.submit_batch(
        [(cid, body) for cid, _, _, body in chunk], purpose=PURPOSE,
        prompt_version=PROMPT_VERSION)
    with conn.cursor() as cur:
        cur.executemany(
            "insert into llm_batch_items (batch_id, custom_id, raw_announcement_id, attempt)"
            " values (%s,%s,%s,%s)",
            [(batch_id, cid, raw_id, attempt) for cid, raw_id, attempt, _ in chunk])
    conn.commit()
    log.info("submitted %s: %d requests, worst case $%s; %d wait for the next round",
             batch_id, len(chunk), estimate, len(items) - len(chunk))
    return {"submitted": [{"batch_id": batch_id, "requests": len(chunk),
                           "worst_case_usd": str(estimate)}],
            "waiting": len(items) - len(chunk), "left_for_review": exhausted}


def collect(conn, client: LlmClient) -> dict:
    # Only this module's batches: the §6 recheck (backfill/recheck.py) runs its own.
    open_batches = conn.execute(
        "select batch_id, model from llm_batches where collected_at is null and purpose = %s",
        (PURPOSE,)).fetchall()
    summary = {"still_running": 0, "collected": 0, "results": 0, "cost_usd": Decimal("0")}
    for batch_id, model in open_batches:
        batch = client.retrieve_batch(batch_id)
        conn.execute("update llm_batches set status = %s where batch_id = %s",
                     (batch.status, batch_id))
        if batch.status not in TERMINAL:
            summary["still_running"] += 1
            conn.commit()
            continue
        if batch.status == "failed":
            log.warning("%s was rejected whole by OpenAI, no request ran: %s", batch_id,
                        failure_reason(batch))

        items = {cid: (raw_id, attempt) for cid, raw_id, attempt in conn.execute(
            "select custom_id, raw_announcement_id, attempt from llm_batch_items"
            " where batch_id = %s and applied_at is null", (batch_id,))}
        lines = []
        if batch.output_file_id:
            lines += client.read_file(batch.output_file_id).splitlines()
        if batch.error_file_id:
            lines += client.read_file(batch.error_file_id).splitlines()
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            item = items.pop(record.get("custom_id"), None)
            if item is None:
                continue
            cost = _apply(conn, client, batch_id, model, record, *item)
            summary["results"] += 1
            summary["cost_usd"] += cost
            conn.execute("update llm_batch_items set applied_at = now() where batch_id = %s"
                         " and custom_id = %s", (batch_id, record["custom_id"]))
        # Requests with no line at all (an expired batch): left pending_llm, so the next
        # submit sends them again, within MAX_SUBMISSIONS.
        conn.execute(
            "update llm_batches set collected_at = %s, output_file_id = %s,"
            " error_file_id = %s where batch_id = %s",
            (datetime.now(timezone.utc), batch.output_file_id, batch.error_file_id, batch_id))
        conn.commit()
        summary["collected"] += 1
        log.info("collected %s (%s)", batch_id, batch.status)
    return summary


def failure_reason(batch) -> str:
    """OpenAI's own reason for rejecting a whole batch, e.g. token_limit_exceeded."""
    errors = getattr(getattr(batch, "errors", None), "data", None) or []
    return "; ".join(f"{getattr(e, 'code', None)}: {getattr(e, 'message', '')}"
                     for e in errors) or "no reason given"


def _apply(conn, client, batch_id, model, record, raw_id, attempt) -> Decimal:
    """Write one result to its order_extractions row. Returns its logged cost."""
    response = record.get("response") or {}
    body = response.get("body") or {}
    if response.get("status_code") != 200 or record.get("error"):
        client.log_batch_result(batch_id=batch_id, model=model, prompt_version=PROMPT_VERSION,
                                purpose=PURPOSE, tier="t1", usage=body.get("usage"),
                                status="error", error=json.dumps(record.get("error") or body)[:500])
        conn.execute("update order_extractions set last_error = %s where raw_announcement_id = %s",
                     ("batch request failed; resubmitted next run", raw_id))
        return Decimal("0")

    cost = client.log_batch_result(batch_id=batch_id, model=model, prompt_version=PROMPT_VERSION,
                                   purpose=PURPOSE, tier="t1", usage=body.get("usage"),
                                   status="ok")
    text = conn.execute("select d.text from order_extractions oe join documents d"
                        " on d.id = oe.document_id where oe.raw_announcement_id = %s",
                        (raw_id,)).fetchone()[0]
    content = body["choices"][0]["message"].get("content") or ""
    try:
        result = interpret(text, content)
    except (json.JSONDecodeError, ValidationError) as exc:
        if attempt >= 2:
            _set_review(conn, raw_id, f"invalid response twice: {exc}"[:500], cost=cost)
        else:
            conn.execute("update order_extractions set last_error = %s,"
                         " llm_cost_usd = llm_cost_usd + %s where raw_announcement_id = %s",
                         ((INVALID + str(exc))[:500], cost, raw_id))
        return cost

    f = result.fields
    conn.execute(
        """update order_extractions set
               path = 'llm', review_status = %(status)s, value_inr = %(value)s,
               currency = %(currency)s, value_flags = %(flags)s, value_high_inr = %(high)s,
               gst_inclusive = %(gst)s,
               provenance_ok = %(prov)s, consideration_raw = %(cons)s, value_span = %(span)s,
               execution_period_raw = %(period)s, awarding_entity = %(awarder)s,
               company_is_recipient = %(recipient)s, stage = %(stage)s,
               llm_cost_usd = llm_cost_usd + %(cost)s, last_error = null,
               processed_at = now()
           where raw_announcement_id = %(raw_id)s""",
        {"status": result.review_status, "value": result.value_inr,
         "currency": result.currency, "flags": result.value_flags,
         "high": result.value_high_inr, "gst": result.gst_inclusive,
         "prov": result.provenance_ok, "cons": f.consideration_raw, "span": f.value_span,
         "period": f.execution_period_raw, "awarder": f.awarding_entity,
         "recipient": f.company_is_recipient_bool, "stage": f.stage, "cost": cost,
         "raw_id": raw_id},
    )
    return cost


def _set_review(conn, raw_id, reason, cost=Decimal("0")):
    conn.execute("update order_extractions set review_status = 'needs_review', last_error = %s,"
                 " llm_cost_usd = llm_cost_usd + %s where raw_announcement_id = %s",
                 (reason, cost, raw_id))


def reparse(conn) -> dict:
    """Re-apply the deterministic parser (T0) to stored document text, for when a value
    rule changes after the documents were processed (20 Oct 2026: ranges, size legends,
    bounds, currencies; AUDIT.md §3). No download and no model call.

    Touches only filings T0 itself verified. One that still verifies is updated in place.
    One that no longer does becomes `pending_llm`, exactly as a T0 miss would have when it
    was first processed, so the next `batch-submit` sends it to T1. Returns the moves."""
    from tradebot.extractor.llm_extract import gst_of
    from tradebot.orders.run import t0_value

    rows = conn.execute("""
        select oe.raw_announcement_id, d.text, oe.value_inr
        from order_extractions oe join documents d on d.id = oe.document_id
        where oe.path = 't0' and oe.review_status = 'verified'""").fetchall()
    moved = Counter()
    for raw_id, text, before in rows:
        ann, money, span, provenance_ok, ok = t0_value(text)
        if ok:
            conn.execute(
                "update order_extractions set value_inr = %s, value_flags = %s,"
                " value_high_inr = %s, currency = %s, gst_inclusive = %s, provenance_ok = %s,"
                " consideration_raw = %s, value_span = %s where raw_announcement_id = %s",
                (money.value_inr, sorted(money.flags) or None, money.high_inr, money.currency,
                 gst_of(money), provenance_ok, ann.raw("consideration_raw"), span, raw_id))
            moved["verified -> verified" + (" (value changed)" if money.value_inr != before
                                             else "")] += 1
        else:
            conn.execute(
                "update order_extractions set path = 'llm', review_status = 'pending_llm',"
                " value_inr = null, value_flags = %s, last_error = %s"
                " where raw_announcement_id = %s",
                (sorted(money.flags) or None,
                 "T0 value no longer verifies under the 20 Oct 2026 rules; sent to T1", raw_id))
            moved["verified -> pending_llm"] += 1
    conn.commit()
    return dict(moved)


_RECIPIENT = {True: "true", False: "false", None: "unknown"}
_STAGES = {"L1", "LoI", "LoA", "PO", "contract", "amendment", "unknown"}


def rejudge(conn) -> dict:
    """Re-apply the current verification rules (`llm_extract.judge`) to model answers
    already stored, without calling the model, for when a rule changes after the answers
    came back. 29 Sep 2026: an unknown stage no longer blocks, provenance accepts a verbatim
    part of the quote, and USD converts at config/fx.yaml's rate.

    Touches only answers the model judged to be an order (`verified` or `needs_review` with
    no error recorded). `not_order`, and review items that never got a usable answer, keep
    their outcome. Returns how many rows moved between statuses."""
    rows = conn.execute("""
        select oe.raw_announcement_id, d.text, oe.consideration_raw, oe.value_span,
               oe.company_is_recipient, oe.stage, oe.review_status
        from order_extractions oe join documents d on d.id = oe.document_id
        where oe.path = 'llm' and oe.review_status in ('verified', 'needs_review')
          and oe.last_error is null""").fetchall()
    moved = Counter()
    for raw_id, text, cons, span, recipient, stage, before in rows:
        fields = OrderFields(
            is_order_announcement=True, company_is_recipient=_RECIPIENT[recipient],
            consideration_raw=cons, value_span=span, awarding_entity=None,
            nature_of_order=None, execution_period_raw=None, domestic_or_international=None,
            stage=stage if stage in _STAGES else "unknown")
        result = judge(text, fields)
        conn.execute(
            "update order_extractions set review_status = %s, value_inr = %s,"
            " provenance_ok = %s, currency = %s, value_flags = %s, value_high_inr = %s,"
            " gst_inclusive = %s where raw_announcement_id = %s",
            (result.review_status, result.value_inr, result.provenance_ok, result.currency,
             result.value_flags, result.value_high_inr, result.gst_inclusive, raw_id))
        moved[f"{before} -> {result.review_status}"] += 1
    conn.commit()
    return dict(moved)
