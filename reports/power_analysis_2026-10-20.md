# The study's noise level, measured - 2026-10-20

Replaces the σ assumption in `reports/power_analysis_2026-09-22.md` (one day's cross-section, Nifty σ and correlation assumed) with a measurement over the loaded year. Produced by `python -m tradebot.backfill.placebo`; read-only, no request, no model call.

## Method

- Placebo dates: every 5th trading day per company, 2025-09-22 to 2026-09-18, 10:00 IST, through `event_study.measure` (the study's own day 0, exclusions and +5-day excess return over Nifty).
- Companies: the 1583 in the frozen universe. Days within ±10 trading days of one of the company's real order events are skipped, so no real event's return is in the sample.
- Kept: no exclusion, no capital action in the window, market cap in D22's primary band (₹500-20,000 cr) on the valuation date. 74,701 placebos built, 54,081 kept.

## +5-day excess return, primary band

| | value |
|---|---|
| placebos | 54,081 |
| standard deviation | **5.75%** |
| robust σ (16th-84th percentile) | **4.43%** |
| median / mean | -0.44% / 0.23% |

By market cap within the band:

| band | n | sd | robust σ |
|---|---|---|---|
| ₹500-2,000 cr | 21,117 | 6.09% | 4.59% |
| ₹2,000-5,000 cr | 14,711 | 5.94% | 4.51% |
| ₹5,000-20,000 cr | 18,253 | 5.17% | 4.17% |

By half of the window (D22 rule 4 compares the halves):

| half | n | sd | robust σ | median |
|---|---|---|---|---|
| to 2026-03-21 | 27,248 | 5.25% | 4.06% | -1.07% |
| after 2026-03-21 | 26,833 | 6.10% | 4.72% | 0.24% |

## The ordinary-day baseline is not zero

The median placebo excess return is -0.44% (mean 0.23%): on an ordinary day these stocks trail Nifty at the median, more so in the first half. D22 tests an event's median against zero (after the 0.75% hurdle), not against this baseline, so the rule as written is conservative by about this much. Recorded, not acted on: D22 is pre-registered and Decided, and changing it is Sravanth's call, before any event return is seen.

## What n clean events can detect (80% power, two-sided α = 0.05)

Median: 2.80 × the bootstrap standard error of the median of n placebo returns. Mean: 2.80 σ / √n.

| clean events | MDE, median | MDE, mean | gross move needed above the 0.75% hurdle (median) |
|---|---|---|---|
| 30 | 2.50% | 2.94% | 3.25% |
| 50 | 1.94% | 2.28% | 2.69% |
| 100 | 1.37% | 1.61% | 2.12% |
| 170 | 1.05% | 1.24% | 1.80% |
| 300 | 0.78% | 0.93% | 1.53% |

## Caveats

- The bootstrap treats returns as independent. Placebos and real events on the same day share its move beyond Nifty (sector moves), and order filings cluster around results season, so the true standard error is somewhat larger: read the MDEs as lower bounds.
- Real news days of other kinds are in the sample, as they would be for any event. That is the right noise level for the study, which compares an event's return with an ordinary day's, not with a news-free one.
- The September 2026 σ ≈ 3.7% was an estimate; the figures above supersede it for D22's power statement in ARCHITECTURE.md §5.11.
