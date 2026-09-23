-- 0001_init.sql - the collector's tables only.
--
-- Slice 1 is "collector, raw store, source health" (ARCHITECTURE Sect.10), so this file
-- creates exactly those tables and nothing else. The rest of the Sect.7 data model
-- (events, documents, orders, prices, ...) arrives in the migration for the slice that
-- first writes to it. Creating the whole schema up front would commit us to column
-- choices for code that does not exist yet, and every slice so far has changed at least
-- one assumption it was built on.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Every announcement exactly as the source gave it (Sect.5.1, Sect.7).
CREATE TABLE IF NOT EXISTS raw_announcements (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- `source` is kept even though D26 leaves only NSE, so a second source later needs
    -- no migration.
    source           text        NOT NULL,
    source_id        text        NOT NULL,

    -- The hash is part of the key, not decoration. NSE exposes no revision marker at all
    -- (Spike A), so a correction comes back under the same source_id with amended text.
    -- Keyed on source_id alone, ON CONFLICT DO NOTHING would drop that correction with no
    -- trace; with the hash in the key it lands as a new revision row instead (Sect.5.3).
    payload_sha256   text        NOT NULL,
    revision         integer     NOT NULL DEFAULT 1,

    exchange_ts      timestamptz,
    disseminated_ts  timestamptz,
    first_seen_at    timestamptz NOT NULL,

    symbol           text,
    company          text,
    isin             text,
    industry         text,
    category_raw     text,
    headline         text,
    attachment_url   text,

    payload          jsonb       NOT NULL,

    UNIQUE (source, source_id, payload_sha256)
);

CREATE INDEX IF NOT EXISTS raw_announcements_source_id_idx
    ON raw_announcements (source, source_id);
CREATE INDEX IF NOT EXISTS raw_announcements_exchange_ts_idx
    ON raw_announcements (exchange_ts);
CREATE INDEX IF NOT EXISTS raw_announcements_symbol_idx
    ON raw_announcements (symbol);

-- Append-only is a rule in CLAUDE.md; this makes it a property of the database.
-- A rule that only lives in prose gets broken by the one query written in a hurry.
CREATE OR REPLACE FUNCTION raw_announcements_is_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'raw_announcements is append-only (CLAUDE.md data rules): % is not permitted',
        TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS raw_announcements_no_update_delete ON raw_announcements;
CREATE TRIGGER raw_announcements_no_update_delete
    BEFORE UPDATE OR DELETE ON raw_announcements
    FOR EACH ROW EXECUTE FUNCTION raw_announcements_is_append_only();

-- One row per poll, not one per source (Sect.7): a single mutable row answers "is it up
-- now?" and nothing else, and history is what makes an outage diagnosable afterwards.
CREATE TABLE IF NOT EXISTS source_health (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source           text        NOT NULL,
    checked_at       timestamptz NOT NULL,
    ok               boolean     NOT NULL,
    error            text,

    -- Beyond Sect.7's columns, because the live endpoint returns only the 20 most recent
    -- records. If a poll returns a full page that is entirely new, the page may have
    -- rolled over since the last poll and filings in between are gone for good -
    -- first_seen_at cannot be backfilled (D23). Recording it per poll is what turns that
    -- risk into a measured rate instead of an assumption.
    http_status      integer,
    latency_ms       integer,
    records_returned integer,
    new_records      integer,
    overflow         boolean     NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS source_health_checked_at_idx
    ON source_health (source, checked_at DESC);
CREATE INDEX IF NOT EXISTS source_health_overflow_idx
    ON source_health (checked_at) WHERE overflow;
