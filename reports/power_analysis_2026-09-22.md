# How many order events does the go/no-go actually need?

22 Sep 2026. Answers Sravanth's question: at our noise level, what effect size can the
primary bucket detect, and what would 24–36 months add?

**Short version.** D22's floor of 30 clean events can only detect a net edge of about
**2.4%**, which is larger than most announcement effects reported anywhere. Twelve months
plausibly yields **36–184** events. To get the detectable edge down near the 0.75% cost
hurdle itself takes roughly **300 events**, which is a 24–36 month window. And the parts of
that funnel that are cheapest to measure need no PDFs and no LLM at all, so the window
should be chosen from measurement rather than from this estimate.

---

## 1. The noise level, measured rather than assumed

Cross-sectional one-day returns for every EQ-series name, 16 → 17 Jul 2026, from the UDiFF
bhavcopies:

| Market-cap band | n | 1-day sd | implied 5-day sd | robust 5-day sd |
|---|---|---|---|---|
| <₹1,000 cr | 559 | 2.04% | 4.56% | 3.56% |
| ₹1,000–10,000 cr | 830 | 2.10% | 4.70% | 3.24% |
| >₹10,000 cr | 565 | 1.99% | 4.44% | 3.55% |

Two things worth noting. Volatility barely varies by cap band on this day — the small-cap
premium people expect is not visible, though one day is one day. And the robust estimate
(from the 16th/84th percentiles) sits well below the raw standard deviation, because the
raw figure is inflated by fat tails and circuit-locked names.

The study measures **excess** return over Nifty, which removes part of the market
component. Taking σ(5-day) ≈ 4.0%, Nifty 5-day σ ≈ 2%, and correlation ≈ 0.4:

> Var(excess) = 16 + 4 − 2(0.4 × 4 × 2) = 13.6 → **σ ≈ 3.7%**

Everything below uses **σ = 3.7%**, with 3.0% and 4.3% as the plausible band.

## 2. What a given number of events can detect

Minimum detectable effect at 80% power, two-sided α = 0.05:

- on the **mean**: MDE = 2.80 σ/√n
- on the **median**: MDE = 3.51 σ/√n

The median carries a √(π/2) ≈ 1.25 penalty *for normally distributed data*. D22 makes the
median the primary statistic, which is the right call for fat-tailed returns — and against
genuinely fat tails the median is **more** efficient than the mean, not less. So the median
column below is a worst case, not a forecast.

| Clean events | MDE (mean) | MDE (median) | Net edge demonstrable above the 0.75% hurdle |
|---|---|---|---|
| 30 | 1.89% | **2.37%** | needs a gross move ≥ 3.1% |
| 50 | 1.47% | 1.84% | ≥ 2.6% gross |
| 100 | 1.04% | 1.30% | ≥ 2.1% gross |
| 200 | 0.73% | 0.92% | ≥ 1.7% gross |
| 300 | 0.60% | 0.75% | ≥ 1.5% gross |
| 500 | 0.46% | 0.58% | ≥ 1.3% gross |

Read the other way — events needed to demonstrate a given **net** edge:

| Net edge (after the 0.75% hurdle) | Events needed |
|---|---|
| 2.5% | 27 |
| 2.0% | 42 |
| 1.5% | 75 |
| 1.0% | 169 |
| 0.5% | 675 |

**So D22's 30-event minimum is a floor against embarrassment, not a power target.** It
protects against declaring a result from a handful of events. It does not give the study
the resolution to see an edge of the size actually worth trading.

## 3. How many events twelve months is likely to produce

Measured: **~8 distinct mainboard order events per ordinary day** (18 Sep 2026, after
collapsing repeat filings by ISIN) → **~2,000 per year**.

The funnel to the primary bucket, with measured values marked:

| Stage | Rate | Source |
|---|---|---|
| Mainboard order events / year | 2,000 | **measured**, one day annualised |
| Extraction verified | 0.85 | assumed; Spike D will measure |
| TTM available | 0.80 | assumed; depends on §5.8 Q4 derivation |
| `value_to_ttm` ≥ 15% | **0.10 – 0.30** | **unknown, and it dominates** |
| Market cap < ₹10,000 cr | 0.75 | **measured**, 6 of 8 filers on 18 Sep |
| Clean of contamination | **0.35 – 0.60** | **unknown, and it also dominates** |

Which gives **36 to 184 clean events from twelve months**, centred near 100. At 100 events
the detectable net edge is about 1.3%.

## 4. What 24–36 months adds

Events scale linearly with the window, so MDE scales as 1/√T:

| Window | Events (if 12 months = 100) | MDE (median) | Net edge demonstrable |
|---|---|---|---|
| 12 months | 100 | 1.30% | ≥ 2.1% gross |
| 24 months | 200 | 0.92% | ≥ 1.7% gross |
| 36 months | 300 | **0.75%** | ≥ 1.5% gross |

**36 months is what it takes to bring the detectable edge down to the cost hurdle itself.**
Below that, the study can only confirm edges comfortably larger than trading costs — which
is not useless, but it means a genuine 1% net edge would come back as "insufficient
evidence" rather than as a GO.

Extending is cheaper than it sounds, and the reason is the Spike A2 correction: the API's
`symbol=` query returns a company's **entire 22-year history in one call**, so the API cost
of 36 months is the same as 12. Only the PR-bundle downloads scale, from ~250 to ~750, and
those are plain archive fetches with no anti-bot surface.

Three costs that do rise:

- **Older XBRL.** Results before April 2025 use the pre-Integrated-Filing format. §5.8
  assumes one parser handles both; Spike C has not verified it, and a 36-month window makes
  that assumption load-bearing for two-thirds of the sample rather than a fraction.
- **Point-in-time universe.** Over three years more companies list, delist and change
  symbols, so the universe has to be rebuilt per date rather than taken as current.
- **Regime.** A longer window spans more regimes, which is good for robustness. D22's
  "same sign in both halves" should become **thirds** at 36 months, since two 18-month
  halves is a weak stability test.

## 5. The recommendation

**Do not choose the window from this estimate. Measure it first, because the measurement is
nearly free.**

The two rates that dominate the funnel — the share of orders at `value_to_ttm` ≥ 15%, and
the contamination rate — differ in an important way. Contamination needs **only the PR
bundles**: it is "did this ISIN file anything else non-noise within ±3 trading days", and
every bundle carries company and category. No PDFs, no API, no LLM, no extraction.

So the cheap sequencing is:

1. Download 36 months of PR bundles (~750 archive requests, a few hours, no anti-bot risk).
2. From those alone, measure the true order-event count per day and the contamination rate.
3. That fixes every funnel term except `value_to_ttm ≥ 15%`.
4. Choose the window knowing the real n, then spend on PDFs and LLM once.

This also front-loads the cheapest data against the most expensive uncertainty, and it
means the decision to extend to 24 or 36 months gets made on counts rather than on the
assumptions in section 3.

**One thing to fix in D22 regardless.** Raise the event floor, or state explicitly that
30 events buys only a ~2.4% resolution and that a null result at that size means
"underpowered", not "no effect". As written, the rule could produce a confident-sounding
no-go that the data was never able to detect either way.
