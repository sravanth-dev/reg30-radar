-- 0012_financials.sql - reported revenue per company per period (ARCHITECTURE §5.8, §7;
-- src/tradebot/revenue/). Point-in-time TTM is computed from these rows by revenue/ttm.py.
--
-- Every filed figure is kept, including restatements: `filed_at` is part of the key, so a
-- period re-filed later is a new row, and ttm.py picks the version knowable at each moment.
CREATE TABLE IF NOT EXISTS financials (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    isin           text          NOT NULL,
    period_start   date,
    period_end     date          NOT NULL,
    period_months  integer       NOT NULL,      -- 3, 6, 9 or 12: chosen explicitly (§5.8)
    basis          text          NOT NULL,      -- consolidated | standalone
    revenue_inr    numeric(20,2) NOT NULL,
    filed_at       timestamptz   NOT NULL,
    source_url     text          NOT NULL,
    context_id     text,
    element        text,
    UNIQUE (isin, period_end, period_months, basis, filed_at)
);
CREATE INDEX IF NOT EXISTS financials_isin_idx ON financials (isin, filed_at);
