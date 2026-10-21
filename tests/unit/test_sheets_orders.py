"""The `orders` Sheets tab: crore/bool/path formatting, the write_numbers/ensure_tab
request shapes, and the rewrite-whole-tab-unless-unchanged behaviour of sync_orders. No
network and no database - fakes stand in for both, in the style of test_sheets.py.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from reg30_radar.sheets import orders
from reg30_radar.sheets.client import SheetsClient

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------------------
# orders.py - pure formatting
# ---------------------------------------------------------------------------------------

def _record(exchange_ts=None, symbol="BDL", company="Bharat Dynamics",
            category_raw="Bagging/Receiving of orders/contracts", bucket="order_win",
            relevance_reason="category is order_win", value_inr=None,
            consideration_raw="Rs. 810.79 Crore", path="t0", provenance_ok=True,
            review_status="verified", stage="contract", company_is_recipient=True,
            awarding_entity="Ministry of Defence", execution_period_raw="24 months",
            currency="INR", gst_inclusive=None, quality="ok", last_error=None,
            attachment_url="https://nsearchives.nseindia.com/corporate/BDL.pdf",
            llm_cost_usd=Decimal("0"), processed_at=None, raw_id=1):
    return (exchange_ts, symbol, company, category_raw, bucket, relevance_reason,
            value_inr, consideration_raw, path, provenance_ok, review_status, stage,
            company_is_recipient, awarding_entity, execution_period_raw, currency,
            gst_inclusive, quality, last_error, attachment_url, llm_cost_usd,
            processed_at, raw_id)


def test_header_has_twenty_three_columns_matching_value_col():
    assert len(orders.HEADER) == 23
    assert orders.HEADER[orders.VALUE_COL - 1] == "Value (Rs cr)"


def test_crore_cell_rounds_half_up_to_two_decimals():
    assert orders._crore_cell(Decimal("8107900000.00")) == "810.79"   # BDL, real filing
    assert orders._crore_cell(Decimal("567337.00")) == "0.06"          # GHCL, real filing
    assert orders._crore_cell(None) == ""


def test_bool_cell_is_yes_no_or_blank():
    assert orders._bool_cell(True) == "yes"
    assert orders._bool_cell(False) == "no"
    assert orders._bool_cell(None) == ""


def test_path_labels():
    t0_cells, _ = orders.to_orders_row(_record(path="t0"))
    llm_cells, _ = orders.to_orders_row(_record(path="llm"))
    assert t0_cells[8] == "T0 parser"
    assert llm_cells[8] == "LLM"


def test_to_orders_row_splits_value_out_of_the_text_block():
    text_cells, value_cell = orders.to_orders_row(_record(value_inr=Decimal("8107900000.00")))
    assert len(text_cells) == 23
    assert text_cells[orders.VALUE_COL - 1] == ""     # never written into the RAW block
    assert value_cell == "810.79"


def test_a_formula_looking_consideration_is_passed_through_unescaped():
    # Safety comes from client.write() sending valueInputOption=RAW - same guarantee as
    # the raw tab (test_sheets.py) - not from this function mangling the text.
    text_cells, _ = orders.to_orders_row(_record(consideration_raw="=SUM(A1:A2)"))
    assert text_cells[7] == "=SUM(A1:A2)"


def test_timestamps_convert_to_ist_text():
    ts = datetime(2026, 9, 25, 4, 30, 0, tzinfo=ZoneInfo("UTC"))  # 10:00:00 IST
    text_cells, _ = orders.to_orders_row(_record(exchange_ts=ts, processed_at=ts))
    assert text_cells[0] == "2026-09-25 10:00:00"
    assert text_cells[21] == "2026-09-25 10:00:00"


# ---------------------------------------------------------------------------------------
# client.py - write_numbers and ensure_tab request shapes
# ---------------------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text

    def json(self):
        return self._json


class _FakeHttpSession:
    def __init__(self):
        self.calls: list[tuple] = []

    def get(self, url, params=None):
        self.calls.append(("GET", url, params, None))
        return _FakeResponse(json_body={})

    def post(self, url, json=None):
        self.calls.append(("POST", url, None, json))
        return _FakeResponse(json_body={})

    def put(self, url, params=None, json=None):
        self.calls.append(("PUT", url, params, json))
        return _FakeResponse(json_body={})


def test_write_numbers_sends_user_entered_and_a_single_column_range():
    session = _FakeHttpSession()
    client = SheetsClient(session=session, spreadsheet_id="SHEET1", tab_name="orders")

    client.write_numbers(orders.VALUE_COL, 2, ["810.79", "", "0.06"])

    method, url, params, body = session.calls[-1]
    assert method == "PUT"
    assert params == {"valueInputOption": "USER_ENTERED"}
    assert body["range"] == "'orders'!G2:G4"
    assert body["values"] == [["810.79"], [""], ["0.06"]]


@pytest.mark.parametrize("bad", ["=1+1", "1e5", "abc", "1,000", "810.79 Crore"])
def test_write_numbers_refuses_anything_not_a_plain_number(bad):
    session = _FakeHttpSession()
    client = SheetsClient(session=session, spreadsheet_id="SHEET1", tab_name="orders")

    with pytest.raises(ValueError):
        client.write_numbers(orders.VALUE_COL, 2, [bad])

    # The check runs before any HTTP call - filing text must never reach USER_ENTERED.
    assert session.calls == []


class _FakeTabSession:
    """Simulates a spreadsheet that may or may not already have this client's tab, and
    answers an addSheet batchUpdate by adding it - enough to drive ensure_tab() without a
    real spreadsheet."""

    def __init__(self, existing_titles: list[str], new_sheet_id: int = 99):
        self.existing_titles = list(existing_titles)
        self.new_sheet_id = new_sheet_id
        self.calls: list[tuple] = []

    def get(self, url, params=None):
        self.calls.append(("GET", url, params, None))
        sheets = [{"properties": {"title": t, "sheetId": i}}
                  for i, t in enumerate(self.existing_titles)]
        return _FakeResponse(json_body={"sheets": sheets})

    def post(self, url, json=None):
        self.calls.append(("POST", url, None, json))
        if url.endswith(":batchUpdate") and json and "addSheet" in json["requests"][0]:
            title = json["requests"][0]["addSheet"]["properties"]["title"]
            self.existing_titles.append(title)
            return _FakeResponse(json_body={"replies": [
                {"addSheet": {"properties": {"sheetId": self.new_sheet_id, "title": title}}}
            ]})
        return _FakeResponse(json_body={})

    def put(self, url, params=None, json=None):
        self.calls.append(("PUT", url, params, json))
        return _FakeResponse(json_body={})


def test_ensure_tab_creates_a_missing_tab():
    session = _FakeTabSession(existing_titles=["raw_announcements"])
    client = SheetsClient(session=session, spreadsheet_id="SHEET1", tab_name="orders")

    client.ensure_tab()

    add_calls = [c for c in session.calls if c[0] == "POST" and c[1].endswith(":batchUpdate")]
    assert len(add_calls) == 1
    assert add_calls[0][3]["requests"][0]["addSheet"]["properties"]["title"] == "orders"
    assert client.sheet_id() == 99   # cached from the addSheet reply, no extra GET needed
    assert "orders" in session.existing_titles


def test_ensure_tab_leaves_an_existing_tab_alone():
    session = _FakeTabSession(existing_titles=["raw_announcements", "orders"])
    client = SheetsClient(session=session, spreadsheet_id="SHEET1", tab_name="orders")

    client.ensure_tab()

    assert not any(c[0] == "POST" and c[1].endswith(":batchUpdate") for c in session.calls)


# ---------------------------------------------------------------------------------------
# sync_orders - rewrite-whole-tab-unless-unchanged, with fakes for both the sheet and DB
# ---------------------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeOrdersConn:
    """Answers exactly the one query sync_orders sends. Not a real database - see
    test_sheets.py's _FakeConn for the same pattern on the raw tab's sync."""

    def __init__(self, rows: list[tuple]):
        self.rows = rows

    def execute(self, sql, params=None):
        assert "from order_extractions" in sql.lower()
        return _FakeCursor(self.rows)


class _FakeSheet:
    """In-memory stand-in for SheetsClient, tracking the orders-specific calls
    (write_numbers, clear_from) alongside the ones test_sheets.py's fake already covers."""

    def __init__(self):
        self.grid: dict[int, list[str]] = {}
        self.write_calls: list[tuple[int, list[list[str]]]] = []
        self.write_numbers_calls: list[tuple[int, int, list[str]]] = []
        self.clear_from_calls: list[int] = []

    def ensure_header(self, header):
        self.grid[1] = list(header)

    def ensure_rows(self, min_rows):
        pass

    def write(self, start_row, rows):
        self.write_calls.append((start_row, [list(r) for r in rows]))
        for offset, row in enumerate(rows):
            self.grid[start_row + offset] = list(row)

    def write_numbers(self, col, start_row, values):
        self.write_numbers_calls.append((col, start_row, list(values)))
        for offset, v in enumerate(values):
            row = self.grid.setdefault(start_row + offset, [""] * len(orders.HEADER))
            row[col - 1] = v

    def clear_from(self, row):
        self.clear_from_calls.append(row)
        self.grid = {r: cells for r, cells in self.grid.items() if r < row}


def test_sync_orders_writes_newest_first_with_value_in_its_own_column():
    rows = [
        _record(raw_id=1, symbol="BDL", value_inr=Decimal("8107900000.00")),
        _record(raw_id=2, symbol="GHCL", value_inr=Decimal("567337.00")),
    ]
    conn = _FakeOrdersConn(rows)
    sheet = _FakeSheet()

    fingerprint, rows_written = orders.sync_orders(conn, sheet, None)

    assert rows_written == 2
    assert sheet.write_calls[0][0] == 2          # starts right after the header
    assert sheet.grid[2][1] == "BDL"             # Symbol column, row 2
    assert sheet.grid[3][1] == "GHCL"
    assert sheet.grid[2][orders.VALUE_COL - 1] == "810.79"
    assert sheet.grid[3][orders.VALUE_COL - 1] == "0.06"
    assert fingerprint  # non-empty


def test_sync_orders_skips_the_write_when_nothing_changed():
    rows = [_record(raw_id=1, symbol="BDL", value_inr=Decimal("8107900000.00"))]
    conn = _FakeOrdersConn(rows)
    sheet = _FakeSheet()
    fingerprint, _ = orders.sync_orders(conn, sheet, None)

    fingerprint2, rows_written = orders.sync_orders(conn, sheet, fingerprint)

    assert rows_written == 0
    assert fingerprint2 == fingerprint
    assert len(sheet.write_calls) == 1   # only the first call actually wrote anything


def test_sync_orders_rewrites_after_a_status_changes():
    rows = [_record(raw_id=1, symbol="BDL", review_status="needs_review")]
    conn = _FakeOrdersConn(rows)
    sheet = _FakeSheet()
    fingerprint, _ = orders.sync_orders(conn, sheet, None)

    rows[0] = _record(raw_id=1, symbol="BDL", review_status="verified")
    fingerprint2, rows_written = orders.sync_orders(conn, sheet, fingerprint)

    assert rows_written == 1
    assert fingerprint2 != fingerprint
    assert sheet.grid[2][10] == "verified"   # Status column


def test_sync_orders_clears_rows_below_the_new_end_when_the_count_shrinks():
    two_rows = [_record(raw_id=1, symbol="BDL"), _record(raw_id=2, symbol="GHCL")]
    conn = _FakeOrdersConn(two_rows)
    sheet = _FakeSheet()
    fingerprint, _ = orders.sync_orders(conn, sheet, None)
    assert 3 in sheet.grid

    conn.rows = [_record(raw_id=1, symbol="BDL")]   # GHCL's row is gone this cycle
    orders.sync_orders(conn, sheet, fingerprint)

    assert 3 not in sheet.grid
    assert sheet.clear_from_calls[-1] == 3   # cleared from end_row + 1 = (1 + 1) + 1


def test_sync_orders_clears_everything_when_the_table_is_empty():
    conn = _FakeOrdersConn([_record(raw_id=1)])
    sheet = _FakeSheet()
    fingerprint, _ = orders.sync_orders(conn, sheet, None)

    conn.rows = []
    fingerprint2, rows_written = orders.sync_orders(conn, sheet, fingerprint)

    assert rows_written == 0
    assert 2 in sheet.clear_from_calls
    assert fingerprint2 != fingerprint
