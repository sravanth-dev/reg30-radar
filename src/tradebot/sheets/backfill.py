"""The `backfill_events` Sheets tab: one row per backfill event, and the study's numbers for
it once `python -m tradebot.backfill study` has run (21 Oct 2026, Sravanth asked to see the
backfill in the Sheet).

View-only, like the other two tabs (D11 as narrowed): Postgres stays the master copy. Read
from `tradebot_backfill`, which only the laptop has, so the tab is skipped where
BACKFILL_DATABASE_URL is not set. Events change as the backfill moves (state, recheck,
study), so the tab is rewritten whole, skipped when a hash of its cells is unchanged: the
same pattern as `sheets/orders.py`.

The study columns come from the latest `study` run only (`event_results`); before the
first run they are blank.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal

from tradebot.sheets.rows import ist_cell, text_cell

HEADER = [
    "Filed (IST)", "Symbol", "Value (Rs cr)", "Currency", "Value flags", "TTM revenue (Rs cr)",
    "Value / TTM (%)", "Value / mcap (%)", "TTM basis", "State", "Company is recipient",
    "Stage", "Awarding entity", "Execution period", "Filings merged",
    "Day 0", "Mcap (Rs cr)", "+1d excess (%)", "+5d excess (%)", "+10d excess (%)",
    "Clean", "Excluded because", "Contaminated by", "Upper circuit day 0", "Price band",
    "Study run (IST)", "ISIN", "event id",
]
# 1-indexed columns written as numbers (sortable), each through client.write_numbers().
NUMBER_COLS = {"Value (Rs cr)": 3, "TTM revenue (Rs cr)": 6, "Value / TTM (%)": 7,
               "Value / mcap (%)": 8, "Mcap (Rs cr)": 17, "+1d excess (%)": 18,
               "+5d excess (%)": 19, "+10d excess (%)": 20}

EVENTS_SQL = """
with latest as (select max(run_at) as run_at from event_results)
select e.event_ts, e.symbol, e.value_inr, e.currency, e.value_flags, e.ttm_revenue_inr,
       e.value_to_mcap, e.ttm_basis, e.state, e.company_is_recipient, e.stage,
       e.awarding_entity, e.execution_period_raw, cardinality(e.raw_ids),
       r.result, r.run_at, e.isin, e.id
from backfill_events e
left join event_results r on r.event_id = e.id and r.run_at = (select run_at from latest)
order by e.event_ts desc, e.id desc
"""

_CRORE = Decimal("10000000")
_TWO_DP = Decimal("0.01")


def _num(value, scale: Decimal = Decimal(1)) -> str:
    """A Decimal-safe plain number cell, 2 dp; blank for None. Never via float."""
    if value is None or value == "":
        return ""
    return str((Decimal(str(value)) / scale).quantize(_TWO_DP, rounding=ROUND_HALF_UP))


def _pct(value) -> str:
    return "" if value in (None, "") else _num(Decimal(str(value)) * 100)


def _yes_no(value) -> str:
    return "" if value is None else ("yes" if value else "no")


def to_row(record: tuple) -> tuple[list[str], dict[int, str]]:
    """One EVENTS_SQL row -> (the RAW text cells, {column: number cell})."""
    (ts, symbol, value_inr, currency, flags, ttm, v_mcap, basis, state, recipient, stage,
     awarding, period, merged, result, run_at, isin, event_id) = record
    res = result or {}
    v_ttm = (value_inr / ttm) if value_inr is not None and ttm else None
    numbers = {
        NUMBER_COLS["Value (Rs cr)"]: _num(value_inr, _CRORE),
        NUMBER_COLS["TTM revenue (Rs cr)"]: _num(ttm, _CRORE),
        NUMBER_COLS["Value / TTM (%)"]: _pct(v_ttm),
        NUMBER_COLS["Value / mcap (%)"]: _pct(v_mcap),
        NUMBER_COLS["Mcap (Rs cr)"]: _num(res.get("mcap_cr")),
        NUMBER_COLS["+1d excess (%)"]: _pct(res.get("excess_1")),
        NUMBER_COLS["+5d excess (%)"]: _pct(res.get("excess_5")),
        NUMBER_COLS["+10d excess (%)"]: _pct(res.get("excess_10")),
    }
    excluded = "; ".join(x for x in (res.get("exclusions"), res.get("capital_action")) if x)
    studied = bool(res)
    text = [
        ist_cell(ts), text_cell(symbol), "", text_cell(currency),
        text_cell(";".join(flags or [])), "", "", "", text_cell(basis), text_cell(state),
        _yes_no(recipient), text_cell(stage), text_cell(awarding), text_cell(period),
        str(merged or ""),
        text_cell(res.get("day0")), "", "", "", "",
        _yes_no(not excluded and not res.get("contaminated_by")) if studied else "",
        text_cell(excluded), text_cell(res.get("contaminated_by")),
        _yes_no(res.get("locked_0") == "upper") if studied else "",
        text_cell(res.get("price_band")), ist_cell(run_at), text_cell(isin), str(event_id),
    ]
    return text, numbers


def _fingerprint(rows: list[tuple]) -> str:
    h = hashlib.sha256()
    for record in rows:
        text, numbers = to_row(record)
        h.update("\x1f".join([*text, *(numbers[c] for c in sorted(numbers))]).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def sync_backfill(conn, sheet, last_fingerprint: str | None) -> tuple[str, int]:
    """Rewrite the whole tab unless nothing changed. Returns (fingerprint, rows_written)."""
    sheet.ensure_header(HEADER)
    rows = conn.execute(EVENTS_SQL).fetchall()
    fingerprint = _fingerprint(rows)
    if fingerprint == last_fingerprint:
        return fingerprint, 0
    if not rows:
        sheet.clear_from(2)
        return fingerprint, 0
    shaped = [to_row(r) for r in rows]
    end_row = 1 + len(rows)
    sheet.ensure_rows(end_row)
    sheet.write(2, [text for text, _ in shaped])
    for col in sorted(NUMBER_COLS.values()):
        sheet.write_numbers(col, 2, [numbers[col] for _, numbers in shaped])
    sheet.clear_from(end_row + 1)
    return fingerprint, len(rows)
