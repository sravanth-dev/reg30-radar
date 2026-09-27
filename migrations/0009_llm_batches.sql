-- 0009_llm_batches.sql - the backfill's Batch API work (CLAUDE.md: backfill LLM work goes
-- through the Batch API; ARCHITECTURE §6; src/tradebot/backfill/batch.py, llm/client.py).

-- One row per submitted batch. estimate_usd is the worst case checked against the cap before
-- submitting; it counts as committed spend until the batch is collected, when each result's
-- real cost lands in llm_calls with this batch_id.
CREATE TABLE IF NOT EXISTS llm_batches (
    batch_id        text PRIMARY KEY,
    purpose         text        NOT NULL,
    model           text        NOT NULL,
    prompt_version  text        NOT NULL,
    submitted_at    timestamptz NOT NULL,
    status          text        NOT NULL,
    requests        integer     NOT NULL,
    estimate_usd    numeric(12,6) NOT NULL,
    input_file_id   text,
    output_file_id  text,
    error_file_id   text,
    collected_at    timestamptz,
    note            text
);

-- Which filing each request in a batch was for, and which attempt it was (§6 allows one
-- retry of an invalid response).
CREATE TABLE IF NOT EXISTS llm_batch_items (
    batch_id             text    NOT NULL REFERENCES llm_batches (batch_id),
    custom_id            text    NOT NULL,
    raw_announcement_id  bigint  NOT NULL,
    attempt              integer NOT NULL,
    applied_at           timestamptz,
    PRIMARY KEY (batch_id, custom_id)
);
CREATE INDEX IF NOT EXISTS llm_batch_items_raw_idx ON llm_batch_items (raw_announcement_id);
