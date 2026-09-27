-- 0014_reconcile_window.sql - reconcile's report window and catch-all-only count (§5.11).
-- A report covers filings since the previous report, not a fixed ±1 day (27 Sep 2026), so
-- each day records where its window started. catch_all_only_symbols lists the order filers
-- the API holds only under a catch-all category (General Updates / Updates / Press
-- Release): likely the same filing labelled differently, but not counted as a match.
ALTER TABLE reconcile_days ADD COLUMN IF NOT EXISTS window_from date;
ALTER TABLE reconcile_days ADD COLUMN IF NOT EXISTS catch_all_only_symbols text[];
