"""Reading `raw_announcements` and writing it to a Sheet, without ever duplicating a row.

The idempotency property this module exists to guarantee: sheet row r always holds the
(r-1)-th filing in raw_announcements.id order. That mapping never changes, because
raw_announcements is append-only (a database trigger enforces it) and this process is the
Sheet's only writer. So a chunk can always be safely re-sent to the same rows - the retry
overwrites identical content, it never appends a duplicate.

The watermark (the last raw_announcements.id confirmed written, and the sheet row it
landed on) is only ever read from a *successful* sheets_sync row. If a run's write reaches
Google but the run then fails before it can record success - a timeout on the hotspot, a
dropped connection - the next run finds the old watermark, redoes that chunk, and writes
the same content to the same cells. Wasteful in that one case; never wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from reg30_radar.sheets.rows import HEADER, SELECT_SQL, to_sheet_row

# Row 1 is the header (client.py writes it via ensure_header), so the first filing always
# lands on row 2.
FIRST_DATA_ROW = 2

_WATERMARK_SQL = """
    select last_raw_id, last_row from sheets_sync where ok order by id desc limit 1
"""

_RECORD_SQL = """
    insert into sheets_sync (ok, rows_written, first_row, last_row, last_raw_id, error)
    values (%s, %s, %s, %s, %s, %s)
"""


@dataclass
class SyncResult:
    rows_written: int
    first_row: int | None
    last_row: int | None
    last_raw_id: int | None


def _last_watermark(conn) -> tuple[int, int]:
    row = conn.execute(_WATERMARK_SQL).fetchone()
    if row is None:
        return 0, FIRST_DATA_ROW - 1
    last_raw_id, last_row = row
    return last_raw_id, last_row


def _record(conn, *, ok: bool, rows_written: int, first_row: int | None,
            last_row: int | None, last_raw_id: int | None, error: str | None) -> None:
    conn.execute(_RECORD_SQL, (ok, rows_written, first_row, last_row, last_raw_id, error))
    conn.commit()


def sync_once(conn, sheet, chunk_size: int = 2000, *, force_from_start: bool = False
              ) -> SyncResult:
    """Write every filing newer than the watermark to `sheet`, in id order, in chunks.

    `force_from_start` is how --rebuild resyncs everything: it skips reading the stored
    watermark and starts from raw_announcements.id 0, so every row is rewritten even
    though the sheet was just cleared.
    """
    sheet.ensure_header(HEADER)

    if force_from_start:
        last_raw_id, last_row = 0, FIRST_DATA_ROW - 1
    else:
        last_raw_id, last_row = _last_watermark(conn)

    rows_written = 0
    first_written: int | None = None
    cur_row, cur_id = last_row, last_raw_id

    try:
        while True:
            batch = conn.execute(SELECT_SQL, (cur_id, chunk_size)).fetchall()
            if not batch:
                break

            sheet_rows = [to_sheet_row(r) for r in batch]
            start_row = cur_row + 1
            sheet.ensure_rows(start_row + len(sheet_rows) - 1)
            sheet.write(start_row, sheet_rows)

            cur_row = start_row + len(sheet_rows) - 1
            cur_id = batch[-1][0]
            rows_written += len(sheet_rows)
            if first_written is None:
                first_written = start_row

            if len(batch) < chunk_size:
                break
    except Exception as exc:
        # Record only what is already durably true: everything up to cur_row/cur_id was
        # written in an earlier, completed loop iteration before this one raised. The
        # watermark is deliberately NOT advanced past that - see the module docstring.
        _record(conn, ok=False, rows_written=rows_written,
                first_row=first_written, last_row=cur_row if rows_written else None,
                last_raw_id=cur_id if rows_written else None, error=str(exc))
        raise

    _record(conn, ok=True, rows_written=rows_written, first_row=first_written,
            last_row=cur_row, last_raw_id=cur_id, error=None)
    return SyncResult(rows_written, first_written, cur_row, cur_id)


def rebuild(conn, sheet, chunk_size: int = 2000) -> SyncResult:
    """Wipe the sheet's data and resync everything from scratch.

    For when the sheet has drifted from the database - a plain sort reordered rows, a
    filter view got saved over the data. Postgres is the source of truth, so recovery is
    always "regenerate the mirror", never "reconcile the sheet".
    """
    sheet.clear_data()
    return sync_once(conn, sheet, chunk_size=chunk_size, force_from_start=True)
