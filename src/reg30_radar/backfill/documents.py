"""The backfill's document stage: download, extract and T0-parse the listed companies'
in-scope filings (§5.4-§5.6, D7 as widened), through the live pipeline's own
`orders.run.process_pending`, so a backfill filing is judged exactly as a live one.

Two differences from the live path, both from CLAUDE.md's rules:
- order extraction by the LLM is deferred to the Batch API. The client handed to the
  pipeline refuses `extract_json` with "deferred to Batch", which the pipeline already
  records as `pending_llm`, and backfill/batch.py submits those later;
- vision OCR stays on the standard API (the recorded exception, §6), so no page image has to
  outlive its PDF, and draws from the backfill's single $3 budget.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from decimal import Decimal

from reg30_radar.common.calendar import IST
from reg30_radar.common.config import ROOT
from reg30_radar.documents.fetch import PdfFetcher
from reg30_radar.llm.client import LlmClient, LlmRefused
from reg30_radar.orders import run as run_mod
from reg30_radar.orders import store as orders_store
from reg30_radar.router.orders import classify, in_scope

log = logging.getLogger("backfill")

WORK_DIR = ROOT / "data" / "backfill_work"
CRORE = Decimal(10) ** 7

# Download tiers, fetched in this order (config/backfill.yaml `documents`, 27 Sep 2026)
ORDER_CATEGORY, HEADLINE_HIT, OTHER_CATCH_ALL = 0, 1, 2
TIER_NAMES = {ORDER_CATEGORY: "order categories", HEADLINE_HIT: "catch-all, headline hit",
              OTHER_CATCH_ALL: "catch-all, body check only"}


class BatchDeferringClient:
    """OCR through the real client; order extraction refused, to be batched instead."""

    def __init__(self, real: LlmClient):
        self.real = real

    def transcribe_image(self, png_bytes, *, prompt_version, max_output_tokens=None):
        return self.real.transcribe_image(png_bytes, prompt_version=prompt_version,
                                          max_output_tokens=max_output_tokens)

    def extract_json(self, *args, **kwargs):
        raise LlmRefused("deferred to the Batch API (backfill)")


WINDOW_ROWS_SQL = """
select distinct on (r.source_id)
    r.id, r.source_id, r.symbol, r.category_raw, r.headline, r.attachment_url,
    r.first_seen_at, r.revision, r.isin
from raw_announcements r
where r.source = 'nse'
  and r.exchange_ts >= %(since)s and r.exchange_ts < %(until)s
  -- a company dropped by an industry rule after its history was fetched; matched by issuer
  -- code, since a filing carries the company's original ISIN (common/isin.py)
  and not exists (select 1 from backfill_universe u
                  where left(u.isin, 7) = left(r.isin, 7) and u.excluded_reason is not null)
order by r.source_id, r.revision desc
"""


def window_rows(conn, since: date, until: date) -> list[dict]:
    """The latest revision of every stored filing dated inside the study window."""
    params = {"since": datetime.combine(since, time.min, IST),
              "until": datetime.combine(until + timedelta(days=1), time.min, IST)}
    cols = ("id", "source_id", "symbol", "category_raw", "headline", "attachment_url",
            "first_seen_at", "revision", "isin")
    return [dict(zip(cols, r)) for r in conn.execute(WINDOW_ROWS_SQL, params).fetchall()]


def company_mcaps(conn) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Each listed company's market cap on the universe date, by issuer code (a filing
    carries the company's original ISIN, common/isin.py) and by symbol (for the filings
    that carry no ISIN; every symbol the company traded under, reissues included)."""
    by_issuer = {isin[:7]: mcap for isin, mcap in conn.execute(
        "select isin, mcap_inr from backfill_universe where mcap_inr is not null")}
    by_symbol = dict(conn.execute(
        "select distinct on (s.symbol) s.symbol, u.mcap_inr from backfill_universe u"
        " join instrument_symbols s on left(s.isin, 9) = left(u.isin, 9)"
        " where u.mcap_inr is not null order by s.symbol, s.last_seen desc").fetchall())
    return by_issuer, by_symbol


def tier_of(row: dict) -> int:
    rel = classify(row["category_raw"], row["headline"])
    if rel.bucket in ("order_win", "order_candidate"):
        return ORDER_CATEGORY
    return HEADLINE_HIT if rel.order_related else OTHER_CATCH_ALL


def todo(conn, rows: list[dict], max_mcap_crore=None) -> tuple[list[dict], int]:
    """(in-scope rows not yet processed, in tier order; how many were left out because
    their company is above `max_mcap_crore` and only a body check would find an order).
    `pending_llm` is not retried here: those wait on a Batch, and processing them again
    would re-download the PDF for nothing. A company whose market cap is unknown is kept,
    the direction that loses nothing."""
    pending = orders_store.pending_raw_ids(conn, [r["id"] for r in rows],
                                           retry_statuses=("download_failed",))
    ceiling = Decimal(max_mcap_crore) * CRORE if max_mcap_crore is not None else None
    by_issuer, by_symbol = company_mcaps(conn) if ceiling is not None else ({}, {})
    keep, left_out = [], 0
    for r in rows:
        if r["id"] not in pending or not in_scope(classify(r["category_raw"], r["headline"])):
            continue
        tier = tier_of(r)
        if tier == OTHER_CATCH_ALL and ceiling is not None:
            mcap = by_issuer.get((r["isin"] or "")[:7]) or by_symbol.get(r["symbol"])
            if mcap is not None and mcap > ceiling:
                left_out += 1
                continue
        keep.append((tier, r))
    keep.sort(key=lambda t: t[0])          # stable: within a tier, the window's own order
    return [r for _, r in keep], left_out


def _ceiling(cfg: dict | None):
    return ((cfg or {}).get("documents") or {}).get("other_catch_all_max_mcap_crore")


def expected(conn, since: date, until: date, cfg: dict | None = None) -> dict:
    """What this stage would download, measured before anything is downloaded."""
    rows = window_rows(conn, since, until)
    waiting, left_out = todo(conn, rows, _ceiling(cfg))
    per_tier = {TIER_NAMES[t]: 0 for t in TIER_NAMES}
    for r in waiting:
        per_tier[TIER_NAMES[tier_of(r)]] += 1
    return {"filings_in_window": len(rows), "to_download": len(waiting), **per_tier,
            "left out (above the catch-all ceiling)": left_out,
            "estimated_gb": round(len(waiting) / 1024, 1)}   # ~1 MB a PDF (WORKLOG, 27 Sep)


def run(conn, since: date, until: date, *, max_downloads: int,
        cfg: dict | None = None) -> run_mod.Summary:
    """Process up to `max_downloads` filings this run, highest tier first; the rest wait
    for the next run."""
    waiting, left_out = todo(conn, window_rows(conn, since, until), _ceiling(cfg))
    batch = waiting[:max_downloads]
    log.info("%d filings to process this run (limit %d; %d waiting in all, %d left out above"
             " the catch-all ceiling)", len(batch), max_downloads, len(waiting), left_out)
    client = BatchDeferringClient(LlmClient(conn=conn, budget="backfill"))
    return run_mod.process_pending(
        conn, batch, fetcher=PdfFetcher(), client=client, work_dir=WORK_DIR,
        retry_statuses=("download_failed",),
    )
