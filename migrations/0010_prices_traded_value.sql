-- 0010_prices_traded_value.sql - the bhavcopy's traded value (TtlTrfVal, rupees), for
-- Sravanth's per-event liquidity field: median daily traded value over the previous 60
-- trading days (config/backfill.yaml, universe.notes rule 3). Taken from the file rather
-- than computed as close x volume, which is not the same number on a day with a range.
ALTER TABLE prices ADD COLUMN IF NOT EXISTS traded_value numeric(20,2);
