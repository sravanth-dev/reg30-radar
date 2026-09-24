-- 0005_llm_calls.sql - one row per LLM/vision call (ARCHITECTURE Sect.6, Sect.7).
--
-- Pulled forward from Slice 5 to back the §5.5 Part B vision-OCR step
-- (src/tradebot/llm/client.py, src/tradebot/documents/ocr.py). Every provider call in this
-- project goes through that one client, and every one of its calls lands a row here,
-- whatever the call was for - `purpose` says which (today: only "ocr").

CREATE TABLE IF NOT EXISTS llm_calls (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                timestamptz NOT NULL,

    tier              text        NOT NULL,   -- "ocr" today; "t1"/"t2" from Slice 5
    model             text        NOT NULL,
    prompt_version    text        NOT NULL,
    purpose           text        NOT NULL,

    -- The `events` table arrives in Slice 2 (see migrations/0003_documents.sql's note on
    -- the same point); this stays a plain nullable column until then.
    event_id          bigint,

    in_tokens         integer     NOT NULL DEFAULT 0,
    cached_tokens     integer     NOT NULL DEFAULT 0,
    out_tokens        integer     NOT NULL DEFAULT 0,

    -- Computed from config/llm.yaml's price table, never estimated (Sect.6).
    cost_usd          numeric(12,6) NOT NULL DEFAULT 0,

    batch_id          text,       -- set when the call went through the Batch API (Slice 5)
    latency_ms        integer,
    status            text        NOT NULL,   -- "ok" | "error"
    escalation_reason text,
    error             text
);

CREATE INDEX IF NOT EXISTS llm_calls_ts_idx ON llm_calls (ts);
CREATE INDEX IF NOT EXISTS llm_calls_purpose_ts_idx ON llm_calls (purpose, ts);
