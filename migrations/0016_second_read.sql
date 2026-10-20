-- 0016_second_read.sql - §5.5 Part C: a value read from this pipeline's own vision OCR
-- needs a second, independent read that agrees before it counts as verified
-- (src/tradebot/extractor/part_c.py, backfill/vision_check.py; AUDIT.md §3).
--
-- second_read:      pending | agrees | disagrees | unavailable (null: not vision-sourced)
-- second_read_inr:  the value that read was about, so a later change of value needs a new one

ALTER TABLE order_extractions ADD COLUMN IF NOT EXISTS second_read text;
ALTER TABLE order_extractions ADD COLUMN IF NOT EXISTS second_read_inr numeric(20,2);
