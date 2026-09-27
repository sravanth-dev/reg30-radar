-- 0011_backfill_events.sql - order events and their study results (ARCHITECTURE §5.3,
-- §5.10, §5.11, §6's state machine; src/tradebot/backfill/events.py, recheck.py, report.py).

-- One row per real-world order: repeat filings of the same order merged on §5.3's exact
-- keys (same attachment SHA-256, or same ISIN and value_inr), never on a similar headline.
CREATE TABLE IF NOT EXISTS backfill_events (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    isin                  text        NOT NULL,
    symbol                text        NOT NULL,
    event_ts              timestamptz NOT NULL,     -- earliest exchange timestamp (§5.3)
    raw_ids               bigint[]    NOT NULL,     -- every filing merged into the event
    primary_raw_id        bigint      NOT NULL,     -- the earliest verified filing
    bucket                text        NOT NULL,
    value_inr             numeric(20,2),
    currency              text,
    company_is_recipient  boolean,
    recipient_source      text,                     -- "extraction" or "category"
    stage                 text,
    awarding_entity       text,
    execution_period_raw  text,
    -- §6: extracted -> calculated -> verified | recheck_pending -> verified | needs_review
    state                 text        NOT NULL,
    state_log             jsonb       NOT NULL DEFAULT '[]'::jsonb,
    ttm_revenue_inr       numeric(20,2),
    ttm_basis             text,
    value_to_mcap         numeric(12,6),
    recheck_value_inr     numeric(20,2),
    recheck_recipient     boolean,
    UNIQUE (primary_raw_id)
);
CREATE INDEX IF NOT EXISTS backfill_events_isin_idx ON backfill_events (isin, event_ts);

-- One row per event per study run: everything event_study.measure() recorded, kept so a
-- verdict can be audited event by event after the fact.
CREATE TABLE IF NOT EXISTS event_results (
    run_at    timestamptz NOT NULL,
    event_id  bigint      NOT NULL REFERENCES backfill_events (id),
    result    jsonb       NOT NULL,
    PRIMARY KEY (run_at, event_id)
);

-- Categories the map does not list (§5.4, §7): logged for review, treated as other news.
CREATE TABLE IF NOT EXISTS unknown_categories (
    category_raw  text PRIMARY KEY,
    first_seen    timestamptz NOT NULL,
    count         integer     NOT NULL
);
