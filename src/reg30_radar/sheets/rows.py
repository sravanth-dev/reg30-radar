"""Turning one `raw_announcements` row into one Sheets row. Pure: no network, no database.

Kept separate from client.py so the formatting rules - IST conversion, the empty-cell
rule, the length cap - can be tested without a fake HTTP session at all.
"""

from __future__ import annotations

from datetime import datetime

from reg30_radar.common.calendar import IST

HEADER = [
    "id", "Filed (IST)", "Symbol", "Company", "Category", "Headline", "PDF",
    "Industry", "ISIN", "Seen by us (IST)", "Revision",
]

# Reads strictly forward from a watermark, in raw_announcements.id order - the same order
# sync.py pins the sheet's rows to. `id > %s`, never `>=`, so the row already written at
# the watermark is never re-selected.
SELECT_SQL = """
    select id, exchange_ts, symbol, company, category_raw, headline, attachment_url,
           industry, isin, first_seen_at, revision
    from raw_announcements
    where id > %s
    order by id asc
    limit %s
"""

# Google Sheets' per-cell character limit. A filing headline is normally a sentence, but
# document text is untrusted (CLAUDE.md) and nothing upstream bounds its length, so this
# is a defensive cap for a case that should not occur, not an expected one.
_CELL_LIMIT = 50_000
_TRUNCATED_MARKER = " …[truncated for Sheets' 50,000-character cell limit]"


def text_cell(value) -> str:
    """Any value -> a plain-text Sheets cell. Public (not `_text`) because sheets/orders.py
    reuses it, so the empty-cell rule and the length cap live in exactly one place."""
    if value is None:
        return ""
    s = str(value)
    if len(s) > _CELL_LIMIT:
        cut = _CELL_LIMIT - len(_TRUNCATED_MARKER)
        s = s[:cut] + _TRUNCATED_MARKER
    return s


def ist_cell(value: datetime | None) -> str:
    """Any tz-aware timestamp -> `YYYY-MM-DD HH:MM:SS` in IST. Public for the same reason
    as `text_cell`."""
    if value is None:
        return ""
    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def to_sheet_row(record: tuple) -> list[str]:
    """One row as SELECT_SQL returns it -> one row of plain-text Sheets cells.

    Every value comes back as a string. It is client.py's job to send it with
    valueInputOption=RAW, which is what keeps it literal - a headline starting with "="
    is written as those literal characters, never evaluated as a formula - so this
    function does not escape anything itself; it only has to never emit a non-string.
    """
    (row_id, exchange_ts, symbol, company, category_raw, headline, attachment_url,
     industry, isin, first_seen_at, revision) = record
    return [
        str(row_id),
        ist_cell(exchange_ts),
        text_cell(symbol),
        text_cell(company),
        text_cell(category_raw),
        text_cell(headline),
        text_cell(attachment_url),
        text_cell(industry),
        text_cell(isin),
        ist_cell(first_seen_at),
        str(revision),
    ]
