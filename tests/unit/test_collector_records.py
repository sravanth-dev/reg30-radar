"""Record parsing: identity, hashing and timestamps. No network, no database.

These are the decisions that are expensive to get wrong. A hash that is not stable turns
every re-poll into a fake revision; an identity key built from the wrong fields turns a
genuine correction into a separate filing, or hides it entirely.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from reg30_radar.collector.records import (
    IST, parse_ts, payload_hash, source_id, to_raw,
)

# Shaped like the records Spike A documented (ARCHITECTURE Sect.5.1).
SAMPLE = {
    "seq_id": 106784063,
    "symbol": "BEL",
    "sm_name": "Bharat Electronics Limited",
    "sm_isin": "INE263A01024",
    "smIndustry": "Aerospace & Defense",
    "an_dt": "18-Sep-2026 10:17:50",
    "exchdisstime": "18-Sep-2026 10:17:52",
    "desc": "Bagging/Receiving of orders/contracts",
    "attchmntText": "BEL bags order worth Rs. 220.66 Crore",
    "attchmntFile": "https://nsearchives.nseindia.com/corporate/BEL_18092026.pdf",
    "old_new": None,
}


def test_timestamps_are_timezone_aware_ist():
    ts = parse_ts("18-Sep-2026 10:17:50")
    assert ts is not None
    # CLAUDE.md allows timezone-aware datetimes only.
    assert ts.tzinfo is not None
    assert ts.utcoffset() == timedelta(hours=5, minutes=30)
    assert ts == datetime(2026, 9, 18, 10, 17, 50, tzinfo=IST)


def test_unparseable_timestamp_is_null_not_a_guess():
    # Never guess a number, and never guess a date either: a wrong day-0 is worse than a
    # missing one, because it is silent.
    assert parse_ts("") is None
    assert parse_ts(None) is None
    assert parse_ts("not a date") is None
    assert parse_ts("2026-09-18T10:17:50") is None


def test_payload_hash_is_stable_across_key_order():
    reordered = dict(reversed(list(SAMPLE.items())))
    assert payload_hash(SAMPLE) == payload_hash(reordered)


def test_payload_hash_changes_when_content_changes():
    amended = SAMPLE | {"attchmntText": "Corrected: Rs. 220.66 Crore"}
    assert payload_hash(amended) != payload_hash(SAMPLE)


def test_source_id_prefers_seq_id():
    assert source_id(SAMPLE) == "106784063"


def test_source_id_falls_back_without_seq_id():
    # seq_id is null on 193 of BEL's 1,035 records, all pre-2015 (Spike A).
    older = SAMPLE | {"seq_id": None}
    assert source_id(older) == "BEL:18-Sep-2026 10:17:50"


def test_fallback_source_id_survives_a_revision():
    # Sect.5.3: the synthesised key must use fields that do NOT change on a revision, so a
    # correction lands as a new revision of the same filing rather than a separate one.
    original = SAMPLE | {"seq_id": None}
    corrected = original | {
        "attchmntText": "Corrected text",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/BEL_18092026_rev.pdf",
    }
    assert source_id(corrected) == source_id(original)
    assert payload_hash(corrected) != payload_hash(original)


def test_to_raw_maps_the_fields_slice_1_stores():
    row = to_raw(SAMPLE)
    assert row.source == "nse"
    assert row.symbol == "BEL"
    assert row.company == "Bharat Electronics Limited"
    assert row.isin == "INE263A01024"
    assert row.industry == "Aerospace & Defense"
    assert row.category_raw == "Bagging/Receiving of orders/contracts"
    assert row.attachment_url.endswith(".pdf")
    assert row.exchange_ts < row.disseminated_ts      # filed before disseminated
    assert row.payload is SAMPLE


def test_to_raw_tolerates_missing_fields():
    # smIndustry was None for HILINFRA (Spike A), so absent fields must not raise.
    sparse = {"seq_id": 1, "symbol": "X", "an_dt": "18-Sep-2026 10:17:50"}
    row = to_raw(sparse)
    assert row.isin is None and row.industry is None and row.attachment_url is None
    assert row.exchange_ts is not None
