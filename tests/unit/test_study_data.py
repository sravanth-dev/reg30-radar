"""backfill/study_data.py's contamination lookup, on real SQL (scratch schema): a company's
other filing counts even when its own `isin` is null, matched on symbol instead - the case
Spike A found (sm_isin not 100% populated) that would otherwise silently understate
contamination and make the study look cleaner than it is."""

from datetime import datetime, timezone

from tradebot.backfill import study_data
from tradebot.common.calendar import IST

ISIN = "INE000T01010"
EVENT_TS = datetime(2026, 1, 15, 11, 0, tzinfo=IST)


def _seed_event(conn):
    conn.execute(
        "insert into backfill_events (isin, symbol, event_ts, raw_ids, primary_raw_id, bucket,"
        " value_inr, currency, company_is_recipient, state) values (%s, 'TEST', %s, '{1}', 1,"
        " 'order_win', 1000000, 'INR', true, 'verified')", (ISIN, EVENT_TS))
    conn.commit()


def _seed_raw(conn, raw_id: int, ts: datetime, *, isin: str | None, symbol: str, category: str):
    conn.execute(
        "insert into raw_announcements (id, source, source_id, payload_sha256, exchange_ts,"
        " first_seen_at, isin, symbol, category_raw, payload) overriding system value"
        " values (%s, 'nse', %s, %s, %s, %s, %s, %s, %s, '{}')",
        (raw_id, f"s{raw_id}", f"h{raw_id}", ts, ts, isin, symbol, category))
    conn.commit()


def test_a_same_company_filing_with_a_null_isin_still_counts_as_contamination(scratch_conn):
    _seed_event(scratch_conn)
    # The event's own filing (raw_id 1) is excluded via raw_ids; a second filing three days
    # later, same symbol, but with NO isin (the HILINFRA case) - must still be found.
    _seed_raw(scratch_conn, 1, EVENT_TS, isin=ISIN, symbol="TEST", category="Bagging/Receiving of orders/contracts")
    _seed_raw(scratch_conn, 2, EVENT_TS.replace(day=18), isin=None, symbol="TEST",
             category="General Updates")

    evs = study_data.load_events(scratch_conn, states=("verified",))
    assert len(evs) == 1
    assert evs[0].other_filings == [(EVENT_TS.replace(day=18).astimezone(timezone.utc),
                                     "catch_all")]


def test_a_null_isin_filing_for_a_different_symbol_is_never_matched(scratch_conn):
    _seed_event(scratch_conn)
    _seed_raw(scratch_conn, 1, EVENT_TS, isin=ISIN, symbol="TEST", category="Bagging/Receiving of orders/contracts")
    _seed_raw(scratch_conn, 2, EVENT_TS.replace(day=18), isin=None, symbol="OTHERCO",
             category="General Updates")

    evs = study_data.load_events(scratch_conn, states=("verified",))
    assert evs[0].other_filings == []


def test_an_unknown_category_is_logged_and_still_counted_as_contaminating(scratch_conn):
    _seed_event(scratch_conn)
    _seed_raw(scratch_conn, 1, EVENT_TS, isin=ISIN, symbol="TEST", category="Bagging/Receiving of orders/contracts")
    _seed_raw(scratch_conn, 2, EVENT_TS.replace(day=16), isin=ISIN, symbol="TEST",
             category="A Category Nobody Mapped")

    evs = study_data.load_events(scratch_conn, states=("verified",))
    assert evs[0].other_filings == [(EVENT_TS.replace(day=16).astimezone(timezone.utc),
                                     "unknown")]
    logged = scratch_conn.execute(
        "select count from unknown_categories where category_raw = 'A Category Nobody Mapped'"
    ).fetchone()
    assert logged == (1,)


def test_a_filing_under_the_companys_original_isin_counts_as_contamination(scratch_conn):
    # The event carries the universe's current ISIN; NSE tags the company's filings with its
    # original one (common/isin.py). Same issuer code, so it must still be found.
    _seed_event(scratch_conn)
    _seed_raw(scratch_conn, 1, EVENT_TS, isin="INE000T01002", symbol="TEST",
              category="Bagging/Receiving of orders/contracts")
    _seed_raw(scratch_conn, 2, EVENT_TS.replace(day=17), isin="INE000T01002", symbol="TEST",
              category="General Updates")
    _seed_raw(scratch_conn, 3, EVENT_TS.replace(day=17), isin="INE000U01010", symbol="TEST",
              category="General Updates")          # another issuer that once used the symbol

    evs = study_data.load_events(scratch_conn, states=("verified",))
    assert evs[0].other_filings == [(EVENT_TS.replace(day=17).astimezone(timezone.utc),
                                     "catch_all")]
