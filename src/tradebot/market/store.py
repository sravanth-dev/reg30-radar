"""Writing one archive day into the market tables (migrations/0007_market_data.sql).

Every row is keyed to an ISIN through that same day's UDiFF bhavcopy, the only file that
carries one (§5.9): `pd`, `mcap` and `bh` are keyed by symbol + series, and a symbol can
change hands between companies over time, so mapping by symbol across days would be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from tradebot.market.parse import BandHit, CorpAction, IndexClose, MarketCap, PriceRow
from tradebot.backfill.reconcile import BundleEntry

# When one ISIN appears under two series on one day, the price row kept is the first of
# these present. EQ is the normal equity series; BE and BZ are trade-for-trade.
SERIES_PREFERENCE = ("EQ", "BE", "BZ")


@dataclass
class DayCounts:
    prices: int = 0
    index_closes: int = 0
    market_caps: int = 0
    unmapped_market_caps: int = 0
    corp_actions: int = 0
    band_hits: int = 0
    announcements: int = 0
    notes: list[str] = field(default_factory=list)


def _series_rank(series: str) -> int:
    return SERIES_PREFERENCE.index(series) if series in SERIES_PREFERENCE else len(SERIES_PREFERENCE)


def save_day(
    conn, day: date, *, prices: list[PriceRow], indices: list[IndexClose] | None = None,
    actions: list[CorpAction] | None = None, caps: list[MarketCap] | None = None,
    hits: list[BandHit] | None = None, entries: list[BundleEntry] | None = None,
) -> DayCounts:
    """Replace everything stored for `day` with what these files say. One transaction:
    a day is either fully loaded or not at all."""
    counts = DayCounts()
    by_key = {(p.symbol, p.series): p.isin for p in prices}
    corp = {(a.symbol, a.series): a.corp_ind for a in (actions or [])}
    band = {(h.symbol, h.series): h.high_low for h in (hits or [])}

    chosen: dict[str, PriceRow] = {}
    for p in prices:
        kept = chosen.get(p.isin)
        if kept is None or _series_rank(p.series) < _series_rank(kept.series):
            chosen[p.isin] = p

    with conn.transaction():
        for table in ("prices", "index_prices", "market_caps"):
            conn.execute(f"delete from {table} where trade_date = %s", (day,))
        conn.execute("delete from bundle_announcements where report_date = %s", (day,))

        with conn.cursor() as cur:
            cur.executemany(
                "insert into prices (trade_date, isin, symbol, series, open, high, low, close,"
                " prev_close, volume, traded_value, corp_ind, band_hit)"
                " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(day, p.isin, p.symbol, p.series, p.open, p.high, p.low, p.close,
                  p.prev_close, p.volume, p.traded_value, corp.get((p.symbol, p.series)),
                  band.get((p.symbol, p.series))) for p in chosen.values()],
            )
            counts.prices = len(chosen)
            counts.corp_actions = sum(1 for p in chosen.values() if (p.symbol, p.series) in corp)
            counts.band_hits = sum(1 for p in chosen.values() if (p.symbol, p.series) in band)

            cur.executemany(
                "insert into instruments (isin, nse_symbol, nse_series, name, instrument_type,"
                " first_seen, last_seen) values (%s,%s,%s,%s,%s,%s,%s)"
                " on conflict (isin) do update set"
                "  first_seen = least(instruments.first_seen, excluded.first_seen),"
                "  last_seen = greatest(instruments.last_seen, excluded.last_seen),"
                # The newest day decides the current symbol, series and name.
                "  nse_symbol = case when excluded.last_seen >= instruments.last_seen"
                "    then excluded.nse_symbol else instruments.nse_symbol end,"
                "  nse_series = case when excluded.last_seen >= instruments.last_seen"
                "    then excluded.nse_series else instruments.nse_series end,"
                "  name = case when excluded.last_seen >= instruments.last_seen"
                "    then excluded.name else instruments.name end",
                [(p.isin, p.symbol, p.series, p.name, p.instrument_type, day, day)
                 for p in chosen.values()],
            )
            cur.executemany(
                "insert into instrument_symbols (isin, symbol, series, first_seen, last_seen)"
                " values (%s,%s,%s,%s,%s) on conflict (isin, symbol, series) do update set"
                "  first_seen = least(instrument_symbols.first_seen, excluded.first_seen),"
                "  last_seen = greatest(instrument_symbols.last_seen, excluded.last_seen)",
                [(p.isin, p.symbol, p.series, day, day) for p in prices],
            )

            if indices:
                cur.executemany(
                    "insert into index_prices (trade_date, index_name, close) values (%s,%s,%s)"
                    " on conflict do nothing",
                    [(day, i.index_name, i.close) for i in indices],
                )
                counts.index_closes = len(indices)

            if caps:
                mapped = {}
                for c in caps:
                    isin = by_key.get((c.symbol, c.series))
                    if isin is None:
                        counts.unmapped_market_caps += 1
                    else:
                        mapped[isin] = c.mcap_inr
                cur.executemany(
                    "insert into market_caps (trade_date, isin, mcap_inr) values (%s,%s,%s)",
                    [(day, isin, v) for isin, v in mapped.items()],
                )
                counts.market_caps = len(mapped)

            if entries:
                cur.executemany(
                    "insert into bundle_announcements (report_date, line_no, symbol, body)"
                    " values (%s,%s,%s,%s)",
                    [(day, n, e.symbol, e.body) for n, e in enumerate(entries, start=1)],
                )
                counts.announcements = len(entries)
    return counts


def mark_day(conn, day: date, *, udiff_status: int | None, pr_status: int | None,
             trading_day: bool | None, note: str | None = None) -> None:
    conn.execute(
        "insert into archive_days (day, udiff_status, pr_status, trading_day, loaded_at, note)"
        " values (%s,%s,%s,%s,%s,%s) on conflict (day) do update set"
        "  udiff_status = excluded.udiff_status, pr_status = excluded.pr_status,"
        "  trading_day = excluded.trading_day, loaded_at = excluded.loaded_at,"
        "  note = excluded.note",
        (day, udiff_status, pr_status, trading_day, datetime.now(timezone.utc), note),
    )
    conn.commit()


def decided_days(conn, since: date, until: date) -> set[date]:
    """Days already settled: loaded as trading days with a PR bundle, or confirmed
    non-trading. A trading day whose bundle failed is retried."""
    rows = conn.execute(
        "select day from archive_days where day between %s and %s and ("
        " trading_day = false or (trading_day = true and pr_status = 200))",
        (since, until),
    ).fetchall()
    return {r[0] for r in rows}
