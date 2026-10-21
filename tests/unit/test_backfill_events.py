"""backfill/events.py merges and §6 transitions; backfill/recheck.py on real SQL."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from reg30_radar.backfill import recheck
from reg30_radar.backfill.events import Filing, group, next_state, recipient, to_event
from reg30_radar.llm.client import LlmClient

T = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
CR = Decimal(10) ** 7


def f(raw_id, *, minutes=0, sha=None, value="283", bucket="catch_all", won=None, isin="INE1"):
    return Filing(raw_id=raw_id, isin=isin, symbol="GENESYS", exchange_ts=T + timedelta(minutes=minutes),
                  bucket=bucket, sha256=sha, value_inr=Decimal(value) * CR if value else None,
                  currency="INR", company_is_recipient=won, stage="contract",
                  awarding_entity=None, execution_period_raw=None)


def test_the_same_order_filed_twice_is_one_event_at_the_earlier_time():
    # GENESYS, 25 Sep: a press release, then the Reg 30 disclosure ~7 hours later.
    events = group([f(2, minutes=420, sha="b"), f(1, sha="a")])
    assert len(events) == 1
    e = to_event(events[0])
    assert e["primary_raw_id"] == 1 and e["event_ts"] == T and e["raw_ids"] == [1, 2]


def test_different_orders_on_one_day_stay_separate():
    assert len(group([f(1, sha="a", value="283"), f(2, sha="b", value="120")])) == 2


def test_one_pdf_under_two_categories_is_one_event_even_without_a_value():
    assert len(group([f(1, sha="x", value=None), f(2, sha="x", value=None)])) == 1


def test_orders_with_no_value_are_never_merged_on_value():
    assert len(group([f(1, sha="a", value=None), f(2, sha="b", value=None)])) == 2


def test_recipient_from_the_extraction_else_the_order_win_category():
    assert recipient([f(1, won=False)]) == (False, "extraction")
    assert recipient([f(1, bucket="order_win")]) == (True, "category")
    assert recipient([f(1, bucket="order_candidate")]) == (None, None)


def test_state_machine_triggers():
    assert next_state(Decimal("0.05"), True) == ("verified", "value_to_mcap < 15% and TTM known")
    assert next_state(Decimal("0.20"), True)[0] == "recheck_pending"
    assert next_state(Decimal("0.05"), False)[0] == "recheck_pending"      # TTM null (§6 4)
    assert next_state(None, True)[0] == "recheck_pending"


# --------------------------------------------------------------- recheck, real SQL

CFG = {"tier1_model": "m1", "tier2_model": "m2",
       "prices": {"m1": {"input": 0.1, "output": 0.5}, "m2": {"input": 0.1, "output": 0.5}},
       "batch_prices": {"m2": {"input": 0.05, "output": 0.25}},
       "caps": {"backfill_usd_per_run": 3.0}, "max_output_tokens": {"order_extract": 800},
       "batch": {"enqueued_token_limit": 2_000_000, "enqueue_share": 0.8}}
DOC = "Genesys has been awarded a contract of Rs. 283 Crore by the municipal corporation."
ANSWER = {"is_order_announcement": True, "company_is_recipient": "true",
          "consideration_raw": "Rs. 283 Crore", "value_span": "Rs. 283 Crore",
          "awarding_entity": None, "nature_of_order": None, "execution_period_raw": None,
          "domestic_or_international": None, "stage": "contract"}


class FakeOpenAI:
    def __init__(self, answer):
        self.answer = answer
        self.files = SimpleNamespace(create=lambda file, purpose: SimpleNamespace(id="in"),
                                     content=self._content)
        self.batches = SimpleNamespace(
            create=lambda **kw: SimpleNamespace(id="rb-1", status="validating"),
            retrieve=lambda bid: SimpleNamespace(status="completed", output_file_id="out",
                                                 error_file_id=None))

    def _content(self, file_id):
        return SimpleNamespace(text=json.dumps({"custom_id": "rc-1-1", "error": None, "response": {
            "status_code": 200, "body": {"choices": [{"message": {"content": json.dumps(self.answer)}}],
                                         "usage": {"prompt_tokens": 500, "completion_tokens": 80}}}}))


def _seed_event(conn, value_cr="283"):
    conn.execute("insert into raw_announcements (id, source, source_id, payload_sha256, first_seen_at,"
                 " payload) overriding system value values (1,'nse','s','h',now(),'{}')")
    conn.execute("insert into documents (id, url, sha256, text, method, extracted_at)"
                 " overriding system value values (1,'u','sha',%s,'fake',now())", (DOC,))
    conn.execute("insert into order_extractions (raw_announcement_id, document_id, bucket,"
                 " order_related, relevance_reason, review_status, processed_at)"
                 " values (1, 1, 'catch_all', true, 'x', 'verified', now())")
    conn.execute("insert into backfill_events (id, isin, symbol, event_ts, raw_ids, primary_raw_id,"
                 " bucket, value_inr, company_is_recipient, state) overriding system value"
                 " values (1, 'INE1', 'GENESYS', now(), '{1}', 1, 'catch_all', %s, true,"
                 " 'recheck_pending')", (Decimal(value_cr) * CR,))
    conn.commit()


def test_recheck_agreement_verifies_the_event(scratch_conn):
    _seed_event(scratch_conn)
    client = LlmClient(conn=scratch_conn, openai_client=FakeOpenAI(ANSWER), config=CFG,
                       budget="backfill")
    assert recheck.submit(scratch_conn, client)["submitted"] == 1
    assert recheck.collect(scratch_conn, client)["verified"] == 1
    state, log = scratch_conn.execute("select state, state_log from backfill_events").fetchone()
    assert state == "verified" and log[-1]["trigger"] == "independent recheck agrees"
    assert scratch_conn.execute("select tier from llm_calls").fetchone()[0] == "t2"


def test_recheck_disagreement_sends_the_event_to_review(scratch_conn):
    _seed_event(scratch_conn, value_cr="2830")     # tier 1 read ten times too much
    client = LlmClient(conn=scratch_conn, openai_client=FakeOpenAI(ANSWER), config=CFG,
                       budget="backfill")
    recheck.submit(scratch_conn, client)
    assert recheck.collect(scratch_conn, client)["needs_review"] == 1
    assert scratch_conn.execute("select state from backfill_events").fetchone()[0] == "needs_review"


def test_an_event_carries_the_universes_isin_not_the_filings_original_one(scratch_conn):
    # Prices and market caps are keyed by the bhavcopy's current ISIN; the filing carries
    # the company's original one (common/isin.py). Before 27 Sep 2026 the event took the
    # filing's, so every order from a company with a past split found no price.
    from reg30_radar.backfill import events
    current, original = "INE019A01038", "INE019A01020"
    scratch_conn.execute("insert into backfill_universe (isin, symbol, series, as_of_date)"
                         " values (%s, 'JSWSTEEL', 'EQ', '2025-09-22')", (current,))
    scratch_conn.execute("insert into raw_announcements (id, source, source_id, payload_sha256,"
                         " exchange_ts, first_seen_at, isin, symbol, payload) overriding system"
                         " value values (1, 'nse', 's', 'h', %s, now(), %s, 'JSWSTEEL', '{}')",
                         (T, original))
    scratch_conn.execute("insert into order_extractions (raw_announcement_id, bucket, order_related,"
                         " relevance_reason, review_status, value_inr, currency, processed_at)"
                         " values (1, 'order_win', true, 'x', 'verified', %s, 'INR', now())",
                         (Decimal(500) * CR,))
    scratch_conn.commit()

    events.build(scratch_conn)
    assert scratch_conn.execute("select isin from backfill_events").fetchall() == [(current,)]
