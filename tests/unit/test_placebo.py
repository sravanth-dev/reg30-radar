"""backfill/placebo.py: placebo dates away from real events, and the noise statistics."""

import statistics

from reg30_radar.backfill.event_study import measure
from reg30_radar.backfill.placebo import (
    GUARD_DAYS, STEP, median_se, placebo_events, robust_sd, usable_excess,
)
from tests.unit.test_event_study import DAYS, market

ISIN = "INE000A01010"


def test_placebos_fall_every_step_days_and_never_near_a_real_event():
    m = market()
    real = {ISIN: {150}}
    evs = placebo_events(m, [ISIN], DAYS[130], DAYS[190], real)
    positions = [m.pos(ev.event_ts.date()) for ev in evs]
    assert positions and all(b - a == STEP for a, b in zip(positions, positions[1:])
                             if b - a < 2 * STEP + GUARD_DAYS)
    assert all(abs(p - 150) > GUARD_DAYS for p in positions)
    # 10:00 IST: day 0 is the placebo day itself.
    assert all(measure(ev, m).day0 == ev.event_ts.date() for ev in evs)


def test_a_flat_market_gives_zero_excess_inside_the_band():
    m = market()
    evs = placebo_events(m, [ISIN], DAYS[130], DAYS[180], {})
    values = usable_excess([measure(ev, m) for ev in evs], (500, 20000))
    assert values and set(values) == {0.0}
    # Outside the band (mcap is Rs 1,000 cr in the fixture): nothing kept.
    assert usable_excess([measure(ev, m) for ev in evs], (5000, 20000)) == []


def test_robust_sd_matches_a_normal_sample_and_ignores_a_fat_tail():
    import random
    rng = random.Random(1)
    xs = [rng.gauss(0, 0.04) for _ in range(20000)]
    assert abs(robust_sd(xs) - 0.04) < 0.002
    assert abs(robust_sd(xs + [5.0] * 50) - 0.04) < 0.003      # tails barely move it
    assert statistics.stdev(xs + [5.0] * 50) > 0.2              # the raw sd explodes


def test_median_se_shrinks_with_the_square_root_of_n():
    import random
    rng = random.Random(2)
    xs = [rng.gauss(0, 0.04) for _ in range(5000)]
    ratio = median_se(xs, 30, draws=800) / median_se(xs, 120, draws=800)
    assert 1.7 < ratio < 2.3
