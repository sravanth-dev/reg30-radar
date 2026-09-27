"""backfill/documents.py's download policy, on real SQL (scratch schema): order categories
first, then catch-all headline hits, then the rest; and a catch-all filing that only a
body check could turn into an order is left out for a company above the ceiling (the
control group, config/backfill.yaml `documents`, 27 Sep 2026)."""

from datetime import date, datetime

from tradebot.backfill import documents
from tradebot.common.calendar import IST

CRORE = 10 ** 7
SMALL, LARGE = "INE100A01011", "INE200B01012"      # Rs 1,000 cr and Rs 60,000 cr


def _seed(conn):
    for isin, symbol, crore in ((SMALL, "SMALLCO", 1000), (LARGE, "LARGECO", 60000)):
        conn.execute("insert into backfill_universe (isin, symbol, series, as_of_date, mcap_inr)"
                     " values (%s, %s, 'EQ', '2025-09-22', %s)", (isin, symbol, crore * CRORE))
        conn.execute("insert into instrument_symbols (isin, symbol, series, first_seen, last_seen)"
                     " values (%s, %s, 'EQ', '2025-03-03', '2026-09-25')", (isin, symbol))
    # (id, isin as NSE sent it, symbol, category, headline). LARGE's filings carry its
    # original ISIN, as NSE's announcements do (common/isin.py).
    filings = [
        (1, SMALL, "SMALLCO", "General Updates", "Change in registered office address"),
        (2, "INE200B01004", "LARGECO", "General Updates", "Change in registered office address"),
        (3, "INE200B01004", "LARGECO", "General Updates", "Receipt of a work order"),
        (4, "INE200B01004", "LARGECO", "Bagging/Receiving of orders/contracts", "Order"),
        (5, None, "LARGECO", "Updates", "Intimation under Regulation 30"),
        (6, SMALL, "SMALLCO", "Trading Window", "Closure of trading window"),
    ]
    ts = datetime(2026, 1, 15, 11, 0, tzinfo=IST)
    for raw_id, isin, symbol, category, headline in filings:
        conn.execute(
            "insert into raw_announcements (id, source, source_id, payload_sha256, exchange_ts,"
            " first_seen_at, isin, symbol, category_raw, headline, payload) overriding system"
            " value values (%s, 'nse', %s, %s, %s, %s, %s, %s, %s, %s, '{}')",
            (raw_id, f"s{raw_id}", f"h{raw_id}", ts, ts, isin, symbol, category, headline))
    conn.commit()


def test_order_categories_then_headline_hits_then_the_rest(scratch_conn):
    _seed(scratch_conn)
    rows = documents.window_rows(scratch_conn, date(2025, 9, 22), date(2026, 9, 18))
    waiting, left_out = documents.todo(scratch_conn, rows)
    # no ceiling: every in-scope filing, in tier order; the Trading Window filing is noise
    assert [r["id"] for r in waiting][:2] == [4, 3]
    assert sorted(r["id"] for r in waiting[2:]) == [1, 2, 5] and left_out == 0


def test_body_check_catch_all_is_left_out_above_the_ceiling(scratch_conn):
    _seed(scratch_conn)
    rows = documents.window_rows(scratch_conn, date(2025, 9, 22), date(2026, 9, 18))
    waiting, left_out = documents.todo(scratch_conn, rows, max_mcap_crore=50000)
    # LARGECO keeps its order filing and its headline hit, loses the two body-check-only
    # filings (one matched by its original ISIN's issuer code, one by symbol, no ISIN)
    assert [r["id"] for r in waiting] == [4, 3, 1]
    assert left_out == 2
