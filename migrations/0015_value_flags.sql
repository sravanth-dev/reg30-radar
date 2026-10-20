-- 0015_value_flags.sql - what a stored value is, not only what it is (D32, 20 Oct 2026).
--
-- "over Rs 5,400 crore" is stored as 5,400 crore and must stay recognisable as a lower
-- bound; a range keeps its high end beside the low one it is valued at; a converted USD
-- figure stays marked as converted. units/money.py has always computed these flags, but
-- nothing kept them, so a reader of order_extractions could not tell a stated value from a
-- bound. ARCHITECTURE §7's `orders` table always had a `value_flags` column.

ALTER TABLE order_extractions ADD COLUMN IF NOT EXISTS value_flags text[];
ALTER TABLE order_extractions ADD COLUMN IF NOT EXISTS value_high_inr numeric(20,2);

-- Carried onto the event from its primary filing, for the study's per-event CSV.
ALTER TABLE backfill_events ADD COLUMN IF NOT EXISTS value_flags text[];
