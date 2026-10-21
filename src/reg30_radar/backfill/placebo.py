"""The study's noise level, measured on placebo dates. `python -m reg30_radar.backfill.placebo`

reports/power_analysis_2026-09-22.md set σ ≈ 3.7% for the +5-day excess return from one
day's cross-section, with the Nifty σ and correlation assumed (GATE 1 audit, 20 Oct 2026).
With 12 months of prices loaded, σ can be measured the way the study itself measures:
placebo "events" on ordinary days, run through `event_study.measure`, with the same day-0
rule, the same exclusions and D22's primary market-cap band.

- One placebo per company on every 5th trading day of the study window, at 10:00 IST (so
  day 0 is that day), the starting day staggered by company so every day is used.
- A day within ±10 trading days of one of the company's real order events is skipped.
  That keeps no real event's return in the sample: D22's rule is that no return is looked
  at before the sample is final, and the placebo measures noise, not the effect.
- Read-only; no request and no model call.

The power figures use the bootstrap: the standard error of the median of n placebo returns,
drawn many times, times 2.80 (80% power, two-sided α = 0.05). That uses the real shape of
the returns, fat tails included, instead of assuming a normal distribution.
"""

from __future__ import annotations

import random
import statistics
import sys
from datetime import date, datetime, time
from decimal import Decimal

from reg30_radar.backfill import event_study
from reg30_radar.backfill.event_study import IST, PRIMARY_HORIZON, EventIn, Market

STEP = 5                 # one placebo per company every 5 trading days
GUARD_DAYS = 10          # skip days this close to a real order event of the company
SAMPLE_SIZES = (30, 50, 100, 170, 300)
BOOTSTRAP_DRAWS = 2000
Z_POWER = 2.80           # 1.96 + 0.84: 80% power, two-sided alpha 0.05


def placebo_events(market: Market, isins: list[str], since: date, until: date,
                   real_day0: dict[str, set[int]]) -> list[EventIn]:
    """Placebo EventIns: (company, every STEP-th trading day), away from real events.
    `real_day0` maps an ISIN to the trading-day positions of its real order events."""
    days = [d for d in market.days if since <= d <= until]
    out = []
    for k, isin in enumerate(isins):
        near = real_day0.get(isin, set())
        for d in days[k % STEP::STEP]:
            i = market.pos(d)
            if any(abs(i - j) <= GUARD_DAYS for j in near):
                continue
            out.append(EventIn(event_id=-1, isin=isin, symbol="", currency="INR",
                               event_ts=datetime.combine(d, time(10, 0), tzinfo=IST),
                               value_inr=None, ttm_revenue_inr=None, execution_months=None))
    return out


def usable_excess(results, band_crore: tuple[float, float]) -> list[float]:
    """+5-day excess returns of placebos the study would have kept in the primary band:
    no exclusion, no capital action in the window, market cap inside the band."""
    return [float(r.excess[PRIMARY_HORIZON]) for r in results
            if not r.exclusions and r.capital_action is None
            and r.excess.get(PRIMARY_HORIZON) is not None and event_study.in_band(r, band_crore)]


def robust_sd(values: list[float]) -> float:
    """Half the 16th-84th percentile spread: σ for a normal distribution, but not
    inflated by the fat tails and circuit-locked names the raw figure includes."""
    q = statistics.quantiles(values, n=100)
    return (q[83] - q[15]) / 2


def median_se(values: list[float], n: int, draws: int = BOOTSTRAP_DRAWS, seed: int = 20261020) -> float:
    """Bootstrap standard error of the median of n returns drawn from `values`."""
    rng = random.Random(seed)
    return statistics.stdev(statistics.median(rng.choices(values, k=n)) for _ in range(draws))


def summary(values: list[float]) -> dict:
    out = {"n": len(values), "sd": statistics.stdev(values), "robust_sd": robust_sd(values),
           "median": statistics.median(values), "mean": statistics.mean(values)}
    out["mde_median"] = {n: Z_POWER * median_se(values, n) for n in SAMPLE_SIZES}
    out["mde_mean"] = {n: Z_POWER * out["sd"] / n ** 0.5 for n in SAMPLE_SIZES}
    return out


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def write_report(path, s: dict, by_band: dict, halves: dict, ctx: dict) -> None:
    lines = [
        f"# The study's noise level, measured - {ctx['run_date']}",
        "",
        "Replaces the σ assumption in `reports/power_analysis_2026-09-22.md` (one day's "
        "cross-section, Nifty σ and correlation assumed) with a measurement over the loaded "
        f"year. Produced by `python -m reg30_radar.backfill.placebo`; read-only, no request, no "
        f"model call.",
        "",
        "## Method",
        "",
        f"- Placebo dates: every {STEP}th trading day per company, {ctx['since']} to "
        f"{ctx['until']}, 10:00 IST, through `event_study.measure` (the study's own day 0, "
        f"exclusions and +{PRIMARY_HORIZON}-day excess return over Nifty).",
        f"- Companies: the {ctx['companies']} in the frozen universe. Days within "
        f"±{GUARD_DAYS} trading days of one of the company's real order events are skipped, "
        f"so no real event's return is in the sample.",
        f"- Kept: no exclusion, no capital action in the window, market cap in D22's primary "
        f"band (₹{ctx['band'][0]:,}-{ctx['band'][1]:,} cr) on the valuation date. "
        f"{ctx['placebos']:,} placebos built, {s['n']:,} kept.",
        "",
        f"## +{PRIMARY_HORIZON}-day excess return, primary band",
        "",
        "| | value |",
        "|---|---|",
        f"| placebos | {s['n']:,} |",
        f"| standard deviation | **{_pct(s['sd'])}** |",
        f"| robust σ (16th-84th percentile) | **{_pct(s['robust_sd'])}** |",
        f"| median / mean | {_pct(s['median'])} / {_pct(s['mean'])} |",
        "",
        "By market cap within the band:",
        "",
        "| band | n | sd | robust σ |",
        "|---|---|---|---|",
        *[f"| {k} | {v['n']:,} | {_pct(v['sd'])} | {_pct(v['robust_sd'])} |"
          for k, v in by_band.items()],
        "",
        "By half of the window (D22 rule 4 compares the halves):",
        "",
        "| half | n | sd | robust σ | median |",
        "|---|---|---|---|---|",
        *[f"| {k} | {v['n']:,} | {_pct(v['sd'])} | {_pct(v['robust_sd'])} | {_pct(v['median'])} |"
          for k, v in halves.items()],
        "",
        "## The ordinary-day baseline is not zero",
        "",
        f"The median placebo excess return is {_pct(s['median'])} (mean {_pct(s['mean'])}): "
        "on an ordinary day these stocks trail Nifty at the median, more so in the first "
        "half. D22 tests an event's median against zero (after the 0.75% hurdle), not "
        "against this baseline, so the rule as written is conservative by about this much. "
        "Recorded, not acted on: D22 is pre-registered and Decided, and changing it is "
        "Sravanth's call, before any event return is seen.",
        "",
        "## What n clean events can detect (80% power, two-sided α = 0.05)",
        "",
        "Median: 2.80 × the bootstrap standard error of the median of n placebo returns. "
        "Mean: 2.80 σ / √n.",
        "",
        "| clean events | MDE, median | MDE, mean | gross move needed above the 0.75% hurdle (median) |",
        "|---|---|---|---|",
        *[f"| {n} | {_pct(s['mde_median'][n])} | {_pct(s['mde_mean'][n])} | "
          f"{_pct(s['mde_median'][n] + 0.0075)} |" for n in SAMPLE_SIZES],
        "",
        "## Caveats",
        "",
        "- The bootstrap treats returns as independent. Placebos and real events on the "
        "same day share its move beyond Nifty (sector moves), and order filings cluster "
        "around results season, so the true standard error is somewhat larger: read the "
        "MDEs as lower bounds.",
        "- Real news days of other kinds are in the sample, as they would be for any event. "
        "That is the right noise level for the study, which compares an event's return with "
        "an ordinary day's, not with a news-free one.",
        "- The September 2026 σ ≈ 3.7% was an estimate; the figures above supersede it for "
        "D22's power statement in ARCHITECTURE.md §5.11.",
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    from reg30_radar.backfill import study_data
    from reg30_radar.backfill.__main__ import _muhurat, _window
    from reg30_radar.common.config import ROOT, load_yaml
    from reg30_radar.common.db import backfill_url, connect

    cfg = load_yaml("backfill.yaml")
    band = tuple(cfg["analysis"]["primary_mcap_crore"])
    since, until = _window(cfg)
    with connect(backfill_url()) as conn:
        conn.read_only = True
        isins = [r[0] for r in conn.execute("select isin from backfill_universe order by isin")]
        market = study_data.load_market(conn, isins, date.fromisoformat(
            str(cfg["window"]["prices_from"])), date.today(), _muhurat(cfg))
        real: dict[str, set[int]] = {}
        for isin, ts in conn.execute("select isin, event_ts from backfill_events"):
            d0 = event_study.day0_of(ts, market)
            if d0 is not None and market.pos(d0) is not None:
                real.setdefault(isin, set()).add(market.pos(d0))
    evs = placebo_events(market, isins, since, until, real)
    results = [event_study.measure(ev, market) for ev in evs]
    s = summary(usable_excess(results, band))
    by_band = {}
    for lo, hi in ((band[0], 2000), (2000, 5000), (5000, band[1])):
        v = usable_excess(results, (lo, hi))
        if len(v) > 30:
            by_band[f"₹{lo:,}-{hi:,} cr"] = summary(v)
    split = date.fromordinal(since.toordinal() + (until.toordinal() - since.toordinal()) // 2)
    halves = {}
    for name, keep in ((f"to {split}", lambda r: r.day0 <= split),
                       (f"after {split}", lambda r: r.day0 > split)):
        v = usable_excess([r for r in results if r.day0 and keep(r)], band)
        halves[name] = summary(v)
    run_date = date.today().isoformat()
    path = ROOT / "reports" / f"power_analysis_{run_date}.md"
    write_report(path, s, by_band, halves, {
        "run_date": run_date, "since": since, "until": until, "companies": len(isins),
        "band": band, "placebos": len(evs)})
    print(f"{s['n']} placebos kept; sd {_pct(s['sd'])}, robust {_pct(s['robust_sd'])}; "
          f"MDE(median) at 30: {_pct(s['mde_median'][30])}; report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
