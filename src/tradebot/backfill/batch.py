"""The backfill's LLM extraction through OpenAI's Batch API (CLAUDE.md, §6).

    submit   every `pending_llm` order filing with extracted text becomes one request in
             a Batch, after the worst-case cost is checked against the $3 backfill cap
    collect  finished Batches are read back; each result is judged by
             `llm_extract.interpret`, the same rules as a live call, and written to its
             `order_extractions` row, with its real cost logged to `llm_calls`

§6's retry rule holds: an invalid response is sent once more, with the error fed back, in
a later Batch; a second invalid response goes to `needs_review`. A request that failed or
expired inside a Batch is resubmitted, at most three times in all, then left for review.
Nothing loops: each run of `submit` or `collect` does one pass.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import ValidationError

from tradebot.extractor.llm_extract import PROMPT_VERSION, build_request, interpret
from tradebot.llm.client import LlmClient

log = logging.getLogger("backfill")

PURPOSE = "order_extract"
MAX_SUBMISSIONS = 3
BATCH_SIZE = 2000
TERMINAL = ("completed", "failed", "expired", "cancelled")
INVALID = "invalid batch response: "

PENDING_SQL = """
select oe.raw_announcement_id, d.text, oe.last_error,
       (select count(*) from llm_batch_items i where i.raw_announcement_id = oe.raw_announcement_id)
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

    submitted = []
    for start in range(0, len(items), BATCH_SIZE):
        chunk = items[start:start + BATCH_SIZE]
        batch_id, estimate = client.submit_batch(
            [(cid, body) for cid, _, _, body in chunk], purpose=PURPOSE,
            prompt_version=PROMPT_VERSION)
        with conn.cursor() as cur:
            cur.executemany(
                "insert into llm_batch_items (batch_id, custom_id, raw_announcement_id, attempt)"
                " values (%s,%s,%s,%s)",
                [(batch_id, cid, raw_id, attempt) for cid, raw_id, attempt, _ in chunk])
        conn.commit()
        submitted.append({"batch_id": batch_id, "requests": len(chunk),
                          "worst_case_usd": str(estimate)})
        log.info("submitted %s: %d requests, worst case $%s", batch_id, len(chunk), estimate)
    return {"submitted": submitted, "left_for_review": exhausted}


def collect(conn, client: LlmClient) -> dict:
    open_batches = conn.execute(
        "select batch_id, model from llm_batches where collected_at is null").fetchall()
    summary = {"still_running": 0, "collected": 0, "results": 0, "cost_usd": Decimal("0")}
    for batch_id, model in open_batches:
        batch = client.retrieve_batch(batch_id)
        conn.execute("update llm_batches set status = %s where batch_id = %s",
                     (batch.status, batch_id))
        if batch.status not in TERMINAL:
            summary["still_running"] += 1
            conn.commit()
            continue

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
               provenance_ok = %(prov)s, consideration_raw = %(cons)s, value_span = %(span)s,
               execution_period_raw = %(period)s, awarding_entity = %(awarder)s,
               company_is_recipient = %(recipient)s, stage = %(stage)s,
               llm_cost_usd = llm_cost_usd + %(cost)s, last_error = null,
               processed_at = now()
           where raw_announcement_id = %(raw_id)s""",
        {"status": result.review_status, "value": result.value_inr,
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
