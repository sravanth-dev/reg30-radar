-- 0008_backfill_universe.sql - the company-wise backfill's list and its reconciliation
-- (ARCHITECTURE §5.1 as changed 27 Sep 2026, §5.11; src/tradebot/backfill/).

-- The companies the backfill covers, built from Sravanth's criteria applied to one as-of
-- trading day. `excluded_reason` marks a company dropped by a rule that can only be applied
-- after its history is fetched (the smIndustry exclusion); it stays listed so the report
-- can count exclusions instead of hiding them.
CREATE TABLE IF NOT EXISTS backfill_universe (
    isin             text PRIMARY KEY,
    symbol           text NOT NULL,
    series           text NOT NULL,
    name             text,
    mcap_inr         numeric(20,2),
    as_of_date       date NOT NULL,
    industry         text,
    excluded_reason  text
);

-- Exactly which criteria produced the list, and when they were frozen (D22). One row per
-- build; the latest row describes the current list.
CREATE TABLE IF NOT EXISTS backfill_universe_meta (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    built_at    timestamptz NOT NULL,
    frozen_on   date        NOT NULL,
    as_of_date  date        NOT NULL,
    criteria    jsonb       NOT NULL,
    companies   integer     NOT NULL
);

-- Per report date: how many of the listed companies' order filings in the PR bundle were
-- found in their symbol= histories within ±1 day (§5.11). Below 95% is reported, never
-- dropped.
CREATE TABLE IF NOT EXISTS reconcile_days (
    report_date           date PRIMARY KEY,
    bundle_orders         integer NOT NULL,
    bundle_order_symbols  integer NOT NULL,
    matched_symbols       integer NOT NULL,
    coverage              numeric(6,4),
    unmatched_symbols     text[],
    offsets               jsonb,
    acceptable            boolean NOT NULL,
    checked_at            timestamptz NOT NULL
);
