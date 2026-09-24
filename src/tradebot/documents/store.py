"""Write extracted documents to Postgres. Plain SQL, matching the collector's store.

One row per distinct PDF, keyed on the file's SHA-256. Sect.5.3 dedups on exactly that hash,
so a company re-filing the same attachment under a second category lands on the existing row
instead of creating a near-duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
    pdf_deleted_at: datetime | None = None
    event_id: int | None = None
    raw_announcement_id: int | None = None


INSERT = """
insert into documents (
    event_id, raw_announcement_id, url, sha256, size_bytes,
    pages, text, is_scanned, method, extracted_at, pdf_deleted_at
) values (
    %(event_id)s, %(raw_announcement_id)s, %(url)s, %(sha256)s, %(size_bytes)s,
    %(pages)s, %(text)s, %(is_scanned)s, %(method)s, %(extracted_at)s, %(pdf_deleted_at)s
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
    got = conn.execute(INSERT, row.__dict__).fetchone()
    return got[0] if got else None


def find_by_sha256(conn, sha256: str) -> dict | None:
    got = conn.execute(
        "select id, url, pages, is_scanned, method, extracted_at, pdf_deleted_at"
        " from documents where sha256 = %s",
        (sha256,),
    ).fetchone()
    if not got:
        return None
    cols = ("id", "url", "pages", "is_scanned", "method", "extracted_at", "pdf_deleted_at")
    return dict(zip(cols, got))


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
