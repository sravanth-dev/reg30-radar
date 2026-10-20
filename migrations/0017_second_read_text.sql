-- 0017_second_read_text.sql - keep what §5.5 Part C's second read actually said, so a
-- disagreement can be reviewed beside the first transcript instead of taken on trust.
-- Text only: the PDF and the page image are still deleted straight after (D8).

ALTER TABLE order_extractions ADD COLUMN IF NOT EXISTS second_read_text text;
