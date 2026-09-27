-- 0007_market_data.sql - daily archive data for the backfill (ARCHITECTURE §5.2, §5.9, §7;
-- src/tradebot/market/). Loaded into tradebot_backfill; the live database carries the same
-- (empty) tables so one schema serves both.
--
-- None of these is append-only: each is derived from a published archive file and can be
-- reloaded from it, so reloading a day replaces that day's rows.

-- One row per ISIN: the identity behind any symbol (§5.2). `industry` is filled later from
-- the announcements API's smIndustry (§5.8's bank/NBFC/insurer exclusion).
CREATE TABLE IF NOT EXISTS instruments (
    isin             text PRIMARY KEY,
    nse_symbol       text NOT NULL,
    nse_series       text NOT NULL,
    name             text,
    instrument_type  text,
    industry         text,
    first_seen       date NOT NULL,
    last_seen        date NOT NULL
);

-- Every symbol an ISIN traded under, with dates. A company that changes symbol mid-window
-- keeps one ISIN; the backfill's symbol= queries need all of its symbols (§5.1, Verify).
CREATE TABLE IF NOT EXISTS instrument_symbols (
    isin        text NOT NULL,
    symbol      text NOT NULL,
    series      text NOT NULL,
    first_seen  date NOT NULL,
    last_seen   date NOT NULL,
    PRIMARY KEY (isin, symbol, series)
);
CREATE INDEX IF NOT EXISTS instrument_symbols_symbol_idx ON instrument_symbols (symbol);

-- Unadjusted daily prices (§5.9). prev_close is NOT corporate-action adjusted (Spike B), so
-- returns are never chained through it. corp_ind is the pd file's ex-date flag, which
-- drives §5.11's capital-action exclusion; band_hit ('H'/'L') is from the bh file.
CREATE TABLE IF NOT EXISTS prices (
    trade_date   date NOT NULL,
    isin         text NOT NULL,
    symbol       text NOT NULL,
    series       text NOT NULL,
    open         numeric(20,2),
    high         numeric(20,2),
    low          numeric(20,2),
    close        numeric(20,2),
    prev_close   numeric(20,2),
    volume       bigint,
    corp_ind     text,
    band_hit     text,
    PRIMARY KEY (trade_date, isin)
);
CREATE INDEX IF NOT EXISTS prices_isin_date_idx ON prices (isin, trade_date);

CREATE TABLE IF NOT EXISTS index_prices (
    trade_date  date NOT NULL,
    index_name  text NOT NULL,
    close       numeric(20,2) NOT NULL,
    PRIMARY KEY (trade_date, index_name)
);

-- Plain rupees, as the mcap file prints them (§5.9).
CREATE TABLE IF NOT EXISTS market_caps (
    trade_date  date NOT NULL,
    isin        text NOT NULL,
    mcap_inr    numeric(20,2) NOT NULL,
    PRIMARY KEY (trade_date, isin)
);
CREATE INDEX IF NOT EXISTS market_caps_isin_date_idx ON market_caps (isin, trade_date);

-- The PR bundle's announcement report (`an`), one row per filing line. It is a *report*
-- covering filings disseminated since the previous one (§5.1), so report_date is not the
-- filing date. Used for per-day reconciliation (§5.11) and the pre-download event count.
CREATE TABLE IF NOT EXISTS bundle_announcements (
    report_date  date    NOT NULL,
    line_no      integer NOT NULL,
    symbol       text    NOT NULL,
    body         text    NOT NULL,
    PRIMARY KEY (report_date, line_no)
);
CREATE INDEX IF NOT EXISTS bundle_announcements_symbol_idx
    ON bundle_announcements (symbol, report_date);

-- The past-date trading calendar (D27) and the loader's checkpoint in one: a day is a
-- trading day when its UDiFF bhavcopy exists. trading_day is null while a day could not be
-- decided (an error rather than a clean 404), which is what makes the loader retry it.
CREATE TABLE IF NOT EXISTS archive_days (
    day           date PRIMARY KEY,
    udiff_status  integer,
    pr_status     integer,
    trading_day   boolean,
    loaded_at     timestamptz NOT NULL,
    note          text
);

-- Generic per-job checkpoints for the backfill's other stages (§7).
CREATE TABLE IF NOT EXISTS backfill_checkpoints (
    job      text NOT NULL,
    key      text NOT NULL,
    done_at  timestamptz NOT NULL,
    detail   jsonb,
    PRIMARY KEY (job, key)
);
