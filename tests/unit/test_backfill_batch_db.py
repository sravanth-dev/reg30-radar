"""The backfill's Batch round trip against real SQL (scratch schema, see conftest.py) and a
fake OpenAI client: submit checks the cap and records the batch; collect writes each result
through the same rules as a live call and logs its cost at the Batch price. No network."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from reg30_radar.backfill import batch
from reg30_radar.extractor.llm_extract import build_request
from reg30_radar.llm.client import LlmClient, LlmRefused

DOC = ("BEL has received orders worth Rs. 572 Crore from Cochin Shipyard for supply of "
       "communication equipment.")
CFG = {
    "tier1_model": "m1", "tier2_model": "PLACEHOLDER",
    "prices": {"m1": {"input": 0.10, "output": 0.50}},
    "batch_prices": {"m1": {"input": 0.05, "output": 0.25}},
    "caps": {"live_usd_per_month": 1.0, "ocr_usd_per_month": 1.0, "backfill_usd_per_run": 3.0},
    "max_output_tokens": {"order_extract": 800},
    "batch": {"enqueued_token_limit": 2_000_000, "enqueue_share": 0.8},
}
GOOD = {"is_order_announcement": True, "company_is_recipient": "true",
        "consideration_raw": "Rs. 572 Crore", "value_span": "Rs. 572 Crore",
        "awarding_entity": "Cochin Shipyard", "nature_of_order": "supply",
        "execution_period_raw": None, "domestic_or_international": "domestic",
        "stage": "PO"}


class FakeOpenAI:
    def __init__(self):
        self.uploaded = None
        self.output_lines = []
        self.batches_made = 0
        self.status, self.errors = "completed", None
        self.files = SimpleNamespace(create=self._create_file, content=self._content)
        self.batches = SimpleNamespace(create=self._create_batch, retrieve=self._retrieve)

    def _create_file(self, file, purpose):
        self.uploaded = file[1].decode("utf-8").splitlines()
        return SimpleNamespace(id="file-in")

    def _create_batch(self, input_file_id, endpoint, completion_window):
        self.batches_made += 1
        return SimpleNamespace(id=f"batch-{self.batches_made}", status="validating")

    def _retrieve(self, batch_id):
        failed = self.status == "failed"
        return SimpleNamespace(status=self.status, output_file_id=None if failed else "file-out",
                               error_file_id=None, errors=self.errors)

    def _content(self, file_id):
        return SimpleNamespace(text="\n".join(self.output_lines))


def _seed(conn, raw_id=1):
    conn.execute(
        "insert into raw_announcements (id, source, source_id, payload_sha256, first_seen_at,"
        " symbol, category_raw, payload) overriding system value values"
        " (%s,'nse','s1','h1',%s,'BEL','Bagging/Receiving of orders/contracts','{}')",
        (raw_id, datetime.now(timezone.utc)))
    conn.execute("insert into documents (id, url, sha256, text, method, extracted_at)"
                 " overriding system value values (1,'u','sha',%s,'fake',now())", (DOC,))
    conn.execute(
        "insert into order_extractions (raw_announcement_id, document_id, bucket, order_related,"
        " relevance_reason, path, review_status, processed_at)"
        " values (%s, 1, 'order_win', true, 'category', 'llm', 'pending_llm', now())", (raw_id,))
    conn.commit()


def _result_line(custom_id, content, prompt_tokens=1000, completion_tokens=100):
    return json.dumps({"custom_id": custom_id, "error": None, "response": {
        "status_code": 200, "body": {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}}})


def test_submit_then_collect_writes_a_verified_order(scratch_conn):
    _seed(scratch_conn)
    fake = FakeOpenAI()
    client = LlmClient(conn=scratch_conn, openai_client=fake, config=CFG, budget="backfill")

    out = batch.submit(scratch_conn, client)
    assert out["submitted"][0]["requests"] == 1
    request = json.loads(fake.uploaded[0])
    assert request["custom_id"] == "oe-1-1" and request["body"]["model"] == "m1"
    # The worst case counts as committed spend until collected.
    assert scratch_conn.execute("select estimate_usd > 0 from llm_batches").fetchone()[0]

    fake.output_lines = [_result_line("oe-1-1", json.dumps(GOOD))]
    summary = batch.collect(scratch_conn, client)
    assert summary["results"] == 1
    status, value, cost = scratch_conn.execute(
        "select review_status, value_inr, llm_cost_usd from order_extractions").fetchone()
    assert status == "verified" and value == Decimal("5720000000.00")
    # The currency is written too; the LLM paths used to leave it empty.
    assert scratch_conn.execute("select currency from order_extractions").fetchone()[0] == "INR"
    # 1000 in x $0.05/M + 100 out x $0.25/M, the Batch price, not the standard one.
    assert cost == Decimal("0.000075")
    assert scratch_conn.execute("select batch_id from llm_calls").fetchone()[0] == "batch-1"


def test_an_invalid_answer_is_retried_once_with_the_error_then_reviewed(scratch_conn):
    _seed(scratch_conn)
    fake = FakeOpenAI()
    client = LlmClient(conn=scratch_conn, openai_client=fake, config=CFG, budget="backfill")

    batch.submit(scratch_conn, client)
    fake.output_lines = [_result_line("oe-1-1", "not json")]
    batch.collect(scratch_conn, client)
    assert scratch_conn.execute("select review_status from order_extractions").fetchone()[0] \
        == "pending_llm"

    batch.submit(scratch_conn, client)                     # the one retry, error fed back
    assert "previous response was invalid" in json.loads(fake.uploaded[0])["body"]["messages"][1]["content"]
    fake.output_lines = [_result_line("oe-1-2", "still not json")]
    batch.collect(scratch_conn, client)
    assert scratch_conn.execute("select review_status from order_extractions").fetchone()[0] \
        == "needs_review"


def test_submit_refuses_when_the_worst_case_would_pass_the_cap(scratch_conn):
    _seed(scratch_conn)
    cfg = {**CFG, "caps": {**CFG["caps"], "backfill_usd_per_run": 0.0000001}}
    client = LlmClient(conn=scratch_conn, openai_client=FakeOpenAI(), config=cfg,
                       budget="backfill")
    try:
        batch.submit(scratch_conn, client)
        raise AssertionError("expected a refusal")
    except Exception as exc:
        assert "cap" in str(exc)
    assert scratch_conn.execute("select count(*) from llm_batches").fetchone()[0] == 0


def _seed_many(conn, n):
    """n order filings waiting on the LLM, all pointing at one document."""
    conn.execute("insert into documents (id, url, sha256, text, method, extracted_at)"
                 " overriding system value values (1,'u','sha',%s,'fake',now())", (DOC,))
    for raw_id in range(1, n + 1):
        conn.execute(
            "insert into raw_announcements (id, source, source_id, payload_sha256, first_seen_at,"
            " symbol, category_raw, payload) overriding system value values"
            " (%s,'nse',%s,%s,now(),'BEL','Bagging/Receiving of orders/contracts','{}')",
            (raw_id, f"s{raw_id}", f"h{raw_id}"))
        conn.execute(
            "insert into order_extractions (raw_announcement_id, document_id, bucket,"
            " order_related, relevance_reason, path, review_status, processed_at)"
            " values (%s, 1, 'order_win', true, 'category', 'llm', 'pending_llm', now())",
            (raw_id,))
    conn.commit()


def test_a_batch_rejected_whole_does_not_use_up_a_submission(scratch_conn):
    # 28 Sep 2026: OpenAI rejected the first backfill batch whole ("Enqueued token limit
    # reached"). No request ran, so the filing must keep all three of its submissions.
    _seed(scratch_conn)
    fake = FakeOpenAI()
    client = LlmClient(conn=scratch_conn, openai_client=fake, config=CFG, budget="backfill")
    fake.status = "failed"
    fake.errors = SimpleNamespace(data=[SimpleNamespace(
        code="token_limit_exceeded", message="Enqueued token limit reached")])
    for _ in range(3):
        batch.submit(scratch_conn, client)
        assert json.loads(fake.uploaded[0])["custom_id"] == "oe-1-1"    # still attempt 1
        batch.collect(scratch_conn, client)
    assert scratch_conn.execute("select review_status from order_extractions").fetchone()[0] \
        == "pending_llm"


def test_a_large_pending_set_goes_out_one_token_sized_batch_at_a_time(scratch_conn):
    _seed_many(scratch_conn, 3)
    fake = FakeOpenAI()
    probe = LlmClient(conn=scratch_conn, openai_client=fake, config=CFG, budget="backfill")
    one = probe.estimate_input_tokens(build_request(DOC, client=probe))
    # room for two and a half requests, so two fit and the third waits
    cfg = {**CFG, "batch": {"enqueued_token_limit": int(one * 2.5 / 0.8), "enqueue_share": 0.8}}
    client = LlmClient(conn=scratch_conn, openai_client=fake, config=cfg, budget="backfill")

    out = batch.submit(scratch_conn, client)
    assert out["submitted"][0]["requests"] == 2 and out["waiting"] == 1
    # nothing more goes out while that batch is still uncollected
    assert batch.submit(scratch_conn, client)["submitted"] == []
    assert fake.batches_made == 1

    fake.output_lines = [_result_line(f"oe-{i}-1", json.dumps(GOOD)) for i in (1, 2)]
    batch.collect(scratch_conn, client)
    out = batch.submit(scratch_conn, client)
    assert out["submitted"][0]["requests"] == 1 and out["waiting"] == 0
    assert json.loads(fake.uploaded[0])["custom_id"] == "oe-3-1"


def test_a_batch_cannot_be_sized_without_the_configured_limit(scratch_conn):
    cfg = {k: v for k, v in CFG.items() if k != "batch"}
    client = LlmClient(conn=scratch_conn, openai_client=FakeOpenAI(), config=cfg,
                       budget="backfill")
    try:
        client.batch_token_room("m1")
        raise AssertionError("expected a refusal")
    except LlmRefused as exc:
        assert "enqueued_token_limit" in str(exc)


def _seed_answer(conn, raw_id, *, text, cons, span, recipient=True, stage="PO",
                 status="needs_review", last_error=None):
    """One stored LLM answer, as batch.collect left it under the old rules."""
    conn.execute(
        "insert into raw_announcements (id, source, source_id, payload_sha256, first_seen_at,"
        " symbol, category_raw, payload) overriding system value values"
        " (%s,'nse',%s,%s,now(),'CO','Bagging/Receiving of orders/contracts','{}')",
        (raw_id, f"s{raw_id}", f"h{raw_id}"))
    conn.execute("insert into documents (id, url, sha256, text, method, extracted_at)"
                 " overriding system value values (%s,'u',%s,%s,'fake',now())",
                 (raw_id, f"sha{raw_id}", text))
    conn.execute(
        "insert into order_extractions (raw_announcement_id, document_id, bucket, order_related,"
        " relevance_reason, path, review_status, consideration_raw, value_span,"
        " company_is_recipient, stage, last_error, processed_at)"
        " values (%s, %s, 'order_win', true, 'category', 'llm', %s, %s, %s, %s, %s, %s, now())",
        (raw_id, raw_id, status, cons, span, recipient, stage, last_error))


def test_rejudge_applies_the_29_sep_rules_to_stored_answers_without_calling_the_model(scratch_conn):
    c = scratch_conn
    # 1. verified value, stage unknown: was review only because of the stage
    _seed_answer(c, 1, text=DOC, cons="Rs. 572 Crore", span="Rs. 572 Crore", stage="unknown")
    # 2. the value quoted across an interleaved table column (RAILTEL)
    _seed_answer(c, 2, text="Value is Rs.\n(in INR); 38,59,27,045/-(ExcludingTax)",
                 cons="Rs. 38,59,27,045/-(ExcludingTax)",
                 span="Rs.\n38,59,27,045/-(ExcludingTax)")
    # 3. a USD order: now converted at the configured Rs 94
    _seed_answer(c, 3, text="Order of USD 7.53 Million (Approximately INR 67.12 Crores).",
                 cons="USD 7.53 Million", span="USD 7.53 Million")
    # 4. no value in the filing: stays in review
    _seed_answer(c, 4, text=DOC, cons=None, span=None)
    # 5. recipient unknown: stays in review
    _seed_answer(c, 5, text=DOC, cons="Rs. 572 Crore", span="Rs. 572 Crore", recipient=None)
    # 6. never got a usable answer: untouched
    _seed_answer(c, 6, text=DOC, cons=None, span=None, last_error="invalid response twice: x")
    c.commit()

    moved = batch.rejudge(c)
    assert moved == {"needs_review -> verified": 3, "needs_review -> needs_review": 2}
    got = dict((r[0], r[1:]) for r in c.execute(
        "select raw_announcement_id, review_status, value_inr, currency from order_extractions"))
    assert got[1] == ("verified", Decimal("5720000000.00"), "INR")
    assert got[2] == ("verified", Decimal("385927045.00"), "INR")
    assert got[3] == ("verified", Decimal("707820000.00"), "USD")
    assert got[4][0] == got[5][0] == got[6][0] == "needs_review"
