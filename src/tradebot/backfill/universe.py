"""The backfill's company list (ARCHITECTURE §5.1, changed 27 Sep 2026).

Built by code from Sravanth's criteria in config/backfill.yaml, applied to the data of the
last trading day on or before `universe.as_of`. Nothing from inside the study year can
reach the selection. A company that later delisted is still in the list, because it was
listed on that day, and a company that listed later is not. The list is refused until the
criteria carry a `frozen_on` date (D22: fixed before any return is computed), and every
build records the criteria it used.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from tradebot.common.config import load_yaml

CRORE = Decimal(10) ** 7


class UniverseNotFrozen(RuntimeError):
    pass


def config() -> dict:
    return load_yaml("backfill.yaml")


def criteria_params(universe_cfg: dict) -> dict:
    """The criteria as SQL parameters. Market-cap bounds are written in crore in config and
    compared in rupees, which is what the mcap file stores (§5.9)."""
    def bound(key):
        value = universe_cfg.get(key)
        return None if value is None else Decimal(str(value)) * CRORE

    return {
        "series": list(universe_cfg.get("series") or []),
        "isin_prefix": (universe_cfg.get("isin_prefix") or "") + "%",
        "mcap_min": bound("mcap_min_crore"),
        "mcap_max": bound("mcap_max_crore"),
    }


CANDIDATES_SQL = """
select p.isin, p.symbol, p.series, i.name, m.mcap_inr
from prices p
join instruments i on i.isin = p.isin
left join market_caps m on m.trade_date = p.trade_date and m.isin = p.isin
where p.trade_date = %(day)s
  and p.series = any(%(series)s)
  and p.isin like %(isin_prefix)s
  and (%(mcap_min)s::numeric is null or m.mcap_inr >= %(mcap_min)s::numeric)
  and (%(mcap_max)s::numeric is null or m.mcap_inr <= %(mcap_max)s::numeric)
order by p.symbol
"""


def as_of_trading_day(conn, as_of: date) -> date:
    day = conn.execute(
        "select max(day) from archive_days where trading_day and day <= %s", (as_of,)
    ).fetchone()[0]
    if day is None:
        raise RuntimeError(f"no loaded trading day on or before {as_of}; run "
                           "python -m tradebot.market for that period first")
    return day


def build(conn, cfg: dict | None = None) -> int:
    """(Re)build `backfill_universe`. Returns the number of companies."""
    cfg = cfg or config()
    ucfg = cfg["universe"]
    if not ucfg.get("frozen_on"):
        raise UniverseNotFrozen(
            "universe.frozen_on is null in config/backfill.yaml: Sravanth sets the criteria "
            "and the date they were fixed before the list is built (D22).")
    day = as_of_trading_day(conn, date.fromisoformat(str(ucfg["as_of"])))
    rows = conn.execute(CANDIDATES_SQL, {**criteria_params(ucfg), "day": day}).fetchall()
    with conn.transaction():
        conn.execute("delete from backfill_universe")
        with conn.cursor() as cur:
            cur.executemany(
                "insert into backfill_universe (isin, symbol, series, name, mcap_inr, as_of_date)"
                " values (%s,%s,%s,%s,%s,%s)",
                [(isin, sym, series, name, mcap, day) for isin, sym, series, name, mcap in rows],
            )
        conn.execute(
            "insert into backfill_universe_meta (built_at, frozen_on, as_of_date, criteria,"
            " companies) values (%s,%s,%s,%s,%s)",
            (datetime.now(timezone.utc), date.fromisoformat(str(ucfg["frozen_on"])), day,
             json.dumps(ucfg, default=str), len(rows)),
        )
    return len(rows)


def apply_exclusions(conn, cfg: dict | None = None) -> int:
    """Mark excluded companies: by hand (`universe.exclude_companies`, ISIN -> reason) and
    by industry (`analysis.exclude_industries`, which needs the announcements stage to have
    filled `industry`). Both are cleared and re-applied from config on every call, so the
    config is the one record of who is out and why. Returns how many are excluded."""
    cfg = cfg or config()
    by_hand = dict(cfg["universe"].get("exclude_companies") or {})
    industries = list(cfg["analysis"].get("exclude_industries") or [])
    conn.execute("update backfill_universe set excluded_reason = null "
                 "where excluded_reason like 'industry:%' or excluded_reason like 'by hand:%'")
    if industries:
        conn.execute(
            "update backfill_universe set excluded_reason = 'industry: ' || industry "
            "where industry = any(%s)", (industries,))
    for isin, reason in by_hand.items():
        conn.execute("update backfill_universe set excluded_reason = %s where isin = %s",
                     (f"by hand: {reason}", isin))
    conn.commit()
    return conn.execute("select count(*) from backfill_universe "
                        "where excluded_reason is not null").fetchone()[0]


EXPECTED_SQL = """
with syms as (
    select distinct s.symbol
    from backfill_universe u join instrument_symbols s on s.isin = u.isin
    where u.excluded_reason is null
)
select
    count(*) filter (where b.body like 'Bagging/Receiving of orders/contracts%%'
                        or b.body like 'Awarding of order(s)/contract(s)%%')   as order_filings,
    count(*) filter (where b.body like 'General Updates%%' or b.body like 'Updates%%'
                        or b.body like 'Press Release%%')                        as catch_all,
    count(distinct b.symbol)                                                      as companies_filing
from bundle_announcements b
join syms on syms.symbol = b.symbol
where b.report_date between %(since)s and %(until)s
"""


def expected_counts(conn, since: date, until: date) -> dict:
    """What the listed companies filed in the window, from the PR bundles alone: no API, no
    PDFs, no LLM (§10's sequencing note). Measured before any download, so the PDF volume
    and whether D22's 30-event floor is reachable are known up front."""
    order_filings, catch_all, companies = conn.execute(
        EXPECTED_SQL, {"since": since, "until": until}).fetchone()
    return {"order_filings": order_filings, "catch_all": catch_all,
            "companies_filing": companies,
            # The live average PDF is about 1 MB (WORKLOG, 27 Sep).
            "estimated_download_gb": round((order_filings + catch_all) / 1024, 1)}
