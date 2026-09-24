-- 0003_documents.sql - the document pipeline's table (ARCHITECTURE Sect.5.5, Sect.7).
--
-- Holds the extracted text of a filing's PDF, and the evidence that the PDF itself is gone.
-- D8 deletes the file after extraction because disk is the binding constraint on the CX22
-- (Sect.3); what survives is the text, the URL and the hash, which Sect.8 keeps so a better
-- parser or prompt can be re-run over the whole backfill without re-downloading from NSE.

CREATE TABLE IF NOT EXISTS documents (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Sect.7 names event_id. The `events` table arrives in Slice 2, so the foreign key
    -- cannot be declared yet and this stays a plain nullable column until then.
    -- raw_announcement_id is what the pipeline can actually key on today, because
    -- raw_announcements exists and carries attachment_url.
    event_id             bigint,
    raw_announcement_id  bigint REFERENCES raw_announcements (id),

    url              text        NOT NULL,

    -- The hash of the file as downloaded. Unique because Sect.5.3 dedups on exactly this:
    -- a company re-filing the same PDF under a second category is one document, not two.
    -- It is also how the Sect.5.5 re-download check confirms a later fetch got the same
    -- bytes as the extraction that is already stored.
    sha256           text        NOT NULL UNIQUE,
    size_bytes       bigint,

    pages            integer,
    text             text,

    -- Little or no extractable text means an image scan. Sect.5.5 sends these to manual
    -- review; whether they get OCR or a vision model is still Open (Sect.11), and Spike D
    -- counts them by market-cap band to settle that with a measurement.
    is_scanned       boolean     NOT NULL DEFAULT false,

    method           text        NOT NULL,
    extracted_at     timestamptz NOT NULL,

    -- Null means the PDF is still on disk, which after a successful run should never
    -- happen. It is recorded rather than assumed so a D8 violation is visible in a query
    -- instead of only in free disk space.
    pdf_deleted_at   timestamptz
);

CREATE INDEX IF NOT EXISTS documents_event_idx ON documents (event_id);
CREATE INDEX IF NOT EXISTS documents_raw_idx ON documents (raw_announcement_id);

-- The two queues a human or a later slice reads: scans that need review, and anything whose
-- PDF outlived its extraction.
CREATE INDEX IF NOT EXISTS documents_scanned_idx ON documents (extracted_at) WHERE is_scanned;
CREATE INDEX IF NOT EXISTS documents_undeleted_idx
    ON documents (extracted_at) WHERE pdf_deleted_at IS NULL;
