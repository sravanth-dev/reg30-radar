"""The backfill report: `reports/backfill_<date>.md` plus a per-event CSV (§5.11, §8:
committed to git).

The verdict comes first and says exactly which pre-registered checks passed. Everything
outside the primary cell is labelled exploratory: it can suggest a hypothesis for forward
testing, never a GO on this same data (D22). Every exclusion is counted, so a thin sample
shows up as a cause rather than a surprise.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from tradebot.backfill.event_study import (
    HORIZONS, PRIMARY_HORIZON, EventResult, Verdict, in_band, primary, stats,
)
from tradebot.common.config import ROOT

REPORTS_DIR = ROOT / "reports"
TTM_BUCKETS = [("<5%", 0, 0.05), ("5-15%", 0.05, 0.15), ("15-40%", 0.15, 0.40), (">40%", 0.40, 1e9)]
MCAP_BUCKETS = [("<1,000 cr", 0, 1000), ("1,000-10,000 cr", 1000, 10000), (">10,000 cr", 10000, 1e9)]


def pct(v: Decimal | None) -> str:
    return "-" if v is None else f"{v * 100:.2f}%"


def _cell_line(label: str, cell: list[EventResult], horizon: int = PRIMARY_HORIZON) -> str:
    s = stats([r.excess[horizon] for r in cell if r.excess.get(horizon) is not None])
    return f"| {label} | {s.n} | {pct(s.median)} | {pct(s.mean)} | {pct(s.hit_rate)} |"


def render(results: list[EventResult], v: Verdict, ctx: dict) -> str:
    band = tuple(ctx["primary_band"])
    universe_band = tuple(ctx["universe_band"])
    cell = primary(results, band)
    lines = [
        f"# Backfill event study - {ctx['run_date']}",
        "",
        f"## VERDICT: {v.decision}",
        "",
        "Pre-registered rule (D22, primary band revised 27 Sep 2026 before any return was "
        "computed): verified order **wins** with value >= 15% of point-in-time TTM revenue, "
        f"market cap Rs {band[0]:,}-{band[1]:,} cr on the valuation date, clean events only, "
        "excess return over the Nifty 50 from the day-0 close to day +5.",
        "",
        "| Check | Passed |",
        "|---|---|",
        *[f"| {name} | {'yes' if ok else 'NO'} |" for name, ok in v.checks.items()],
        "",
        "| Primary cell | n | median | mean | hit rate |",
        "|---|---|---|---|---|",
        f"| all | {v.overall.n} | {pct(v.overall.median)} | {pct(v.overall.mean)} | {pct(v.overall.hit_rate)} |",
        f"| first half | {v.first_half.n} | {pct(v.first_half.median)} | {pct(v.first_half.mean)} | {pct(v.first_half.hit_rate)} |",
        f"| second half | {v.second_half.n} | {pct(v.second_half.median)} | {pct(v.second_half.mean)} | {pct(v.second_half.hit_rate)} |",
        "",
        "What the sample size buys (reports/power_analysis_2026-09-22.md): at n = 30 the "
        "study resolves only a median edge of about 2.4% net of costs. A null result near "
        "that size means **underpowered**, not evidence of no effect.",
        "",
        "## Sensitivity (exploratory, never a GO)",
        "",
        "| Cell, +5 days | n | median | mean | hit rate |",
        "|---|---|---|---|---|",
        _cell_line("primary without leadership-tagged events (rule 4)",
                   [r for r in cell if not r.leadership]),
        _cell_line("primary, tradeable only (not locked upper at the day-0 close)",
                   [r for r in cell if r.tradeable]),
        _cell_line(f"study universe Rs {universe_band[0]:,}-{universe_band[1]:,} cr",
                   primary(results, universe_band)),
        _cell_line("control: above Rs 50,000 cr", primary(results, (50000, 10 ** 9))),
        _cell_line("primary, contaminated events instead of clean",
                   [r for r in results if r.usable and not r.clean and r.company_is_recipient
                    and r.materiality and r.materiality.value_to_ttm is not None
                    and r.materiality.value_to_ttm >= Decimal("0.15") and in_band(r, band)]),
        "",
        "## Exploratory grid: median excess return (n), clean wins",
        "",
        "| value / TTM | market cap | " + " | ".join(f"+{h}" for h in HORIZONS) + " |",
        "|---|---|" + "---|" * len(HORIZONS),
    ]
    clean_wins = [r for r in results if r.clean and r.company_is_recipient is True
                  and r.materiality and r.materiality.value_to_ttm is not None]
    for tname, tlo, thi in TTM_BUCKETS:
        for mname, mlo, mhi in MCAP_BUCKETS:
            group = [r for r in clean_wins
                     if Decimal(str(tlo)) <= r.materiality.value_to_ttm < Decimal(str(thi))
                     and in_band(r, (mlo, mhi))]
            cells = []
            for h in HORIZONS:
                s = stats([r.excess[h] for r in group if r.excess.get(h) is not None])
                cells.append(f"{pct(s.median)} ({s.n})")
            lines.append(f"| {tname} | {mname} | " + " | ".join(cells) + " |")

    reasons = Counter(e for r in results for e in r.exclusions)
    lines += [
        "",
        "## Funnel and exclusions",
        "",
        *[f"- {k}: {v}" for k, v in ctx.get("funnel", {}).items()],
        f"- events measured: {len(results)}",
        *[f"- excluded, {k}: {n}" for k, n in reasons.most_common()],
        f"- excluded, capital action in the window (§5.9): "
        f"{sum(1 for r in results if r.capital_action)}",
        f"- usable: {sum(1 for r in results if r.usable)}; clean: "
        f"{sum(1 for r in results if r.clean)}; contaminated: "
        f"{sum(1 for r in results if r.usable and not r.clean)}; leadership-tagged: "
        f"{sum(1 for r in results if r.leadership)}",
        f"- company placed the order, or unknown: "
        f"{sum(1 for r in results if r.company_is_recipient is not True)}",
        f"- day 0 on a Muhurat session (reported separately): "
        f"{sum(1 for r in results if r.muhurat_day0)}",
        "",
        "## Data behind it",
        "",
        *[f"- {k}: {v}" for k, v in ctx.get("data", {}).items()],
        "",
    ]
    return "\n".join(lines)


CSV_FIELDS = ["event_id", "symbol", "isin", "event_ts", "day0", "valuation_date", "mcap_cr",
              "value_to_ttm", "next12m_to_ttm", "value_to_mcap", "materiality_flags",
              "company_is_recipient", "series", *[f"excess_{h}" for h in HORIZONS],
              *[f"excess_from_open_{h}" for h in HORIZONS], "pre_5", "pre_20",
              "volume_ratio", "median_traded_value_60", "history_days", "locked_0",
              "locked_1", "locked_2", "locked_3", "after_hours", "exclusions",
              "capital_action", "ex_dividend", "contaminated_by", "leadership",
              "muhurat_day0", "days_since_previous_order"]


def row(r: EventResult) -> dict:
    m = r.materiality
    return {
        "event_id": r.event_id, "symbol": r.symbol, "isin": r.isin,
        "event_ts": r.event_ts.isoformat(), "day0": r.day0, "valuation_date": r.valuation_date,
        "mcap_cr": None if r.mcap_inr is None else round(r.mcap_inr / Decimal(10) ** 7, 2),
        "value_to_ttm": m and m.value_to_ttm, "next12m_to_ttm": m and m.next12m_to_ttm,
        "value_to_mcap": m and m.value_to_mcap,
        "materiality_flags": ";".join(sorted(m.flags)) if m else "",
        "company_is_recipient": r.company_is_recipient, "series": r.series,
        **{f"excess_{h}": r.excess.get(h) for h in HORIZONS},
        **{f"excess_from_open_{h}": r.excess_from_open.get(h) for h in HORIZONS},
        "pre_5": r.pre_excess.get(5), "pre_20": r.pre_excess.get(20),
        "volume_ratio": r.volume_ratio, "median_traded_value_60": r.median_traded_value_60,
        "history_days": r.history_days,
        **{f"locked_{k}": r.locked.get(k) for k in range(4)},
        "after_hours": r.after_hours, "exclusions": ";".join(r.exclusions),
        "capital_action": r.capital_action, "ex_dividend": r.ex_dividend,
        "contaminated_by": ";".join(r.contaminated_by), "leadership": r.leadership,
        "muhurat_day0": r.muhurat_day0, "days_since_previous_order": r.days_since_previous_order,
    }


def write(results: list[EventResult], v: Verdict, ctx: dict,
          out_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"backfill_{ctx['run_date']}"
    md = out_dir / f"{stem}.md"
    md.write_text(render(results, v, ctx), encoding="utf-8")
    csv_path = out_dir / f"{stem}_events.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in results:
            w.writerow(row(r))
    return md, csv_path
