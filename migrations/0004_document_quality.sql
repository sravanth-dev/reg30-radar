-- 0004_document_quality.sql - per-page quality outcome for the §5.5 document pipeline.
--
-- Replaces the char-count `is_scanned` heuristic's job of gating manual review: that
-- heuristic passed a genuinely garbled page (WORKLOG, 24 Sep 2026 evening - an invisible
-- OCR text layer with a broken font produced plenty of characters, just wrong ones). The
-- new gate is `quality <> 'ok'`, decided page by page in `documents/quality.py` and
-- `documents/text.py`. `is_scanned` stays as a column - redefined as "any page is a
-- full-page image", a fact about the file's layout, not a guess about its text.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS quality        text NOT NULL DEFAULT 'ok',
    -- "ok" (every page's kept text passed assessment), "partial" (some pages did not),
    -- "unreadable" (none did). §5.5's manual-review queue is `quality <> 'ok'`.

    ADD COLUMN IF NOT EXISTS page_report     jsonb,
    -- One entry per page: verdict, method, source, chars, image_fraction, glyphless_font,
    -- cid_ratio, common_word_ratio, ocr_attempted. Lets a quality call be audited without
    -- re-downloading the PDF, which D8 has already deleted by the time anyone looks.

    ADD COLUMN IF NOT EXISTS rejected_text   text,
    -- The best (still unusable) attempt's text for every page that did not assess "ok".
    -- Kept out of `text` so it never reaches the parser or a model, kept here so nothing
    -- is silently thrown away.

    ADD COLUMN IF NOT EXISTS ocr_pages       integer NOT NULL DEFAULT 0;
    -- Pages routed to vision OCR, whether or not Part B was configured to answer (§5.5).

CREATE INDEX IF NOT EXISTS documents_quality_idx ON documents (extracted_at)
    WHERE quality <> 'ok';
