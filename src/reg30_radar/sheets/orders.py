"""Turning `order_extractions` rows into the `orders` Sheets tab.

Pure formatting lives here, same split as `sheets/rows.py`: client.py does the writing,
this does the reading and shaping, so both can be tested without a fake HTTP session.

**Why this tab is rewritten whole every cycle, unlike the raw tab.** `raw_announcements`
is append-only, so `sheets/sync.py` can pin each filing to a fixed row forever.
`order_extractions` is not: `orders/store.py` upserts a row, so a filing that first landed
as `pending_llm` can later become `verified` with a real value. There is no append-only
position to pin to, so instead of a watermark this reads the whole table, order-related
filings only, and compares a hash of everything it would write against the hash from last
time - if nothing changed, it skips the write entirely (ARCHITECTURE.md D11, v1.5).
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal

from reg30_radar.sheets.rows import ist_cell, text_cell

HEADER = [
    "Filed (IST)", "Symbol", "Company", "Category", "Bucket", "Why it's an order",
    "Value (Rs cr)", "Value as written", "Extracted by", "Provenance OK", "Status",
    "Stage", "Company is recipient", "Awarding entity", "Execution period", "Currency",
    "GST incl.", "Doc quality", "Note", "PDF", "LLM cost ($)", "Processed (IST)", "raw id",
]

# 1-indexed column letter math (client.py's _col_letter): "Value (Rs cr)" is the 7th
# header entry, column G. Written separately from the rest of the row - see to_orders_row.
VALUE_COL = 7

# The same joins orders/report.py's ROWS_QUERY uses (that module writes reports/*.md from
# this same table), restricted to order-related filings and ordered newest-filed-first,
# since there is no watermark here to read forward from - every cycle re-reads everything.
ORDERS_SQL = """
select ra.exchange_ts, ra.symbol, ra.company, ra.category_raw, oe.bucket,
       oe.relevance_reason, oe.value_inr, oe.consideration_raw, oe.path,
       oe.provenance_ok, oe.review_status, oe.stage, oe.company_is_recipient,
       oe.awarding_entity, oe.execution_period_raw, oe.currency, oe.gst_inclusive,
       d.quality, oe.last_error, ra.attachment_url, oe.llm_cost_usd, oe.processed_at,
       ra.id
from order_extractions oe
join raw_announcements ra on ra.id = oe.raw_announcement_id
left join documents d on d.id = oe.document_id
where oe.order_related
order by ra.exchange_ts desc nulls last, ra.id desc
"""

_PATH_LABELS = {"t0": "T0 parser", "llm": "LLM", "none": ""}

_CRORE = Decimal("10000000")
_TWO_DP = Decimal("0.01")


def _bool_cell(value: bool | None) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"


def _crore_cell(value_inr: Decimal | None) -> str:
    """value_inr (rupees, as order_extractions stores it) -> crore, 2dp text.

    Decimal throughout, never float (CLAUDE.md's money rule) - this is what
    client.write_numbers() is handed, and it re-validates the result is a plain number
    before it goes anywhere near USER_ENTERED, so a mistake here would be caught, not
    silently sent to the API as something else.
    """
    if value_inr is None:
        return ""
    return str((value_inr / _CRORE).quantize(_TWO_DP, rounding=ROUND_HALF_UP))


def to_orders_row(record: tuple) -> tuple[list[str], str]:
    """One ORDERS_SQL row -> (the RAW text cells, the Value cell on its own).

    Split in two because client.py writes them with two different valueInputOptions: the
    text block stays RAW (filing text is untrusted, CLAUDE.md), while the Value column
    goes through write_numbers()'s USER_ENTERED so it sorts as a number in the sheet.
    """
    (exchange_ts, symbol, company, category_raw, bucket, relevance_reason, value_inr,
     consideration_raw, path, provenance_ok, review_status, stage, company_is_recipient,
     awarding_entity, execution_period_raw, currency, gst_inclusive, quality, last_error,
     attachment_url, llm_cost_usd, processed_at, raw_id) = record

    text_cells = [
        ist_cell(exchange_ts),
        text_cell(symbol),
        text_cell(company),
        text_cell(category_raw),
        text_cell(bucket),
        text_cell(relevance_reason),
        "",  # Value (Rs cr) - filled in by write_numbers(), never written here
        text_cell(consideration_raw),
        text_cell(_PATH_LABELS.get(path, path)),
        _bool_cell(provenance_ok),
        text_cell(review_status),
        text_cell(stage),
        _bool_cell(company_is_recipient),
        text_cell(awarding_entity),
        text_cell(execution_period_raw),
        text_cell(currency),
        _bool_cell(gst_inclusive),
        text_cell(quality),
        text_cell(last_error),
        text_cell(attachment_url),
        text_cell(llm_cost_usd),
        ist_cell(processed_at),
        str(raw_id),
    ]
    return text_cells, _crore_cell(value_inr)


def _fingerprint(rows: list[tuple]) -> str:
    """A stable hash of everything sync_orders would write, built from the *formatted*
    cells rather than the raw SQL rows - so a column added later can't silently break the
    "nothing changed" comparison without also changing what actually gets written.
    """
    h = hashlib.sha256()
    for record in rows:
        text_cells, value_cell = to_orders_row(record)
        h.update("\x1f".join([*text_cells, value_cell]).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def sync_orders(conn, sheet, last_fingerprint: str | None) -> tuple[str, int]:
    """Rewrite the whole `orders` tab from `order_extractions`, newest filing first,
    unless nothing has changed since `last_fingerprint`.

    Returns (new_fingerprint, rows_written); rows_written is 0 both when nothing changed
    and when the table is genuinely empty - the caller only logs on a nonzero count.
    """
    sheet.ensure_header(HEADER)

    rows = conn.execute(ORDERS_SQL).fetchall()
    fingerprint = _fingerprint(rows)
    if fingerprint == last_fingerprint:
        return fingerprint, 0

    if not rows:
        sheet.clear_from(2)
        return fingerprint, 0

    text_rows: list[list[str]] = []
    value_cells: list[str] = []
    for record in rows:
        text_cells, value_cell = to_orders_row(record)
        text_rows.append(text_cells)
        value_cells.append(value_cell)

    end_row = 1 + len(rows)
    sheet.ensure_rows(end_row)
    sheet.write(2, text_rows)
    sheet.write_numbers(VALUE_COL, 2, value_cells)
    # In case this cycle has fewer rows than the last write - nothing stale left below.
    sheet.clear_from(end_row + 1)

    return fingerprint, len(rows)
