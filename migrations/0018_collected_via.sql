-- 0018_collected_via.sql - how each raw row was collected (GATE 1 audit, D30).
--
-- first_seen_at means "when we first saw it", and that is only a live observation when a
-- live poll saw it. A row recovered after an outage (a gap query or a catch-up) carries the
-- recovery time, which is honest but not real-time; the forward-collected sample (D23)
-- must be able to tell the two apart. Values: live, gap, catchup, backfill. Rows stored
-- before this migration are null: they came from the live poll, its gap query or a manual
-- catch-up, which cannot be told apart afterwards (raw_announcements is append-only, so
-- they are never back-filled).

ALTER TABLE raw_announcements ADD COLUMN IF NOT EXISTS collected_via text;
