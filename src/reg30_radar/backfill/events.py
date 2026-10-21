"""Order events from verified extractions (ARCHITECTURE §5.3, §6's state machine).

Repeat filings of one order are merged on an **exact** key only: the same attachment
SHA-256 (one PDF filed under two categories), or the same ISIN and `value_inr` (GENESYS
filed its ₹283 cr contract as a press release and again as the Reg 30 disclosure, WORKLOG
25 Sep). Never on a similar headline: companies file several genuinely different orders on
one day (§5.3). The event's time is the earliest filing's exchange timestamp.

State machine (§6): an event starts `extracted`; `advance()` records `calculated` and then
`verified` (value below 15% of market cap and TTM known) or `recheck_pending`, which
backfill/recheck.py settles. Every transition is logged with its trigger, and an event
enters `recheck_pending` at most once, so the loop cannot run twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

HIGH_STAKES = Decimal("0.15")        # §6 trigger 4


@dataclass(frozen=True)
class Filing:
    raw_id: int
    isin: str
    symbol: str
    exchange_ts: datetime
    bucket: str
    sha256: str | None
    value_inr: Decimal | None
    currency: str | None
    company_is_recipient: bool | None
    stage: str | None
    awarding_entity: str | None
    execution_period_raw: str | None
    value_flags: list[str] | None = None


def group(filings: list[Filing]) -> list[list[Filing]]:
    """Filings that describe one order, merged on the exact keys above (union-find)."""
    parent = list(range(len(filings)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_by_key: dict[tuple, int] = {}
    for i, f in enumerate(filings):
        keys = []
        if f.sha256:
            keys.append(("sha", f.sha256))
        if f.value_inr is not None:
            keys.append(("value", f.isin, f.value_inr))
        for key in keys:
            if key in first_by_key:
                parent[find(i)] = find(first_by_key[key])
            else:
                first_by_key[key] = i

    groups: dict[int, list[Filing]] = {}
    for i, f in enumerate(filings):
        groups.setdefault(find(i), []).append(f)
    return [sorted(g, key=lambda f: (f.exchange_ts, f.raw_id)) for g in groups.values()]


def recipient(members: list[Filing]) -> tuple[bool | None, str | None]:
    """Whether the company won the order. The extraction's answer when it has one; failing
    that, "Bagging/Receiving of orders/contracts" says so by its own name. Anything else
    stays unknown, and an unknown recipient is never in the primary cell."""
    for f in members:
        if f.company_is_recipient is not None:
            return f.company_is_recipient, "extraction"
    if all(f.bucket == "order_win" for f in members):
        return True, "category"
    return None, None


def to_event(members: list[Filing]) -> dict:
    first = members[0]
    won, source = recipient(members)
    return {
        "isin": first.isin, "symbol": first.symbol, "event_ts": first.exchange_ts,
        "raw_ids": [f.raw_id for f in members], "primary_raw_id": first.raw_id,
        "bucket": first.bucket, "value_inr": first.value_inr, "currency": first.currency,
        "company_is_recipient": won, "recipient_source": source, "stage": first.stage,
        "awarding_entity": first.awarding_entity,
        "execution_period_raw": first.execution_period_raw,
        "value_flags": first.value_flags,
    }


FILINGS_SQL = """
select ra.id, coalesce(by_issuer.isin, by_symbol.isin), ra.symbol, ra.exchange_ts, oe.bucket,
       d.sha256, oe.value_inr, oe.currency, oe.company_is_recipient, oe.stage,
       oe.awarding_entity, oe.execution_period_raw, oe.value_flags
from order_extractions oe
join raw_announcements ra on ra.id = oe.raw_announcement_id
left join documents d on d.id = oe.document_id
-- The event carries the universe's ISIN, which is what prices and market caps are keyed by.
-- A filing's own ISIN is the company's original one, so it is matched by issuer code
-- (common/isin.py); symbol is used only when the filing carries no ISIN at all.
left join backfill_universe by_issuer on left(by_issuer.isin, 7) = left(ra.isin, 7)
left join instrument_symbols s on ra.isin is null and s.symbol = ra.symbol
left join backfill_universe by_symbol on by_symbol.isin = s.isin
where oe.order_related and oe.review_status = 'verified' and ra.exchange_ts is not null
order by ra.exchange_ts
"""


def build(conn) -> dict:
    """(Re)build `backfill_events` from verified extractions. An event keeps its state and
    recheck result across rebuilds, unless its value changed: then it starts again at
    `extracted`, with its ratios and recheck cleared and the reset logged, because a
    ratio or a recheck of the old value says nothing about the new one (audit, 20 Oct
    2026). An event no longer produced is deleted."""
    seen, filings = set(), []
    for row in conn.execute(FILINGS_SQL):
        if row[0] in seen or row[1] is None:
            continue
        seen.add(row[0])
        filings.append(Filing(*row))
    events = [to_event(g) for g in group(filings)]
    with conn.transaction():
        for e in events:
            conn.execute(
                """insert into backfill_events (isin, symbol, event_ts, raw_ids, primary_raw_id,
                       bucket, value_inr, currency, company_is_recipient, recipient_source, stage,
                       awarding_entity, execution_period_raw, value_flags, state, state_log)
                   values (%(isin)s, %(symbol)s, %(event_ts)s, %(raw_ids)s, %(primary_raw_id)s,
                       %(bucket)s, %(value_inr)s, %(currency)s, %(company_is_recipient)s,
                       %(recipient_source)s, %(stage)s, %(awarding_entity)s,
                       %(execution_period_raw)s, %(value_flags)s, 'extracted', '[]'::jsonb)
                   on conflict (primary_raw_id) do update set
                       state = case when backfill_events.value_inr is distinct from
                                         excluded.value_inr then 'extracted'
                                    else backfill_events.state end,
                       state_log = case when backfill_events.value_inr is distinct from
                                             excluded.value_inr
                                        then backfill_events.state_log || jsonb_build_array(
                                            jsonb_build_object('to', 'extracted', 'trigger',
                                                'value changed on rebuild', 'at', now()))
                                        else backfill_events.state_log end,
                       ttm_revenue_inr = case when backfill_events.value_inr is distinct from
                                excluded.value_inr then null else backfill_events.ttm_revenue_inr end,
                       ttm_basis = case when backfill_events.value_inr is distinct from
                                excluded.value_inr then null else backfill_events.ttm_basis end,
                       value_to_mcap = case when backfill_events.value_inr is distinct from
                                excluded.value_inr then null else backfill_events.value_to_mcap end,
                       recheck_value_inr = case when backfill_events.value_inr is distinct from
                                excluded.value_inr then null else backfill_events.recheck_value_inr end,
                       recheck_recipient = case when backfill_events.value_inr is distinct from
                                excluded.value_inr then null else backfill_events.recheck_recipient end,
                       value_flags = excluded.value_flags,
                       raw_ids = excluded.raw_ids, event_ts = excluded.event_ts,
                       value_inr = excluded.value_inr, currency = excluded.currency,
                       company_is_recipient = excluded.company_is_recipient,
                       recipient_source = excluded.recipient_source, stage = excluded.stage,
                       awarding_entity = excluded.awarding_entity,
                       execution_period_raw = excluded.execution_period_raw""", e)
        keep = [e["primary_raw_id"] for e in events]
        conn.execute("delete from event_results where event_id in (select id from"
                     " backfill_events where not (primary_raw_id = any(%s)))", (keep,))
        conn.execute("delete from backfill_events where not (primary_raw_id = any(%s))", (keep,))
    return {"verified_filings": len(filings), "events": len(events),
            "merged_filings": len(filings) - len(events)}


def next_state(value_to_mcap: Decimal | None, ttm_known: bool) -> tuple[str, str]:
    """§6: (state, trigger) for an event that has just been calculated."""
    if value_to_mcap is None:
        return "recheck_pending", "market cap unknown"
    if value_to_mcap >= HIGH_STAKES:
        return "recheck_pending", f"value_to_mcap {value_to_mcap} >= 15%"
    if not ttm_known:
        return "recheck_pending", "TTM revenue unknown"
    return "verified", "value_to_mcap < 15% and TTM known"


def log_transition(conn, event_id: int, to_state: str, trigger: str) -> None:
    entry = {"to": to_state, "trigger": trigger, "at": datetime.now(timezone.utc).isoformat()}
    conn.execute("update backfill_events set state = %s, state_log = state_log || %s::jsonb"
                 " where id = %s", (to_state, json.dumps([entry]), event_id))
