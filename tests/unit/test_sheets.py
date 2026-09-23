"""The Google Sheets mirror: row formatting, the API request shape, and the idempotent-
retry property sync.py exists to guarantee. No network and no database - the fakes below
stand in for the Sheets HTTP session and for a psycopg connection.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tradebot.sheets import sync
from tradebot.sheets.client import SheetsClient, _col_letter
from tradebot.sheets.rows import HEADER, to_sheet_row

UTC = ZoneInfo("UTC")
IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------------------
# rows.py - pure formatting
# ---------------------------------------------------------------------------------------

def _record(row_id=1, exchange_ts=None, symbol="BEL", company="Bharat Electronics",
            category_raw="Bagging/Receiving of orders/contracts", headline="=SUM(A1:A2)",
            attachment_url="https://nsearchives.nseindia.com/corporate/x.pdf",
            industry="Aerospace & Defense", isin="INE263A01024", first_seen_at=None,
            revision=1):
    return (row_id, exchange_ts, symbol, company, category_raw, headline, attachment_url,
            industry, isin, first_seen_at, revision)


def test_header_has_eleven_plain_columns():
    assert len(HEADER) == 11
    assert HEADER[0] == "id"


def test_timestamps_convert_utc_to_ist_text():
    ts = datetime(2026, 9, 23, 4, 9, 5, tzinfo=UTC)  # 09:39:05 IST
    row = to_sheet_row(_record(exchange_ts=ts, first_seen_at=ts))
    assert row[1] == "2026-09-23 09:39:05"
    assert row[9] == "2026-09-23 09:39:05"


def test_missing_values_become_empty_strings_not_none():
    row = to_sheet_row(_record(exchange_ts=None, isin=None, first_seen_at=None))
    assert row[1] == "" and row[8] == "" and row[9] == ""
    assert None not in row


def test_a_formula_looking_headline_is_passed_through_unescaped():
    # Safety comes from client.write() sending valueInputOption=RAW (tested below), not
    # from this function mangling the text - it must reach the API byte-for-byte.
    row = to_sheet_row(_record(headline="=SUM(A1:A2)"))
    assert row[5] == "=SUM(A1:A2)"


def test_long_text_is_capped_with_a_visible_marker():
    row = to_sheet_row(_record(headline="x" * 60_000))
    assert len(row[5]) <= 50_000
    assert row[5].endswith("truncated for Sheets' 50,000-character cell limit]")


def test_all_cells_are_strings():
    row = to_sheet_row(_record())
    assert all(isinstance(c, str) for c in row)


# ---------------------------------------------------------------------------------------
# client.py - pure helpers and request shape
# ---------------------------------------------------------------------------------------

def test_col_letter():
    assert _col_letter(1) == "A"
    assert _col_letter(11) == "K"
    assert _col_letter(26) == "Z"
    assert _col_letter(27) == "AA"


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text

    def json(self):
        return self._json


_PROPS = {"sheets": [{"properties": {
    "title": "raw_announcements", "sheetId": 42, "gridProperties": {"rowCount": 1000},
}}]}


class _FakeHttpSession:
    """Records every call. Answers grid metadata from a fixed fixture and an empty header
    read, which is enough to drive client.py's logic without a real API."""

    def __init__(self, properties=None, row_count=1000):
        self.calls: list[tuple] = []
        self._row_count = row_count
        self._props = properties or _PROPS

    def get(self, url, params=None):
        self.calls.append(("GET", url, params, None))
        if "/values/" in url:
            return _FakeResponse(json_body={})  # no values yet at this range
        props = {**self._props}
        props["sheets"][0]["properties"]["gridProperties"]["rowCount"] = self._row_count
        return _FakeResponse(json_body=props)

    def post(self, url, json=None):
        self.calls.append(("POST", url, None, json))
        return _FakeResponse(json_body={})

    def put(self, url, params=None, json=None):
        self.calls.append(("PUT", url, params, json))
        return _FakeResponse(json_body={})


def test_write_always_uses_raw_input_option_and_a_fixed_range():
    session = _FakeHttpSession()
    client = SheetsClient(session=session, spreadsheet_id="SHEET1", tab_name="raw_announcements")

    client.write(2, [["1", "2026-09-23 09:39:05"]])

    method, url, params, body = session.calls[-1]
    assert method == "PUT"
    assert params == {"valueInputOption": "RAW"}
    assert body["range"] == "'raw_announcements'!A2:B2"
    assert body["values"] == [["1", "2026-09-23 09:39:05"]]


def test_ensure_rows_grows_grid_only_when_needed():
    session = _FakeHttpSession(row_count=10)
    client = SheetsClient(session=session, spreadsheet_id="SHEET1", tab_name="raw_announcements")

    client.ensure_rows(5)
    assert not any(c[0] == "POST" and c[1].endswith(":batchUpdate") for c in session.calls)

    client.ensure_rows(20)
    grow_calls = [c for c in session.calls if c[0] == "POST" and c[1].endswith(":batchUpdate")]
    assert len(grow_calls) == 1
    assert grow_calls[0][3]["requests"][0]["appendDimension"]["length"] == 10


# ---------------------------------------------------------------------------------------
# sync.py - the idempotent-retry property, with fakes for both the sheet and the DB
# ---------------------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _FakeConn:
    """Dispatches on which query sync.py sent. Not a real database - just enough to drive
    sync.py's control flow with no network and no Postgres, per this file's docstring."""

    def __init__(self, raw_rows):
        self.raw_rows = raw_rows  # list of 11-tuples, shaped like SELECT_SQL's result
        self.sync_log: list[dict] = []

    def execute(self, sql, params=()):
        s = sql.lower()
        if "select last_raw_id, last_row from sheets_sync" in s:
            ok_rows = [r for r in self.sync_log if r["ok"]]
            if not ok_rows:
                return _FakeCursor(one=None)
            latest = ok_rows[-1]
            return _FakeCursor(one=(latest["last_raw_id"], latest["last_row"]))
        if "from raw_announcements" in s:
            after_id, limit = params
            batch = [r for r in self.raw_rows if r[0] > after_id][:limit]
            return _FakeCursor(many=batch)
        if "insert into sheets_sync" in s:
            ok, rows_written, first_row, last_row, last_raw_id, error = params
            self.sync_log.append(dict(
                ok=ok, rows_written=rows_written, first_row=first_row,
                last_row=last_row, last_raw_id=last_raw_id, error=error,
            ))
            return _FakeCursor()
        raise AssertionError(f"unexpected SQL in fake conn: {sql!r}")

    def commit(self):
        pass


class _FakeSheet:
    """In-memory stand-in for SheetsClient. `raise_after_writes` simulates a write that
    lands at Google but whose response never reaches us (a hotspot timeout)."""

    def __init__(self, raise_after_writes: int | None = None):
        self.grid: dict[int, list[str]] = {}
        self.write_calls: list[tuple[int, list[list[str]]]] = []
        self.cleared = False
        self._raise_after_writes = raise_after_writes
        self._writes_done = 0

    def ensure_header(self, header):
        self.grid[1] = list(header)

    def ensure_rows(self, min_rows):
        pass  # the fake grid is unbounded

    def write(self, start_row, rows):
        self.write_calls.append((start_row, [list(r) for r in rows]))
        for offset, row in enumerate(rows):
            self.grid[start_row + offset] = list(row)
        self._writes_done += 1
        if self._writes_done == self._raise_after_writes:
            raise TimeoutError("simulated: write reached Google, the reply did not reach us")

    def clear_data(self):
        self.cleared = True
        self.grid = {row: cells for row, cells in self.grid.items() if row == 1}


def _raw_row(row_id: int):
    ts = datetime(2026, 9, 23, 9, 0, 0, tzinfo=IST)
    return (row_id, ts, "BEL", "Bharat Electronics", "Bagging/Receiving of orders/contracts",
            "BEL bags order", "https://x/y.pdf", "Aerospace & Defense", "INE263A01024",
            ts, 1)


def test_sync_once_writes_new_rows_from_row_two_and_records_the_watermark():
    conn = _FakeConn([_raw_row(1), _raw_row(2)])
    sheet = _FakeSheet()

    result = sync.sync_once(conn, sheet, chunk_size=10)

    assert result.rows_written == 2
    assert result.first_row == 2
    assert result.last_row == 3
    assert result.last_raw_id == 2
    assert sheet.grid[2][0] == "1" and sheet.grid[3][0] == "2"
    assert conn.sync_log[-1]["ok"] is True


def test_sync_once_with_nothing_new_writes_zero_rows():
    conn = _FakeConn([])
    sheet = _FakeSheet()

    result = sync.sync_once(conn, sheet, chunk_size=10)

    assert result.rows_written == 0
    assert result.first_row is None
    assert sheet.write_calls == []


def test_running_again_after_a_full_sync_writes_nothing_new():
    conn = _FakeConn([_raw_row(1), _raw_row(2)])
    sheet = _FakeSheet()
    sync.sync_once(conn, sheet, chunk_size=10)

    second = sync.sync_once(conn, sheet, chunk_size=10)

    assert second.rows_written == 0
    assert len(sheet.write_calls) == 1  # only the first run actually wrote anything


def test_retry_after_a_write_succeeds_but_the_record_step_fails_does_not_duplicate():
    # chunk_size=1 so each filing is its own write() call, and the simulated failure on
    # the first one leaves the second and third rows genuinely unattempted this run.
    conn = _FakeConn([_raw_row(1), _raw_row(2), _raw_row(3)])
    sheet = _FakeSheet(raise_after_writes=1)

    with pytest.raises(TimeoutError):
        sync.sync_once(conn, sheet, chunk_size=1)

    # The chunk landed on the sheet even though this run "failed" from our side...
    assert sheet.grid[2][0] == "1"
    # ...but only ok=True rows count as the watermark, so the next run does not know that.
    assert conn.sync_log[-1]["ok"] is False

    # Retry, this time against a sheet that succeeds - starting from the *old* watermark,
    # because the failed run's progress was never recorded.
    sheet2 = _FakeSheet()
    result = sync.sync_once(conn, sheet2, chunk_size=1)

    assert result.rows_written == 3
    # Same starting row, same content, as the first (unrecorded) attempt would have used.
    assert sheet2.write_calls[0] == (2, [to_sheet_row(_raw_row(1))])
    # No sheet row ever ends up holding two different filings.
    assert len(sheet2.grid) == 4  # header + 3 data rows, one filing each


def test_rebuild_clears_the_sheet_and_resyncs_from_the_first_row():
    conn = _FakeConn([_raw_row(1), _raw_row(2)])
    sheet = _FakeSheet()
    sync.sync_once(conn, sheet, chunk_size=10)  # pretend a prior sync already ran

    result = sync.rebuild(conn, sheet, chunk_size=10)

    assert sheet.cleared is True
    assert result.rows_written == 2
    assert result.first_row == 2
    assert sheet.grid[2][0] == "1" and sheet.grid[3][0] == "2"
