"""One processing core for both branches of the order-extraction run (ARCHITECTURE.md
§5.4-§5.6): `python -m tradebot.orders --date ...` over already-scraped data, and
`python -m tradebot.orders --follow` running live next to the collector. See
`__main__.py`'s module docstring for why live processing is a separate process rather than
something the collector does inline.

The two branches differ only in which `raw_announcements` rows they hand to
`process_pending` - everything about classifying, downloading, extracting and writing the
result is exactly one code path, so a filing is handled identically whichever branch
touched it first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from tradebot.documents import store as documents_store
from tradebot.documents.ocr import maybe_transcribe
from tradebot.documents.pipeline import process_url as _real_process_url
from tradebot.extractor.annexure import parse_annexure, parse_company_is_recipient, parse_stage
from tradebot.extractor.llm_extract import extract_order_fields
from tradebot.extractor.provenance import verify as verify_provenance
from tradebot.llm.client import LlmClient
from tradebot.orders import store as orders_store
from tradebot.router.orders import Relevance, classify, in_scope, llm_allowed, refine_with_body
from tradebot.units.money import is_suspect, parse_money

log = logging.getLogger("orders")

# §5.1/D25 politeness pacing already lives in PdfFetcher; this is a second, independent
# circuit breaker on top of it, because two 401/403s in a row means the session itself has
# gone bad (expired cookies, a block), and pacing alone won't fix that - only stopping and
# re-warming on the next run will.
STOP_AFTER_CONSECUTIVE_AUTH_FAILURES = 2


def _cost_since(conn, *, purpose: str, since: datetime) -> Decimal:
    """Sum of `llm_calls.cost_usd` for one purpose, logged at or after `since`. Used to
    read back a cost the caller has no other way to know (`maybe_transcribe`'s contract is
    just `str | None` - see the comment where this is called in `_process_one`).
    """
    row = conn.execute(
        "select coalesce(sum(cost_usd), 0) from llm_calls where purpose = %s and ts >= %s",
        (purpose, since),
    ).fetchone()
    return Decimal(row[0])


@dataclass
class Summary:
    considered: int = 0
    downloaded: int = 0
    download_failed: int = 0
    order_related: int = 0
    verified: int = 0
    needs_review: int = 0
    not_order: int = 0
    pending_llm: int = 0
    ocr_pages: int = 0
    llm_calls: int = 0
    llm_cost_usd: Decimal = Decimal("0")
    stopped_early: str | None = None
    # A gate audit (§5.4): any filing where an LLM/OCR call happened without
    # llm_allowed(relevance) being true first. Must always be empty; a non-empty list here
    # is a bug in this module, not a filing to review.
    gate_violations: list[int] = field(default_factory=list)
    dates_touched: set = field(default_factory=set)
    rows: list[dict] = field(default_factory=list)   # for report.py; one dict per filing


SELECT_LATEST_REVISIONS = """
select distinct on (source_id)
    id, source_id, symbol, category_raw, headline, attachment_url, first_seen_at, revision
from raw_announcements
where source = %(source)s
  {date_clause}
order by source_id, revision desc
"""


def select_latest_revisions(
    conn, *, source: str = "nse", since: datetime | None = None, until: datetime | None = None,
) -> list[dict]:
    """The latest revision of every filing in range (or the whole table, for --follow).

    `revision` rows are separate `raw_announcements` rows sharing one `source_id` (§5.3) -
    an older revision is superseded and must not be downloaded or scored a second time.
    """
    params: dict = {"source": source}
    clause = ""
    if since is not None:
        clause += " and first_seen_at >= %(since)s"
        params["since"] = since
    if until is not None:
        clause += " and first_seen_at < %(until)s"
        params["until"] = until
    sql = SELECT_LATEST_REVISIONS.format(date_clause=clause)
    rows = conn.execute(sql, params).fetchall()
    cols = ("id", "source_id", "symbol", "category_raw", "headline", "attachment_url",
            "first_seen_at", "revision")
    return [dict(zip(cols, r)) for r in rows]


def _gst_flag(money) -> bool | None:
    if "gst_inclusive" in money.flags:
        return True
    if "gst_exclusive" in money.flags:
        return False
    return None


def t0_value(doc_text: str):
    """The deterministic parser's value for one document (§5.6 steps 1-3): (annexure,
    money, span, provenance_ok, ok). One function for the live path and for the backfill's
    `reparse`, so a rule change re-applied to stored text is judged exactly as new text is."""
    ann = parse_annexure(doc_text)
    money = parse_money(ann.raw("consideration_raw"))
    span = ann.span("consideration_raw")
    provenance_ok = verify_provenance(doc_text, span, money.value_inr)
    # Provenance proves the number came from the document, not that it is the order's value
    # in rupees: VASCONEQ's ₹660.79 crore passed as ₹660.79, and a size legend gave ₹100
    # (units/money.py). Such a value is not verified, so the filing escalates to T1 like any
    # other T0 miss.
    return ann, money, span, provenance_ok, provenance_ok and not is_suspect(money)


def _t0_row(row, relevance: Relevance, *, document_id: int, doc_text: str,
            processed_at: datetime, attempts: int) -> tuple[orders_store.ExtractionRow, bool]:
    """Try the deterministic parser first (§5.6 step 1-3). Returns (row, verified)."""
    ann, money, span, provenance_ok, ok = t0_value(doc_text)
    consideration = ann.raw("consideration_raw")
    # company_is_recipient and stage read the whole document, not just the labelled
    # consideration row - already built in extractor/annexure.py (the same functions
    # eval/__main__.py's predict() uses) and simply not wired in here until now. Without
    # them, a T0-verified order win like BDL or GHCL reported both fields as null while an
    # LLM-escalated one reported real values - an inconsistency with no reason behind it,
    # caught by reading the first real run's own output (WORKLOG, 25 Sep 2026).
    extraction = orders_store.ExtractionRow(
        raw_announcement_id=row["id"], document_id=document_id, bucket=relevance.bucket,
        order_related=True, relevance_reason=relevance.reason,
        path="t0", consideration_raw=consideration, value_span=span,
        value_inr=money.value_inr, provenance_ok=provenance_ok, currency=money.currency,
        gst_inclusive=_gst_flag(money), value_flags=sorted(money.flags) or None,
        value_high_inr=money.high_inr,
        execution_period_raw=ann.raw("execution_period_raw"),
        awarding_entity=ann.raw("awarding_entity"),
        company_is_recipient=parse_company_is_recipient(doc_text),
        stage=parse_stage(doc_text),
        review_status="verified" if ok else "needs_review",
        attempts=attempts, processed_at=processed_at,
    )
    return extraction, ok


def _llm_row(row, relevance: Relevance, *, document_id: int, doc_text: str, client: LlmClient,
             processed_at: datetime, attempts: int) -> orders_store.ExtractionRow:
    """Escalate to T1 (§6) - only ever called when `llm_allowed(relevance)` is true."""
    assert llm_allowed(relevance), "gate bypass: LLM called on a non-order-related filing"
    result = extract_order_fields(doc_text, client=client)
    fields = result.fields
    return orders_store.ExtractionRow(
        raw_announcement_id=row["id"], document_id=document_id, bucket=relevance.bucket,
        order_related=True, relevance_reason=relevance.reason,
        path="llm",
        consideration_raw=fields.consideration_raw if fields else None,
        value_span=fields.value_span if fields else None,
        value_inr=result.value_inr, provenance_ok=result.provenance_ok,
        currency=result.currency, gst_inclusive=result.gst_inclusive,
        value_flags=result.value_flags, value_high_inr=result.value_high_inr,
        execution_period_raw=fields.execution_period_raw if fields else None,
        awarding_entity=fields.awarding_entity if fields else None,
        company_is_recipient=fields.company_is_recipient_bool if fields else None,
        stage=fields.stage if fields else None,
        review_status=result.review_status, llm_cost_usd=result.cost_usd,
        attempts=attempts, last_error=result.error, processed_at=processed_at,
    )


def _process_one(conn, row, relevance: Relevance, *, fetcher, client: LlmClient,
                  work_dir: Path, summary: Summary, process_url_fn=_real_process_url,
                  get_text_fn=documents_store.get_text) -> str | None:
    """One filing. Returns an auth-failure marker ("401"/"403") when the download failed
    that way, so the caller's consecutive-failure breaker can see it; None otherwise.

    `process_url_fn` and `get_text_fn` default to the real `documents` pipeline, and are
    overridden only by tests: `documents.pipeline.process_url` already has its own
    real-Postgres-backed test coverage (`test_documents.py`), and `raw_announcements` is
    append-only with no delete path (CLAUDE.md, migrations/0001_init.sql's trigger) - a
    test that inserted a real row there could never clean it up. Faking the pipeline
    boundary here keeps this module's own tests fast, hermetic, and DB-free (§9), while
    still exercising every line of *this* module's logic for real.
    """
    now = datetime.now(timezone.utc)
    prior_attempts = orders_store.attempts_so_far(conn, row["id"])
    url = row["attachment_url"]

    # Count the attempt before doing any work. A worker killed mid-filing (a PDF too large
    # for the container's memory limit, §9) would otherwise leave no trace, and Docker's
    # restart policy would hand it the same filing again, forever. With the attempt already
    # recorded, a crash leaves a retryable row that stops after MAX_ATTEMPTS, 15 minutes
    # apart. Every normal outcome below overwrites this row.
    orders_store.upsert(conn, orders_store.ExtractionRow(
        raw_announcement_id=row["id"], bucket=relevance.bucket,
        order_related=relevance.order_related, relevance_reason=relevance.reason,
        review_status="download_failed",
        last_error="interrupted: processing started but did not finish",
        attempts=prior_attempts + 1, processed_at=now,
    ))

    if not url:
        orders_store.upsert(conn, orders_store.ExtractionRow(
            raw_announcement_id=row["id"], bucket=relevance.bucket,
            order_related=relevance.order_related, relevance_reason=relevance.reason,
            review_status="download_failed", last_error="no attachment_url",
            attempts=prior_attempts + 1, processed_at=now,
        ))
        summary.download_failed += 1
        return None

    # The gate: only an order-related filing (by category, or by headline keyword) gets an
    # OCR function at all. `process_url` cannot reach the LLM on its own - it only ever
    # gets this closure, never a client.
    ocr_fn = (lambda png: maybe_transcribe(png, client=client)) if llm_allowed(relevance) else None

    outcome = process_url_fn(url, work_dir=work_dir, conn=conn, raw_announcement_id=row["id"],
                           fetcher=fetcher, ocr=ocr_fn)

    if not outcome.ok:
        orders_store.upsert(conn, orders_store.ExtractionRow(
            raw_announcement_id=row["id"], bucket=relevance.bucket,
            order_related=relevance.order_related, relevance_reason=relevance.reason,
            review_status="download_failed", last_error=outcome.error,
            attempts=prior_attempts + 1, processed_at=now,
        ))
        summary.download_failed += 1
        error = outcome.error or ""
        if "HTTP 401" in error:
            return "401"
        if "HTTP 403" in error:
            return "403"
        return None

    summary.downloaded += 1
    summary.ocr_pages += outcome.ocr_pages
    doc_text = get_text_fn(conn, outcome.document_id)

    # `documents.ocr.maybe_transcribe` returns only the transcript, not its cost (its
    # contract - `OcrFn` - is fixed by `documents/text.py`, from the previous session, and
    # changing it would ripple through that module's own tests for no benefit there). The
    # cost is still logged to `llm_calls` by `LlmClient` itself, so it's read back the same
    # way `_check_cap` reads spend-to-date: sum what was logged since this filing started.
    # Calls are sequential (`process_pending` never runs two filings concurrently), so this
    # window belongs to this filing alone. Caught by a real run under-reporting its own
    # cost (WORKLOG, 24 Sep 2026 night, continued) - the summary's "LLM cost" line must
    # mean total spend on a filing, OCR included, or it is simply wrong.
    ocr_cost = _cost_since(conn, purpose="ocr", since=now) if ocr_fn is not None else Decimal("0")

    relevance = refine_with_body(relevance, doc_text)
    if relevance.order_related:
        summary.order_related += 1
    else:
        orders_store.upsert(conn, orders_store.ExtractionRow(
            raw_announcement_id=row["id"], document_id=outcome.document_id,
            bucket=relevance.bucket, order_related=False, relevance_reason=relevance.reason,
            path="none", review_status="not_order", llm_cost_usd=ocr_cost,
            attempts=prior_attempts + 1, processed_at=now,
        ))
        summary.not_order += 1
        summary.llm_cost_usd += ocr_cost
        return None

    if not doc_text.strip():
        # Unreadable through every method (including OCR, if it was tried) - nothing to
        # extract from, so an LLM call here would only be a guess in disguise. CLAUDE.md:
        # never guess a number.
        orders_store.upsert(conn, orders_store.ExtractionRow(
            raw_announcement_id=row["id"], document_id=outcome.document_id,
            bucket=relevance.bucket, order_related=True, relevance_reason=relevance.reason,
            path="none", review_status="needs_review", llm_cost_usd=ocr_cost,
            last_error=f"document text unreadable (quality={outcome.quality})",
            attempts=prior_attempts + 1, processed_at=now,
        ))
        summary.needs_review += 1
        summary.llm_cost_usd += ocr_cost
        return None

    extraction, t0_ok = _t0_row(row, relevance, document_id=outcome.document_id,
                                 doc_text=doc_text, processed_at=now,
                                 attempts=prior_attempts + 1)

    if not t0_ok and llm_allowed(relevance):
        # §6: "the parser wins when it verifies" - escalation only on T0 failure, and only
        # for a filing the gate already allows.
        extraction = _llm_row(row, relevance, document_id=outcome.document_id,
                               doc_text=doc_text, client=client, processed_at=now,
                               attempts=prior_attempts + 1)
        summary.llm_calls += 1

    extraction.llm_cost_usd += ocr_cost
    summary.llm_cost_usd += extraction.llm_cost_usd

    orders_store.upsert(conn, extraction)
    status = extraction.review_status
    if status == "verified":
        summary.verified += 1
    elif status == "needs_review":
        summary.needs_review += 1
    elif status == "not_order":
        summary.not_order += 1
    elif status == "pending_llm":
        summary.pending_llm += 1
    summary.rows.append({
        "symbol": row["symbol"], "category_raw": row["category_raw"],
        "bucket": relevance.bucket, "reason": relevance.reason,
        "quality": outcome.quality, "path": extraction.path,
        "consideration_raw": extraction.consideration_raw, "value_inr": extraction.value_inr,
        "provenance_ok": extraction.provenance_ok, "review_status": extraction.review_status,
        "company_is_recipient": extraction.company_is_recipient, "stage": extraction.stage,
        "llm_cost_usd": extraction.llm_cost_usd,
    })
    return None


def process_pending(
    conn, raw_rows: list[dict], *, fetcher, client: LlmClient, work_dir: Path,
    max_requests: int | None = None, process_url_fn=_real_process_url,
    get_text_fn=documents_store.get_text,
    retry_statuses: tuple[str, ...] = orders_store.PENDING_STATUSES,
) -> Summary:
    """The single code path both `--date`/`--from`/`--to` and `--follow` call.

    `raw_rows` is whatever the caller already selected (`select_latest_revisions`, bounded
    by date or not) - this only classifies, downloads and extracts. `process_url_fn` and
    `get_text_fn` are test-only overrides; see `_process_one`'s docstring for why.
    """
    summary = Summary()
    candidate_ids = [r["id"] for r in raw_rows]
    pending_ids = orders_store.pending_raw_ids(conn, candidate_ids,
                                               retry_statuses=retry_statuses)
    to_process = [r for r in raw_rows if r["id"] in pending_ids]

    # Classify before counting: `--max-requests` guards the number of *downloads* this run
    # is about to make, which is only the in-scope subset. Checking it against every
    # pending row (most of a day's filings are out of scope and never downloaded at all)
    # would refuse a normal run for the wrong reason - caught by the first real run, which
    # had 723 pending rows but only ~124 in scope.
    classified = [(row, classify(row["category_raw"], row["headline"])) for row in to_process]
    in_scope_rows = [(row, rel) for row, rel in classified if in_scope(rel)]

    if max_requests is not None and len(in_scope_rows) > max_requests:
        summary.stopped_early = (
            f"in-scope pending count {len(in_scope_rows)} exceeds --max-requests "
            f"{max_requests}; stopping before any download"
        )
        log.warning(summary.stopped_early)
        return summary

    consecutive_auth_failures = 0
    for row, relevance in in_scope_rows:
        summary.considered += 1
        auth_failure = _process_one(conn, row, relevance, fetcher=fetcher, client=client,
                                     work_dir=work_dir, summary=summary,
                                     process_url_fn=process_url_fn, get_text_fn=get_text_fn)
        summary.dates_touched.add(row["first_seen_at"].date())

        if auth_failure:
            consecutive_auth_failures += 1
            if consecutive_auth_failures >= STOP_AFTER_CONSECUTIVE_AUTH_FAILURES:
                summary.stopped_early = (
                    f"stopped after {consecutive_auth_failures} consecutive "
                    f"HTTP {auth_failure} responses"
                )
                log.error(summary.stopped_early)
                break
        else:
            consecutive_auth_failures = 0

    return summary
