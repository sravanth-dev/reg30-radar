"""The backfill's Batch round trip against real SQL (scratch schema, see conftest.py) and a
fake OpenAI client: submit checks the cap and records the batch; collect writes each result
through the same rules as a live call and logs its cost at the Batch price. No network."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from tradebot.backfill import batch
from tradebot.llm.client import LlmClient

DOC = ("BEL has received orders worth Rs. 572 Crore from Cochin Shipyard for supply of "
       "communication equipment.")
CFG = {
    "tier1_model": "m1", "tier2_model": "PLACEHOLDER",
    "prices": {"m1": {"input": 0.10, "output": 0.50}},
    "batch_prices": {"m1": {"input": 0.05, "output": 0.25}},
    "caps": {"live_usd_per_month": 1.0, "ocr_usd_per_month": 1.0, "backfill_usd_per_run": 3.0},
    "max_output_tokens": {"order_extract": 800},
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
        self.files = SimpleNamespace(create=self._create_file, content=self._content)
        self.batches = SimpleNamespace(create=self._create_batch, retrieve=self._retrieve)

    def _create_file(self, file, purpose):
        self.uploaded = file[1].decode("utf-8").splitlines()
        return SimpleNamespace(id="file-in")

    def _create_batch(self, input_file_id, endpoint, completion_window):
        self.batches_made += 1
        return SimpleNamespace(id=f"batch-{self.batches_made}", status="validating")

    def _retrieve(self, batch_id):
        return SimpleNamespace(status="completed", output_file_id="file-out", error_file_id=None)

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
