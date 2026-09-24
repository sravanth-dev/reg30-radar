-- 0006_order_extractions.sql - one row per in-scope filing, order-related or not
-- (ARCHITECTURE.md §5.4, §5.6; src/tradebot/orders/).
--
-- Not §7's `orders` table: that one hangs off `events` (Slice 2) and carries the full §6
-- state machine, and both are still to come. This is what makes src/tradebot/orders/
-- idempotent and resumable - a filing that already has a row here is never downloaded or
-- sent to the LLM again - and it is what both the --date batch run and the --follow live
-- worker read and write, since they share one processing core.

CREATE TABLE IF NOT EXISTS order_extractions (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    raw_announcement_id   bigint NOT NULL UNIQUE REFERENCES raw_announcements (id),
    document_id           bigint REFERENCES documents (id),

    bucket                text        NOT NULL,   -- order_win / order_candidate / red_flag /
                                                    -- catch_all / out_of_scope (router/orders.py)
    order_related         boolean     NOT NULL,
    relevance_reason      text        NOT NULL,

    -- How the value (if any) was obtained. "none": no value found by either path.
    -- "not_order": the LLM triage on a catch_all filing decided it isn't one after all.
    path                  text        NOT NULL DEFAULT 'none',

    consideration_raw     text,
    value_span            text,
    value_inr             numeric(20,2),
    provenance_ok         boolean,

    currency              text,
    gst_inclusive         boolean,
    execution_period_raw  text,
    awarding_entity       text,
    company_is_recipient  boolean,
    stage                 text,

    -- verified / needs_review / not_order / download_failed / pending_llm. This is the
    -- retry queue: download_failed and pending_llm rows are picked up again by a later
    -- run or follow cycle, everything else is a finished outcome.
    review_status         text        NOT NULL,

    llm_cost_usd          numeric(12,6) NOT NULL DEFAULT 0,
    attempts              integer     NOT NULL DEFAULT 0,
    last_error            text,

    processed_at          timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS order_extractions_pending_idx ON order_extractions (processed_at)
    WHERE review_status IN ('download_failed', 'pending_llm');
CREATE INDEX IF NOT EXISTS order_extractions_review_idx ON order_extractions (review_status);
