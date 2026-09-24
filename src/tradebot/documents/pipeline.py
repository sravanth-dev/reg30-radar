"""The §5.5 document pipeline: download → SHA-256 → text → store → delete the PDF.

D8 is the rule this module exists to honour: the PDF goes away as soon as its text is safe,
because disk is the binding constraint on the CX22 (§3). The text, URL and hash are what
survive, and §8 keeps them so a better parser can re-run over the whole backfill without
asking NSE for thousands of files again.

Two safety properties are built in rather than left to care:

- **The pipeline only ever deletes inside its own working directory.** `tests/labelled/`
  holds the permanent ground-truth PDFs (D8's one exception) and a pipeline bug that reached
  them would destroy the only hand-labelled data in the project. So the delete refuses any
  path that is not under the work directory it was given, and says so.
- **The PDF is deleted only after the text is committed.** Deleting first and storing second
  would turn one failed transaction into a permanently lost filing, since the attachment URL
  is not guaranteed to stay live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradebot.common.config import documents as documents_config
from tradebot.common.config import llm as llm_config
from tradebot.documents.fetch import Fetched, PdfFetcher, sha256_of
from tradebot.documents.store import DocumentRow, find_by_sha256, insert, mark_pdf_deleted
from tradebot.documents.text import OcrFn, extract

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class Outcome:
    ok: bool
    url: str
    sha256: str | None = None
    document_id: int | None = None
    pages: int = 0
    chars: int = 0
    is_scanned: bool = False
    quality: str = "ok"
    ocr_pages: int = 0
    method: str | None = None
    pdf_deleted: bool = False
    already_stored: bool = False
    needs_review: bool = False
    error: str | None = None


class UnsafeDeletePath(Exception):
    """Raised when something asks the pipeline to delete a file it did not download."""


def _delete_downloaded(path: Path, work_dir: Path) -> bool:
    """Remove a downloaded PDF, refusing anything outside the work directory.

    The check is on the resolved paths, so a symlink or a `..` cannot walk out of the
    sandbox into the repository.
    """
    path = Path(path).resolve()
    root = Path(work_dir).resolve()
    if not path.is_relative_to(root):
        raise UnsafeDeletePath(
            f"refusing to delete {path}: outside the work directory {root}. "
            f"D8's delete applies only to files this pipeline downloaded."
        )
    path.unlink(missing_ok=True)
    return not path.exists()


def process_url(
    url: str,
    *,
    work_dir: Path,
    conn=None,
    fetcher: PdfFetcher | None = None,
    event_id: int | None = None,
    raw_announcement_id: int | None = None,
    ocr: OcrFn | None = None,
) -> Outcome:
    """Run one attachment through the whole pipeline.

    `conn` may be None, which runs everything except the database write. That is what the
    eval harness uses, and it keeps the extraction path testable without a database
    (§9: most tests need none).

    `ocr` is None by default - §5.5 Part B stays dormant unless a caller explicitly passes
    `tradebot.documents.ocr.maybe_transcribe` (which itself no-ops until Sravanth configures
    a vision model and cap). Nothing here reaches the network for OCR on its own.
    """
    fetcher = fetcher or PdfFetcher()
    got: Fetched = fetcher.fetch(url, work_dir)
    if not got.ok or got.path is None:
        return Outcome(False, url, sha256=got.sha256, error=got.error)

    # A hash we already hold means the bytes are already extracted and stored (§5.3's
    # dedup case). Nothing to re-extract; the file still has to go.
    if conn is not None:
        existing = find_by_sha256(conn, got.sha256)
        if existing:
            deleted = _delete_downloaded(got.path, work_dir)
            return Outcome(True, url, sha256=got.sha256, document_id=existing["id"],
                           pages=existing["pages"] or 0,
                           is_scanned=bool(existing["is_scanned"]),
                           quality=existing["quality"], ocr_pages=existing["ocr_pages"] or 0,
                           method=existing["method"], pdf_deleted=deleted,
                           already_stored=True,
                           needs_review=existing["quality"] != "ok")

    docs_cfg = documents_config()["ocr"]
    max_ocr_pages = int(llm_config().get("ocr_max_pages_per_document", 10))
    doc = extract(
        got.path, ocr=ocr, dpi=int(docs_cfg["dpi"]), max_ocr_pages=max_ocr_pages,
    )
    now = datetime.now(IST)

    document_id = None
    if conn is not None:
        document_id = insert(conn, DocumentRow(
            url=url, sha256=got.sha256, size_bytes=got.size_bytes,
            pages=doc.pages, text=doc.text, is_scanned=doc.is_scanned,
            quality=doc.quality, page_report=doc.page_report,
            rejected_text=doc.rejected_text, ocr_pages=doc.ocr_pages,
            method=doc.method, extracted_at=now,
            event_id=event_id, raw_announcement_id=raw_announcement_id,
        ))
        # Commit the text before touching the file. If the process dies here the PDF is
        # still on disk and `store.undeleted()` will surface it; the reverse order would
        # lose the filing.
        conn.commit()

    deleted = _delete_downloaded(got.path, work_dir)
    if conn is not None and document_id is not None and deleted:
        mark_pdf_deleted(conn, document_id, datetime.now(IST))
        conn.commit()

    return Outcome(
        ok=True, url=url, sha256=got.sha256, document_id=document_id,
        pages=doc.pages, chars=len(doc.text.strip()), is_scanned=doc.is_scanned,
        quality=doc.quality, ocr_pages=doc.ocr_pages,
        method=doc.method, pdf_deleted=deleted,
        # §5.5's manual-review queue is `quality <> 'ok'`, replacing the old char-count
        # `is_scanned` gate - which a garbled-but-plentiful text layer could pass (WORKLOG,
        # 24 Sep 2026 evening).
        needs_review=doc.quality != "ok",
    )


def verify_stored(url: str, sha256: str, *, work_dir: Path,
                  fetcher: PdfFetcher | None = None) -> bool:
    """Re-download and confirm the bytes still hash to what we stored (§5.5).

    Used when a later re-run wants the PDF back. A mismatch means the company replaced the
    attachment at the same URL, so the stored text no longer describes what is published -
    which is a finding, not a retry.
    """
    fetcher = fetcher or PdfFetcher()
    got = fetcher.fetch(url, work_dir)
    if not got.ok or got.path is None:
        return False
    try:
        return sha256_of(got.path) == sha256
    finally:
        _delete_downloaded(got.path, work_dir)
