"""Write extracted documents to Postgres. Plain SQL, matching the collector's store.

One row per distinct PDF, keyed on the file's SHA-256. Sect.5.3 dedups on exactly that hash,
so a company re-filing the same attachment under a second category lands on the existing row
instead of creating a near-duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from psycopg.types.json import Jsonb


@dataclass
class DocumentRow:
    url: str
    sha256: str
    size_bytes: int
    pages: int
    text: str
    is_scanned: bool
    method: str
    extracted_at: datetime
    quality: str = "ok"
    page_report: list = field(default_factory=list)
    rejected_text: str = ""
    ocr_pages: int = 0
    pdf_deleted_at: datetime | None = None
    event_id: int | None = None
    raw_announcement_id: int | None = None


INSERT = """
insert into documents (
    event_id, raw_announcement_id, url, sha256, size_bytes,
    pages, text, is_scanned, method, extracted_at, pdf_deleted_at,
    quality, page_report, rejected_text, ocr_pages
) values (
    %(event_id)s, %(raw_announcement_id)s, %(url)s, %(sha256)s, %(size_bytes)s,
    %(pages)s, %(text)s, %(is_scanned)s, %(method)s, %(extracted_at)s, %(pdf_deleted_at)s,
    %(quality)s, %(page_report)s, %(rejected_text)s, %(ocr_pages)s
)
on conflict (sha256) do nothing
returning id
"""


def insert(conn, row: DocumentRow) -> int | None:
    """Insert one document. Returns its id, or None when the hash was already stored.

    `do nothing` rather than `do update` is deliberate: the text is derived from immutable
    bytes, so a second sighting of the same hash has nothing new to say. Re-extracting with
    a better method is a separate, explicit operation, not a side effect of re-downloading.
    """
    params = dict(row.__dict__)
    params["page_report"] = Jsonb(params["page_report"])
    got = conn.execute(INSERT, params).fetchone()
    return got[0] if got else None


def find_by_sha256(conn, sha256: str) -> dict | None:
    got = conn.execute(
        "select id, url, pages, is_scanned, method, extracted_at, pdf_deleted_at,"
        " quality, ocr_pages"
        " from documents where sha256 = %s",
        (sha256,),
    ).fetchone()
    if not got:
        return None
    cols = ("id", "url", "pages", "is_scanned", "method", "extracted_at", "pdf_deleted_at",
            "quality", "ocr_pages")
    return dict(zip(cols, got))


def get_text(conn, document_id: int) -> str:
    """The kept text for one document. Used by `orders/run.py` after `process_url`, since
    `Outcome` deliberately doesn't carry the full text - this covers the dedup path too
    (`Outcome.already_stored`), where the text belongs to a document row from an earlier
    filing that happened to share the same PDF bytes.
    """
    row = conn.execute("select text from documents where id = %s", (document_id,)).fetchone()
    return row[0] if row and row[0] else ""


def get_page_report(conn, document_id: int) -> list:
    """The per-page report for one document: which pages came from vision OCR (§5.5
    Part C) is what decides whether a value read from it needs a second read."""
    row = conn.execute("select page_report from documents where id = %s",
                       (document_id,)).fetchone()
    return row[0] if row and row[0] else []


def mark_pdf_deleted(conn, document_id: int, when: datetime) -> None:
    conn.execute(
        "update documents set pdf_deleted_at = %s where id = %s and pdf_deleted_at is null",
        (when, document_id),
    )


def undeleted(conn, limit: int = 50) -> list[dict]:
    """Documents whose PDF is recorded as still on disk - a D8 violation queue.

    After a successful run this should always be empty. It is a query rather than a log line
    so the answer survives a restart.
    """
    rows = conn.execute(
        "select id, url, sha256, extracted_at from documents"
        " where pdf_deleted_at is null order by extracted_at limit %s",
        (limit,),
    ).fetchall()
    return [dict(zip(("id", "url", "sha256", "extracted_at"), r)) for r in rows]


def needs_review(conn, limit: int = 50) -> list[dict]:
    """Documents whose quality is not `ok` - the §5.5 manual-review queue.

    Replaces the earlier char-count `is_scanned` gate, which a garbled-but-plentiful text
    layer could pass (WORKLOG, 24 Sep 2026 evening).
    """
    rows = conn.execute(
        "select id, url, sha256, quality, ocr_pages, extracted_at from documents"
        " where quality <> 'ok' order by extracted_at limit %s",
        (limit,),
    ).fetchall()
    cols = ("id", "url", "sha256", "quality", "ocr_pages", "extracted_at")
    return [dict(zip(cols, r)) for r in rows]
