"""orders/run.py: the shared processing core for both branches, offline.

No real database and no real PDF download: `process_pending` takes `process_url_fn` and
`get_text_fn` overrides precisely so this module's own logic (the gate, idempotency,
retries, the gate audit) can be tested without needing a real Postgres row in the
append-only `raw_announcements` table (see run.py's `_process_one` docstring for why that
matters) or a real network call. `documents.pipeline.process_url` itself is already
covered for real in `test_documents.py`.

The HMT fixture is used directly through the real `documents.text.extract()` ladder in the
OCR-routing tests, so those specifically exercise genuine quality/OCR behaviour, not a
canned stand-in for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from tradebot.documents.pipeline import Outcome
from tradebot.documents.text import extract as real_extract
from tradebot.orders import store as orders_store
from tradebot.orders.run import Summary, process_pending
from tradebot.llm.client import LlmResult

HMT = Path(__file__).resolve().parents[1] / "fixtures" / "scans" / "hmt_glyphless.pdf"
LABELLED = Path(__file__).resolve().parents[1] / "labelled"


# --------------------------------------------------------------------- fakes

class FakeOrdersConn:
    """Just enough of orders_store.py's two queries to run process_pending offline - an
    in-memory stand-in for `order_extractions`, never touching a real database.
    """

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.commits = 0
        # (purpose, ts, cost) - CountingLlmClient below appends here on each fake call, so
        # _cost_since's query can be answered for real rather than stubbed to zero.
        self.llm_calls_log: list[tuple[str, datetime, Decimal]] = []

    def execute(self, sql, params=None):
        s = sql.lower()
        if "insert into order_extractions" in s:
            row = dict(params)
            row.setdefault("value_inr", None)
            self.rows[row["raw_announcement_id"]] = row
            return _Result(one=(row["raw_announcement_id"],))
        if "select raw_announcement_id, review_status, attempts, processed_at" in s:
            (raw_ids,) = params
            out = [
                (rid, r["review_status"], r["attempts"], r["processed_at"])
                for rid, r in self.rows.items() if rid in raw_ids
            ]
            return _Result(many=out)
        if "select attempts from order_extractions" in s:
            (rid,) = params
            row = self.rows.get(rid)
            return _Result(one=(row["attempts"],) if row else None)
        if "select coalesce(sum(cost_usd), 0) from llm_calls" in s:
            purpose, since = params
            total = sum((c for p, ts, c in self.llm_calls_log if p == purpose and ts >= since),
                        Decimal("0"))
            return _Result(one=(total,))
        raise AssertionError(f"FakeOrdersConn cannot handle: {sql}")

    def commit(self):
        self.commits += 1


@dataclass
class _Result:
    one: tuple | None = None
    many: list | None = None

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many or []


class FakeProcessUrl:
    """Stands in for `documents.pipeline.process_url`. Two modes per URL: canned text
    (`plan_text`, for logic tests that don't care about real PDF mechanics) or the real
    quality/OCR ladder against a real PDF (`plan_real_pdf`, for the OCR-routing tests).
    """

    def __init__(self):
        self.calls: list[dict] = []
        self._next_id = 1
        self.texts: dict[int, str] = {}
        self._plans: dict[str, tuple] = {}

    def plan_text(self, url, text, *, quality="ok", ocr_pages=0, is_scanned=False):
        self._plans[url] = ("text", text, quality, ocr_pages, is_scanned)

    def plan_failure(self, url, error):
        self._plans[url] = ("fail", error)

    def plan_real_pdf(self, url, pdf_path):
        self._plans[url] = ("real_pdf", pdf_path)

    def __call__(self, url, *, work_dir, conn, raw_announcement_id, fetcher, ocr):
        self.calls.append({"url": url, "ocr": ocr, "raw_announcement_id": raw_announcement_id})
        plan = self._plans.get(url)
        if plan is None:
            return Outcome(ok=False, url=url, error="FakeProcessUrl: no plan for this url")

        if plan[0] == "fail":
            return Outcome(ok=False, url=url, error=plan[1])

        if plan[0] == "text":
            _, text, quality, ocr_pages, is_scanned = plan
            doc_id = self._next_id
            self._next_id += 1
            self.texts[doc_id] = text
            return Outcome(ok=True, url=url, sha256=f"fake-{doc_id}", document_id=doc_id,
                            pages=1, chars=len(text.strip()), is_scanned=is_scanned,
                            quality=quality, ocr_pages=ocr_pages, method="fake",
                            pdf_deleted=True)

        # "real_pdf": run the genuine per-page ladder, OCR included, against a real file -
        # this is what makes the OCR-routing tests below trustworthy.
        _, pdf_path = plan
        doc = real_extract(pdf_path, ocr=ocr)
        doc_id = self._next_id
        self._next_id += 1
        self.texts[doc_id] = doc.text
        return Outcome(ok=True, url=url, sha256=f"fake-{doc_id}", document_id=doc_id,
                        pages=doc.pages, chars=len(doc.text.strip()), is_scanned=doc.is_scanned,
                        quality=doc.quality, ocr_pages=doc.ocr_pages, method=doc.method,
                        pdf_deleted=True)


def fake_get_text(fake_process_url: FakeProcessUrl):
    def _get_text(conn, document_id):
        return fake_process_url.texts.get(document_id, "")
    return _get_text


class CountingLlmClient:
    """Counts vision and extraction calls separately, which is exactly what the gate audit
    needs to check. `ocr_text` / `extract_response` control what each call returns. When
    given a `conn` (a `FakeOrdersConn`), it also logs each call's cost the way the real
    `LlmClient` logs to `llm_calls` - needed for tests that check OCR cost actually reaches
    the report (see `_cost_since` in run.py, and its regression test below).
    """

    def __init__(self, *, ocr_text: str | None = None, extract_response: dict | None = None,
                 conn=None, ocr_cost: Decimal = Decimal("0.0001")):
        self.ocr_calls = 0
        self.extract_calls = 0
        self._ocr_text = ocr_text
        self._extract_response = extract_response
        self._conn = conn
        self._ocr_cost = ocr_cost

    def transcribe_image(self, png_bytes, *, prompt_version, max_output_tokens=None):
        self.ocr_calls += 1
        if self._conn is not None:
            self._conn.llm_calls_log.append(("ocr", datetime.now(timezone.utc), self._ocr_cost))
        return self._ocr_text

    def extract_json(self, document_text, *, prompt_version, schema_name, json_schema,
                      max_output_tokens=None, retry_note=None):
        self.extract_calls += 1
        if self._conn is not None:
            self._conn.llm_calls_log.append(
                ("order_extract", datetime.now(timezone.utc), Decimal("0.0001")))
        return LlmResult(text=json.dumps(self._extract_response or {}), model="fake",
                          in_tokens=10, out_tokens=10, cached_tokens=0,
                          cost_usd=Decimal("0.0001"))


def _raw_row(id_, *, category_raw, headline="", attachment_url="https://x.invalid/a.pdf",
             first_seen_at=None):
    return {
        "id": id_, "source_id": f"src-{id_}", "symbol": f"SYM{id_}",
        "category_raw": category_raw, "headline": headline,
        "attachment_url": attachment_url,
        "first_seen_at": first_seen_at or datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc),
        "revision": 1,
    }


GOOD_FIELDS = {
    "is_order_announcement": True, "company_is_recipient": "true",
    "consideration_raw": "Rs 5 Crs", "value_span": "Rs 5 Crs",
    "awarding_entity": "X", "nature_of_order": "supply", "execution_period_raw": "6 months",
    "domestic_or_international": "domestic", "stage": "PO",
}


# --------------------------------------------------------------------- gate audit

def test_out_of_scope_filing_makes_no_downloads_or_calls():
    row = _raw_row(1, category_raw="Trading Window", headline="Closure of Trading Window")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    client = CountingLlmClient()
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert fpu.calls == []
    assert client.ocr_calls == 0
    assert client.extract_calls == 0
    assert conn.rows == {}   # never even given a row - out of scope entirely


def test_red_flag_filing_makes_no_downloads_or_calls():
    row = _raw_row(2, category_raw="Action(s) taken or orders passed",
                    headline="orders passed by NCLT")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    client = CountingLlmClient()
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert fpu.calls == []
    assert client.ocr_calls == 0
    assert client.extract_calls == 0


def test_order_win_unreadable_pdf_gets_exactly_one_ocr_call():
    """The real HMT fixture, fed as a Bagging/Receiving filing: order-related, so OCR is
    offered; the fixture's page fails every other method, so OCR is exactly the routing
    this tests - one call, no more.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    row = _raw_row(3, category_raw="Bagging/Receiving of orders/contracts",
                    headline="Company bags order", attachment_url="https://x.invalid/hmt.pdf")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_real_pdf(row["attachment_url"], HMT)
    client = CountingLlmClient(ocr_text=None)   # OCR "unavailable", like Part B dormant
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert len(fpu.calls) == 1
    assert client.ocr_calls == 1
    assert client.extract_calls == 0   # nothing to extract from - stayed unreadable
    stored = conn.rows[3]
    assert stored["review_status"] == "needs_review"


def test_order_win_unreadable_pdf_with_working_ocr_reaches_extraction():
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    row = _raw_row(4, category_raw="Bagging/Receiving of orders/contracts",
                    headline="Company bags order", attachment_url="https://x.invalid/hmt2.pdf")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_real_pdf(row["attachment_url"], HMT)
    ocr_text = (
        "We have received a work order worth Rs. 5 Crs from a customer, to be executed "
        "within 6 months, dated 22 September 2026."
    )
    client = CountingLlmClient(ocr_text=ocr_text, extract_response=dict(
        GOOD_FIELDS, consideration_raw="Rs. 5 Crs", value_span="Rs. 5 Crs"))
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert client.ocr_calls == 1
    # T0 can't find the labelled annexure rows in free-form OCR prose, so it escalates -
    # exactly the "code first, LLM only on failure" path (§6).
    assert client.extract_calls == 1
    assert conn.rows[4]["review_status"] == "verified"
    assert conn.rows[4]["path"] == "llm"


def test_ocr_cost_is_folded_into_the_filings_reported_llm_cost():
    """Regression: a real run under-reported its own spend by the exact amount its OCR
    calls cost, because `maybe_transcribe`'s return value carries only the transcript, not
    its cost (WORKLOG, 24 Sep 2026 night, continued). The fix reads the cost back from
    `llm_calls` via `_cost_since`; this checks the number that reaches both the per-filing
    row and the run's overall Summary actually includes it.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    row = _raw_row(8, category_raw="Bagging/Receiving of orders/contracts",
                    headline="Company bags order", attachment_url="https://x.invalid/hmt3.pdf")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_real_pdf(row["attachment_url"], HMT)
    ocr_text = "We have received a work order worth Rs. 5 Crs, executed within 6 months."
    client = CountingLlmClient(
        ocr_text=ocr_text,
        extract_response=dict(GOOD_FIELDS, consideration_raw="Rs. 5 Crs",
                               value_span="Rs. 5 Crs"),
        conn=conn, ocr_cost=Decimal("0.0050"),
    )
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    # OCR (0.0050) + extraction (0.0001, CountingLlmClient's fixed per-call cost) = 0.0051.
    assert conn.rows[8]["llm_cost_usd"] == Decimal("0.0051")
    assert summary.llm_cost_usd == Decimal("0.0051")


def test_catch_all_generic_headline_flips_via_body_but_never_gets_ocr():
    """§5.4's HILINFRA case: a real order hidden behind a generic headline. The body
    prefilter must flip relevance after extraction, and reach LLM extraction if T0 can't
    verify - but OCR must never be offered, because relevance wasn't order-related yet
    when the download happened.
    """
    row = _raw_row(5, category_raw="Press Release",
                    headline="Company has informed the Exchange about General Updates")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    body = "We are pleased to announce receipt of a Letter of Award worth Rs. 5 Crs."
    fpu.plan_text(row["attachment_url"], body, quality="ok")
    client = CountingLlmClient(extract_response=dict(
        GOOD_FIELDS, consideration_raw="Rs. 5 Crs", value_span="Rs. 5 Crs"))
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    # ocr=None was handed to process_url_fn for this filing - verified via the recorded call.
    assert fpu.calls[0]["ocr"] is None
    assert client.ocr_calls == 0
    assert conn.rows[5]["order_related"] is True
    assert conn.rows[5]["review_status"] == "verified"


def test_catch_all_with_no_keyword_anywhere_is_not_order_and_makes_no_llm_call():
    row = _raw_row(6, category_raw="General Updates",
                    headline="Company has informed the Exchange about General Updates")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_text(row["attachment_url"], "Nothing to do with any order or contract here.")
    client = CountingLlmClient()
    process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                     process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert client.ocr_calls == 0
    assert client.extract_calls == 0
    assert conn.rows[6]["order_related"] is False
    assert conn.rows[6]["review_status"] == "not_order"


def test_unreadable_catch_all_with_no_headline_match_is_never_escalated():
    """The accepted limitation (§5.4): a scanned catch_all filing with a generic headline
    can't be checked for a hidden order, and must not reach the LLM as a workaround.
    """
    row = _raw_row(7, category_raw="Updates", headline="General update")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_text(row["attachment_url"], "", quality="unreadable", is_scanned=True)
    client = CountingLlmClient()
    process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                     process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert client.ocr_calls == 0
    assert client.extract_calls == 0
    assert conn.rows[7]["review_status"] == "not_order"


def test_gate_violations_list_stays_empty_across_a_mixed_batch():
    rows = [
        _raw_row(10, category_raw="Trading Window", attachment_url="u10"),
        _raw_row(11, category_raw="Action(s) taken or orders passed", attachment_url="u11"),
        _raw_row(12, category_raw="Bagging/Receiving of orders/contracts", attachment_url="u12"),
        _raw_row(13, category_raw="General Updates", attachment_url="u13"),
    ]
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_text("u12", "Rs. 5 Crs order received", quality="ok")
    fpu.plan_text("u13", "nothing relevant")
    client = CountingLlmClient(extract_response=dict(GOOD_FIELDS))
    summary = process_pending(conn, rows, fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert summary.gate_violations == []


def test_t0_verified_order_still_fills_company_is_recipient_and_stage():
    """Regression: BDL and GHCL, both real order wins verified entirely by T0 in the first
    real run, came back with `company_is_recipient`/`stage` null while an LLM-escalated
    filing had both filled - not because T0 couldn't tell, but because `_t0_row` never
    called the already-built `parse_company_is_recipient`/`parse_stage` (WORKLOG, 25 Sep
    2026). Confirmed here with the same wording those functions are proven against
    elsewhere (extractor/annexure.py's own tests, §5.6's PLACED/RECEIVED patterns).
    """
    row = _raw_row(90, category_raw="Bagging/Receiving of orders/contracts")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_text(
        row["attachment_url"],
        "Broad consideration or size of the order(s): Rs. 5 Crs\n"
        "We have received a work order from a customer under this contract.",
        quality="ok",
    )
    client = CountingLlmClient()
    process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                     process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    stored = conn.rows[90]
    assert stored["path"] == "t0"
    assert stored["review_status"] == "verified"
    assert stored["company_is_recipient"] is True
    assert stored["stage"] == "PO"
    assert client.extract_calls == 0   # T0 alone was enough - no LLM needed


# --------------------------------------------------------------------- idempotency

def test_second_run_over_the_same_row_makes_no_downloads_or_calls():
    row = _raw_row(20, category_raw="Bagging/Receiving of orders/contracts")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_text(row["attachment_url"], "Rs. 5 Crs order received", quality="ok")
    client = CountingLlmClient(extract_response=dict(GOOD_FIELDS))

    process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                     process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    first_calls = len(fpu.calls)
    assert first_calls == 1

    summary2 = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                                process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert len(fpu.calls) == first_calls   # no second download
    assert summary2.considered == 0        # not even classified again


def test_follow_style_cycle_only_processes_the_new_row():
    row_a = _raw_row(30, category_raw="Bagging/Receiving of orders/contracts",
                      attachment_url="ua")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_text("ua", "Rs. 5 Crs order received", quality="ok")
    client = CountingLlmClient(extract_response=dict(GOOD_FIELDS))
    process_pending(conn, [row_a], fetcher=None, client=client, work_dir=Path("."),
                     process_url_fn=fpu, get_text_fn=fake_get_text(fpu))

    # A --follow cycle re-selects everything; row_a must be skipped, row_b processed.
    row_b = _raw_row(31, category_raw="General Updates", headline="letter of award received",
                      attachment_url="ub")
    fpu.plan_text("ub", "not an order")
    summary = process_pending(conn, [row_a, row_b], fetcher=None, client=client,
                               work_dir=Path("."), process_url_fn=fpu,
                               get_text_fn=fake_get_text(fpu))
    assert summary.considered == 1
    assert {c["url"] for c in fpu.calls} == {"ua", "ub"}   # ua from before, ub is new


# --------------------------------------------------------------------- bounded retry

def test_download_failure_is_retried_only_after_the_delay():
    row = _raw_row(40, category_raw="Bagging/Receiving of orders/contracts")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_failure(row["attachment_url"], "HTTP 500")
    client = CountingLlmClient()

    process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                     process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert conn.rows[40]["review_status"] == "download_failed"
    assert conn.rows[40]["attempts"] == 1

    # Immediately again: too soon, must not retry.
    summary2 = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                                process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert summary2.considered == 0
    assert conn.rows[40]["attempts"] == 1

    # Past the retry delay: retried once more.
    conn.rows[40]["processed_at"] = datetime.now(timezone.utc) - timedelta(minutes=16)
    summary3 = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                                process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert summary3.considered == 1
    assert conn.rows[40]["attempts"] == 2


def test_download_failure_stops_retrying_after_max_attempts():
    row = _raw_row(41, category_raw="Bagging/Receiving of orders/contracts")
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_failure(row["attachment_url"], "HTTP 500")
    client = CountingLlmClient()

    for _ in range(orders_store.MAX_ATTEMPTS):
        process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                         process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
        conn.rows[41]["processed_at"] = datetime.now(timezone.utc) - timedelta(minutes=16)

    assert conn.rows[41]["attempts"] == orders_store.MAX_ATTEMPTS
    summary = process_pending(conn, [row], fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert summary.considered == 0   # exhausted - not retried a fourth time


def test_consecutive_auth_failures_stop_the_run():
    rows = [
        _raw_row(50, category_raw="Bagging/Receiving of orders/contracts", attachment_url="u50"),
        _raw_row(51, category_raw="Bagging/Receiving of orders/contracts", attachment_url="u51"),
        _raw_row(52, category_raw="Bagging/Receiving of orders/contracts", attachment_url="u52"),
    ]
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    fpu.plan_failure("u50", "HTTP 403")
    fpu.plan_failure("u51", "HTTP 403")
    fpu.plan_text("u52", "should never be reached")
    client = CountingLlmClient()
    summary = process_pending(conn, rows, fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu))
    assert len(fpu.calls) == 2   # stopped before the third
    assert summary.stopped_early is not None


def test_max_requests_refuses_to_start_a_run_that_is_too_large():
    rows = [_raw_row(i, category_raw="Bagging/Receiving of orders/contracts",
                      attachment_url=f"u{i}") for i in range(60, 65)]
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    client = CountingLlmClient()
    summary = process_pending(conn, rows, fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu),
                               max_requests=2)
    assert fpu.calls == []
    assert summary.stopped_early is not None


def test_max_requests_counts_only_in_scope_rows_not_every_pending_row():
    # Regression: the first real run against 23 Sep's data had 723 pending rows but only
    # ~124 in scope, and --max-requests 200 refused to start anything because the count
    # was taken before classification. Most rows here are out-of-scope noise; only 2 are
    # in-scope, which must fit comfortably under max_requests=2.
    rows = [_raw_row(i, category_raw="Trading Window", attachment_url=f"noise{i}")
            for i in range(100, 150)]
    rows += [_raw_row(i, category_raw="Bagging/Receiving of orders/contracts",
                       attachment_url=f"order{i}") for i in range(150, 152)]
    conn = FakeOrdersConn()
    fpu = FakeProcessUrl()
    for r in rows:
        if r["attachment_url"].startswith("order"):
            fpu.plan_text(r["attachment_url"], "Rs. 5 Crs order received", quality="ok")
    client = CountingLlmClient(extract_response=dict(GOOD_FIELDS))
    summary = process_pending(conn, rows, fetcher=None, client=client, work_dir=Path("."),
                               process_url_fn=fpu, get_text_fn=fake_get_text(fpu),
                               max_requests=2)
    assert summary.stopped_early is None
    assert len(fpu.calls) == 2   # only the 2 in-scope filings were ever downloaded


def test_a_worker_killed_mid_filing_leaves_a_counted_retryable_row():
    """§9: a container killed at its memory limit must not restart-loop on one filing.
    The attempt is recorded before the work, so each crash counts and the filing stops
    being retried after MAX_ATTEMPTS."""
    row = _raw_row(42, category_raw="Bagging/Receiving of orders/contracts")
    conn = FakeOrdersConn()

    def killed(url, **kw):
        raise MemoryError("stand-in for the kernel OOM-killing the container")

    for attempt in range(1, orders_store.MAX_ATTEMPTS + 1):
        with pytest.raises(MemoryError):
            process_pending(conn, [row], fetcher=None, client=CountingLlmClient(),
                            work_dir=Path("."), process_url_fn=killed,
                            get_text_fn=lambda c, d: "")
        assert conn.rows[42]["attempts"] == attempt
        assert conn.rows[42]["review_status"] == "download_failed"
        assert conn.rows[42]["last_error"].startswith("interrupted")
        conn.rows[42]["processed_at"] = datetime.now(timezone.utc) - timedelta(minutes=16)

    summary = process_pending(conn, [row], fetcher=None, client=CountingLlmClient(),
                              work_dir=Path("."), process_url_fn=killed,
                              get_text_fn=lambda c, d: "")
    assert summary.considered == 0   # no fourth attempt, so no restart loop
