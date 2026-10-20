"""Fetching and storing quarterly revenue for the backfill's event companies (ARCHITECTURE §5.8).

NSE publishes results in two listings, split at the April-2025 "Integrated Filing" cutover:
- `corporates-financial-results` (Spike C): the older "Financial Results" filings, up to
  the quarter ended 31-Dec-2024 (BEL's listing ends there, filed 30-Jan-2025);
- `integrated-filing-results` (Spike C2, 27 Sep 2026): "Integrated Filing - Financials",
  from the quarter ended 31-Mar-2025 on.
Both link one XBRL file per filing on nsearchives, and `revenue/xbrl.py` reads both (the
Spike C2 check: BEL's FY26 minus its 9M equals its own stated Q4, to the rupee). So each
company costs two listing calls plus one download per filing whose quarter ends on or
after `window.results_from`; older filings are never downloaded. Every fact the parser
reads is stored, and `revenue/ttm.py` decides which quarters it needs.

Only companies with a backfill event are fetched: TTM is used for nothing but an event's
ratios, so the stage runs after `events`, and fetching the whole universe would cost
about three times the requests for no change in any result.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

from tradebot.collector.records import parse_ts
from tradebot.revenue.xbrl import parse as parse_xbrl

log = logging.getLogger("backfill")

KEEP_MONTHS = (3, 6, 9, 12)     # quarter, half-year, nine-months, full year


@dataclass(frozen=True)
class Filing:
    """One results filing from either listing, reduced to what the loader needs."""
    xbrl_url: str
    filed_at: datetime
    period_end: date


def _day(text: str | None) -> date | None:
    """'31-Dec-2024' (old listing) or '30-JUN-2026' (integrated); %b ignores case."""
    try:
        return datetime.strptime((text or "").strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _has_link(url: str) -> bool:
    # Rows before ~2018 in the old listing carry a "-" placeholder instead of a link.
    return bool(url) and url != "-" and not url.endswith("/-")


def _filed_at(row: dict) -> datetime | None:
    """Old listing: the exchange dissemination time if given (matches other `filed_at` uses
    in this project - "DD-Mon-YYYY HH:MM:SS", which `exchdisstime` already carries and
    `parse_ts` expects), else `filingDate`, which this endpoint gives to the minute only
    ("DD-Mon-YYYY HH:MM") and so needs ":00" appended before `parse_ts` can read it. A row
    with neither, or with the "-" placeholder some older rows carry, returns None and is
    skipped rather than guessed."""
    if row.get("exchdisstime"):
        return parse_ts(row["exchdisstime"])
    filing_date = row.get("filingDate")
    return parse_ts(f"{filing_date}:00") if filing_date else None


def old_filing(row: dict) -> Filing | None:
    url, filed_at, end = row.get("xbrl") or "", _filed_at(row), _day(row.get("toDate"))
    if not _has_link(url) or filed_at is None or end is None:
        return None
    return Filing(url, filed_at, end)


def integrated_filing(row: dict) -> Filing | None:
    """A revised filing's figures were public only from its revision, so the later of
    `broadcast_Date` and `revised_Date` is its `filed_at` - using the earlier would let
    point-in-time TTM see numbers before they existed."""
    url, end = row.get("xbrl") or "", _day(row.get("qe_Date"))
    dates = [d for d in (parse_ts(row.get("broadcast_Date")), parse_ts(row.get("revised_Date")))
             if d is not None]
    if not _has_link(url) or not dates or end is None:
        return None
    return Filing(url, max(dates), end)


MAX_PAGES = 5      # 100 rows: far more results filings than any company has in the window


def _integrated_listing(client, symbol: str, pause=lambda: None):
    """Every page of the integrated listing. It answers 20 rows a page; three companies
    (ITI, MCLOUD, AHLUCONT) had more and lost their oldest rows when only page 1 was read
    (WORKLOG, 4 Oct 2026). Returns (result, requests sent); `result.total` stays, so a
    listing still short after MAX_PAGES is visible as truncated."""
    first = client.fetch_integrated_results(symbol)
    sent = 1
    while (first.ok and first.total is not None and len(first.rows) < first.total
           and sent < MAX_PAGES):
        pause()
        more = client.fetch_integrated_results(symbol, page=sent + 1)
        sent += 1
        if not more.ok:
            return more, sent
        if not more.rows:
            break
        first.rows.extend(more.rows)
    return first, sent


# (name, how to ask the client, how to read a row) - the two listings in date order.
# `ask` returns (result, requests sent).
SOURCES = (
    ("financial_results", lambda client, symbol, pause: (client.fetch_results_listing(symbol), 1),
     old_filing),
    ("integrated_filing", _integrated_listing, integrated_filing),
)


def distinct_facts(facts) -> tuple[list, int]:
    """One fact per (period end, months, basis) within one file. Two facts that agree
    collapse into one (a quarter's OneD and FourD contexts often repeat a figure); two that
    disagree are both dropped and counted, because keeping whichever came first, as the
    insert's conflict clause used to, is a silent guess (audit, 20 Oct 2026)."""
    by_key: dict[tuple, list] = {}
    for x in facts:
        by_key.setdefault((x.period_end, x.months, x.basis), []).append(x)
    kept, dropped = [], 0
    for group in by_key.values():
        if len({x.revenue_inr for x in group}) == 1:
            kept.append(group[0])
        else:
            dropped += len(group)
    return kept, dropped


def pending_companies(conn) -> list[tuple[str, str]]:
    """(isin, symbol to query) for event companies not yet fetched. The symbol is the
    latest the issuer traded under, found by the ISIN's first nine characters, because
    NSE files a company's history under its current symbol (LTIM's under LTM) and a
    reissued ISIN can come with a new one (SABTNL became AQYLON)."""
    return conn.execute("""
        select u.isin,
               (select s.symbol from instrument_symbols s
                where left(s.isin, 9) = left(u.isin, 9)
                order by s.last_seen desc, s.symbol limit 1)
        from backfill_universe u
        where u.excluded_reason is null
          and exists (select 1 from backfill_events e where e.isin = u.isin)
          and not exists (select 1 from backfill_checkpoints c
                          where c.job = 'revenue' and c.key = u.isin)
        order by u.isin""").fetchall()


def fetch_company(conn, client, fetcher, isin: str, symbol: str, since: date,
                  pause=lambda: None) -> tuple[bool, str, int]:
    """Fetch one company: both listings, then every in-range filing's XBRL. Returns
    (ok, summary, requests sent). Checkpointed only when both listings and every download
    succeeded, like `backfill/announcements.py`, so a re-run retries a partial company
    (rows already stored are skipped by the insert's conflict clause)."""
    requests, detail, filings, truncated_any = 0, {}, [], False
    for n, (name, ask, read) in enumerate(SOURCES):
        if n:
            pause()
        result, sent = ask(client, symbol, pause)
        requests += sent
        if not result.ok:
            return False, f"{name} listing: {result.error}", requests
        read_rows = [read(r) for r in result.rows]
        usable = [f for f in read_rows if f is not None]
        in_range = [f for f in usable if f.period_end >= since]
        # A listing that says it holds more rows than it returned was cut off at one page.
        truncated = result.total is not None and result.total > len(result.rows)
        if truncated:
            truncated_any = True
            log.warning("%s: %s listing truncated (%d of %d rows)", symbol, name,
                        len(result.rows), result.total)
        detail[name] = {"rows": len(result.rows), "no_link_or_date": len(read_rows) - len(usable),
                        "before_window": len(usable) - len(in_range), "truncated": truncated}
        filings.extend(in_range)

    stored = failed = unparseable = conflicting = 0
    for f in filings:
        fetched = fetcher.get(f.xbrl_url)          # market.fetch.ArchiveFetcher: bytes, no disk
        requests += 1
        if not fetched.ok:
            failed += 1
            continue
        try:
            facts = parse_xbrl(fetched.content)
        except Exception as exc:      # a malformed instance is skipped, not fatal (never guess)
            log.warning("%s: %s unparseable: %s", symbol, f.xbrl_url, exc)
            unparseable += 1
            continue
        kept, dropped = distinct_facts(
            [x for x in facts if x.months in KEEP_MONTHS and x.basis is not None])
        if dropped:
            log.warning("%s: %s: %d facts dropped, two values for one period",
                        symbol, f.xbrl_url, dropped)
            conflicting += dropped
        with conn.cursor() as cur:
            cur.executemany(
                "insert into financials (isin, period_start, period_end, period_months, basis,"
                " revenue_inr, filed_at, source_url, context_id, element)"
                " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " on conflict (isin, period_end, period_months, basis, filed_at) do nothing",
                [(isin, x.period_start, x.period_end, x.months, x.basis, x.revenue_inr,
                  f.filed_at, f.xbrl_url, x.context_id, x.element) for x in kept])
        stored += len(kept)

    summary = (f"{stored} facts from {len(filings)} filings ({failed} failed, "
               f"{unparseable} unparseable, {conflicting} conflicting)")
    if failed or truncated_any:
        # A short listing is retried next run rather than checkpointed as complete: it
        # was checkpointed before, so the missing rows were never fetched (4 Oct 2026).
        conn.commit()
        return False, summary, requests
    detail.update({"filings": len(filings), "stored": stored, "unparseable": unparseable,
                   "conflicting": conflicting})
    conn.execute("insert into backfill_checkpoints (job, key, done_at, detail) values"
                 " ('revenue', %s, %s, %s)",
                 (isin, datetime.now(timezone.utc), json.dumps(detail)))
    conn.commit()
    return True, summary, requests


def run(conn, cfg, *, max_requests: int, client=None, fetcher=None, sleep=time.sleep) -> dict:
    """`client` (NseClient) fetches the listings from www.nseindia.com; `fetcher`
    (ArchiveFetcher) downloads the XBRL files from nsearchives - two hosts, two sessions,
    the split `documents/fetch.py` already made between the collector and PDF downloads.

    `NseClient` has no minimum-gap pacing of its own (unlike `ArchiveFetcher`, which paces
    itself before every `.get()`), so listing calls are paced here exactly as
    `backfill/announcements.py` paces its `symbol=` queries.
    """
    from tradebot.collector.nse import NseClient, jittered
    from tradebot.common.config import nse as cfg_nse
    from tradebot.market.fetch import ArchiveFetcher

    client = client or NseClient(
        min_gap=float(cfg_nse()["pacing"]["backfill_min_gap_seconds"]))
    fetcher = fetcher or ArchiveFetcher()
    gap = float(client.cfg["pacing"]["backfill_min_gap_seconds"])
    jitter = client.cfg["pacing"]["jitter_seconds"]
    pause = lambda: sleep(jittered(gap, jitter))   # noqa: E731 - one line, used twice
    since = date.fromisoformat(str(cfg["window"]["results_from"]))

    todo = pending_companies(conn)
    log.info("%d event companies pending revenue fetch (quarters ending from %s)",
             len(todo), since)
    done = failed = requests = 0
    for i, (isin, symbol) in enumerate(todo):
        # Stop before a company that could overrun the cap: two listings plus about 16
        # downloads (two quarters in the old listing and six integrated, both bases).
        if requests + 18 > max_requests:
            log.warning("stopping at --max-requests %d", max_requests)
            break
        if i:
            pause()
        ok, summary, sent = fetch_company(conn, client, fetcher, isin, symbol, since, pause)
        requests += sent
        log.info("%s %s: %s", isin, "ok" if ok else "FAILED", summary)
        done, failed = (done + 1, failed) if ok else (done, failed + 1)
    mismatches = fy_check(conn)
    return {"fetched": done, "failed": failed, "requests": requests,
            "remaining": len(todo) - done, "fy_mismatches": mismatches}


def fy_check(conn) -> int:
    """§5.8: log every full year whose four filed quarters do not add up to it."""
    from tradebot.revenue.ttm import Period, fy_mismatches
    rows = conn.execute("select isin, period_end, period_months, basis, revenue_inr, filed_at"
                        " from financials order by isin").fetchall()
    by_isin: dict[str, list] = {}
    for isin, end, months, basis, value, filed in rows:
        by_isin.setdefault(isin, []).append(Period(end, months, basis, value, filed))
    n = 0
    for isin, periods in by_isin.items():
        for end, basis, fy, total in fy_mismatches(periods):
            n += 1
            log.warning("%s %s FY %s: four quarters sum to %s, the year says %s",
                        isin, basis, end, total, fy)
    return n
