"""Writing polls and filings to Postgres.

`raw_announcements` is append-only and unique on (source, source_id, payload_sha256).
Everything below follows from that: inserts never update, conflicts are expected and
cheap, and a revision is a new row rather than an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg.types.json import Jsonb

from tradebot.collector.records import RawAnnouncement

_INSERT = """
insert into raw_announcements (
    source, source_id, payload_sha256, revision,
    exchange_ts, disseminated_ts, first_seen_at,
    symbol, company, isin, industry, category_raw, headline, attachment_url, payload,
    collected_via
)
values (
    %(source)s, %(source_id)s, %(payload_sha256)s,
    -- A changed payload under an existing source_id is revision 2, 3, ... rather than a
    -- silently dropped correction (Sect.5.3). Computed in the statement so it stays
    -- correct without reading the row first.
    (select coalesce(max(revision), 0) + 1
       from raw_announcements
      where source = %(source)s and source_id = %(source_id)s),
    %(exchange_ts)s, %(disseminated_ts)s, %(first_seen_at)s,
    %(symbol)s, %(company)s, %(isin)s, %(industry)s,
    %(category_raw)s, %(headline)s, %(attachment_url)s, %(payload)s, %(collected_via)s
)
on conflict (source, source_id, payload_sha256) do nothing
returning id, revision
"""


@dataclass
class InsertOutcome:
    inserted: int
    duplicates: int
    revisions: int


COLLECTED_VIA = ("live", "gap", "catchup", "backfill")


def insert_announcements(
    conn, rows: list[RawAnnouncement], first_seen_at: datetime, *, collected_via: str
) -> InsertOutcome:
    """Insert every row that is not already stored, byte for byte.

    `collected_via` records whether a live poll saw the row (migration 0018): only then is
    `first_seen_at` a real-time observation.

    `first_seen_at` is passed in rather than read from the clock here, so that one poll's
    rows all carry the same value - they were all first seen in the same poll, and giving
    them microsecond-apart timestamps would imply a precision we do not have.
    """
    if collected_via not in COLLECTED_VIA:
        raise ValueError(f"collected_via must be one of {COLLECTED_VIA}, got {collected_via!r}")
    inserted = duplicates = revisions = 0
    for row in rows:
        result = conn.execute(
            _INSERT,
            {
                "source": row.source,
                "source_id": row.source_id,
                "payload_sha256": row.payload_sha256,
                "exchange_ts": row.exchange_ts,
                "disseminated_ts": row.disseminated_ts,
                "first_seen_at": first_seen_at,
                "symbol": row.symbol,
                "company": row.company,
                "isin": row.isin,
                "industry": row.industry,
                "category_raw": row.category_raw,
                "headline": row.headline,
                "attachment_url": row.attachment_url,
                "payload": Jsonb(row.payload),
                "collected_via": collected_via,
            },
        ).fetchone()
        if result is None:
            duplicates += 1
        else:
            inserted += 1
            if result[1] > 1:
                revisions += 1
    return InsertOutcome(inserted, duplicates, revisions)


def record_poll(
    conn,
    *,
    source: str,
    checked_at: datetime,
    ok: bool,
    error: str | None = None,
    http_status: int | None = None,
    latency_ms: int | None = None,
    records_returned: int | None = None,
    new_records: int | None = None,
    overflow: bool = False,
) -> None:
    """One row per poll, success or failure (Sect.7)."""
    conn.execute(
        """
        insert into source_health (
            source, checked_at, ok, error,
            http_status, latency_ms, records_returned, new_records, overflow
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (source, checked_at, ok, error, http_status, latency_ms,
         records_returned, new_records, overflow),
    )


def known_hashes(conn, source: str, limit: int = 5000) -> set[str]:
    """The most recent payload hashes, used to tell a new filing from a re-poll in memory.

    The database is still the authority - the unique constraint is what actually prevents
    duplicates. This set exists only so the collector can count *new* records per poll,
    which is what the overflow check reads.
    """
    rows = conn.execute(
        """
        select payload_sha256 from raw_announcements
        where source = %s
        order by id desc
        limit %s
        """,
        (source, limit),
    ).fetchall()
    return {r[0] for r in rows}
