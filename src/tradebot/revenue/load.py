"""Fetching and storing quarterly revenue for listed companies (ARCHITECTURE §5.8).

One request per company against the confirmed "Financial Results" listing endpoint (Spike
C, 27 Sep 2026): `GET /api/corporates-financial-results?symbol=&period=Quarterly` returns a
company's whole results history with one `xbrl` URL per filing. One further request per
filing that has a real link (older rows before ~2018 carry a `"-"` placeholder instead and
are skipped, not guessed). Every fact `revenue/xbrl.py` can read from that file is stored;
the caller (`revenue/ttm.py`) decides which quarters it needs.

**Known gap, not silently accepted** (§5.8, §11): this endpoint's data stops around when
NSE's "Integrated Filing – Financial" regime began (April 2025) - confirmed on BEL, whose
listing here ends 30-Jan-2025. The backfill's study window (22 Sep 2025 – 18 Sep 2026) sits
almost entirely after that cutover, so this loader alone will leave most companies' most
recent quarters missing, and TTM for most events null rather than wrong - `ttm.py` never
guesses a gap closed. The Integrated Filing API's own path is still unknown (§5.8); this
loader is written so that filling that in later is one more listing source, not a rewrite.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from tradebot.collector.records import parse_ts
from tradebot.revenue.xbrl import parse as parse_xbrl

log = logging.getLogger("backfill")

KEEP_MONTHS = (3, 6, 9, 12)     # quarter, half-year, nine-months, full year


def _filed_at(row: dict) -> datetime | None:
    """The exchange dissemination time if given (matches other `filed_at` uses in this
    project - "DD-Mon-YYYY HH:MM:SS", which `exchdisstime` already carries and
    `parse_ts` expects), else `filingDate`, which this endpoint gives to the minute only
    ("DD-Mon-YYYY HH:MM") and so needs ":00" appended before `parse_ts` can read it. A row
    with neither, or with the "-" placeholder some older rows carry, returns None and is
    skipped rather than guessed."""
    if row.get("exchdisstime"):
        return parse_ts(row["exchdisstime"])
    filing_date = row.get("filingDate")
    return parse_ts(f"{filing_date}:00") if filing_date else None


def listing_rows(client, symbol: str) -> list[dict] | None:
    """One company's whole results history, or None on a failed request."""
    result = client.fetch_results_listing(symbol)
    return result.rows if result.ok else None


def pending_isins(conn) -> list[tuple[str, str]]:
    """(isin, symbol) for listed companies whose results have not been fetched yet."""
    return conn.execute("""
        select u.isin, u.symbol from backfill_universe u
        where u.excluded_reason is null
          and not exists (select 1 from backfill_checkpoints c
                          where c.job = 'revenue' and c.key = u.isin)
        order by u.isin""").fetchall()


def fetch_company(conn, client, fetcher, isin: str, symbol: str) -> tuple[bool, str]:
    """Fetch one company's results listing, then every filing with a real XBRL link.
    Checkpointed only on full success, like `backfill/announcements.py`."""
    rows = listing_rows(client, symbol)
    if rows is None:
        return False, "results listing request failed"

    stored, skipped, failed = 0, 0, 0
    for row in rows:
        xbrl_url = row.get("xbrl") or ""
        if not xbrl_url or xbrl_url.endswith("/-"):
            skipped += 1
            continue
        filed_at = _filed_at(row)
        if filed_at is None:
            skipped += 1
            continue
        fetched = fetcher.get(xbrl_url)          # market.fetch.ArchiveFetcher: bytes, no disk
        if not fetched.ok:
            failed += 1
            continue
        try:
            facts = parse_xbrl(fetched.content)
        except Exception as exc:      # a malformed instance is skipped, not fatal (never guess)
            log.warning("%s: %s unparseable: %s", symbol, xbrl_url, exc)
            failed += 1
            continue
        with conn.cursor() as cur:
            cur.executemany(
                "insert into financials (isin, period_start, period_end, period_months, basis,"
                " revenue_inr, filed_at, source_url, context_id, element)"
                " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " on conflict (isin, period_end, period_months, basis, filed_at) do nothing",
                [(isin, f.period_start, f.period_end, f.months, f.basis, f.revenue_inr,
                  filed_at, xbrl_url, f.context_id, f.element)
                 for f in facts if f.months in KEEP_MONTHS and f.basis is not None])
        stored += len(facts)

    conn.execute("insert into backfill_checkpoints (job, key, done_at, detail) values"
                " ('revenue', %s, %s, %s)",
                (isin, datetime.now(timezone.utc),
                 json.dumps({"rows": len(rows), "stored": stored, "skipped": skipped,
                            "failed": failed})))
    conn.commit()
    return True, f"{stored} facts from {len(rows)} filings ({skipped} no xbrl, {failed} failed)"


def run(conn, cfg, *, max_requests: int, client=None, fetcher=None, sleep=time.sleep) -> dict:
    """`client` (NseClient) fetches each company's results listing; `fetcher` (ArchiveFetcher)
    downloads the XBRL files it links to - two hosts, two sessions, same split
    `documents/fetch.py` already made between the collector and PDF downloads.

    `NseClient` only closes idle connections; it has no minimum-gap pacing of its own
    (unlike `ArchiveFetcher`, which paces itself before every `.get()`), so the listing call
    is paced here exactly as `backfill/announcements.py` paces its `symbol=` queries -
    otherwise this loop would send one request per company with no gap at all.
    """
    from tradebot.collector.nse import NseClient, jittered
    from tradebot.market.fetch import ArchiveFetcher

    client = client or NseClient()
    fetcher = fetcher or ArchiveFetcher()
    gap = float(client.cfg["pacing"]["backfill_min_gap_seconds"])
    jitter = client.cfg["pacing"]["jitter_seconds"]

    todo = pending_isins(conn)
    log.info("%d companies pending revenue fetch", len(todo))
    done = failed = requests = 0
    for i, (isin, symbol) in enumerate(todo):
        if requests + 2 > max_requests:      # a listing call plus at least one XBRL file
            log.warning("stopping at --max-requests %d", max_requests)
            break
        if i:
            sleep(jittered(gap, jitter))
        ok, summary = fetch_company(conn, client, fetcher, isin, symbol)
        requests += 1
        log.info("%s %s: %s", isin, "ok" if ok else "FAILED", summary)
        done, failed = (done + 1, failed) if ok else (done, failed + 1)
    return {"fetched": done, "failed": failed, "remaining": len(todo) - done}
