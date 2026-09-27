-- 0013_band_history.sql - reconstructing each stock's price band (2/5/10/20%) on a past
-- date (ARCHITECTURE §11, resolved 27 Sep 2026; src/tradebot/market/bands.py).
--
-- NSE publishes the CURRENT band per symbol (`sec_list.csv`) and a DAILY change log
-- (`eq_band_changes_{ddmmyyyy}.csv`, "From","To") but no historical snapshot. The band on
-- any past date is reconstructed by walking the change log backward from the current
-- snapshot: undo every change dated after the target date, in reverse order.

-- The live band per symbol/series as of one fetch - the anchor reconstruction walks back
-- from. One row per symbol+series; refreshed by re-running the loader.
CREATE TABLE IF NOT EXISTS band_snapshot (
    symbol      text NOT NULL,
    series      text NOT NULL,
    band        text,           -- "2"/"5"/"10"/"20", or null (no band / not found)
    as_of_date  date NOT NULL,
    PRIMARY KEY (symbol, series)
);

-- Every change NSE has published for a symbol, one row per (symbol, series, date). Rows
-- accumulate across loader runs; a symbol with no row in this table for a given date is
-- assumed unchanged on that date (never guessed - see bands.py's reconstruct()).
CREATE TABLE IF NOT EXISTS band_changes (
    symbol       text NOT NULL,
    series       text NOT NULL,
    change_date  date NOT NULL,
    from_band    text,
    to_band      text,
    PRIMARY KEY (symbol, series, change_date)
);

-- Resumable per-day loader state, matching archive_days' shape: a 404 means no changes
-- were published that day (verified, 27 Sep 2026 - two Sundays both gave a clean 404, not
-- an empty 200), so "checked" is recorded either way and the day is never re-fetched.
CREATE TABLE IF NOT EXISTS band_days (
    day         date PRIMARY KEY,
    status      integer,     -- the HTTP status actually seen (200 or 404); null on error
    changes     integer,     -- rows found that day, 0 on a 404 day
    loaded_at   timestamptz NOT NULL
);
