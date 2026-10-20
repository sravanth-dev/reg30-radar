"""Loading the backfill database into the event study's inputs (backfill/event_study.py).

Point-in-time throughout: each event gets the TTM revenue knowable before its filing
(revenue/ttm.py), the market cap of the trading day before its day 0 (event_study), and the
other filings of its own company for the contamination and leadership checks.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from tradebot.backfill.event_study import NEW_ISIN, Bar, EventIn, Market
from tradebot.calculator.materiality import execution_months
from tradebot.common.calendar import IST
from tradebot.revenue.ttm import Period, ttm_as_of
from tradebot.router.orders import bucket_of

NIFTY = "Nifty 50"


def load_market(conn, isins: list[str], since: date, until: date,
                muhurat: set[date]) -> Market:
    """Prices and market caps per company, filed under the universe ISIN the events carry.

    A company's rows are read under every ISIN sharing its first nine characters (issuer
    code + security type 01, equity shares), because NSDL reissues the ISIN after a split
    and 38 universe companies changed ISIN during the window (BEML on 3 Nov 2025, KOTAKBANK,
    MCX, ...); read by the universe ISIN alone, their prices stop at the switch. The two
    ISINs never trade on the same day (0 overlaps in the loaded prices). The first day
    under a new ISIN is marked NEW_ISIN, which event_study counts as a capital action,
    because prices are unadjusted across the switch. Rights entitlements (security type
    20) have a different ninth-character prefix and are never mixed in."""
    company_of = {isin[:9]: isin for isin in isins}
    if len(company_of) != len(set(isins)):
        raise ValueError("two companies share an ISIN prefix; prices would be mixed")
    prefixes = list(company_of)
    days = [r[0] for r in conn.execute(
        "select day from archive_days where trading_day and day between %s and %s order by day",
        (since, until))]
    nifty = dict(conn.execute(
        "select trade_date, close from index_prices where index_name = %s"
        " and trade_date between %s and %s", (NIFTY, since, until)).fetchall())
    bars: dict[str, dict[date, Bar]] = defaultdict(dict)
    last_isin: dict[str, str] = {}
    for (isin, d, o, h, lo, c, vol, tv, series, corp, band) in conn.execute(
            "select isin, trade_date, open, high, low, close, volume, traded_value, series,"
            " corp_ind, band_hit from prices where left(isin, 9) = any(%s)"
            " and trade_date between %s and %s order by trade_date", (prefixes, since, until)):
        company = company_of[isin[:9]]
        if last_isin.get(company, isin) != isin:
            corp = f"{corp} {NEW_ISIN}" if corp else NEW_ISIN
        last_isin[company] = isin
        bars[company][d] = Bar(o, h, lo, c, vol, tv, series, corp, band)
    mcap: dict[str, dict[date, object]] = defaultdict(dict)
    for isin, d, v in conn.execute(
            "select isin, trade_date, mcap_inr from market_caps where left(isin, 9) = any(%s)"
            " and trade_date between %s and %s", (prefixes, since, until)):
        mcap[company_of[isin[:9]]][d] = v
    return Market(days=days, nifty=nifty, bars=dict(bars), mcap=dict(mcap), muhurat=muhurat)


def _periods(conn, isin: str) -> list[Period]:
    return [Period(*row) for row in conn.execute(
        "select period_end, period_months, basis, revenue_inr, filed_at from financials"
        " where isin = %s", (isin,))]


def log_unknown(conn, category: str | None, seen_at: datetime) -> None:
    conn.execute("insert into unknown_categories (category_raw, first_seen, count)"
                 " values (%s, %s, 1) on conflict (category_raw) do update set"
                 " count = unknown_categories.count + 1", (category or "", seen_at))


def load_events(conn, states: tuple[str, ...] = ("verified",)) -> list[EventIn]:
    """Events in the given states, each with its point-in-time TTM and its company's
    other filings within 10 calendar days either side (enough for ±3 trading days)."""
    rows = conn.execute(
        "select id, isin, symbol, event_ts, raw_ids, value_inr, currency,"
        " execution_period_raw, company_is_recipient from backfill_events"
        " where state = any(%s) order by event_ts", (list(states),)).fetchall()
    all_events = conn.execute(
        "select isin, event_ts from backfill_events where company_is_recipient is not false"
        " order by event_ts").fetchall()
    out, periods_cache = [], {}
    now = datetime.now(timezone.utc)
    for (eid, isin, symbol, ts, raw_ids, value, currency, period_raw, won) in rows:
        if isin not in periods_cache:
            periods_cache[isin] = _periods(conn, isin)
        ttm, basis = ttm_as_of(periods_cache[isin], ts)
        others = []
        # Match on the isin's issuer code, because a filing carries the company's original
        # ISIN and the event the universe's current one (common/isin.py); fall back to symbol
        # only when a row's own isin is null - Spike A found sm_isin is not 100% populated
        # (null for HILINFRA). Missing a company's other filing here would understate
        # contamination, making the study look cleaner than it is. A ±10-day window makes
        # the (already rare in practice) risk of a symbol once used by a different company
        # falling in the same window negligible.
        for fts, category in conn.execute(
                "select exchange_ts, category_raw from raw_announcements"
                " where (left(isin, 7) = left(%(isin)s, 7)"
                "        or (isin is null and symbol = %(symbol)s))"
                " and exchange_ts between %(from)s and %(to)s and not (id = any(%(raw_ids)s))",
                {"isin": isin, "symbol": symbol, "from": ts - timedelta(days=10),
                 "to": ts + timedelta(days=10), "raw_ids": raw_ids}):
            bucket = bucket_of(category)
            if bucket == "unknown":
                log_unknown(conn, category, now)
            others.append((fts, bucket))
        previous = max((t for i, t in all_events if i == isin and t < ts), default=None)
        out.append(EventIn(
            event_id=eid, isin=isin, symbol=symbol, event_ts=ts, value_inr=value,
            currency=currency or "INR", ttm_revenue_inr=ttm, ttm_basis=basis,
            execution_months=execution_months(period_raw, ts.astimezone(IST).date()),
            other_filings=others, previous_order_ts=previous, company_is_recipient=won))
    conn.commit()
    return out
