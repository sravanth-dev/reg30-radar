"""backfill/study_data.py's contamination lookup, on real SQL (scratch schema): a company's
other filing counts even when its own `isin` is null, matched on symbol instead - the case
Spike A found (sm_isin not 100% populated) that would otherwise silently understate
contamination and make the study look cleaner than it is."""

from datetime import datetime, timezone

from reg30_radar.backfill import study_data
from reg30_radar.common.calendar import IST

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


def test_prices_follow_a_reissued_isin_and_the_switch_is_a_capital_action(scratch_conn):
    # BEML, 3 Nov 2025: a 1:2 split reissued INE258A01016 as INE258A01024 (NSE flagged XO).
    # A second switch with no NSE flag must be marked too: 14 of 57 real switches had none.
    # The rights entitlement (security type 20) must never be mixed in.
    from datetime import date
    from decimal import Decimal
    from reg30_radar.backfill.event_study import NEW_ISIN

    c = scratch_conn
    rows = [("2025-10-30", "INE258A01016", "4400.00", None),
            ("2025-10-31", "INE258A01016", "4399.80", None),
            ("2025-11-03", "INE258A01024", "2187.00", "XO"),
            ("2025-11-04", "INE258A01024", "2150.40", None),
            ("2025-11-05", "INE258A01032", "2140.00", None),
            ("2025-11-05", "INE258A20016", "12.00", None)]           # BEML-RE, not the stock
    for d, isin, close, corp in rows:
        c.execute("insert into prices (trade_date, isin, symbol, series, close, corp_ind)"
                  " values (%s, %s, 'BEML', 'EQ', %s, %s)", (d, isin, close, corp))
        c.execute("insert into market_caps (trade_date, isin, mcap_inr) values (%s, %s, 1)",
                  (d, isin))
    for d in ("2025-10-30", "2025-10-31", "2025-11-03", "2025-11-04", "2025-11-05"):
        c.execute("insert into archive_days (day, trading_day, loaded_at) values (%s, true, now())",
                  (d,))
    c.commit()

    m = study_data.load_market(c, ["INE258A01016"], date(2025, 10, 1), date(2025, 11, 30), set())
    bars = m.bars["INE258A01016"]
    assert [bars[d].close for d in sorted(bars)] == [
        Decimal("4400.00"), Decimal("4399.80"), Decimal("2187.00"), Decimal("2150.40"),
        Decimal("2140.00")]
    assert bars[date(2025, 11, 3)].corp_ind == f"XO {NEW_ISIN}"
    assert bars[date(2025, 11, 4)].corp_ind is None
    assert bars[date(2025, 11, 5)].corp_ind == NEW_ISIN
    assert len(m.mcap["INE258A01016"]) == 5
