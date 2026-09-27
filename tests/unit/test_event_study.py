"""backfill/event_study.py on a hand-built market where every right answer is known.

200 weekday trading days from 2 Jan 2025; the Nifty and the stock sit at 100 unless a test
moves them. Each test changes one thing and checks the one rule it exercises."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from tradebot.backfill.event_study import (
    Bar, EventIn, Market, day0_of, measure, primary, verdict,
)
from tradebot.common.calendar import IST

CR = Decimal(10) ** 7


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(date(2025, 1, 2), 200)
D0 = DAYS[150]                                   # a Thursday, well past 120 days of history


def bar(close="100", **kw) -> Bar:
    c = Decimal(close)
    return Bar(open=kw.get("open", c), high=kw.get("high", c), low=kw.get("low", c), close=c,
               volume=kw.get("volume", 1000), traded_value=kw.get("traded_value", Decimal(100000)),
               series=kw.get("series", "EQ"), corp_ind=kw.get("corp_ind"),
               band_hit=kw.get("band_hit"))


def market(stock=None, nifty=None, mcap=None) -> Market:
    stock = stock or {}
    return Market(
        days=DAYS,
        nifty={d: Decimal(nifty.get(d, "100")) if nifty else Decimal(100) for d in DAYS},
        bars={"INE000A01010": {d: stock.get(d, bar()) for d in DAYS}},
        mcap={"INE000A01010": mcap or {d: Decimal(1000) * CR for d in DAYS}},
    )


def event(ts: datetime, value_cr="200", ttm_cr="1000", **kw) -> EventIn:
    return EventIn(event_id=kw.get("event_id", 1), isin="INE000A01010", symbol="ABC",
                   event_ts=ts, value_inr=Decimal(value_cr) * CR, currency="INR",
                   ttm_revenue_inr=Decimal(ttm_cr) * CR, execution_months=None,
                   other_filings=kw.get("other_filings", []))


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST)


# ------------------------------------------------------------------ timing

def test_day0_is_the_filing_day_before_the_close_and_the_next_day_after():
    m = market()
    assert day0_of(at(D0, 11), m) == D0
    assert day0_of(at(D0, 15, 29), m) == D0
    assert day0_of(at(D0, 16, 45), m) == DAYS[151]
    saturday = D0 + timedelta(days=(5 - D0.weekday()) % 7)
    assert day0_of(at(saturday, 10), m) == m.first_on_or_after(saturday)


def test_market_cap_is_valued_the_trading_day_before_day0_never_on_it():
    mcap = {d: Decimal(1000) * CR for d in DAYS}
    mcap[D0] = Decimal(5000) * CR                # day 0's close already holds the reaction
    r = measure(event(at(D0, 11)), market(mcap=mcap))
    assert r.valuation_date == DAYS[149]
    assert r.mcap_inr == Decimal(1000) * CR
    assert r.materiality.value_to_mcap == Decimal("0.200000")


# ------------------------------------------------------------------ returns

def test_excess_return_is_stock_minus_nifty_from_day0_close():
    stock = {DAYS[155]: bar("110")}              # +10% at +5
    nifty = {DAYS[155]: "102"}                   # +2% at +5
    r = measure(event(at(D0, 11)), market(stock=stock, nifty=nifty))
    assert r.excess[5] == Decimal("0.08")
    assert r.excess[1] == Decimal("0")


def test_pre_event_drift_is_measured_before_day0():
    stock = {DAYS[144]: bar("95")}               # d0-6 at 95, d0-1 at 100: +5.26%
    r = measure(event(at(D0, 11)), market(stock=stock))
    assert round(r.pre_excess[5], 4) == Decimal("0.0526")


# ------------------------------------------------------------------ exclusions

def test_short_history_is_a_hard_exclusion():
    stock = {d: bar() for d in DAYS[100:]}       # listed 50 days before day 0
    m = market()
    m.bars["INE000A01010"] = stock
    r = measure(event(at(D0, 11)), m)
    assert any("history" in e for e in r.exclusions) and not r.usable


def test_sme_series_and_no_trade_on_day0_are_hard_exclusions():
    r = measure(event(at(D0, 11)), market(stock={D0: bar(series="SM")}))
    assert any("mainboard" in e for e in r.exclusions)
    m = market()
    del m.bars["INE000A01010"][D0]
    assert any("day 0" in e for e in measure(event(at(D0, 11)), m).exclusions)


def test_a_capital_action_in_the_window_excludes_but_a_dividend_does_not():
    r = measure(event(at(D0, 11)), market(stock={DAYS[153]: bar(corp_ind="XB")}))
    assert r.capital_action and not r.usable
    r = measure(event(at(D0, 11)), market(stock={DAYS[153]: bar(corp_ind="XD")}))
    assert r.ex_dividend and r.usable


def test_a_recent_event_without_its_full_window_is_flagged_not_measured():
    r = measure(event(at(DAYS[197], 11)), market())
    assert "event window not complete in the loaded data" in r.exclusions


# ------------------------------------------------------------------ confounders

def test_other_news_within_three_trading_days_contaminates():
    near = at(DAYS[152], 17)                     # day 0 of that filing = DAYS[153]
    far = at(DAYS[156], 11)
    r = measure(event(at(D0, 11), other_filings=[(near, "results"), (far, "results")]),
                market())
    assert r.contaminated_by == ["results"] and not r.clean


def test_noise_is_ignored_and_leadership_is_its_own_tag():
    r = measure(event(at(D0, 11), other_filings=[(at(D0, 12), "noise"),
                                                  (at(D0, 13), "leadership")]), market())
    assert r.clean and r.leadership


# ------------------------------------------------------------------ circuits

def test_locked_upper_means_band_hit_and_close_at_the_high():
    stock = {D0: bar("120", high=Decimal("120"), band_hit="H"),
             DAYS[151]: bar("125", high=Decimal("126"), band_hit="H")}
    r = measure(event(at(D0, 11)), market(stock=stock))
    assert r.locked[0] == "upper" and not r.tradeable
    assert r.locked[1] is None                   # hit the band but closed off it


# ------------------------------------------------------------------ the verdict

def _results(n, excess5, day0=D0):
    out = []
    for i in range(n):
        r = measure(event(at(day0, 11), event_id=i), market())
        r.excess[5] = Decimal(excess5)
        out.append(r)
    return out


def test_primary_cell_uses_the_value_to_ttm_and_band_rules():
    small = measure(event(at(D0, 11), value_cr="100", ttm_cr="1000"), market())   # 10%
    big = measure(event(at(D0, 11), value_cr="200", ttm_cr="1000"), market())     # 20%
    assert primary([small, big], (500, 20000)) == [big]
    assert primary([big], (2000, 20000)) == []   # mcap Rs 1,000 cr is outside


def _both_halves(n, excess5):
    rs = _results(n, excess5)
    for r in rs[: n // 2]:
        r.day0 = DAYS[50]                        # first half; the rest stay at D0
    return rs


def test_go_needs_thirty_clean_events_and_both_statistics_above_the_hurdle():
    split = DAYS[100]
    assert verdict(_both_halves(30, "0.02"), split).decision == "GO"
    assert verdict(_both_halves(29, "0.02"), split).decision == "INSUFFICIENT DATA"
    assert verdict(_both_halves(30, "0.005"), split).decision == "NO-GO"   # under the hurdle


def test_all_events_in_one_half_cannot_pass_the_halves_check():
    v = verdict(_results(30, "0.02"), split=DAYS[100])
    assert not v.checks["same sign in both halves"] and v.decision == "NO-GO"


def test_opposite_signs_in_the_two_halves_is_no_go():
    early = _results(20, "0.05", day0=DAYS[50])
    late = _results(20, "-0.01", day0=D0)
    for r in early:
        r.day0 = DAYS[50]
    v = verdict(early + late, split=DAYS[100])
    assert not v.checks["same sign in both halves"] and v.decision == "NO-GO"
