-- 0002_sheets_sync.sql - watermark and audit trail for the Google Sheets mirror
-- (src/tradebot/sheets/). raw_announcements is never altered by this file; the sync only
-- ever reads it.
--
-- One row per sync run, mirroring source_health's shape (Sect.7): a single mutable row
-- would only answer "did the last sync work?", and this also has to answer "where did it
-- leave off?" so the next run can resume without ever writing a row twice with different
-- content (see src/tradebot/sheets/sync.py's fixed-position design).

CREATE TABLE IF NOT EXISTS sheets_sync (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at       timestamptz NOT NULL DEFAULT now(),
    ok           boolean     NOT NULL,
    rows_written integer     NOT NULL DEFAULT 0,
    first_row    integer,
    last_row     integer,

    -- The watermark. Only rows with ok = true are ever read back (sync.py), so a run that
    -- fails partway leaves the next run to safely redo whatever it could not confirm was
    -- recorded - re-writing the same content to the same sheet rows, never a new position.
    last_raw_id  bigint,

    error        text
);

CREATE INDEX IF NOT EXISTS sheets_sync_run_at_idx ON sheets_sync (run_at DESC);
