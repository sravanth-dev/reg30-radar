"""Turning one API record into one raw row. Pure functions: no network, no database.

Everything here is testable from a fixture, which matters because these are the decisions
that are expensive to get wrong - the identity key and the payload hash together decide
whether a re-poll is a duplicate, a revision, or a new filing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

SOURCE = "nse"

# "18-Sep-2026 10:17:50" - the only shape seen across 1,035 BEL records in Spike A.
_TS_FORMAT = "%d-%b-%Y %H:%M:%S"


@dataclass(frozen=True)
class RawAnnouncement:
    source: str
    source_id: str
    payload_sha256: str
    exchange_ts: datetime | None
    disseminated_ts: datetime | None
    symbol: str | None
    company: str | None
    isin: str | None
    industry: str | None
    category_raw: str | None
    headline: str | None
    attachment_url: str | None
    payload: dict


def parse_ts(value) -> datetime | None:
    """Parse an NSE timestamp into a timezone-aware IST datetime.

    Returns None rather than guessing when the value is absent or malformed. A naive
    datetime is never returned: CLAUDE.md allows timezone-aware only, and a naive value
    that silently means IST is the kind of thing that survives until it reaches a
    point-in-time calculation and quietly shifts a day-0.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), _TS_FORMAT).replace(tzinfo=IST)
    except ValueError:
        return None


def payload_hash(record: dict) -> str:
    """SHA-256 over the record, canonicalised so key order cannot change the hash.

    The hash is half of the uniqueness key, so an unstable hash would turn every re-poll
    of an unchanged filing into a fresh "revision" row.
    """
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_id(record: dict) -> str:
    """A stable identifier for this filing.

    `seq_id` is the natural choice but is null on older records - 193 of BEL's 1,035, all
    pre-2015 (Spike A) - so it cannot be relied on alone across the archive. The fallback
    is built from symbol and filing timestamp only, deliberately: Sect.5.3 requires a
    synthesised key to use fields that do NOT change on a revision, and the description and
    attachment are exactly the fields a correction rewrites.
    """
    seq = record.get("seq_id")
    if seq not in (None, "", "null"):
        return str(seq)
    return f"{record.get('symbol') or '?'}:{record.get('an_dt') or '?'}"


def to_raw(record: dict) -> RawAnnouncement:
    return RawAnnouncement(
        source=SOURCE,
        source_id=source_id(record),
        payload_sha256=payload_hash(record),
        exchange_ts=parse_ts(record.get("an_dt")),
        disseminated_ts=parse_ts(record.get("exchdisstime")),
        symbol=_clean(record.get("symbol")),
        company=_clean(record.get("sm_name")),
        isin=_clean(record.get("sm_isin")),
        industry=_clean(record.get("smIndustry")),
        category_raw=_clean(record.get("desc")),
        headline=_clean(record.get("attchmntText")),
        attachment_url=_clean(record.get("attchmntFile")),
        payload=record,
    )


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
