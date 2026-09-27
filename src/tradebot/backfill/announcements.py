"""Company-wise announcements for the backfill (ARCHITECTURE §5.1, changed 27 Sep 2026).

One `symbol=` query per listed company returns its whole filing history in every category
(Spike A). The part that falls inside the window, plus a margin, is stored in the backfill
database's `raw_announcements` through the collector's own `to_raw`/`insert_announcements`,
so identity, revisions and hashing are exactly the live path's. `first_seen_at` is the
backfill run's time. That is honest, and it is never used as a live observation (D23).

Then every report date is reconciled against the PR bundle (§5.11): of the listed
companies' order filings the bundle proves exist, how many does the API history hold
within ±1 day.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

from tradebot.backfill.reconcile import ApiRecord, BundleEntry, coverage_is_acceptable, reconcile
from tradebot.collector import nse
from tradebot.collector import store as raw_store
from tradebot.collector.records import SOURCE, parse_ts, to_raw
from tradebot.common.isin import same_issuer

log = logging.getLogger("backfill")

JOB = "announcements"


def select_records(rows: list[dict], isin: str, keep_from: date, keep_to: date) -> list[dict]:
    """The records to store from one symbol's history.

    Kept: filed inside [keep_from, keep_to], and carrying an ISIN of this company's issuer.
    The ISIN is compared by issuer code, not in full, because the API tags filings with the
    company's original ISIN while `isin` is the bhavcopy's current one (common/isin.py). A
    record under the same symbol but another issuer is a different company that once used
    the symbol, and is dropped. A record with no ISIN at all is kept, because symbol and
    date are then the only identity it has.
    """
    out = []
    for r in rows:
        filed = parse_ts(r.get("an_dt"))
        if filed is None or not (keep_from <= filed.date() <= keep_to):
            continue
        record_isin = (r.get("sm_isin") or "").strip()
        if record_isin and not same_issuer(record_isin, isin):
            continue
        out.append(r)
    return out


def latest_industry(rows: list[dict], isin: str) -> str | None:
    """The most recent non-empty smIndustry the company's own records carry (§5.8)."""
    best = None
    for r in rows:
        if not same_issuer(r.get("sm_isin") or isin, isin) or not r.get("smIndustry"):
            continue
        filed = parse_ts(r.get("an_dt"))
        if filed and (best is None or filed > best[0]):
            best = (filed, r["smIndustry"].strip())
    return best[1] if best else None


def pending_companies(conn) -> list[tuple[str, list[str]]]:
    """(isin, every symbol it traded under) for listed companies not yet fetched."""
    rows = conn.execute("""
        select u.isin, array_agg(distinct s.symbol order by s.symbol)
        from backfill_universe u
        join instrument_symbols s on s.isin = u.isin
        where u.excluded_reason is null
          and not exists (select 1 from backfill_checkpoints c
                          where c.job = %s and c.key = u.isin)
        group by u.isin order by u.isin
    """, (JOB,)).fetchall()
    return [(isin, list(symbols)) for isin, symbols in rows]


def fetch_company(conn, client, isin: str, symbols: list[str], keep_from: date,
                  keep_to: date, pause) -> tuple[bool, str]:
    """Fetch and store one company. Returns (ok, summary). Nothing is checkpointed unless
    every symbol's query succeeded, so a partial company is fetched again next run."""
    kept, industry, per_symbol = [], None, {}
    for n, symbol in enumerate(symbols):
        if n:
            pause()
        result = client.fetch_symbol(symbol)
        if not result.ok:
            return False, f"{symbol}: {result.error}"
        records = select_records(result.rows, isin, keep_from, keep_to)
        # other_issuer is recorded so a filter that drops a whole company shows up in the
        # checkpoint, rather than having to be inferred from a run of zero-kept companies.
        other_issuer = sum(1 for r in result.rows
                           if (r.get("sm_isin") or "").strip()
                           and not same_issuer(r["sm_isin"], isin))
        per_symbol[symbol] = {"returned": len(result.rows), "kept": len(records),
                              "other_issuer": other_issuer}
        kept.extend(records)
        industry = industry or latest_industry(result.rows, isin)

    now = datetime.now(timezone.utc)
    outcome = raw_store.insert_announcements(conn, [to_raw(r) for r in kept], first_seen_at=now)
    conn.execute("update backfill_universe set industry = %s where isin = %s", (industry, isin))
    conn.execute("update instruments set industry = %s where isin = %s", (industry, isin))
    conn.execute(
        "insert into backfill_checkpoints (job, key, done_at, detail) values (%s,%s,%s,%s)"
        " on conflict (job, key) do update set done_at = excluded.done_at,"
        " detail = excluded.detail",
        (JOB, isin, now, json.dumps({"symbols": per_symbol, "inserted": outcome.inserted})),
    )
    conn.commit()
    return True, f"{len(kept)} kept, {outcome.inserted} new ({', '.join(symbols)})"


def run(conn, window: dict, *, max_requests: int, client=None, sleep=time.sleep) -> dict:
    client = client or nse.NseClient()
    gap = float(client.cfg["pacing"]["backfill_min_gap_seconds"])
    jitter = client.cfg["pacing"]["jitter_seconds"]
    pause = lambda: sleep(nse.jittered(gap, jitter))   # noqa: E731 - one line, used twice

    margin = timedelta(days=int(window["announcement_margin_days"]))
    keep_from = date.fromisoformat(str(window["announcements_from"])) - margin
    keep_to = date.fromisoformat(str(window["announcements_to"])) + margin

    todo = pending_companies(conn)
    log.info("%d companies to fetch", len(todo))
    done = failed = requests = auth_failures = 0
    for i, (isin, symbols) in enumerate(todo):
        if requests + len(symbols) > max_requests:
            log.warning("stopping at --max-requests %d", max_requests)
            break
        if i:
            pause()
        ok, summary = fetch_company(conn, client, isin, symbols, keep_from, keep_to, pause)
        requests += len(symbols)
        log.info("%s %s: %s", isin, "ok" if ok else "FAILED", summary)
        if ok:
            done += 1
            auth_failures = 0
        else:
            failed += 1
            auth_failures = auth_failures + 1 if ("401" in summary or "403" in summary) else 0
            if auth_failures >= 2:
                log.error("stopping: two consecutive 401/403 answers")
                break
    return {"fetched": done, "failed": failed, "requests": requests,
            "remaining": len(todo) - done}


def reconcile_window(conn, since: date, until: date, floor: float = 0.95) -> dict:
    """Reconcile every report date in the window (§5.11) and store the result per day."""
    universe_symbols = {r[0] for r in conn.execute("""
        select distinct s.symbol from backfill_universe u
        join instrument_symbols s on s.isin = u.isin where u.excluded_reason is null""")}
    api = [ApiRecord(sym, filed, desc or "") for sym, filed, desc in conn.execute("""
        select symbol, (exchange_ts at time zone 'Asia/Kolkata')::date, category_raw
        from raw_announcements
        where source = %s and exchange_ts is not null
          and (exchange_ts at time zone 'Asia/Kolkata')::date between %s and %s""",
        (SOURCE, since - timedelta(days=3), until + timedelta(days=3)))]
    report_dates = [r[0] for r in conn.execute(
        "select distinct report_date from bundle_announcements where report_date between %s"
        " and %s order by 1", (since, until))]

    below = 0
    now = datetime.now(timezone.utc)
    for day in report_dates:
        bundle = [BundleEntry(sym, body) for sym, body in conn.execute(
            "select symbol, body from bundle_announcements where report_date = %s", (day,))]
        cov = reconcile(day, bundle, api, window_days=1, universe=universe_symbols)
        ok = coverage_is_acceptable(cov, floor)
        below += 0 if ok else 1
        conn.execute(
            "insert into reconcile_days (report_date, bundle_orders, bundle_order_symbols,"
            " matched_symbols, coverage, unmatched_symbols, offsets, acceptable, checked_at)"
            " values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (report_date) do update set"
            " bundle_orders = excluded.bundle_orders,"
            " bundle_order_symbols = excluded.bundle_order_symbols,"
            " matched_symbols = excluded.matched_symbols, coverage = excluded.coverage,"
            " unmatched_symbols = excluded.unmatched_symbols, offsets = excluded.offsets,"
            " acceptable = excluded.acceptable, checked_at = excluded.checked_at",
            (day, cov.bundle_orders, len(cov.bundle_order_symbols),
             len(cov.matched_order_symbols), cov.order_symbol_coverage,
             sorted(cov.unmatched_order_symbols),
             json.dumps({str(k): v for k, v in cov.offset_histogram.items()}), ok, now),
        )
    conn.commit()
    return {"report_dates": len(report_dates), "below_floor": below}
