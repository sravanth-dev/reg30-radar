"""The event study and the pre-registered verdict (ARCHITECTURE §5.11, D22; Sravanth's
rules in config/backfill.yaml `universe.notes`).

Pure functions over plain data: backfill/study_data.py loads the database into `Market` and
`EventIn`, and this module decides, per event and then overall. Nothing here reads a clock
or a database, so every rule is tested on a hand-built market with known answers.

Timing, fixed before any return exists:
- **day 0** is the filing date if it was filed before 15:30 IST on a trading day, otherwise
  the next trading day (§5.11);
- the **valuation date** is the last trading day whose close came before the filing, which
  is always the trading day before day 0. Market cap is taken there, never on day 0,
  because a filing during market hours means day 0's close already holds the reaction
  (rule 1);
- returns run from day 0's close (conservative), minus the Nifty 50 over the same days;
  prices are unadjusted, and any window holding a capital action is excluded instead
  (§5.9).
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from tradebot.calculator.materiality import Materiality, compute
from tradebot.common.calendar import IST

CLOSE_TIME = time(15, 30)
HORIZONS = (1, 3, 5, 10)
PRE = (5, 20)
PRIMARY_HORIZON = 5
CAPITAL_ACTIONS = ("XB", "XS", "XR", "XO")          # §5.9: excluded; XD is tagged, kept
MAINBOARD = ("EQ", "BE", "BZ")
MIN_HISTORY = 120                                    # rule 5
CONTAMINATION_DAYS = 3                               # §5.11
# Buckets that count as other news near an order (§5.11). Leadership is a separate
# confounder tag (rule 4); noise is nothing.
CONTAMINATING = {"results", "other_material", "red_flag", "order_win", "order_candidate",
                 "catch_all", "unknown"}
COST_HURDLE = Decimal("0.0075")                      # D22
MIN_EVENTS = 30                                      # D22
CRORE = Decimal(10) ** 7


@dataclass(frozen=True)
class Bar:
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    traded_value: Decimal | None
    series: str
    corp_ind: str | None = None
    band_hit: str | None = None


@dataclass
class Market:
    days: list[date]                                 # every trading day, ascending
    nifty: dict[date, Decimal]
    bars: dict[str, dict[date, Bar]]                 # isin -> day -> bar
    mcap: dict[str, dict[date, Decimal]]             # isin -> day -> rupees
    muhurat: set[date] = field(default_factory=set)

    def __post_init__(self):
        self._pos = {d: i for i, d in enumerate(self.days)}

    def pos(self, d: date) -> int | None:
        return self._pos.get(d)

    def shift(self, d: date, n: int) -> date | None:
        """The trading day n trading days after (n<0: before) trading day d."""
        i = self._pos.get(d)
        if i is None or not 0 <= i + n < len(self.days):
            return None
        return self.days[i + n]

    def first_on_or_after(self, d: date) -> date | None:
        i = bisect.bisect_left(self.days, d)
        return self.days[i] if i < len(self.days) else None


def day0_of(ts: datetime, market: Market) -> date | None:
    """§5.11: the filing date if filed before 15:30 IST on a trading day, else the next
    trading day."""
    local = ts.astimezone(IST)
    d = local.date()
    if market.pos(d) is not None and local.time() < CLOSE_TIME:
        return d
    return market.first_on_or_after(date.fromordinal(d.toordinal() + 1))


@dataclass
class EventIn:
    event_id: int
    isin: str
    symbol: str
    event_ts: datetime
    value_inr: Decimal | None
    currency: str
    ttm_revenue_inr: Decimal | None          # as filed before event_ts (rule 1, §5.8)
    execution_months: Decimal | None
    other_filings: list[tuple[datetime, str]] = field(default_factory=list)  # (ts, bucket)
    previous_order_ts: datetime | None = None


@dataclass
class EventResult:
    event_id: int
    isin: str
    symbol: str
    event_ts: datetime
    day0: date | None = None
    valuation_date: date | None = None
    mcap_inr: Decimal | None = None
    materiality: Materiality | None = None
    series: str | None = None
    excess: dict[int, Decimal | None] = field(default_factory=dict)
    excess_from_open: dict[int, Decimal | None] = field(default_factory=dict)
    pre_excess: dict[int, Decimal | None] = field(default_factory=dict)
    volume_ratio: Decimal | None = None
    median_traded_value_60: Decimal | None = None
    history_days: int = 0
    locked: dict[int, str | None] = field(default_factory=dict)   # k -> "upper"/"lower"
    after_hours: bool = False
    exclusions: list[str] = field(default_factory=list)            # hard (rule 5)
    capital_action: str | None = None                              # excluded, reported
    ex_dividend: bool = False
    contaminated_by: list[str] = field(default_factory=list)
    leadership: bool = False
    muhurat_day0: bool = False
    days_since_previous_order: int | None = None

    @property
    def usable(self) -> bool:
        return not self.exclusions and self.capital_action is None

    @property
    def clean(self) -> bool:
        return self.usable and not self.contaminated_by

    @property
    def tradeable(self) -> bool:
        """Entry at day 0's close is fillable: not locked at the upper circuit then."""
        return self.locked.get(0) != "upper"


def _ret(later: Decimal | None, earlier: Decimal | None) -> Decimal | None:
    if later is None or earlier is None or earlier <= 0:
        return None
    return later / earlier - 1


def _excess(stock: Decimal | None, index: Decimal | None) -> Decimal | None:
    return None if stock is None or index is None else stock - index


def measure(ev: EventIn, market: Market) -> EventResult:
    """Everything the study records about one event."""
    r = EventResult(ev.event_id, ev.isin, ev.symbol, ev.event_ts)
    bars = market.bars.get(ev.isin, {})
    local = ev.event_ts.astimezone(IST)
    r.after_hours = not (market.pos(local.date()) is not None and local.time() < CLOSE_TIME)

    d0 = day0_of(ev.event_ts, market)
    if d0 is None:
        r.exclusions.append("no trading day after the filing in the loaded data")
        return r
    r.day0 = d0
    r.muhurat_day0 = d0 in market.muhurat
    r.valuation_date = market.shift(d0, -1)
    r.mcap_inr = market.mcap.get(ev.isin, {}).get(r.valuation_date) if r.valuation_date else None
    r.materiality = compute(ev.value_inr, ttm_revenue_inr=ev.ttm_revenue_inr,
                            mcap_inr=r.mcap_inr, execution_months=ev.execution_months)

    bar0 = bars.get(d0)
    r.series = bar0.series if bar0 else None
    # --- hard exclusions (rule 5)
    if bar0 is None or bar0.close is None:
        r.exclusions.append("no price on day 0 (suspended or not traded)")
    elif bar0.series not in MAINBOARD:
        r.exclusions.append(f"not NSE mainboard on day 0 (series {bar0.series})")
    i0 = market.pos(d0)
    r.history_days = sum(1 for d in market.days[:i0] if d in bars)
    if r.history_days < MIN_HISTORY:
        r.exclusions.append(f"only {r.history_days} trading days of history before day 0")

    def close(k: int) -> Decimal | None:
        d = market.shift(d0, k)
        b = bars.get(d) if d else None
        return b.close if b else None

    def nifty(k: int) -> Decimal | None:
        d = market.shift(d0, k)
        return market.nifty.get(d) if d else None

    for k in HORIZONS:
        r.excess[k] = _excess(_ret(close(k), close(0)), _ret(nifty(k), nifty(0)))
    for n in PRE:
        r.pre_excess[n] = _excess(_ret(close(-1), close(-1 - n)), _ret(nifty(-1), nifty(-1 - n)))
    if r.after_hours and bar0 is not None and bar0.open:
        # The Nifty file gives closes only, so the index leg runs from the previous close:
        # a small approximation, recorded here, on an exploratory variant (§5.11).
        for k in HORIZONS:
            r.excess_from_open[k] = _excess(_ret(close(k), bar0.open), _ret(nifty(k), nifty(-1)))
    if market.shift(d0, PRIMARY_HORIZON) is None:
        r.exclusions.append("event window not complete in the loaded data")
    elif r.excess[PRIMARY_HORIZON] is None and not r.exclusions:
        r.exclusions.append("no price data for the event window")

    # --- corporate actions in the window [-20, +10] (§5.9, D21)
    for k in range(-max(PRE), max(HORIZONS) + 1):
        d = market.shift(d0, k)
        b = bars.get(d) if d else None
        code = (b.corp_ind or "") if b else ""
        hit = next((c for c in CAPITAL_ACTIONS if c in code), None)
        if hit and r.capital_action is None:
            r.capital_action = f"{hit} on {d}"
        if "XD" in code:
            r.ex_dividend = True

    # --- liquidity and volume (rule 3, §5.11)
    past = [market.shift(d0, -k) for k in range(1, 61)]
    values = [bars[d].traded_value for d in past if d and d in bars and bars[d].traded_value is not None]
    if values:
        r.median_traded_value_60 = Decimal(statistics.median(values))
    baseline = [bars[d].volume for d in past[:20]
                if d and d in bars and bars[d].volume is not None and d not in market.muhurat]
    if baseline and bar0 is not None and bar0.volume is not None and statistics.mean(baseline) > 0:
        r.volume_ratio = (Decimal(bar0.volume) / Decimal(statistics.mean(baseline))).quantize(
            Decimal("0.0001"))

    # --- circuit locks on day 0..+3 (rule 3; "locked" decided 27 Sep 2026)
    for k in range(0, 4):
        d = market.shift(d0, k)
        b = bars.get(d) if d else None
        r.locked[k] = None
        if b and b.band_hit == "H" and b.close is not None and b.close == b.high:
            r.locked[k] = "upper"
        elif b and b.band_hit == "L" and b.close is not None and b.close == b.low:
            r.locked[k] = "lower"

    # --- other news near the order (§5.11; rule 4)
    for ts, bucket in ev.other_filings:
        fd0 = day0_of(ts, market)
        fi = market.pos(fd0) if fd0 else None
        if fi is None or abs(fi - i0) > CONTAMINATION_DAYS:
            continue
        if bucket == "leadership":
            r.leadership = True
        elif bucket in CONTAMINATING:
            r.contaminated_by.append(bucket)

    if ev.previous_order_ts is not None:
        prev0 = day0_of(ev.previous_order_ts, market)
        if prev0 is not None and market.pos(prev0) is not None:
            r.days_since_previous_order = i0 - market.pos(prev0)
    return r


# ------------------------------------------------------------------ the verdict (D22)

@dataclass
class Stats:
    n: int
    median: Decimal | None
    mean: Decimal | None
    hit_rate: Decimal | None


def stats(values: list[Decimal]) -> Stats:
    if not values:
        return Stats(0, None, None, None)
    return Stats(len(values), Decimal(statistics.median(values)),
                 Decimal(statistics.mean(values)),
                 Decimal(sum(1 for v in values if v > 0)) / len(values))


def in_band(r: EventResult, band_crore: tuple[float, float]) -> bool:
    lo, hi = band_crore
    return r.mcap_inr is not None and Decimal(str(lo)) * CRORE <= r.mcap_inr <= Decimal(str(hi)) * CRORE


def primary(results: list[EventResult], band_crore: tuple[float, float]) -> list[EventResult]:
    """D22's primary cell: clean events, value_to_ttm >= 15%, market cap in the band on the
    valuation date. Leadership-tagged events are in: rule 4 makes them a separate tag, not
    contamination, and the report shows the cell without them as well."""
    return [r for r in results
            if r.clean and r.materiality and r.materiality.value_to_ttm is not None
            and r.materiality.value_to_ttm >= Decimal("0.15") and in_band(r, band_crore)
            and r.excess.get(PRIMARY_HORIZON) is not None]


@dataclass
class Verdict:
    decision: str                   # "GO" | "NO-GO" | "INSUFFICIENT DATA"
    overall: Stats
    first_half: Stats
    second_half: Stats
    checks: dict[str, bool]


def verdict(cell: list[EventResult], split: date) -> Verdict:
    """D22 verbatim: at least 30 clean events; median minus the 0.75% hurdle > 0; mean
    minus the hurdle > 0; and the sign the same in both halves of the window."""
    values = [r.excess[PRIMARY_HORIZON] for r in cell]
    first = [r.excess[PRIMARY_HORIZON] for r in cell if r.day0 < split]
    second = [r.excess[PRIMARY_HORIZON] for r in cell if r.day0 >= split]
    s, s1, s2 = stats(values), stats(first), stats(second)
    checks = {
        "at least 30 clean events": s.n >= MIN_EVENTS,
        "median minus 0.75% > 0": s.median is not None and s.median - COST_HURDLE > 0,
        "mean minus 0.75% > 0": s.mean is not None and s.mean - COST_HURDLE > 0,
        "same sign in both halves": (s1.median is not None and s2.median is not None
                                     and (s1.median > 0) == (s2.median > 0)),
    }
    if not checks["at least 30 clean events"]:
        decision = "INSUFFICIENT DATA"
    elif all(checks.values()):
        decision = "GO"
    else:
        decision = "NO-GO"
    return Verdict(decision, s, s1, s2, checks)
