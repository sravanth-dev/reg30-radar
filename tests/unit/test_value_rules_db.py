"""The 20 Oct 2026 value rules re-applied to stored data, on real SQL in a scratch schema of
the backfill database (conftest.py): `reparse` (T0 over stored text), flags kept by
`rejudge`, and an event that starts again when its value changes."""

from decimal import Decimal

from tradebot.backfill import batch, events

CR = Decimal(10) ** 7
LEGEND = ("Name of the entity: Navy\nBroad consideration or size of the order(s)/contract(s)"
          " in Rs. Crore 100 to 250 250 to 500 500 to 1000 1000 to 2000 Above 2000\n")
GOOD = "Name of the entity: NHAI\nBroad consideration or size of the order(s): Rs. 283 Crore\n"
OVER = "Broad consideration or size of the order(s): over Rs. 5,400 Crores\n"


def _filing(conn, n, text, *, path, status, value=None, cons=None, span=None,
            recipient=True, isin="INE111A01011"):
    conn.execute("insert into raw_announcements (id, source, source_id, payload_sha256,"
                 " exchange_ts, first_seen_at, isin, symbol, payload) overriding system value"
                 " values (%s, 'nse', %s, 'h', now(), now(), %s, 'COCHINSHIP', '{}')",
                 (n, f"s{n}", isin))
    conn.execute("insert into documents (id, url, sha256, text, method, extracted_at)"
                 " overriding system value values (%s, 'u', %s, %s, 'fake', now())",
                 (n, f"sha{n}", text))
    conn.execute("insert into order_extractions (raw_announcement_id, document_id, bucket,"
                 " order_related, relevance_reason, path, review_status, value_inr,"
                 " consideration_raw, value_span, company_is_recipient, processed_at)"
                 " values (%s, %s, 'order_win', true, 'x', %s, %s, %s, %s, %s, %s, now())",
                 (n, n, path, status, value, cons, span, recipient))


def test_reparse_sends_a_legend_value_back_to_the_model_and_keeps_good_ones(scratch_conn):
    _filing(scratch_conn, 1, LEGEND, path="t0", status="verified", value=Decimal("100"))
    _filing(scratch_conn, 2, GOOD, path="t0", status="verified", value=283 * CR)
    _filing(scratch_conn, 3, OVER, path="t0", status="verified", value=5400 * CR)
    scratch_conn.commit()

    moved = batch.reparse(scratch_conn)
    assert moved == {"verified -> pending_llm": 1, "verified -> verified": 2}
    rows = dict((r[0], r[1:]) for r in scratch_conn.execute(
        "select raw_announcement_id, path, review_status, value_inr, value_flags"
        " from order_extractions order by 1"))
    assert rows[1][:3] == ("llm", "pending_llm", None) and "band_only" in rows[1][3]
    assert rows[2][1:3] == ("verified", 283 * CR)
    assert rows[3][1:] == ("verified", 5400 * CR, ["lower_bound"])
    # the legend filing is now in the queue the next batch-submit reads
    queued = [r[0] for r in scratch_conn.execute(batch.PENDING_SQL)]
    assert queued == [1]


def test_rejudge_keeps_the_flags_and_refuses_a_band_read_as_rupees(scratch_conn):
    _filing(scratch_conn, 1, "₹ Cr\n2,500 to 5,000 Large order", path="llm", status="verified",
            value=Decimal("2500"), cons="2,500 to 5,000", span="2,500 to 5,000")
    _filing(scratch_conn, 2, "order worth over ₹ 5,400/- Crores", path="llm",
            status="verified", value=5400 * CR, cons="over ₹ 5,400/- Crores",
            span="over ₹ 5,400/- Crores")
    scratch_conn.commit()
    batch.rejudge(scratch_conn)
    rows = dict((r[0], r[1:]) for r in scratch_conn.execute(
        "select raw_announcement_id, review_status, value_flags from order_extractions"))
    assert rows[1][0] == "needs_review"                       # L&T: the scale is not quoted
    assert rows[2] == ("verified", ["lower_bound"])            # BEML-style: D32


def test_an_event_whose_value_changed_starts_again(scratch_conn):
    scratch_conn.execute("insert into backfill_universe (isin, symbol, series, as_of_date)"
                         " values ('INE111A01011', 'COCHINSHIP', 'EQ', '2025-09-22')")
    _filing(scratch_conn, 1, GOOD, path="t0", status="verified", value=283 * CR)
    scratch_conn.commit()
    events.build(scratch_conn)
    scratch_conn.execute("update backfill_events set state = 'verified', value_to_mcap = 0.05,"
                         " ttm_revenue_inr = 1")
    scratch_conn.execute("update order_extractions set value_inr = %s", (300 * CR,))
    scratch_conn.commit()

    events.build(scratch_conn)
    state, vm, ttm, value, log = scratch_conn.execute(
        "select state, value_to_mcap, ttm_revenue_inr, value_inr, state_log"
        " from backfill_events").fetchone()
    assert (state, vm, ttm, value) == ("extracted", None, None, 300 * CR)
    assert log[-1]["trigger"] == "value changed on rebuild"

    # an unchanged value keeps its state across a rebuild, as before
    scratch_conn.execute("update backfill_events set state = 'verified'")
    scratch_conn.commit()
    events.build(scratch_conn)
    assert scratch_conn.execute("select state from backfill_events").fetchone()[0] == "verified"
