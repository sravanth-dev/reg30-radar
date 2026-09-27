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

from tradebot.common.calendar import IST
from tradebot.common.config import ROOT
from tradebot.documents.fetch import PdfFetcher
from tradebot.llm.client import LlmClient, LlmRefused
from tradebot.orders import run as run_mod
from tradebot.orders import store as orders_store
from tradebot.router.orders import classify, in_scope

log = logging.getLogger("backfill")

WORK_DIR = ROOT / "data" / "backfill_work"


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
    r.first_seen_at, r.revision
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
            "first_seen_at", "revision")
    return [dict(zip(cols, r)) for r in conn.execute(WINDOW_ROWS_SQL, params).fetchall()]


def todo(conn, rows: list[dict]) -> list[dict]:
    """In-scope rows not yet processed. `pending_llm` is not retried here: those wait on a
    Batch, and processing them again would re-download the PDF for nothing."""
    pending = orders_store.pending_raw_ids(conn, [r["id"] for r in rows],
                                           retry_statuses=("download_failed",))
    return [r for r in rows
            if r["id"] in pending and in_scope(classify(r["category_raw"], r["headline"]))]


def expected(conn, since: date, until: date) -> dict:
    """What this stage would download, measured before anything is downloaded."""
    rows = window_rows(conn, since, until)
    waiting = todo(conn, rows)
    return {"filings_in_window": len(rows), "to_download": len(waiting),
            "estimated_gb": round(len(waiting) / 1024, 1)}   # ~1 MB a PDF (WORKLOG, 27 Sep)


def run(conn, since: date, until: date, *, max_downloads: int) -> run_mod.Summary:
    """Process up to `max_downloads` filings this run; the rest wait for the next run."""
    batch = todo(conn, window_rows(conn, since, until))[:max_downloads]
    log.info("%d filings to process this run (limit %d)", len(batch), max_downloads)
    client = BatchDeferringClient(LlmClient(conn=conn, budget="backfill"))
    return run_mod.process_pending(
        conn, batch, fetcher=PdfFetcher(), client=client, work_dir=WORK_DIR,
        retry_statuses=("download_failed",),
    )
