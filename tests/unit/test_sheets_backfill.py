"""sheets/backfill.py: the backfill_events tab, offline (fake connection, fake sheet)."""

from datetime import datetime, timezone
from decimal import Decimal

from reg30_radar.sheets import backfill
from tests.unit.test_sheets_orders import _FakeCursor, _FakeSheet

CR = Decimal(10) ** 7
TS = datetime(2026, 2, 6, 10, 30, tzinfo=timezone.utc)


def _record(result=None, value=Decimal(250) * CR, ttm=Decimal(1000) * CR):
    return (TS, "BAJEL", value, "INR", ["range"], ttm, Decimal("0.123456"), "consolidated",
            "verified", True, "order", "PGCIL", "18 months", 2, result,
            TS if result else None, "INE0KCE01017", 522)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        assert "from backfill_events" in sql.lower()
        return _FakeCursor(self.rows)


def test_header_and_number_columns_line_up():
    for name, col in backfill.NUMBER_COLS.items():
        assert backfill.HEADER[col - 1] == name


def test_a_row_before_any_study_run_has_blank_study_columns():
    text, numbers = backfill.to_row(_record())
    assert numbers[3] == "250.00" and numbers[6] == "1000.00"
    assert numbers[7] == "25.00" and numbers[8] == "12.35"          # value/TTM, value/mcap %
    assert numbers[19] == "" and text[20] == "" and text[16 - 1] == ""
    assert len(text) == len(backfill.HEADER)


def test_the_study_columns_come_from_the_latest_result():
    result = {"day0": "2026-02-06", "mcap_cr": 6123.4, "excess_5": "-0.0123",
              "exclusions": "", "capital_action": None, "contaminated_by": "results",
              "locked_0": None, "price_band": "20"}
    text, numbers = backfill.to_row(_record(result))
    assert numbers[19] == "-1.23" and numbers[17] == "6123.40"
    assert text[15] == "2026-02-06" and text[20] == "no"       # contaminated, so not clean
    assert text[22] == "results"


def test_sync_skips_the_write_when_nothing_changed():
    sheet, conn = _FakeSheet(), _Conn([_record()])
    fp, n = backfill.sync_backfill(conn, sheet, None)
    assert n == 1 and len(sheet.write_numbers_calls) == len(backfill.NUMBER_COLS)
    calls = len(sheet.write_calls)
    assert backfill.sync_backfill(conn, sheet, fp) == (fp, 0) and len(sheet.write_calls) == calls


def test_clear_from_clears_whole_rows_and_skips_below_the_grid(monkeypatch):
    from reg30_radar.sheets.client import SheetsClient
    from tests.unit.test_sheets_orders import _FakeHttpSession
    s = _FakeHttpSession()
    c = SheetsClient(session=s, spreadsheet_id="x", tab_name="backfill_events", api_base="https://h")
    monkeypatch.setattr(c, "row_count", lambda: 1282)
    c.clear_from(1283)                                    # the grid ends above: no request
    assert s.calls == []
    c.clear_from(100)
    assert "100%3A1282" in s.calls[0][1]                  # whole rows, every column
