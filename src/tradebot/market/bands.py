"""Reconstructing a stock's price band (2/5/10/20%) on a past date (ARCHITECTURE §11,
resolved 27 Sep 2026; migrations/0013_band_history.sql).

NSE publishes the **current** band per symbol (`sec_list.csv`) and a **daily change log**
(`eq_band_changes_{ddmmyyyy}.csv`) but no historical snapshot. Reconstruction walks the
change log backward from the current snapshot: to find the band on date D, undo every
recorded change dated after D, most recent first. A symbol with no recorded change between
D and the snapshot date is assumed to have held its current band throughout - the loader
covers every calendar day of the study window, so "no row" genuinely means "no NSE-published
change", not a gap in what was fetched. A symbol absent from the current snapshot (delisted
since) cannot be reconstructed at all and returns None, never a guess.

A day with no changes gives a clean HTTP 404, verified on two Sundays (27 Sep 2026), so the
loader treats 404 as "checked, nothing published" rather than an error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from tradebot.market.fetch import ArchiveFetcher
from tradebot.market.parse import _rows

log = logging.getLogger("backfill")

SEC_LIST_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"
BAND_CHANGES_URL = "https://nsearchives.nseindia.com/content/equities/eq_band_changes_{ddmmyyyy}.csv"


@dataclass(frozen=True)
class BandSnapshot:
    symbol: str
    series: str
    band: str | None


def parse_sec_list(csv_text: str) -> list[BandSnapshot]:
    """`Symbol,Series,Security Name,Band,Remarks` - the current band per symbol."""
    out = []
    for r in _rows(csv_text):
        symbol, series = r.get("Symbol", ""), r.get("Series", "")
        if symbol and series:
            out.append(BandSnapshot(symbol, series, r.get("Band") or None))
    return out


@dataclass(frozen=True)
class BandChange:
    symbol: str
    series: str
    from_band: str | None
    to_band: str | None


def parse_band_changes(csv_text: str) -> list[BandChange]:
    """`Sr. No,Symbol,Series,Security Name,From,To` - one day's published changes."""
    out = []
    for r in _rows(csv_text):
        symbol, series = r.get("Symbol", ""), r.get("Series", "")
        if symbol and series:
            out.append(BandChange(symbol, series, r.get("From") or None, r.get("To") or None))
    return out


def save_snapshot(conn, rows: list[BandSnapshot], as_of: date) -> int:
    with conn.transaction():
        conn.execute("delete from band_snapshot")
        with conn.cursor() as cur:
            cur.executemany(
                "insert into band_snapshot (symbol, series, band, as_of_date) values (%s,%s,%s,%s)",
                [(r.symbol, r.series, r.band, as_of) for r in rows])
    return len(rows)


def save_day(conn, day: date, changes: list[BandChange], *, status: int) -> None:
    with conn.transaction():
        conn.execute("delete from band_changes where change_date = %s", (day,))
        with conn.cursor() as cur:
            cur.executemany(
                "insert into band_changes (symbol, series, change_date, from_band, to_band)"
                " values (%s,%s,%s,%s,%s)",
                [(c.symbol, c.series, day, c.from_band, c.to_band) for c in changes])
        conn.execute("insert into band_days (day, status, changes, loaded_at) values (%s,%s,%s,%s)"
                     " on conflict (day) do update set status = excluded.status,"
                     " changes = excluded.changes, loaded_at = excluded.loaded_at",
                     (day, status, len(changes), datetime.now(timezone.utc)))


def reconstruct(conn, pairs: list[tuple[str, str, date]]) -> dict[tuple[str, str, date], str | None]:
    """Band for each (symbol, series, date). One bulk query, not one per event - the same
    "load everything the study needs, then look it up in memory" shape as `study_data.
    load_market`. A pair with no snapshot row (delisted since) maps to None.

    Filters by symbol alone in SQL (a plain list-to-array match, the pattern already used
    throughout this project) and narrows to the exact (symbol, series) pair in Python -
    `(col_a, col_b) = any(...)` would need an array of Postgres composite rows, which a
    Python list of tuples does not reliably adapt to.
    """
    if not pairs:
        return {}
    wanted = {(s, sr) for s, sr, _ in pairs}
    symbols = sorted({s for s, _ in wanted})
    snap = {(s, sr): (band, as_of) for s, sr, band, as_of in conn.execute(
        "select symbol, series, band, as_of_date from band_snapshot where symbol = any(%s)",
        (symbols,)) if (s, sr) in wanted}
    changes: dict[tuple[str, str], list[tuple[date, str | None]]] = {}
    for symbol, series, change_date, from_band in conn.execute(
            "select symbol, series, change_date, from_band from band_changes"
            " where symbol = any(%s) order by change_date desc", (symbols,)):
        if (symbol, series) in wanted:
            changes.setdefault((symbol, series), []).append((change_date, from_band))

    out: dict[tuple[str, str, date], str | None] = {}
    for symbol, series, target in pairs:
        anchor = snap.get((symbol, series))
        if anchor is None:
            out[(symbol, series, target)] = None
            continue
        band, as_of = anchor
        if target >= as_of:
            out[(symbol, series, target)] = band
            continue
        # Undo every change dated after the target, most recent first (the list is already
        # sorted that way): each one's from_band is what the band was just before it.
        for change_date, from_band in changes.get((symbol, series), []):
            if change_date <= target:
                break
            band = from_band
        out[(symbol, series, target)] = band
    return out


def run(conn, since: date, until: date, *, max_requests: int, fetcher=None) -> dict:
    """Fetch the current snapshot (once) and every calendar day's change log in
    [since, until] not already loaded. Every calendar day is tried, weekends included -
    band changes are exchange notices, not tied to trading days, and D27's own "Muhurat can
    fall on a weekend" lesson argues against assuming otherwise without checking."""
    fetcher = fetcher or ArchiveFetcher()
    today = datetime.now(timezone.utc).date()

    have_snapshot = conn.execute("select count(*) from band_snapshot").fetchone()[0] > 0
    if not have_snapshot:
        result = fetcher.get(SEC_LIST_URL)
        if not result.ok:
            log.error("sec_list.csv fetch failed: %s - band reconstruction has no anchor", result.error)
            return {"snapshot": "failed", "days_loaded": 0}
        n = save_snapshot(conn, parse_sec_list(result.content.decode("utf-8", "replace")), today)
        conn.commit()
        log.info("band snapshot: %d symbols as of %s", n, today)

    done = {r[0] for r in conn.execute(
        "select day from band_days where day between %s and %s", (since, until))}
    days = [since + timedelta(n) for n in range((until - since).days + 1) if since + timedelta(n) not in done]
    log.info("%d days to check for band changes, %d already done", len(days), len(done))

    loaded = errors = 0
    for day in days:
        if fetcher.requests + 1 > max_requests:
            log.warning("stopping at --max-requests %d", max_requests)
            break
        # ArchiveFetcher.get() paces itself (min_gap + jitter, idle-reconnect) before every
        # request - no separate sleep needed here, matching market/__main__.py's own loop.
        url = BAND_CHANGES_URL.format(ddmmyyyy=day.strftime("%d%m%Y"))
        result = fetcher.get(url)
        if result.status == 404:
            save_day(conn, day, [], status=404)
            loaded += 1
        elif result.ok:
            changes = parse_band_changes(result.content.decode("utf-8", "replace"))
            save_day(conn, day, changes, status=200)
            loaded += 1
        else:
            log.warning("%s: %s", day, result.error)
            errors += 1
        conn.commit()
    log.info("band history: %d days loaded, %d errors, %d requests", loaded, errors, fetcher.requests)
    return {"days_loaded": loaded, "errors": errors, "requests": fetcher.requests}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from tradebot.common.db import backfill_url, connect
    from tradebot.common.logs import configure as configure_logging

    parser = argparse.ArgumentParser(prog="python -m tradebot.market.bands")
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--max-requests", type=int, default=1000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    with connect(backfill_url()) as conn:
        out = run(conn, args.date_from, args.date_to, max_requests=args.max_requests)
    for k, v in out.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
