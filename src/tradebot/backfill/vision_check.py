"""§5.5 Part C's second read. `python -m tradebot.backfill vision-check`

A value read from this pipeline's own vision OCR is not verified on the span check alone
(extractor/part_c.py). For each such value this stage:
1. downloads the PDF again from its URL (D8 deleted it after extraction) and checks the
   SHA-256 matches what was stored, so it re-reads the same document;
2. renders the page or pages the value sits on exactly as the first read did, and
   transcribes them blind: the model sees the image only, never the first transcript;
3. accepts the value only if the new transcript gives the same value: its quote verifies
   there (extractor/provenance.py), or one line of it, or two adjacent lines, reads as exactly
   that amount with nothing blocking it (units/money.py). An independent read may print the
   same amount differently ("Rs.283 Cr." against "Rs. 283 Crore"), and requiring the first
   read's exact wording would make it a check of formatting, not of the value. Disagreement,
   or no way to re-read, sends it to review. The new transcript is kept beside the first.

The PDF is deleted again straight after, inside the work directory only (D8). Every
request goes through the NSE guard; the model calls draw from the backfill's $3 budget on
the standard API, as all OCR does (§6). Values a second read already confirmed are skipped.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from tradebot.common.config import ROOT, documents as documents_config, llm as llm_config
from tradebot.documents.pipeline import _delete_downloaded
from tradebot.documents.text import render_page_png
from tradebot.extractor import part_c
from tradebot.extractor.provenance import occurrences, verify
from tradebot.llm.client import LlmRefused
from tradebot.units.money import is_suspect, parse_money

log = logging.getLogger("backfill")

WORK_DIR = ROOT / "data" / "backfill_work"
PROMPT_VERSION = "ocr_transcribe_v1"
PURPOSE = "ocr_second_read"

CANDIDATES_SQL = """
select oe.raw_announcement_id, d.text, d.page_report, d.sha256, ra.attachment_url,
       oe.value_span, oe.value_inr, oe.review_status, oe.second_read, oe.second_read_inr
from order_extractions oe
join documents d on d.id = oe.document_id
join raw_announcements ra on ra.id = oe.raw_announcement_id
where (oe.review_status = 'verified' or oe.second_read = 'pending')
  and oe.value_inr is not null
  and exists (select 1 from jsonb_array_elements(d.page_report) p
              where p->>'source' = 'vision' and p->>'verdict' = 'ok')
order by oe.raw_announcement_id
"""


def pages_to_read(text: str, page_report: list, value_span: str, value_inr: Decimal) -> list[int]:
    """The page numbers to re-read: the vision pages the value sits on when the pages can
    be told apart, otherwise every vision page (capped like the first read)."""
    kept = [p for p in page_report if p.get("verdict") == "ok"]
    vision = [p["page"] for p in kept if p.get("source") == "vision"]
    spans = part_c.page_spans(text, page_report)
    found = occurrences(text, value_span, value_inr)
    if spans and found:
        on = {kept[i]["page"] for i, (start, end, source) in enumerate(spans)
              for offset in found if start <= offset < end and source == "vision"}
        if on:
            return sorted(on)
    return vision[:int(llm_config().get("ocr_max_pages_per_document", 10))]


def agrees(transcript: str, value_span: str | None, value_inr: Decimal) -> bool:
    """Whether an independent transcript gives the same value (see the module docstring)."""
    if not transcript:
        return False
    if verify(transcript, value_span, value_inr):
        return True
    lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]
    candidates = lines + [a + " " + b for a, b in zip(lines, lines[1:])]
    for text in candidates:
        money = parse_money(text)
        if money.value_inr == value_inr and not is_suspect(money):
            return True
    return False


def _render(path, page_numbers: list[int]) -> list[bytes]:
    import pdfplumber
    cfg = documents_config()["ocr"]
    with pdfplumber.open(path) as pdf:
        return [render_page_png(pdf.pages[n - 1], dpi=int(cfg["dpi"]),
                                grayscale=bool(cfg.get("grayscale", True)))
                for n in page_numbers if 0 < n <= len(pdf.pages)]


def _record(conn, raw_id: int, *, second_read: str, value_inr, status: str,
            transcript: str | None = None) -> None:
    conn.execute("update order_extractions set second_read = %s, second_read_inr = %s,"
                 " review_status = %s, second_read_text = coalesce(%s, second_read_text)"
                 " where raw_announcement_id = %s",
                 (second_read, value_inr, status, transcript, raw_id))
    conn.commit()


def run(conn, *, client, fetcher=None, work_dir=WORK_DIR, max_requests: int = 100) -> dict:
    from tradebot.documents.fetch import PdfFetcher

    fetcher = fetcher or PdfFetcher()
    out = {"not_vision": 0, "already_agreed": 0, "agrees": 0, "disagrees": 0,
           "unavailable": 0, "downloads": 0, "ocr_pages": 0}
    for (raw_id, text, report, sha, url, span, value, status,
         second, second_inr) in conn.execute(CANDIDATES_SQL).fetchall():
        if not part_c.vision_sourced(text, report, span, value):
            if second is not None:
                conn.execute("update order_extractions set second_read = null,"
                             " second_read_inr = null where raw_announcement_id = %s", (raw_id,))
                conn.commit()
            out["not_vision"] += 1
            continue
        if second == "agrees" and second_inr == value:
            out["already_agreed"] += 1
            continue
        if out["downloads"] >= max_requests:
            log.warning("stopping at --max-requests %d", max_requests)
            break

        got = fetcher.fetch(url, work_dir) if url else None
        out["downloads"] += 1
        if got is None or not got.ok or got.sha256 != sha:
            reason = "no url" if got is None else (got.error or "sha256 differs from the stored one")
            log.warning("%s: no second read possible (%s)", raw_id, reason)
            if got is not None and got.path:
                _delete_downloaded(got.path, work_dir)
            _record(conn, raw_id, second_read="unavailable", value_inr=value,
                    status="needs_review")
            out["unavailable"] += 1
            continue
        try:
            images = _render(got.path, pages_to_read(text, report, span, value))
        finally:
            _delete_downloaded(got.path, work_dir)          # D8: as soon as it is rendered

        transcripts = []
        try:
            for png in images:
                transcripts.append(client.transcribe_image(
                    png, prompt_version=PROMPT_VERSION, purpose=PURPOSE))
                out["ocr_pages"] += 1
        except LlmRefused as exc:
            # The backfill cap is reached or OCR is not configured: wait, never guess.
            log.warning("second reads stopped: %s", exc)
            _record(conn, raw_id, second_read="pending", value_inr=value, status="needs_review")
            break
        transcript = "\n\n".join(t for t in transcripts if t)
        ok = agrees(transcript, span, value)
        # An empty transcript is no second read at all, not a disagreement (RPPINFRA).
        verdict = "agrees" if ok else ("disagrees" if transcript.strip() else "unavailable")
        _record(conn, raw_id, second_read=verdict, value_inr=value,
                status="verified" if ok else "needs_review", transcript=transcript)
        out[verdict] += 1
        log.info("%s: second read %s", raw_id, verdict if ok else verdict.upper())
    return out
