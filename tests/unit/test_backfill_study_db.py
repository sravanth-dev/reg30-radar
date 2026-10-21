"""The `calculate` and `study` stages end to end on real SQL (scratch schema): one company,
200 trading days, one verified order worth 20% of TTM revenue. Checks the SQL in
study_data.py, the §6 transitions, and that a report is written."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from reg30_radar.backfill import __main__ as backfill
from reg30_radar.backfill import report
from reg30_radar.common.calendar import IST

CR = Decimal(10) ** 7
ISIN = "INE000T01010"


def weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(date(2025, 3, 3), 280)
EVENT_DAY = DAYS[160]


def seed(conn, value_cr="200", mcap_cr="1000"):
    with conn.cursor() as cur:
        cur.executemany("insert into archive_days (day, udiff_status, pr_status, trading_day,"
                        " loaded_at) values (%s, 200, 200, true, now())", [(d,) for d in DAYS])
        cur.executemany("insert into index_prices (trade_date, index_name, close)"
                        " values (%s, 'Nifty 50', 100)", [(d,) for d in DAYS])
        cur.executemany(
            "insert into prices (trade_date, isin, symbol, series, open, high, low, close,"
            " volume, traded_value) values (%s, %s, 'TEST', 'EQ', 100, 100, 100, %s, 1000, 100000)",
            [(d, ISIN, 110 if d >= DAYS[165] else 100) for d in DAYS])   # +10% by day +5
        cur.executemany("insert into market_caps (trade_date, isin, mcap_inr) values (%s,%s,%s)",
                        [(d, ISIN, Decimal(mcap_cr) * CR) for d in DAYS])
        filed = lambda d: datetime.combine(d, time(18, 0), IST)   # noqa: E731
        for end, months, value, filed_on in [
            # All four filed before the event (mid-October 2025). A quarter filed later
            # must not count (rule 1): an earlier version of this test seeded two such
            # quarters, and TTM correctly came back unknown.
            (date(2024, 9, 30), 3, 250, date(2024, 11, 10)), (date(2024, 12, 31), 3, 250, date(2025, 2, 10)),
            (date(2025, 3, 31), 3, 250, date(2025, 5, 20)), (date(2025, 6, 30), 3, 250, date(2025, 8, 10)),
            (date(2025, 9, 30), 3, 900, date(2025, 11, 10))]:   # filed after: ignored
            cur.execute("insert into financials (isin, period_end, period_months, basis,"
                        " revenue_inr, filed_at, source_url) values (%s,%s,%s,'consolidated',%s,%s,'u')",
                        (ISIN, end, months, Decimal(value) * CR, filed(filed_on)))
    conn.execute(
        "insert into backfill_events (isin, symbol, event_ts, raw_ids, primary_raw_id, bucket,"
        " value_inr, currency, company_is_recipient, state) values (%s, 'TEST', %s, '{1}', 1,"
        " 'order_win', %s, 'INR', true, 'extracted')",
        (ISIN, datetime.combine(EVENT_DAY, time(11, 0), IST), Decimal(value_cr) * CR))
    # A band snapshot and one change, so study()'s price-band enrichment has something real
    # to reconstruct: on EVENT_DAY (before the 1 Sep 2026 change) the band was 5%.
    conn.execute("insert into band_snapshot (symbol, series, band, as_of_date)"
                 " values ('TEST', 'EQ', '10', %s)", (date(2026, 9, 27),))
    conn.execute("insert into band_changes (symbol, series, change_date, from_band, to_band)"
                 " values ('TEST', 'EQ', '2026-09-01', '5', '10')")
    conn.commit()


def test_calculate_verifies_a_modest_order_and_study_writes_a_report(scratch_conn, tmp_path,
                                                                      monkeypatch):
    seed(scratch_conn)
    cfg = {"window": {"announcements_from": str(DAYS[140]), "announcements_to": str(DAYS[200]),
                      "prices_from": str(DAYS[0])},
           "analysis": {"primary_mcap_crore": [500, 20000], "universe_mcap_crore": [500, 50000],
                        "muhurat_days": []}}
    # TTM known before the event: 4 x Rs 250 cr = Rs 1,000 cr; value/TTM 20%, value/mcap 20%.
    assert backfill.calculate(scratch_conn, cfg) == {"verified": 0, "recheck_pending": 1}
    state, ttm, v2m = scratch_conn.execute(
        "select state, ttm_revenue_inr, value_to_mcap from backfill_events").fetchone()
    assert state == "recheck_pending" and ttm == Decimal(1000) * CR and v2m == Decimal("0.2")

    scratch_conn.execute("update backfill_events set state = 'verified'")   # as a recheck would
    scratch_conn.commit()
    monkeypatch.setattr(report, "REPORTS_DIR", tmp_path)
    real_write = report.write
    monkeypatch.setattr(report, "write", lambda results, v, ctx: real_write(results, v, ctx, tmp_path))
    out = backfill.study(scratch_conn, cfg)
    assert out["events"] == 1 and out["primary_n"] == 1
    assert out["verdict"] == "INSUFFICIENT DATA"            # one event, not thirty
    text = (tmp_path / f"backfill_{date.today().isoformat()}.md").read_text(encoding="utf-8")
    assert "VERDICT: INSUFFICIENT DATA" in text and "10.00%" in text   # +10% excess at +5
    assert scratch_conn.execute("select count(*) from event_results").fetchone()[0] == 1

    csv_path = tmp_path / f"backfill_{date.today().isoformat()}_events.csv"
    row = csv_path.read_text(encoding="utf-8").splitlines()[1].split(",")
    header = csv_path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert dict(zip(header, row))["price_band"] == "5"   # reconstructed as of EVENT_DAY
