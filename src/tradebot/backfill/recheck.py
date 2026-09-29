"""§6's independent recheck of high-stakes orders, through the Batch API.

An event in `recheck_pending` (value ≥ 15% of market cap, or market cap or TTM unknown) is
extracted again by `tier2_model` from the document text alone. That model never sees tier
1's answer, which is what makes the second read independent. If both reads agree on
`value_inr` and `company_is_recipient`, the event becomes `verified`; if they disagree,
or the recheck cannot give an answer, it goes to `needs_review`. An event is rechecked at
most once, plus one retry of an invalid response (§6), so the loop cannot run twice.

With `tier2_model` set to gpt-6-luna "for now" (Sravanth, 27 Sep 2026), the second read is
the same model reading blind. That catches a misread that does not repeat, but not one
the model makes every time.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from tradebot.backfill.batch import failure_reason
from tradebot.backfill.events import log_transition
from tradebot.extractor.llm_extract import PROMPT_VERSION, build_request, interpret
from tradebot.llm.client import LlmClient

log = logging.getLogger("backfill")

PURPOSE = "recheck"
TERMINAL = ("completed", "failed", "expired", "cancelled")

PENDING_SQL = """
select e.id, e.primary_raw_id, d.text,
       -- tries so far; a batch rejected whole ('failed') never ran, so not counted
       (select count(*) from llm_batch_items i join llm_batches b using (batch_id)
        where b.purpose = 'recheck' and i.raw_announcement_id = e.primary_raw_id
          and b.status <> 'failed')
from backfill_events e
join order_extractions oe on oe.raw_announcement_id = e.primary_raw_id
join documents d on d.id = oe.document_id
where e.state = 'recheck_pending'
  and not exists (select 1 from llm_batch_items i join llm_batches b using (batch_id)
                  where b.purpose = 'recheck' and b.collected_at is null
                    and i.raw_announcement_id = e.primary_raw_id)
order by e.id
"""


def submit(conn, client: LlmClient) -> dict:
    items = []
    for event_id, raw_id, text, tries in conn.execute(PENDING_SQL).fetchall():
        if tries >= 2:
            log_transition(conn, event_id, "needs_review", "recheck gave no usable answer twice")
            continue
        items.append((f"rc-{event_id}-{tries + 1}", raw_id, tries + 1,
                      build_request(text, client=client, tier="t2")))
    conn.commit()
    if not items:
        return {"submitted": 0}
    # One batch per model in OpenAI's queue, sized to the enqueued-token limit (batch.py).
    bodies = [body for _, _, _, body in items]
    chunk = items[:client.batch_fit(bodies, client.batch_token_room(bodies[0]["model"]))]
    if not chunk:
        log.info("an earlier %s batch is not collected yet; collect it first",
                 bodies[0]["model"])
        return {"submitted": 0, "waiting": len(items)}
    batch_id, estimate = client.submit_batch(
        [(cid, body) for cid, _, _, body in chunk], purpose=PURPOSE,
        prompt_version=PROMPT_VERSION)
    with conn.cursor() as cur:
        cur.executemany(
            "insert into llm_batch_items (batch_id, custom_id, raw_announcement_id, attempt)"
            " values (%s,%s,%s,%s)", [(batch_id, cid, raw, n) for cid, raw, n, _ in chunk])
    conn.commit()
    return {"submitted": len(chunk), "waiting": len(items) - len(chunk),
            "batch_id": batch_id, "worst_case_usd": str(estimate)}


def collect(conn, client: LlmClient) -> dict:
    out = {"still_running": 0, "verified": 0, "needs_review": 0, "retry": 0}
    for batch_id, model in conn.execute(
            "select batch_id, model from llm_batches where collected_at is null"
            " and purpose = %s", (PURPOSE,)).fetchall():
        batch = client.retrieve_batch(batch_id)
        if batch.status not in TERMINAL:
            out["still_running"] += 1
            continue
        if batch.status == "failed":
            log.warning("%s was rejected whole by OpenAI, no request ran: %s", batch_id,
                        failure_reason(batch))
        lines = []
        for file_id in (batch.output_file_id, batch.error_file_id):
            if file_id:
                lines += client.read_file(file_id).splitlines()
        for line in filter(str.strip, lines):
            record = json.loads(line)
            cid = record.get("custom_id", "")
            event_id = int(cid.split("-")[1])
            outcome = _apply(conn, client, batch_id, model, event_id, record)
            out[outcome] += 1
            conn.execute("update llm_batch_items set applied_at = now() where batch_id = %s"
                         " and custom_id = %s", (batch_id, cid))
        conn.execute("update llm_batches set collected_at = now(), status = %s,"
                     " output_file_id = %s, error_file_id = %s where batch_id = %s",
                     (batch.status, batch.output_file_id, batch.error_file_id, batch_id))
        conn.commit()
    return out


def _apply(conn, client, batch_id, model, event_id, record) -> str:
    response = record.get("response") or {}
    body = response.get("body") or {}
    ok = response.get("status_code") == 200 and not record.get("error")
    client.log_batch_result(batch_id=batch_id, model=model, prompt_version=PROMPT_VERSION,
                            purpose=PURPOSE, tier="t2", usage=body.get("usage"),
                            status="ok" if ok else "error",
                            error=None if ok else json.dumps(record.get("error") or body)[:500])
    if not ok:
        return "retry"          # still recheck_pending; the next submit sends it again
    value, won, text = conn.execute(
        "select e.value_inr, e.company_is_recipient, d.text from backfill_events e"
        " join order_extractions oe on oe.raw_announcement_id = e.primary_raw_id"
        " join documents d on d.id = oe.document_id where e.id = %s", (event_id,)).fetchone()
    try:
        result = interpret(text, body["choices"][0]["message"].get("content") or "")
    except (json.JSONDecodeError, ValidationError):
        return "retry"
    second_won = result.fields.company_is_recipient_bool if result.fields else None
    conn.execute("update backfill_events set recheck_value_inr = %s, recheck_recipient = %s"
                 " where id = %s", (result.value_inr, second_won, event_id))
    if result.value_inr == value and second_won == won and value is not None:
        log_transition(conn, event_id, "verified", "independent recheck agrees")
        return "verified"
    log_transition(conn, event_id, "needs_review",
                   f"recheck disagrees: value {value} vs {result.value_inr}, "
                   f"recipient {won} vs {second_won}")
    return "needs_review"
