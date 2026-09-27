"""market/bands.py: parsing real NSE column shapes, and reconstructing a past band by
walking the change log backward from the current snapshot (§11, 27 Sep 2026). The
reconstruction tests run on real SQL (scratch schema)."""

from datetime import date

from tradebot.market.bands import parse_band_changes, parse_sec_list, reconstruct

SEC_LIST = (
    "Symbol,Series,Security Name,Band,Remarks\n"
    "21STCENMGM,EQ,21ST CENTURY MANAGEMENT SERVICES LIMITED,2,\"-\"\n"
    "ABAN,BE,ABAN OFFSHORE LIMITED,2,\"-\"\n"
    "NOBAND,EQ,A COMPANY WITH NO BAND,,\"-\"\n"
)

BAND_CHANGES = (
    "Sr. No,Symbol,Series,Security Name,From,To\n"
    "1,JITFINFRA,BE,JITF INFRALOGISTICS LIMITED,10,5\n"
    "2,DIGISPICE,BE,DIGISPICE TECHNOLOGIES LIMITED,20,5\n"
)


def test_parse_sec_list_reads_real_columns_and_blank_band_is_none():
    rows = parse_sec_list(SEC_LIST)
    assert rows[0].symbol == "21STCENMGM" and rows[0].series == "EQ" and rows[0].band == "2"
    assert rows[2].symbol == "NOBAND" and rows[2].band is None


def test_parse_band_changes_reads_real_columns():
    rows = parse_band_changes(BAND_CHANGES)
    assert [(r.symbol, r.from_band, r.to_band) for r in rows] == [
        ("JITFINFRA", "10", "5"), ("DIGISPICE", "20", "5")]


def _seed(conn):
    conn.execute("insert into band_snapshot (symbol, series, band, as_of_date)"
                 " values ('ABC', 'EQ', '10', %s)", (date(2026, 9, 27),))
    conn.execute("insert into band_changes (symbol, series, change_date, from_band, to_band)"
                 " values ('ABC', 'EQ', %s, '5', '10')", (date(2026, 6, 1),))
    conn.execute("insert into band_changes (symbol, series, change_date, from_band, to_band)"
                 " values ('ABC', 'EQ', %s, '2', '5')", (date(2025, 12, 1),))
    conn.commit()


def test_reconstruct_undoes_changes_back_to_the_target_date(scratch_conn):
    _seed(scratch_conn)
    out = reconstruct(scratch_conn, [
        ("ABC", "EQ", date(2026, 9, 27)),    # today: the live snapshot value
        ("ABC", "EQ", date(2026, 7, 1)),     # after the 1-Jun change, before any later one
        ("ABC", "EQ", date(2026, 1, 1)),     # after the 1-Dec-2025 change, before 1-Jun
        ("ABC", "EQ", date(2025, 1, 1)),     # before every recorded change
    ])
    assert out[("ABC", "EQ", date(2026, 9, 27))] == "10"
    assert out[("ABC", "EQ", date(2026, 7, 1))] == "10"
    assert out[("ABC", "EQ", date(2026, 1, 1))] == "5"
    assert out[("ABC", "EQ", date(2025, 1, 1))] == "2"


def test_reconstruct_returns_none_for_a_symbol_absent_from_the_snapshot(scratch_conn):
    _seed(scratch_conn)
    out = reconstruct(scratch_conn, [("DELISTED", "EQ", date(2026, 1, 1))])
    assert out[("DELISTED", "EQ", date(2026, 1, 1))] is None


def test_reconstruct_never_confuses_two_series_of_the_same_symbol(scratch_conn):
    _seed(scratch_conn)
    # A second series for the same symbol, with its own independent band - the SQL filters
    # by symbol alone, so this checks the Python-side (symbol, series) narrowing works.
    scratch_conn.execute("insert into band_snapshot (symbol, series, band, as_of_date)"
                         " values ('ABC', 'BE', '20', %s)", (date(2026, 9, 27),))
    scratch_conn.commit()
    out = reconstruct(scratch_conn, [("ABC", "BE", date(2026, 9, 27))])
    assert out[("ABC", "BE", date(2026, 9, 27))] == "20"
