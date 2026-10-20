"""`order_extractions`: one row per in-scope filing (ARCHITECTURE.md §5.4, §5.6).

This is what makes both branches of `orders/run.py` idempotent and resumable. A raw
filing that already has a finished row here is never re-downloaded or re-sent to the LLM;
one with a retryable row (`download_failed`/`pending_llm`) is retried, but only while under
the attempt cap and only after the retry delay has passed - so a bad network blip or a
reached spend cap waits and comes back, it never spins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Bounded retries (plan, verified in test_orders_run.py): a download or LLM failure is
# retried up to MAX_ATTEMPTS times, at least RETRY_DELAY apart, never in a tight loop.
MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=15)

PENDING_STATUSES = ("download_failed", "pending_llm")


@dataclass
class ExtractionRow:
    raw_announcement_id: int
    bucket: str
    order_related: bool
    relevance_reason: str
    review_status: str
    processed_at: datetime
    document_id: int | None = None
    path: str = "none"
    consideration_raw: str | None = None
    value_span: str | None = None
    value_inr: Decimal | None = None
    provenance_ok: bool | None = None
    currency: str | None = None
    gst_inclusive: bool | None = None
    value_flags: list[str] | None = None
    value_high_inr: Decimal | None = None
    execution_period_raw: str | None = None
    awarding_entity: str | None = None
    company_is_recipient: bool | None = None
    stage: str | None = None
    llm_cost_usd: Decimal = Decimal("0")
    attempts: int = 1
    last_error: str | None = None


UPSERT = """
insert into order_extractions (
    raw_announcement_id, document_id, bucket, order_related, relevance_reason, path,
    consideration_raw, value_span, value_inr, provenance_ok, currency, gst_inclusive,
    value_flags, value_high_inr,
    execution_period_raw, awarding_entity, company_is_recipient, stage, review_status,
    llm_cost_usd, attempts, last_error, processed_at
) values (
    %(raw_announcement_id)s, %(document_id)s, %(bucket)s, %(order_related)s,
    %(relevance_reason)s, %(path)s, %(consideration_raw)s, %(value_span)s, %(value_inr)s,
    %(provenance_ok)s, %(currency)s, %(gst_inclusive)s, %(value_flags)s,
    %(value_high_inr)s, %(execution_period_raw)s,
    %(awarding_entity)s, %(company_is_recipient)s, %(stage)s, %(review_status)s,
    %(llm_cost_usd)s, %(attempts)s, %(last_error)s, %(processed_at)s
)
on conflict (raw_announcement_id) do update set
    document_id = excluded.document_id, bucket = excluded.bucket,
    order_related = excluded.order_related, relevance_reason = excluded.relevance_reason,
    path = excluded.path, consideration_raw = excluded.consideration_raw,
    value_span = excluded.value_span, value_inr = excluded.value_inr,
    provenance_ok = excluded.provenance_ok, currency = excluded.currency,
    gst_inclusive = excluded.gst_inclusive, value_flags = excluded.value_flags,
    value_high_inr = excluded.value_high_inr,
    execution_period_raw = excluded.execution_period_raw,
    awarding_entity = excluded.awarding_entity,
    company_is_recipient = excluded.company_is_recipient, stage = excluded.stage,
    review_status = excluded.review_status, llm_cost_usd = excluded.llm_cost_usd,
    attempts = excluded.attempts, last_error = excluded.last_error,
    processed_at = excluded.processed_at
returning id
"""


def upsert(conn, row: ExtractionRow) -> int:
    got = conn.execute(UPSERT, row.__dict__).fetchone()
    conn.commit()
    return got[0]


def existing_for(conn, raw_ids: list[int]) -> dict[int, dict]:
    """The current order_extractions row, if any, for each of these raw_announcement_ids."""
    if not raw_ids:
        return {}
    rows = conn.execute(
        "select raw_announcement_id, review_status, attempts, processed_at "
        "from order_extractions where raw_announcement_id = any(%s)",
        (raw_ids,),
    ).fetchall()
    return {r[0]: {"review_status": r[1], "attempts": r[2], "processed_at": r[3]}
            for r in rows}


def pending_raw_ids(conn, raw_ids: list[int], *, now: datetime | None = None,
                    retry_statuses: tuple[str, ...] = PENDING_STATUSES) -> set[int]:
    """Which of these ids still need processing: no row at all, or a retryable row that is
    under the attempt cap and past its retry delay.

    The backfill passes `retry_statuses=("download_failed",)`: its `pending_llm` rows are
    waiting on a Batch (backfill/batch.py), and retrying them here would download the PDF
    again for nothing.
    """
    if not raw_ids:
        return set()
    now = now or datetime.now(timezone.utc)
    existing = existing_for(conn, raw_ids)
    pending = set()
    for rid in raw_ids:
        info = existing.get(rid)
        if info is None:
            pending.add(rid)
            continue
        if info["review_status"] not in retry_statuses:
            continue
        if info["attempts"] >= MAX_ATTEMPTS:
            continue
        if now - info["processed_at"] < RETRY_DELAY:
            continue
        pending.add(rid)
    return pending


def attempts_so_far(conn, raw_announcement_id: int) -> int:
    row = conn.execute(
        "select attempts from order_extractions where raw_announcement_id = %s",
        (raw_announcement_id,),
    ).fetchone()
    return row[0] if row else 0
