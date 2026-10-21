# ARCHITECTURE.md — Reg30 Radar, Phase 1: announcements → order signals

Version 1.6 · 20 Oct 2026 · Owner: Sravanth

Change log:
- v1.6 (20 Oct 2026) records the GATE 1 audit of Sravanth's 20 Oct brief (`AUDIT.md`, `STATUS.md`): the VPS is cancelled (D28), and four decisions taken at the gate (D29-D32): the LLM stays on OpenAI under the existing caps, live collection restarts only as one process behind an NSE lock, the third documents tier is skipped for the verdict, and stated bounds count as flagged lower bounds. It also fixes three stale lines (§5.11's collected-universe floor, §11's primary band, §6's tier 2). Decisions taken while finishing Phase 1 are marked **Proposed** where they land.
- v1.5 adds a second tab, `orders`, to the same Google Sheet (`src/reg30_radar/sheets/orders.py`), mirroring `order_extractions` - order-related filings only, with the value, extractor, and review status - so Sravanth can see the pipeline's output online without SQL. A further, still-narrow piece of D11 pulled forward, same as v1.2's raw mirror: view-only, no scoring. Unlike the raw tab, `order_extractions` rows change after they're first written (`pending_llm` → `verified`), so there is no append-only position to pin a row to; the tab is rewritten whole each cycle instead, skipped when a content hash shows nothing changed. `client.py` gains `ensure_tab()` (so a new tab no longer needs the hand rename v1.2's first live sync required), `write_numbers()` (one `USER_ENTERED` column, value-shape-checked before any HTTP call, so the sortable ₹-crore column can never receive filing text), and `clear_from()`.
- v1.4 replaces the §5.5 char-count `is_scanned` heuristic with a per-page quality ladder (`documents/quality.py`, `documents/text.py`) after a live demo showed it could pass a genuinely garbled document (an invisible-OCR text layer with a broken font, plenty of characters, all wrong). Builds vision OCR as the closing move on the §11 scanned-PDF item, but dormant: `llm/client.py` (the single provider entry point CLAUDE.md requires, pulled forward from Slice 5), `documents/ocr.py`, `prompts/ocr_transcribe_v1.md`, `migrations/0004_document_quality.sql`, `migrations/0005_llm_calls.sql`. Adds the §5.6/§6 provenance rule for vision-read numbers. Records a finding that reversed part of the plan: a whole-page readability score cannot separate the regression fixture from an already-accepted page with the same garbled-bilingual-header pattern (BEL) — the two are told apart by font provenance instead. See §5.5 for the full reasoning.
- v1.3 builds the §5.5 document pipeline (`src/reg30_radar/documents/`): download, SHA-256, extract, store, delete-the-PDF. The unit normalizer and annexure parser (`units/`, `extractor/`) and the eval harness (`eval/`) were already built and scored once against the labelled set (44% exact `value_inr`, T0 alone — see `reports/extraction_baseline_2026-09-24.md`); this slice is the pipeline that will feed them PDFs from the live collector rather than from `tests/labelled/`. Adds the `documents` table (`migrations/0003_documents.sql`) and `nse.documents` to `config/sources.yaml`.
- v1.2 pulls part of **D11** forward from Phase 2: a one-way, view-only mirror of
  `raw_announcements` into a Google Sheet (`src/reg30_radar/sheets/`), so the collector's
  output can be browsed without writing SQL each time. Postgres stays authoritative; the
  Sheet is disposable and `--rebuild` regenerates it. Scored orders and the daily digest
  stay in Phase 2, per D11 as written. Adds `google-auth` to §9's approved dependencies and
  a `sheets_sync` watermark table to §7.
- v1.1 revises **D6** from a flat 60 s to three pacing bands, after measuring when filings actually arrive: 64–67% of a day's filings land after 16:00 and the busiest hour is 17:00, so the post-close window is eased to 3 min rather than the 10 min first proposed — 10 min would overflow the endpoint's 20-record page, which a measured 23-filing window on 23 Sep showed is not hypothetical. §5.1 and `config/sources.yaml` follow.
- v1.0 makes bundle-vs-API reconciliation a permanent backfill step rather than a spike finding (§5.11, `src/reg30_radar/backfill/reconcile.py`), and records the statistical power of the pre-registered rule: 30 events resolves only a ~2.4% net edge, so §5.11 now states what the floor does and does not buy. D26 is final — BSE is out.
- v0.9 **corrects two measurement errors of mine** that made the API look far worse than it is. The `an<date>.txt` bundle is a *report* for that date covering filings disseminated since the previous report, so comparing it to the API's same-date query was a category error; and the Spike A claim that the symbol query "stops at 31 Oct 2025" came from string-sorting `DD-Mon-YYYY`. Corrected: **mainboard order coverage is 8 of 8** on the day tested, and the symbol query spans 2004 to the previous day. The backfill is not blocked.
- v0.8 (Spike A2) measures the API gap **inside the study universe** and finds it fatal: 72% of operating-company filings and 21 of 23 order filings are missing, at a rate that does not improve for recent dates. No parameter reaches the full day. §5.1 now records this; §5.11 and D27 gain the Muhurat rules; §10 gains the Spike D counts.
- v0.7 (open-loop audit) repairs eight self-contradictions left behind by the v0.5 and v0.6 reversals — most seriously §7, which still described `prev_close` as corporate-action adjusted after Spike B disproved it. Adds **D26** (BSE dropped from Phase 1) and **D27** (trading-day calendar split by direction), and records the router's ambiguous input in §5.4.
- v0.6 (Slice 0, Spike A) documents the announcements API record shape (§5.1) and **reverses the hybrid plan again**: the API is a partial view of any past day, while the PR bundle's `an` file is the complete one. `sm_isin` and `smIndustry` answer §5.3's ISIN attachment and §5.8's sector source.
- v0.5 (Slice 0, Spike B) verifies the NSE bulk-archive URL patterns and depth (§5.2, §5.9) and **reverses the corporate-action design**: `PrvsClsgPric` is *not* adjusted, so returns cannot be chained through it (§5.9, §5.11). Records the robots.txt / terms-of-use conflict in §3.
- v0.4 (Slice 0, Step 0 review) reworks the LLM routing and verification rules (§6), makes verification provenance-based, fixes the announcement-source plan to a hybrid (§5.1), and settles the data-quality decisions: return chaining, band hitters, Q4 derivation, dedup keys, revision rows, sector column. Adds D23. Corrects D6, D10, D14, D19, D20.
- v0.3 (Slice 0, Step 0) adds D19–D22: work runs on the laptop, the build order may be re-ordered to reach the verdict first, corporate actions and circuit limits are handled in Phase 1, and the go/no-go rule is pre-registered (§5.9, §5.11). Records the first fixture findings in §5.1 and §5.9.
- v0.2 switches the LLM from OpenRouter free models to the OpenAI API with model routing (D4, D5, §3, §6).

How to read this file:
- **Decided**: chosen by Sravanth. Don't change without asking.
- **Default**: proposed and not objected to. Fine to implement; flag it if reality disagrees.
- **Open**: undecided. Ask before implementing any choice.
- **Verify**: an assumption to check in Slice 0 before building on it.

---

## 1. Goal

Find out, with evidence, whether NSE order-win filings move stock prices in a way Sravanth can trade, before building anything live.

Phase 1 builds:
1. **Collector**: every NSE corporate announcement, with the exchange timestamp and our first-seen timestamp. (BSE dropped by D26.)
2. **Category lookup (router)**: route each filing to a bucket using the exchange's own category. No LLM.
3. **Order extractor**: pull order details from the filing PDF and normalize the value to rupees.
4. **Revenue loader**: point-in-time trailing-12-month (TTM) revenue from NSE quarterly results (XBRL).
5. **Calculator**: order value vs TTM revenue and vs market cap.
6. **Backfill + event study**: run 1–5 over 12 months of history and measure price moves after order wins.

We collect and classify everything, but act only on order wins.

### Not in Phase 1
Order placement or any broker code · media sources (Moneycontrol etc.) · live alerts ·
**scored-orders / daily-digest Google Sheets sync** (D11's Phase 2 scope — a plain
view-only mirror of the raw filings runs now, §7 `sheets_sync`) · intraday prices ·
SME-platform companies · everything in §5.12.

---

## 2. Decisions

| # | Topic | Decision | Status |
|---|---|---|---|
| D1 | Development | Claude Code on the Windows laptop → private GitHub repo → VPS pulls | Decided |
| D2 | Runtime | Docker Compose services on the Hetzner CX22, next to n8n | Decided |
| D3 | Database | New database `tradebot` inside the existing Postgres; never touch n8n's database | Decided |
| D4 | LLM | OpenAI API on existing credits, with model routing: code first (T0), a cheap model (T1), a stronger model only on escalation (T2) | Decided |
| D5 | LLM budget | As close to zero as possible: hard spend caps, with a queue that waits at the cap (cap amounts in §6 are Default) | Decided |
| D6 | Polling | **Revised 23 Sep 2026 into three jittered bands** on a trading day: **60 s from 08:00 to 15:30** (continuous trading), **3 min from 15:30 to 22:00** (post-close), **10 min** outside those and on non-trading days. The original was a flat 60 s to 22:00. The window still runs to 22:00, and the reason is now measured rather than asserted: on 17 and 21 Sep 2026, **64% and 67% of the day's filings arrived after 16:00**, and the single busiest hour of the day is **17:00** — companies file when the board meeting ends, not when trading closes. The live feed on 23 Sep agreed (32% after 15:30 by 16:38, with the day unfinished). So the post-close window is eased off, not switched off: dropping it to 10 min was considered and rejected, because the endpoint shows only the 20 most recent filings and that day's 16:10 ten-minute window already held 23 | Decided |
| D7 | PDFs downloaded | **Widened 24 Sep 2026 (night)**: order-win, order-candidate and **every** catch-all item (`General Updates`/`Updates`/`Press Release`), not only LLM-confirmed catch-all. Measured on 23 Sep 2026's 725 filings: only 7 sit in the order categories, but 117 are catch-all and 52 of those have a generic headline that hides whatever the PDF actually says (the HILINFRA pattern, §5.4) - so "LLM-confirmed" as a pre-download filter was circular, since confirming needs the PDF text the filter was gating. Links only for the rest. The LLM itself stays gated separately: `router/orders.py`'s `llm_allowed` decides which of these downloaded documents may reach OCR or extraction (§5.4, §6) | Decided |
| D8 | PDF retention | Delete each PDF after text extraction; keep text, URL and SHA-256. The `tests/labelled/` PDFs stay in the repo permanently — **exception confirmed** | Decided |
| D9 | Universe | NSE mainboard only. The original clause about BSE filings for dual-listed companies is moot since D26 dropped BSE from Phase 1 | Decided |
| D10 | Backfill | 12 months of announcements. Prices, market caps and band hitters: 12 months **+ 30 trading days**, so the −20-day pre-event window and 20-day average volume have room at the start. Results: 24 months, so four quarters precede the earliest event | Decided |
| D11 | Google Sheets | Phase 2: scored orders + daily digest, one-way (view-only). **Narrowed forward, v1.2**: a plain one-way mirror of `raw_announcements` (no scoring, no digest) runs now, so the filings can be browsed without SQL — see §7 `sheets_sync` and §9. **Extended, v1.5**: a second tab mirrors `order_extractions` (order-related filings, extractor, value, status) - still view-only and still not the Phase 2 scored/digest tab, since `value_to_ttm` and the other ratios don't exist yet (§5.10 is not built). **Extended 21 Oct 2026 (Sravanth asked; Proposed):** a third tab, `backfill_events`, one row per backfill event with its value, ratios, state and the latest study run's returns, read from `tradebot_backfill` (`sheets/backfill.py`). Still view-only, and not live alerts or a digest | Decided |
| D12 | Python | Same version on laptop and VPS: 3.14. **Windows/cp314 verified** in Step 0 — all 11 approved deps installed from wheels on 3.14.2, no source builds. **Linux verified 27 Sep 2026**: the Docker image (python:3.14-slim, Python 3.14.7) installs every approved dependency from manylinux wheels, and the unit suite passes inside it (259 passed; the 2 layout checks that fail there look for docs excluded from the image on purpose) | Default |
| D13 | Secrets | `.env` on each machine only; `.env.example` committed | Default |
| D14 | Backups | Nightly `pg_dump` of `tradebot` to Google Drive, in place **before the backfill**, not before live use: the backfill is weeks of scraping plus LLM spend and is the expensive thing to lose. **Mechanism decided 27 Sep 2026: rclone** to a Google Drive remote, run nightly by cron on each machine that holds a database worth keeping (the VPS for live data, the laptop while the backfill runs) | Default (mechanism Decided) |
| D15 | LLM logging | Every call logged: model, prompt version, tokens, status | Default |
| D16 | Raw data | Append-only; never edited | Default |
| D17 | Time | `timestamptz` everywhere; Asia/Kolkata at the edges; no naive datetimes | Default |
| D18 | Alerts | Deferred until after the backfill verdict | Default |
| D19 | Where code runs | Spikes and the 12-month backfill run on the **laptop, over a phone hotspot — not the campus network** — into a local Postgres. The VPS runs only the live collector, writing to a `tradebot` database created in the existing Postgres via `docker exec psql`. No SSH tunnel and no change to n8n's containers in Phase 1. **Widened 27 Sep 2026 (Sravanth): the VPS runs all three live processes** - the collector, `orders --follow` and the Sheets mirror - not the collector alone. The laptop cannot reach the VPS database without the tunnel this decision rules out, so leaving extraction on the laptop would cut it off from live data. The cost is that the VPS IP also downloads order-related and catch-all PDFs from `nsearchives.nseindia.com` (about 120-170 a day at the >=3 s backfill pace) and calls OpenAI. The live data the laptop collected from 23 Sep is moved to the VPS once, by `pg_dump` and restore at cutover | Decided |
| D20 | Build order | §10 stays as written for now. A revised build order is proposed **after** Slice 0, from the spike results | Decided |
| D21 | Price data quality | Corporate actions and circuit limits are handled in Phase 1, not deferred (§5.9, §5.11) | Decided |
| D22 | Verdict | The go/no-go rule is pre-registered in §5.11 and fixed before any returns are computed. **Revised 27 Sep 2026, before any return was computed (Sravanth):** the primary market-cap band is ₹500–20,000 crore on the event's valuation date, replacing "below ₹10,000 crore"; everything else in the rule is unchanged | Decided |
| D23 | Live collection | Not deferred to Phase 2. After Slice 0, a **minimal NSE-only live collector** runs on the VPS: raw store only, no BSE, no dedup, no health dashboard. Rationale: `first_seen_at` cannot be backfilled, and forward-collected data is the only honest test for anything found by exploration (§5.11) | Decided |
| D24 | NSE terms of use | **Sravanth's decision (21 Sep 2026): proceed.** Phase 1 collects public corporate filings for personal research, redistributes nothing and runs at low volume. Recorded as the owner's call on his own risk, not as a legal conclusion reached by this document — the conflicting texts stay quoted in §3 so the decision is auditable | Decided |
| D25 | No evasion | The collector is a **polite client, not an evasive one** (Decided). Permitted: fixed low rates, jitter, session warm-up, exponential backoff, a single consistent User-Agent, honouring errors. Not built: proxy or IP rotation, User-Agent rotation, browser fingerprint spoofing, CAPTCHA solving, or anything else whose purpose is to defeat the Akamai layer rather than to reduce load. Beyond the principle, this is also what works: bot management scores rotation and spoofing far more harshly than a slow, steady, consistent session, so evasion is the thing most likely to earn the hard block D19 exists to avoid | Decided |
| D26 | BSE | **Dropped from Phase 1 — final.** Spike A2 passed without it: mainboard order coverage through NSE alone is 8/8 on the day tested, so BSE has nothing to add and will not be probed again in Phase 1. D9 already restricted BSE to companies also listed on NSE, which makes it pure duplication for the study, and it was never probed. Dropping it removes a second anti-bot surface and most of Slice 2. The "which exchange publishes first" question that justified keeping both timestamps is answered for free by the API's `difference` field (§5.1). Revisit in Phase 2 only if it earns its place | Decided |
| D27 | Trading-day calendar | **Split by direction.** Past dates: a trading day is any date for which a UDiFF bhavcopy or PR bundle exists — free, self-maintaining, and correct because the answer is already known. Future dates: Sravanth uploads `config/holidays_2026.yaml` by hand. The bhavcopy is published *after* the close, so its existence cannot tell the live collector at 08:00 whether today is a trading day; using it that way would put a look-ahead dependency in the one place the system runs forward | Decided |
| D28 | VPS | **Cancelled, Oct 2026** (Sravanth). D1/D2's deploy path (git pull on the VPS, Compose next to n8n) is void until he chooses hosting at GATE 2. D19's live half and D23 run nowhere meanwhile: the live collector last polled 1 Oct 2026 09:31 on the laptop, and the `first_seen_at` hole from then on is permanent. The pg_dump cutover never happened, so the live data stays on the laptop. Spike E is moot | Decided |
| D29 | LLM provider at GATE 1 | 20 Oct 2026. The brief said "free OpenRouter models only, $0"; asked at the gate, Sravanth chose to **keep the OpenAI API under the existing caps (D4, D5, §6), buying no credits**. The OpenRouter line described the v0.1 design. Spent before the gate: $0.45 of the $3 backfill cap, $0.11 on the live path | Decided |
| D30 | Live runner | 20 Oct 2026 (Sravanth, GATE 1). Live collection restarts only through **one process** that polls and then runs the order pipeline in the same loop, holding an NSE lock, because the brief allows only one process on the machine to talk to NSE at a time. The old two-process setup (collector + `orders --follow`) is retired | Decided |
| D31 | Third documents tier | 20 Oct 2026 (Sravanth, GATE 1): **skipped.** The 24,425 catch-all PDFs that only a body check could turn into orders (~24 GB, ~37 h over the hotspot) are not downloaded; the verdict uses tier one (order categories plus headline hits), and the report states the undercount (on live data about one order in four was visible only in a PDF body). Reverses the 27 Sep plan to fetch them on later nights, and WORKLOG's rule that `study` waits for every tier. D7 is unchanged for the live path | Decided |
| D32 | Stated bounds | 20 Oct 2026 (Sravanth, GATE 1). "over ₹X" (also above, more than, exceeding, at least) gives value_inr = X with a `lower_bound` flag, so it can pass D22's ≥15% test conservatively; a range gives low/high with value_inr = low and a `range` flag; a band-only disclosure (a size legend, no figure) gives null + `band_only`, sent to review | Decided |

---

## 3. Constraints that shape the design

- **VPS**: Hetzner CX22, which is 2 vCPU, ~3.7 GB RAM and ~39 GB disk, shared with n8n, Postgres, Caddy and Jarvis Mini. Disk is the binding constraint, so PDFs are deleted after extraction and every container gets a memory limit.
- **LLM cost**: OpenAI API on existing credits, with near-zero spend as the goal. Current prices differ by ~50× on input between the cheapest current-generation model (GPT-5.6 Luna, $0.20 per million input tokens) and the flagship (GPT-6 Astra, $10). The design follows from this:
  - code first;
  - the cheap model for most LLM work;
  - the strong model only on objective escalation triggers;
  - the Batch API for the backfill;
  - hard spend caps, with a queue that waits instead of failing.
- **Exchange websites**: expect anti-bot behaviour (browser-like headers, session cookies, 401/403 on bare requests). Be polite: backoff, no parallel requests, and a *jittered* interval rather than a fixed one — perfect periodicity from a datacentre IP is the clearest bot signature there is.
  The VPS IP is whitelisted with Angel One. NSE blocking it would not affect the broker (different hosts), but the IP is identified and expensive to change, because rotating it means redoing the broker whitelist. So the data source and the trading access share a single address where only one of them is cheap to replace.
  Hence D19: the backfill — by far the highest-volume, highest-risk traffic — runs from the laptop, and the VPS only ever polls at a low rate.
- **robots.txt vs the terms of use — they conflict** (Spike B, both read 21 Sep 2026; **Open**, §11).
  - `https://www.nseindia.com/robots.txt` is permissive in full: `User-agent: *`, `Allow: /`, with a single `Disallow: /market-data-test`. Nothing this project touches is disallowed.
  - `https://www.nseindia.com/static/nse-terms-of-use` says the opposite, verbatim: "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."
  - The clause is written about the *Website / Mobile Application*. The files this project reads are pre-built static archives on `nsearchives.nseindia.com`, which is arguably a different thing — but that is a legal reading, not an engineering one, and this document does not make it. Recorded here so the choice is Sravanth's, made knowingly, rather than something that happened by default.
  - Facts either way: the filings are public disclosures, nothing is redistributed, the volume is small and paced, and Phase 1 is personal research.
  - **Resolved by D24**: Sravanth's call is to proceed. Both texts stay quoted above so the decision remains auditable, and D25 fixes what "proceed" does and does not license.
- **Anti-bot layer** (Spike B, Verified): the homepage sets `AKA_A2`, `_abck`, `ak_bmsc` and `bm_sz` — Akamai Bot Manager. A session warm-up against `https://www.nseindia.com/` is required before the archive hosts will answer, and the request must carry browser-like headers. This sits awkwardly against §5.1's "consistent, identifiable User-Agent": an honest UA is what robots.txt would invite, and is also what the bot manager is most likely to refuse. Unresolved (§11).
- **Volume** (one ordinary day, NSE only, Fri 18 Sep 2026): ~1,229 announcements from ~881 companies, of which 22 were order-win filings from 12 companies.

---

## 4. System overview

```
[collector]  NSE announcements   (60 s in market window / 10 min otherwise, jittered)
      |
      v
raw_announcements  (append-only)
      |
      v
[normalizer]  attach ISIN → keep NSE-mainboard universe → merge repeat filings into one event
      |
      v
[router]  exchange category → bucket  (config/category_map.yaml)
      |-- noise ............ stored, nothing else
      |-- other_material ... stored (used for contamination checks)
      |-- red_flag ......... stored (Phase 2: alerts on held names)
      |-- results .......... stored (revenue loader uses results filings)
      |-- catch_all ........ keyword prefilter → LLM triage (budgeted) → may become order_candidate
      |-- order_candidate .. ┐
      `-- order_win ........ ┴→ [documents] download PDF → text → delete PDF
                                        |
                                        v
                          [extractor] annexure parser → LLM fallback → verify → unit normalizer
                                        |
[revenue loader] results XBRL → financials → point-in-time TTM revenue
[market data]    NSE bhavcopy + market-cap file → prices, market_caps, Nifty
                                        |
                                        v
                          [calculator] value ÷ TTM revenue · next-12-month value ÷ TTM revenue · value ÷ market cap · flags
                                        |
                                        v
                          [backfill + event study] 12 months → report by bucket → go / no-go
```

---

## 5. Components

### 5.1 Collector
Purpose: capture every announcement exactly once, with the exchange timestamp and our first-seen timestamp.

- **Sources** (all URLs, headers and parameters live in `config/sources.yaml`, never hardcoded):
  - NSE corporate announcements: `GET https://www.nseindia.com/api/corporate-announcements`.
    **Verified** (Spike A, 22 Sep 2026) — the live query, the date-range query and the full field list are documented below. NSE also publishes an official RSS feed; it is still untested and remains a possible cross-check.
  - BSE: **removed from Phase 1 by D26.**
- **Modes**:
  - `live`: poll on the schedule below.
  - `backfill`: date range, resumable (checkpoint per source per day), slow pacing (Default ≥3 s between requests).
- **Schedule** (D6, revised 23 Sep 2026): on trading days, every **60 s** from 08:00 to 15:30 and every **3 min** from 15:30 to 22:00, all **jittered**; every 10 min at all other times and on non-trading days. The bands live in `config/sources.yaml` under `pacing.bands` and are half-open, so 15:30 belongs to the post-close band only. Post-close is slower but deliberately not idle: most of the day's filings arrive there (see D6). A fixed interval from a datacentre IP is the clearest bot signature there is, so the interval is never exactly periodic. Trading days come from D27: for **past** dates, a day counts as a trading day if a UDiFF bhavcopy or PR bundle exists for it; for **future** dates, from `config/holidays_2026.yaml`, which Sravanth maintains by hand (template: `config/holidays_2026.example.yaml`). The live collector **fails loudly** when that file is missing, unparseable, or has no entry covering today — it must never fall back to assuming every day is a trading day, because that failure is silent and would poison `first_seen_at` for the forward-collected sample.
  - **Special sessions** (D27). A Muhurat session trades on a weekend and lasts about an hour: 8 Nov 2026 falls on a Sunday, and 21 Oct 2025 sits inside the backfill window. The archive-derived calendar handles past ones correctly with no special case, because a bhavcopy is published for them; the hand-maintained file must be able to say so in advance, which is what its `special_sessions` block with `trades: true` and `full_length: false` is for.
  - **Post-close reconciliation** (D27). After each day's bhavcopy lands, compare what the calendar predicted against what the exchange did, and alert on either direction: predicted trading but no bhavcopy (an unannounced closure), or predicted closed but a bhavcopy exists (a special session nobody entered — exactly the Muhurat failure). This is the only check that catches a stale file before it silently costs a day of collection.
  - **Next year's file**: from **1 December**, warn once a day until `config/holidays_<year+1>.yaml` exists. The collector would otherwise fail loudly on 1 January, which is correct but late.
- **Idempotent**: unique on (source, source_id); re-polling never creates duplicates.
- **Politeness**: one request at a time per source; exponential backoff with jitter on errors; on 401/403, refresh the session once, then back off; consistent User-Agent.
  **Built 20 Oct 2026 (brief, D30): one gate for every NSE request, `src/reg30_radar/common/nse_guard.py`.** The audit found that each of the three clients paced only against its own last request, that no loop stopped on repeated failure (a DNS outage on 4 Oct marked 55 companies failed in three minutes, and the backfill's 401/403 stop could never fire), and that nothing kept a second process off NSE. The gate does four things:
  - It takes `data/nse.lock` on a process's first NSE request (PID, start time, command line). A second live process refuses with `NseBusy`, and a lock left by a dead process is replaced. On Windows, liveness is checked with `OpenProcess`, because `os.kill(pid, 0)` there terminates the process.
  - It measures the gap from the end of the previous NSE request on any host: `live_min_gap_seconds` (2 s), or the backfill's 3 s, plus jitter.
  - It sets backoff after a failure (≈30, 60, 120, 240 s with jitter) as a minimum gap rather than an extra sleep, so it never compounds with a caller's own backoff.
  - The 5th consecutive failed request raises `NseHardStop` (a BaseException, so the clients' `except Exception` cannot swallow it). Entry points end through `nse_guard.run`, which logs one line and exits 3.
  Warm-ups are paced and status-checked like any request. A JSON body that is neither a list nor an object with a `data` list, or announcement rows missing the keys `collector/records.py` reads, raise `NseStructureChanged` at once.
  **Proposed** (implementation choices, 20 Oct 2026):
  - A clean archive 404, and a file over the size cap, do not count as failures.
  - A PDF that comes back as a non-PDF (an Akamai page) does count.
  - The live collector now exits after 5 consecutive failed polls instead of backing off for ever. Restarting it is the hosting layer's job (GATE 2).
- **Health**: update `source_health` on every poll. Log a warning if a source has no successful poll for 10 minutes inside the market window.
- **The live runner, built 20 Oct 2026 (D30): `python -m reg30_radar.live`.** One process polls on D6's schedule and, after each poll, runs the order pipeline (§5.4-5.6) in the same loop, under the NSE lock. Each cycle's order work has a budget, so the next poll is never late: at most `live_filings_per_cycle` filings (6), and none started within `live_poll_margin_seconds` (20 s) of the next poll; the rest are taken next cycle (`config/documents.yaml`). It stops with exit code 2 on a missing or unusable holidays file, instead of polling on; it exits 3 after 5 consecutive failed NSE requests (`nse_guard`). It warns once when no poll has succeeded for 10 minutes inside the trading window, and once a day from 1 December until next year's holidays file exists. Restarting it is the hosting layer's job (GATE 2). `collector` and `orders --follow` remain as modules, but are not run side by side any more.
- **Catch-up, built 20 Oct 2026: `python -m reg30_radar.catchup`.** One date-range request per calendar day, from the day of the last successful live poll to today. Each request gets a `source_health` row; an answer holding rows from other days, or a round size of 1,000 or more, is flagged. Rows carry `collected_via = 'catchup'` (migration 0018; `live`, `gap` and `backfill` are the other values), so a recovered row never passes as a live `first_seen_at`. It only collects; `live` works through the backlog within its budget and lookback. **21 Oct 2026 (Sravanth): the 1-20 Oct backlog is not processed**, so the lookback is 6 h (`live_lookback_days: 0.25`); those 7,806 rows stay stored, without their PDFs.
- **Order-path retries, fixed 20 Oct 2026 (GATE 1 audit).** A connection-level download failure (DNS, reset, timeout) uses up none of a filing's 3 attempts. A provider failure (`llm/client.py`'s `LlmProviderError`) leaves the filing `pending_llm` and ends the cycle's order work; on the OCR path it no longer marks the document unreadable for good. A `pending_llm` filing is never dropped: it is exempt from the attempt cap (the 15-minute spacing stays), is read however old it is, and is retried from its stored text, with no second download.
- **Stored** (raw): source, source_id, payload hash, exchange_ts, first_seen_at, symbol, company name, ISIN, raw category string, headline/description, attachment URL, full payload (jsonb). `source` is retained even though D26 leaves only NSE, so adding a second source later needs no migration.
- **Verified** (Slice 0 Step 0, from `tests/fixtures/an18092026.txt`, 1,265 lines): the PR bundle's announcement file carries **company name, symbol, category and description text — and nothing else**. It has no per-filing timestamp, no attachment URL and no ISIN.
  Consequences: (a) the PR bundle **cannot** drive the backfill on its own, because day-0 determination and point-in-time discipline need the exchange timestamp, and the document pipeline needs the PDF link — both must come from the JSON endpoint or the per-filing page; (b) the file **is** sufficient to test the router (§5.4), which only reads the category string; (c) it is a good completeness cross-check on whatever the JSON endpoint returns for the same day.

#### Spike A findings (22 Sep 2026)

**Verified — the record shape.** `GET https://www.nseindia.com/api/corporate-announcements`
returns a bare JSON array. Headers and the warm-up URL are now in `config/sources.yaml`.
Twenty fields, every one populated in the sample:

| Field | Example | Use |
|---|---|---|
| `seq_id` | `106784063` | identifier — **but null on older records** (see below) |
| `sm_isin` | `INE00RL01028` | **the ISIN**, 100% populated across 1,035 BEL records |
| `smIndustry` | `Textile Products` | **the sector source §5.8 needed**, but see coverage below |
| `an_dt` | `18-Sep-2026 10:17:50` | filing timestamp, **with time of day** |
| `exchdisstime` | `18-Sep-2026 10:17:52` | exchange dissemination timestamp |
| `difference` | `00:00:02` | the lag between the two, given for free |
| `desc` | `Press Release` | the category string the router keys on |
| `attchmntFile` | `https://nsearchives.nseindia.com/corporate/HIGHWAY123_…pdf` | the PDF URL |
| `hasXbrl` | `true` / `false` | 111 true, 924 false across BEL's history |
| `sm_name`, `symbol`, `sort_date`, `dt`, `attchmntText`, `fileSize`, `attFileSize` | | supporting |
| `old_new`, `bflag`, `csvName`, `orgid` | all `null` | no revision marker is exposed here |

`difference` is worth noting: §5.3 wanted to learn which exchange publishes first, and this
field already gives NSE's own filing-to-dissemination lag per record, at no cost.

**Verified — identity.** `seq_id` is **null on older records**: 193 of BEL's 1,035 rows, all
of them pre-2015. It is therefore not usable as a primary key on its own across the archive.
`(seq_id, an_dt)` was unique across all 1,035 rows, and every row was distinct as a whole
record. This supports the payload-hash key in §5.3 rather than a bare `source_id`.
No `modified`, `revision` or `updated` field exists, and `old_new` was null on every row, so
**the API exposes no revision marker** — revisions have to be detected by payload hash.

**Verified — sector coverage is not total.** `smIndustry` was populated on 1,035 of 1,035
BEL records, but was `None` for HILINFRA. So it is the right source for the bank / NBFC /
insurer exclusion, and the exclusion still needs a fallback for the names it misses.

**CHANGED — the API is a partial view of any past day, and cannot drive the backfill.**
This reverses the hybrid plan as written in v0.5, which assumed the API was authoritative and
the bundle merely lacked timestamps. The opposite is true. Four query modes, each limited
differently:

| Query | Result |
|---|---|
| no parameters | the 20 most recent records only |
| `symbol=BEL` | 1,035 records spanning **22-Sep-2004 to 17-Sep-2026** — 22 years, 70 of them in 2026 |
| `from_date=18-09-2026&to_date=18-09-2026` | 563 records across 392 symbols |
| `symbol=BEL` **and** the date range | **0 records**; same for MASON; HILINFRA returned 1 |

The date-range result is the serious one. For 18 Sep 2026 it returns 563 filings, where the
PR bundle's `an18092026.txt` carries roughly 1,229. **BEL and MASON are absent from the API
response entirely**, although the bundle shows BEL filed twice and MASON five times that day.
In order-bucket terms the API returned **3 order wins where the bundle shows 22**.

The timestamps in that response span `00:20:00` to `23:59:24`, so it is not truncated by time
of day, and all 563 `seq_id` values were distinct, so it is not deduplicated either. It is
simply a subset, and not one whose rule is yet known.

**Consequence for §5.1.** The daily PR bundle is the **complete** record of what was filed;
the API is the only source of the timestamp, ISIN, industry and PDF URL, and it does not carry
most past filings. So the hybrid cannot be built as specified until that gap is understood.
Unknown, and the subject of the next spike: whether a different `index` value, a pagination
parameter, or the CSV export hinted at by the null `csvName` field reaches the full day.
Until then, **no backfill design should assume a PDF URL is obtainable for an arbitrary past
order filing.**

**Volume estimate (question 5), contingent on that being solved.** From the 18 Sep fixture:
22 `order_win` + 1 `order_candidate` = 23 filings needing a lookup, from 12 distinct companies.
Over ~250 trading days that is roughly **5,750 per-filing lookups**, or about **3,000
symbol-day lookups** if one call per company per day serves all of its filings. At the
§5.1 pacing of one request every 3 s that is 5 to 10 hours of polite traffic — entirely
feasible, and spread over the laptop's hotspot under D19. Volume is not the obstacle;
completeness is.


#### Spike A2 findings (22 Sep 2026) — the gap is inside the universe, and it is fatal

Spike A compared 563 API records against all 1,229 bundle bodies. That was the wrong
denominator: the study only cares about NSE mainboard. Measured properly, against
`tests/fixtures/an18092026.txt` and the 18 Sep bhavcopy for segment:

| Segment | Bundle bodies | Missing from API | Companies | Wholly absent |
|---|---|---|---|---|
| **Operating companies** | 976 | **700 (72%)** | 680 | **462 (68%)** |
| Funds / ETFs | 48 | 46 (96%) | 46 | 45 |
| SME | 99 | 99 (100%) | 56 | 56 |
| Not in the bhavcopy | 106 | 105 (99%) | 98 | 97 |

The decisive number is narrower still. **Of the 23 order filings that day, the API carries
2.** BEL filed twice and appears not at all; MASON filed five times and appears not at all.
Only BEML and ZAGGLE come through, one filing each.

**It is not an ageing effect.** 21 Sep 2026, three days before this was measured, shows 493
API records against 1,670 bundle lines — **30%**, the same as 18 Sep. The API is
approximately 30% complete at every depth tested, so **shrinking the study window gains
nothing**: there is no recent period where the data is whole.

**No parameter reaches the full day.** Tested and rejected: `csv=true` (returns the same 563
rows, as `text/csv`, with columns SYMBOL, COMPANY NAME, SUBJECT, DETAILS, BROADCAST
DATE/TIME, RECEIPT, DISSEMINATION, DIFFERENCE, ATTACHMENT); `page=2` (ignored, same 563);
omitting `index` (`Missing index`); `type=xbrl` (ignored); `index=equities_xbrl` (empty).
The filings page offers two views, "Announcements" and "Announcements XBRL", so a second
view exists — but every one of the 563 records already has `hasXbrl: true`, and none carries
an `-XBRL` suffix in `desc`, so the split is not simply XBRL versus not. The parameter that
selects it is still unknown.

**CORRECTED (same day, before this was acted on).** Two measurement errors of mine made the
gap look far worse than it is.

1. **The bundle is a *report*, not a filing-date index.** `an18092026.txt` covers filings
   disseminated since the previous report, so it contains filings timestamped the evening of
   17 Sep. BEL's `Bagging/Receiving of orders/contracts` sits at `17-Sep-2026 16:43:18` in the
   API — after the 15:30 close — and appears in the 18 Sep bundle. Comparing bundle(D) against
   API(D) was a category error.
2. **The "symbol query stops at Oct 2025" claim was a string-sort artifact**, from sorting
   `DD-Mon-YYYY` lexicographically. It actually spans 22-Sep-2004 to 17-Sep-2026.

Re-measured with a two-day window (17 + 18 Sep, 1,029 API records):

| Measure | Same-day only | Two-day window |
|---|---|---|
| Bundle bodies covered | 279 / 1,229 (23%) | 538 / 1,229 (44%) |
| Bundle symbols wholly absent | 660 / 880 | 505 / 880 |
| **Order-filing symbols found** | 3 / 12 | **8 / 12** |

And the eight found are **exactly the eight mainboard issuers**: BEL, BEML, CPL, GPTINFRA,
JISLDVREQS, JISLJALEQS, UNIVASTU, ZAGGLE. The four missing — MASON, INNOMET, ENVIRO, MDL —
are all SME, which D9 excludes from the universe anyway.

**So for the study universe, order coverage on the day tested is 8 of 8.** The residual 56% of
uncovered bodies is SME, debt, funds and window edges, none of which Phase 1 needs. The
backfill is **not** blocked, and the 30%-at-every-depth figure in the table above is an
artifact of the wrong denominator and the wrong date window, not a property of the API.

**This makes the hybrid better than originally designed.** The symbol query returns a
company's entire 22-year history in one call, so the backfill is one request per *company*,
not per company-day: roughly 300–600 distinct mainboard order filers over twelve months,
which at §5.1 pacing is well under an hour of traffic.

**Still to confirm before Slice 1 builds on this** — one day proves a pattern, not a rate:
- the exact report-window boundary (is it previous close to today's close, or a fixed hour?),
  which decides whether a ±1-day or ±2-day window is needed for reconciliation;
- whether 8/8 holds across several days, not one;
- whether the *live* endpoint carries the same completeness as the symbol query, since D23's
  forward collection depends on it. Poll it for one full day and reconcile against that
  evening's bundle.

**BSE was not ruled in or out.** Two requests were spent against
`api.bseindia.com/BseIndiaAPI/api/AnnGetData/w`; both returned HTTP 200 with the body
`"No Record Found!"`, meaning the endpoint is live but the parameter shape was guessed wrong.
D26 stands as a live-path decision; BSE as a historical source is untested and now unlikely
to be needed.

- **Hybrid backfill plan** (follows from the above). Two sources, each doing only what it is good for. Per the A2 correction, the API half **does** work for past dates provided the report-window offset is respected:
  1. **Daily PR bundle** — prices, market caps, Nifty, band hitters, and a daily index of *who filed what category*. One archive download per trading day, no anti-bot surface.
  2. **Announcements API** — called **once per company** that the bundle's index shows filing an `order_win` or `order_candidate`, using `symbol=`, which returns that company's whole history in one response. Match the bundle's report-date entries against it on a ±1-day window, never same-day.
  This keeps API traffic proportional to order filings (roughly 22 a day) rather than to all filings (roughly 1,229 a day) — about a 55× reduction against paginating the API for the full history.
  **CHANGED 27 Sep 2026 (Sravanth): company-wise over a filtered list.** The backfill does not cover every company. Sravanth supplies **criteria** (market-cap band, series, sector exclusions and the like), and code builds the company list from the data **as of 22 Sep 2025**, the window start. It uses the last trading day on or before that date, so the list cannot see the future. Companies delisted during the year stay in; companies listed after that date are out. The list is frozen before any return is computed (D22). For each listed company the backfill makes **one `symbol=` query**, which returns its whole filing history in every category, and keeps the window. Why company-wise: the history is complete per company, which is exactly what per-ISIN contamination (§5.11) and catch-all orders need; the study measures each company's price response to its own orders; TTM revenue is fetched per company anyway; and the request count is the list's length. §5.1's original plan picked companies by "filed an order category", which would have missed orders filed under catch-all categories; a list fixed by criteria does not have that gap. For listed companies, PDFs are downloaded for the order categories **and every catch-all filing** (D7 as widened). `reconcile.py` runs per report date with `universe=` set to the list, so the 95% coverage gate measures the listed companies. The listed companies' order-filing count is taken from the PR bundles before any PDF is downloaded, because D22 needs ≥30 clean primary-bucket events. **Verified 27 Sep 2026:** a `symbol=` query for a company's **current** symbol returns its whole history, including filings made under an earlier symbol, which the API relabels (LTIMindtree's 153 in-window filings come back under `LTM`); the earlier symbol returns nothing. The fetch queries every symbol the ISIN traded under, so both are covered. Two related identity facts from the same run: NSE's announcements carry a company's *original* ISIN (§5.3), and 38 universe companies were issued a new ISIN during the window (§5.9). The backfill writes to its own laptop database, `tradebot_backfill` (`BACKFILL_DATABASE_URL`), so 12 months of history never reaches the live database, the Sheet or `orders --follow`.

### 5.2 Instruments and ISIN map
Purpose: one identity per company (ISIN) behind any NSE symbol. This also defines the universe.

- NSE side: the daily UDiFF bhavcopy gives ISIN, symbol and series.
  - **Verified** (Spike B, 21 Sep 2026). URL pattern:
    `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`
    — a zip holding one CSV of the same name. Fetched 200 for 2025-08-05, 2025-08-06, 2026-03-11, 2026-07-16, 2026-07-17 and 2026-09-18, so depth comfortably exceeds the 12 months + 30 trading days D10 asks for.
  - 34 columns, and the column set is **identical to the BSE UDiFF fixture** already in `tests/fixtures/`. One parser handles both exchanges, which is what §5.2 assumed.
  - `ISIN`, `TckrSymb`, `SctySrs`, `OpnPric`, `ClsPric` and `PrvsClsgPric` all present on every date checked.
  - Size: about 3,080–3,440 rows across all series, of which roughly 2,380 are `EQ`.
- BSE side: **out of scope (D26)**. The BSE UDiFF bhavcopy existed only to map scrip codes to ISINs so BSE filings could be processed, and there are no BSE filings now. `tests/fixtures/BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV` stays in the repo as the evidence that both exchanges publish an identical UDiFF column set, which is what lets one parser serve either.
- Universe rule (D9, unchanged): the ISIN has an NSE mainboard listing (series other than SM/ST). Filings for ISINs outside the universe are stored raw and not processed.
- Store but don't act on in Phase 1: NSE series (EQ vs BE/BZ), ASM/GSM membership. These become trade-time filters later.

### 5.3 Normalizer and dedup
- Attach ISIN: from the announcement's own `sm_isin` field where present (Spike A found it 100% populated on the records it returns), otherwise by symbol against the bhavcopy.
  **CHANGED 27 Sep 2026 (night): `sm_isin` is the company's *original* ISIN, not its current one.** NSDL reissues an ISIN after a face-value split, and the bhavcopy carries the new one, but the announcements API keeps tagging filings with the old: JSWSTEEL files as `INE019A01020` and trades as `INE019A01038`. So `sm_isin` identifies the company correctly but cannot be joined to prices, market caps or the universe as-is. Every such join compares the ISIN's **issuer code**, its first seven characters (`INE019A`), never the whole ISIN (`src/reg30_radar/common/isin.py`; `left(isin, 7)` in SQL), and a backfill event carries the universe's current ISIN. Found when 85 of the first 495 backfill companies (17%, HDFCBANK, SBIN and HAL among them) kept no filings although the API had returned hundreds each; measured against the live feed, 65 of 65 such companies showed the mismatch and 294 of 294 working ones did not. No two universe companies share an issuer code. A same-issuer bond ISIN (HUDCO's `INE031A07873`) counts as the same company, since category, not ISIN, decides whether a filing matters. `raw_announcements.isin` still stores exactly what NSE sent.
- Normalize the category string: trim, collapse spaces, strip a trailing `-XBRL`. Keep suffixes like `(Sub-para 4-Para B)` as a separate `para` attribute.
- **Dedup** (Decided). D26 removes the cross-exchange case, but dedup still matters *within* NSE: MASON filed five times on 18 Sep 2026, four of them `(Sub-para 4-Para B)` repeats of the same order.
  Merge only on an **exact** key — the same attachment SHA-256, or the same (ISIN, `value_inr`). Never on "similar headline": companies routinely file several *genuinely different* order wins on the same day (18 Sep 2026: 22 order filings from 12 companies), so a fuzzy rule would collapse real, distinct events. A merged `event` holds every contributing raw row; event time = earliest exchange timestamp.
- **Revisions** (Decided). `raw_announcements` is append-only *and* unique on (source, source_id), which on its own would silently discard NSE's corrections — the same ID returns with amended text or a new attachment and `ON CONFLICT DO NOTHING` drops it with no trace. So the uniqueness key includes a **payload hash**, and a changed payload for an existing source_id is stored as a **new revision row** rather than ignored. If the source turns out to have no stable ID (Spike A), the synthesised key must be built from fields that do not change on a revision.
- The question of which exchange publishes first, which originally justified keeping a timestamp per exchange, is answered for free by the API's `difference` field — NSE's own filing-to-dissemination lag, per record (§5.1).

### 5.4 Router (category lookup)
- `config/category_map.yaml`: normalized category → one bucket from {`noise`, `order_win`, `order_candidate`, `catch_all`, `red_flag`, `other_material`, `results`}. (The exchange key is gone with D26.)
- Unknown category → bucket `catch_all` (safe default) and a row in `unknown_categories` for weekly review.
  **Built on the order path, 20 Oct 2026 (Proposed, matching this rule):** `router/orders.py` used to put an unknown category out of scope, and the live path never logged it. It is now read as catch_all (headline prefilter, PDF downloaded per D7) and logged once per filing when it is first processed.
- **The PR bundle does not emit a clean category field** (audit, 22 Sep 2026). This matters because §5.1 makes the bundle the only *complete* record of a past day, and the router keys on category.
  Each line of `an<date>.txt` is `COMPANY NAME SYMBOL : CATEGORY+DESCRIPTION` with **no delimiter between the category and the description**, so a category can only be recovered by prefix-matching against a known list. Measured on `an18092026.txt`: the file parses to exactly 1,229 bodies, and only **593 of them (48%)** start with one of the 49 `desc` values the API returned for the same day. Unmatched examples include `Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent`, `Alteration Of Capital and Fund Raising-XBRL` and `Board Meeting Intimation`. Part of that gap is the API's own incompleteness, but the conclusion holds either way: **the router needs a canonical category dictionary, and none exists yet.**
  - **The order buckets are safe.** `Bagging/Receiving of orders/contracts` and `Awarding of order(s)/contract(s)` are distinctive prefixes that match cleanly — that is how the 22 + 1 count for 18 Sep was obtained. The ambiguity bites `noise` versus `other_material`, and the `catch_all` keyword prefilter. It constrains Slice 3; it does not threaten order detection or the go/no-go.
  - Fix: source the category list from NSE's own filings-page dropdown during Spike A2 and commit it as `config/category_map.yaml`. Until then, any body matching no known category goes to `catch_all` and `unknown_categories`, which is the safe direction.
- **Keyword prefilter** (catch_all only). A filing becomes an LLM-triage candidate if its headline matches order / contract / award / letter of award / LoA / LoI / work order / purchase order / L1 / lowest bidder. It is suppressed if it matches orders passed / income tax / assessment / NCLT / court. Only candidates reach the LLM.
- **Built** (24 Sep 2026, night, continued): `config/category_map.yaml` and `src/reg30_radar/router/orders.py`, ahead of the full Slice-3 router. Deliberately narrower than the eventual `{noise, order_win, order_candidate, catch_all, red_flag, other_material, results}` mapping - it only encodes the four buckets already Decided above (order_win, order_candidate, red_flag, catch_all) and treats everything else as `out_of_scope`, since Slice 3's `noise`/`other_material`/`results` split and the `unknown_categories` log are not built yet. `classify()` applies the headline prefilter (both lists); `refine_with_body()` applies a second, narrower prefilter to extracted body text after download, for a catch_all filing whose headline didn't match (the HILINFRA case) - stronger phrases only (work order, letter of award/intent, LoA/LoI/L1/lowest bidder, "bagged/secured/received/won an order/contract"), because a bare "order"/"contract" match on body prose would fire on "in order to" constantly, whereas that risk is low enough on a headline to keep the full list there. `llm_allowed()` is the single function anything in `src/reg30_radar/orders/` may call before offering OCR or an LLM client to a filing - structurally, not by convention (§6).
- **Rules from the Fri 18 Sep 2026 NSE file** (these become router tests):
  - `Declaration of NAV`, `Shareholders meeting`, `Analysts/Institutional Investor Meet/Con. Call Updates`, `Analyst/Investor Meet Para A`, `Trading Window`, `Copy of Newspaper Publication` → `noise`. Together these were ~40% of the day's filings.
  - `Bagging/Receiving of orders/contracts` (with or without `(Sub-para 4-Para B)`) → `order_win`.
  - `Awarding of order(s)/contract(s)` → `order_candidate`. The category doesn't say whether the company won or gave the order (BEML filed under it). The PDF decides.
  - `Action(s) taken or orders passed`, `Actions initiated/taken or orders passed` → `red_flag`, never `order_win`. The word "order" is misleading here.
  - `Amendment or termination of orders/contracts` → `red_flag`.
  - `General Updates`, `Updates`, `Press Release` → `catch_all`. That day, a real order win arrived as a Press Release (HILINFRA: ₹220.66 crore toll-operations contract; market cap ~₹315 crore). An EPC contract under General Updates read as the company *placing* an order (GREENPOWER). A tax-appeal "order" came under Updates (KNRCON).
  - Assert on category → bucket mappings, not exact totals. The rough parse found ~1,229 filings, but multi-line entries can shift counts.

### 5.5 Document pipeline
- Runs for `order_win`, `order_candidate` and every `catch_all` item (D7, widened 24 Sep 2026 night).
- Steps: download PDF → SHA-256 → **per-page quality ladder** (pdfplumber → pypdf → vision OCR) → save kept text in `documents` → **delete the PDF** (D8).
- **Built** (24 Sep 2026): `src/reg30_radar/documents/fetch.py` (streamed download, capped at `nse.documents.max_bytes` in `config/sources.yaml` — 25 MiB by default, because the worker runs under `mem_limit: 512m` alongside n8n and pdfplumber holds a page's objects in memory while parsing, so an oversized file is the one download that can take the container down); `text.py` (extraction, already existed); `pipeline.py` (`process_url`, orchestrating the whole sequence); `store.py` (the `documents` table).
  - **Safety property, tested**: the delete step refuses any path outside the work directory it was given, even via a `..` traversal. `tests/labelled/` is D8's one permanent exception, and a pipeline bug that reached it would destroy the project's only hand-labelled ground truth — so the refusal is enforced in code (`UnsafeDeletePath`), not left to caller discipline.
  - **Ordering property, tested**: the PDF is deleted only *after* the extracted text is committed, never before. Deleting first would turn one failed transaction into a permanently lost filing, since the attachment URL is not guaranteed to stay live.
  - Dedup reuses `sha256`: a second sighting of an already-stored hash is recognised before extraction and the pipeline just deletes the redundant download, per §5.3.
  - Runs without a database (`conn=None`) for testing, matching §9's rule that most tests need none — this is what let 12 new tests run against a real labelled PDF with no live network and no Postgres.
- Keep URL, SHA-256, page count, text, extraction method and timestamps. If a later re-run needs the PDF, re-download it from the URL and check the hash matches.
- Exception (**confirmed**, D8): PDFs in the labelled test set (`tests/labelled/`) stay in the repo permanently.

**Per-page quality ladder** (**built**, 24 Sep 2026 later — `documents/quality.py`, `documents/text.py`, `documents/ocr.py`, `llm/client.py`). Replaces the earlier char-count `is_scanned` heuristic, which a live demo on 24 Sep 2026 evening showed could pass a genuinely garbled document: an invisible OCR text layer with a broken font (`GlyphLessFont`) produced plenty of characters, just wrong ones, and the old heuristic only counted characters. Fixture: `tests/fixtures/scans/hmt_glyphless.pdf`.

Each page is tried in order, stopping at the first attempt that assesses `ok` (`documents/quality.py`):
1. **pdfplumber** → assess.
2. Not `ok` → **pypdf** for that page → assess; keep the better of the two.
3. Still not `ok` → **vision OCR** (Part B below), if configured. The page is rendered with pdfplumber's own `page.to_image()` — never a direct import of pypdfium2 or Pillow, so no dependency outside §9 — as a grayscale PNG at the dpi in `config/documents.yaml`.
4. Still not `ok` → the page's outcome is `unreadable`: its text is **excluded** from `documents.text`, so noise never reaches the parser or a model, and kept in `documents.rejected_text` instead, so a quality call stays auditable without re-downloading a PDF that D8 has already deleted.

Verdict rules, in `documents/quality.py`, calibrated against the 41 pages of the 18 labelled PDFs plus the HMT fixture: `empty` (< 40 chars) · `broken_font` (`(cid:NN)` placeholders exceed 25% of tokens — set above BEML's measured ~11%, the one real case in the labelled set) · `garbled` (a page sourced entirely from a font named `GlyphLessFont`, **or**, as a safety net, ≥ 30 word tokens with a common-word ratio below 0.15) · otherwise `ok`. Document `quality` is `ok` (every page `ok`) / `partial` (some pages not) / `unreadable` (no page `ok`); §5.5's manual-review queue is `quality <> 'ok'`. `is_scanned` stays as a column, redefined as "any page is a full-page image (≥ 90% of area)" — a fact about the file's layout, not a guess about its text.

**A finding that changed the design from what was planned.** The plan for this slice expected a whole-page word-readability score alone to separate HMT's garbled page from the accepted ones, with HMT sitting "far below" the good pages' measured range (0.18–0.58). Measured against the real re-downloaded fixture, that is not true: HMT's readability score, however the word list is built, lands *inside* that range — specifically inside the range of BEL (already in the labelled set), whose page carries the exact same pattern of a garbled bilingual header next to a clean, correct English body containing the real order value ("Rs.847 Crore"). No whole-page ratio threshold can flag HMT without also flagging BEL, and BEL's real, extractable content would then be lost for nothing. What actually distinguishes them is not readability but **provenance**: BEL/HECPROJECT/HEG's full-page-image pages use real, named embedded fonts (Helvetica, Times, Calibri) — the text was typed into the PDF, a font-encoding artifact (a legacy 8-bit Hindi font) rather than evidence the content is unreliable. HMT's entire page, including the part that reads as ordinary English, comes from one font literally named `GlyphLessFont` — a third-party OCR tool's own invisible text layer, which this project has no way to independently check. So a page sourced entirely from such a font is never trusted on the strength of looking readable, the same way §5.6 never trusts a number without a provenance check. This single rule catches HMT with zero false alarms on the 41 labelled pages, none of which use such a font. Full reasoning in `documents/quality.py`'s module docstring.

**Part B — vision OCR, dormant.** Pulled forward from Slice 5's LLM client, built now but inert until Sravanth supplies `OPENAI_API_KEY`, a vision-capable `ocr_model` id with its prices, and an OCR spend cap in `config/llm.yaml` — all three ship as `PLACEHOLDER`/null. `src/reg30_radar/llm/client.py` is the one entry point CLAUDE.md requires for every provider call; it fails closed on a null cap (§6), computes cost from the price table, logs every call to `llm_calls` (`migrations/0005_llm_calls.sql`), and never retries in a loop. `documents/ocr.py`'s `maybe_transcribe` wraps it so a refusal (unset model, null cap, missing key) returns `None` rather than raising — an image page just lands as `unreadable` → review, nothing crashes. The model is a **transcriber, not an extractor**: `prompts/ocr_transcribe_v1.md` asks for a verbatim copy — numbers, punctuation and table rows as printed, `[illegible]` where unreadable, no correcting or summarising — and instructs it to ignore any instructions the image itself contains (CLAUDE.md's untrusted-document-text rule, applied to an image). The transcript then goes through the same quality check as any other attempt. A per-document page cap (`ocr_max_pages_per_document` in `config/llm.yaml`, default 10) stops one pathological PDF from triggering unbounded spend.

**Part C — provenance for vision-read numbers** (documented now, enforced when the orders state machine is built in Slice 5). §5.6 verifies a number by finding its span in the document text; on a vision-transcribed page that text *is the model's own output*, so the span check alone would be circular — it proves the extractor copied the transcript, not that the transcript matches the image. Every page now records its `source`: `text_layer` (native PDF text, not a full-page image), `ocr_overlay` (a full-page image with someone else's text layer on it, like BEL's), or `vision` (this pipeline's own OCR). A number taken from a `vision` page will not be allowed to make an order `verified` on the span check alone — it will need a second, independent read agreeing on the value, or it goes to manual review, mirroring §6's escalation trigger 4. `ocr_overlay` pages get no extra restriction: BEL's case shows a full-page-image page's real content can be reliable even when part of the page is not.
  **Enforced 20 Oct 2026** (`extractor/part_c.py`, `backfill/vision_check.py`, migration 0016; GATE 1 audit). Until then nothing enforced it, on the live path or in the backfill, and 42 verified backfill values came from documents with vision pages.
  - **Vision-sourced test.** The value's verifying quote is located in the stored text (`provenance.occurrences`). Its page is worked out from the page report: kept pages are joined by a blank line, and each page's character count is recorded. If any occurrence sits on a non-vision page, the value stands on that page. If the counts do not reproduce the text (12 of 94 OCR'd documents), the value is treated as vision-sourced.
  - **The gate.** `part_c.gate` is applied on every path that can mark a value verified: the live T0/LLM path, the Batch apply, `rejudge` and `reparse`. A vision-sourced value waits as `needs_review` with `second_read = 'pending'`.
  - **The second read**, `python -m reg30_radar.backfill vision-check`, re-reads it as follows:
    - It downloads the PDF again by its URL, and the SHA-256 must match.
    - It renders the value's page exactly as the first read did, and transcribes it blind (the model sees the image only, under purpose `ocr_second_read`, from the same OCR cap).
    - It deletes the PDF again (D8).
    - The value must verify against the new transcript.
    The result is stored with the value it was about (`second_read_inr`), so a later change of value needs a new read.
  - **Proposed:** the second read uses the same model as the first ("T2 = T1 for now", Sravanth, 27 Sep). It is blind, so it catches a misread that does not repeat, but not one the model makes every time.

### 5.6 Order extractor
Target fields. The first group mirrors the disclosure format SEBI requires for order wins (circular dated 13 Jul 2023):
- `awarding_entity`, `domestic_or_international`, `nature_of_order`, `significant_terms`, `execution_period_raw` → `execution_months`, `consideration_raw` → `value_inr`, `gst_inclusive` (true/false/unknown), `currency`, `promoter_interest`, `related_party`, `receipt_datetime` (some filings state it), `reporting_delay_reason`.

Our own fields:
- `company_is_recipient` (true/false/unknown): catches filings where the company *placed* an order rather than won one.
- `stage`: L1 / LoI / LoA / PO / contract / amendment / unknown.
- `is_follow_up`: a repeat or clarification of an earlier filing (e.g. details re-filed because NSE asked). Old news. **Determined in code, not by a model** (Decided): match (ISIN, `value_inr`, `awarding_entity`) against earlier orders. It matters more than it looks — leaving follow-ups in the sample dilutes the measured signal with non-events.
- `extractor` (`annexure_parser` or the model ID), `prompt_version`, `verified`, `review_status`.

Order of operations:
1. **Annexure parser** (deterministic, no LLM): find the labelled rows and pull the raw strings. Row labels vary: "Broad consideration or size of the order(s)", "Broad consideration for the order(s)", even the misspelt "Board commercial consideration…". Match loosely on "consideration".
2. **LLM fallback** (§6), only for required fields the parser couldn't fill.
3. **Verify by provenance** (Decided). Substring presence is not provenance: a document containing "13.51" anywhere would "verify" a value the model lifted from a date or an unrelated line item. So **both the parser and the model return the exact quoted span** they took the value from, and code checks two things — the span occurs verbatim in the document text, and the span contains the value. A field failing either check is rejected and `review_status = needs_review`.
   **CHANGED 29 Sep 2026 (Sravanth): a verbatim part of the quote is enough.** The check now accepts any continuous run of words from the quote that appears verbatim (whitespace aside) in the text **and** parses to exactly the reported value; the whole quote is tried first. The reason is measured: PDF tables come out with their columns interleaved, so RAILTEL's text reads `Rs.\n(in INR); 38,59,27,045/-`, the label column inside the value, and a model quoting the value as a reader sees it produces a quote that is not one piece of the text. That failed 54 correct answers in the first backfill batch; 51 pass the new rule. The property that matters is kept: the number must come verbatim from the document and parse to the same value, and a real passage that parses to a different number still fails (`extractor/provenance.py`).
   **Tightened 20 Oct 2026:** a part of the quote must occur as whole tokens, so "13.51 Crs" no longer verifies inside "113.51 Crs" (`extractor/provenance.py`).
   On a page whose text came from this project's own vision OCR (§5.5 Part C, `source = vision`), the span check alone is circular — it proves the extractor copied the transcript, not that the transcript matches the image — so a value from such a page needs a second, independent read agreeing on it before it can be `verified`.
4. **Normalize** with the unit normalizer (§5.7).

**The model never normalizes** (Decided). It returns raw strings and spans only. Every conversion — units, scale, currency, dates, ratios — happens in code, where it is testable and reviewable. This also removes a whole class of silent error: a model that "helpfully" converts crore to rupees cannot be checked against the source text, because the converted number is not in it.

**Built** (24 Sep 2026, night, continued): `src/reg30_radar/extractor/provenance.py` (the span check above, `verify(doc_text, value_span, value_inr)` - shared by both the parser and the LLM path, so one function decides what "verified" means everywhere) and `src/reg30_radar/extractor/llm_extract.py` (step 2, the LLM fallback - `extract_order_fields`, `prompts/order_extract_v1.md`). Escalation is gated twice: `router/orders.py`'s `llm_allowed` decides whether a filing may reach the LLM at all (§5.4), and within that, §6's "the parser wins when it verifies" decides whether T0's own result already passes `provenance.verify` before T1 is tried. A response that fails JSON parsing or Pydantic validation is retried once with the error fed back, then given up to `needs_review` (§6). `is_follow_up` and the fuller field set (`significant_terms`, `receipt_datetime`, `reporting_delay_reason`) are not built yet - this pass covers what the first order-extraction run needs.

### 5.7 Unit normalizer (pure functions, heavily unit-tested)
- Output is `Decimal` rupees. Never float.
- Handles:
  - currency markers: ₹, Rs., Rs, INR;
  - units: crore (cr, crs, crores), lakh (lac, lakhs), million (mn), billion (bn);
  - Indian digit grouping (65,02,160.50) and a trailing "/-";
  - "approx"/"approximately"/"about" → `approx` flag;
  - "incl./including GST" → `gst_inclusive`;
  - ranges → low/high values plus a flag;
  - foreign currency → **USD converted at a fixed ₹94** (Sravanth, 29 Sep 2026, "for now", so a USD order's ratios can be computed; `config/fx.yaml`), flagged `fx_converted`, with the original currency kept in `order_extractions.currency`; **every other currency flagged and not converted**, and sent to review. Each amount's currency is read **beside the number that was chosen**, not from anywhere in the string, and a crore/lakh amount is rupees: otherwise "INR 651 Crores (USD 73.47 million)" would have its crore figure multiplied by the dollar rate;
  - **Built 20 Oct 2026 (D32 and the GATE 1 audit, AUDIT.md §3).** Twenty values had been verified below ₹1 lakh: 15 L&T band disclosures read as rupees, and two size legends read as ₹100 and ₹0. The cause was that the range branch returned before the under-₹1-lakh suspect check. Now:
    - A range gives low/high with value = low and `range`.
    - A scale printed before the number counts ("₹ Cr 1,000 to 2,500").
    - A size legend (several ranges, or one plus "Above N") gives `band_only` with no value.
    - "over / above / more than / exceeding / at least / N+" gives `lower_bound`, and the value counts (D32).
    - Dates and spans of years are never ranges.
    - "Three Million Six Hundred Thousand" confirms a numeral like the Indian words do.
    - "(Rs. in crore)" after a number gives its scale.
    - Currency markers are word-bounded regexes: "rs" no longer matches inside "orders".
    - Ringgit, dinar, riyal and other currencies are recognised as foreign and left unconverted.
    The flags are stored (`order_extractions.value_flags`, `value_high_inr`, `backfill_events.value_flags`; migration 0015).
    **Proposed:**
    - "up to / not exceeding ₹X" gives `upper_bound`, never verified.
    - A string with no currency marker, crore/lakh word or "/-" gives `no_currency_marker`, never verified.
    - A value below ₹1 lakh is never verified, on any path: `money.is_suspect` is the one gate both judges apply.
    - A rounded figure restated exactly in the same string ("₹44.60 Lakh (Rs. 44,60,400/-)") gives the exact one, when it lies within half a unit of the rounded figure's last printed digit and is in the same currency (MCLOUD, labelled set). Measured on the 2,237 stored order documents: no stored value changes.
    - A numeral that is one piece of a longer dotted run ("~2.917.6 crore", HCC, dots as thousands separators) gives no value and `malformed_number`: read naively it was ₹6 crore for a ₹2,917 crore order, and which dot is the decimal point cannot be known. Found by reading the 21 Oct spot check, not by the provenance check, which it passed. It changed 1 of the 2,237 stored order documents.
    - **Tried and reverted, 20 Oct 2026:** joining a scale word that wrapped onto the next line ("over ₹ 5,400/-" / "Crores", BEML). On the stored documents it gave T0 nine new values; one was wrong, a cumulative "total export order value to ₹1,226 million" read in prose instead of the order's ₹266 million. Under §6 the parser wins whenever it verifies, so a T0 rule must be precise before it is broad; the LLM already reads all nine correctly.
  - **Indian number words** (Decided): "Rupees Thirteen Crore Fifty One Lakh only" and similar must parse in code. Filings write values in words often enough that a digits-only parser would reject correct answers and fill the review queue with them.
- Execution period → months. Examples: "10 Months from Work Order", "2 Years", "Within 6 months", "60 days", "Delivery Completion is November, 2026" (absolute dates use the filing date as reference). Anything unclear → null.
- Test vectors, taken from real filings:

| Raw string | value_inr | Flags |
|---|---|---|
| `₹ 13.51 Crs` | 135100000 | |
| `Approx. ₹2.89 Crores` | 28900000 | approx |
| `INR 72226994.2/- incl. of GST` | 72226994.20 | gst_inclusive |
| `INR 65,02,160.50/-` | 6502160.50 | |
| `INR 17.79 Crores (including GST)` | 177900000 | gst_inclusive |
| `Rs. 10.18 Crores New Order (approx.)` | 101800000 | approx |
| `Rs. 220.66 Crore` | 2206600000 | |

### 5.8 Revenue loader
- Source: NSE quarterly financial results in XBRL. Since April 2025 NSE takes these through "Integrated Filing – Financial"; earlier quarters are under the older "Financial Results" filings. Both use SEBI's in-capmkt/in-bse-fin taxonomy, so one parser handles both (**Verified**, Spike C, 27 Sep 2026 — see below). **The older "Financial Results" era is reachable** at `GET https://www.nseindia.com/api/corporates-financial-results` (`symbol=`, `period=Quarterly`), which returns one company's history with an `xbrl` URL per filing — for BEL, real dates back to 2011 and a real XBRL link from 2018 onward (older rows carry a `"-"` placeholder instead of a link). **The post-April-2025 "Integrated Filing" era: found and verified, Spike C2, 27 Sep 2026.** Two guesses by analogy had 404'd; Sravanth then captured the real call from the Integrated Filing page: `GET https://www.nseindia.com/api/integrated-filing-results` (`symbol=`, `period_ended=all`, `type=Integrated Filing- Financials`, `page`, `size`), returning `{data, totalCount}` with one row per filing and basis: `qe_Date`, `consolidated`, `audited`, `type_Sub`, `broadcast_Date`, `revised_Date`, and an `xbrl` link on nsearchives. Verified in 6 requests: it answers an ordinary warmed-up session; the page's `issuer` parameter is not needed (identical bytes without it); BEL's 12 rows reach back to the quarter ended **31-Mar-2025**, so the two listings meet with no gap (the older one ends at 31-Dec-2024). The files use the same in-capmkt taxonomy, and `revenue/xbrl.py` reads them unchanged: BEL's Q1 FY27 revenue is ₹55,469,800,000 (Sravanth's check), and FY26 (₹276,101,100,000) minus 9M (₹173,856,800,000) equals the ₹102,244,300,000 Q4 the FY26 filing states itself, to the rupee (`tests/fixtures/xbrl/`). `broadcast_Date` is the filing's `filed_at`; a revised filing counts from the later of it and `revised_Date`. `revenue/load.py` reads both listings and downloads only filings whose quarter ends on or after `window.results_from`, for companies with a backfill event only.
- Extract per ISIN per quarter: revenue from operations, period end, period length, basis (consolidated/standalone), unit/scale, `filed_at` (exchange timestamp), source URL.
- Basis (Default): consolidated if filed, else standalone. Record which one was used.
- **Discrete vs cumulative contexts** (Decided). The in-capmkt taxonomy carries both discrete-quarter and cumulative (H1, 9M, FY) contexts. Picking the wrong one double-counts silently, which is the single most likely source of quietly wrong TTM. The parser (`revenue/xbrl.py`) selects on a fact's actual start/end date, never a context's name.
  **Verified and revised, Spike C, 27 Sep 2026: the raw `<context>` element's own dates cannot be trusted either — real BEL filings break both ways.** A Jan-2025 Q3 filing's cumulative context ("FourD") declares the *same* startDate/endDate as the discrete quarter's context ("OneD"), a template copy-paste bug, even though its revenue (₹146.19bn) is plainly nine months' worth against the quarter's ₹57.7bn — reading context dates alone would silently collide the two facts under one key, exactly the "quietly wrong TTM" this decision was written to prevent, now demonstrated rather than merely feared. A 2018 Q4 filing goes further: its revenue facts reference `contextRef="OneD"`/`"FourD"`, and **no such `<context>` element exists in the instance at all**. Both filings correctly tag `DateOfStartOfReportingPeriod`/`DateOfEndOfReportingPeriod` facts alongside the revenue figure, and those are right in both cases — so the parser reads a fact's period from these declared elements first, falling back to the context's own dates only when no declared pair exists. `NatureOfReportStandaloneConsolidated` is likewise read per context, not as one global flag, since a filing can carry both a standalone and a consolidated context. Regression tests reproduce both real defects (`tests/unit/test_xbrl.py`).
  **End-to-end check, real data**: BEL's FY24 Q3 filing (9-month cumulative, ₹117.04bn) and Q4/FY filing (full year ₹202.68bn, discrete Q4 ₹85.64bn) give `FY − 9M = 85,640,800,000.00`, **exactly** BEL's own directly-reported Q4 figure, to the rupee.
- **Q2 derivation** (**Proposed**, 20 Oct 2026): `Q2 = H1 − Q1`, alongside the Decided Q4 rule.
  - **Why.** 47 Integrated-Filing Q2 files (25 companies, filed Nov 2025) carry no 3-month revenue at all: their quarter context holds the Apr–Sep figure. So TTM was null from Q2 on. Confirmed without a download: DBL re-filed in June 2026 with the true quarter, and H1 − Q1 = 4,546.23 − 2,620.34 = 1,925.89 cr, the revision to the rupee. Across the 45 cases with a later revision, 30 match exactly and 10 match within the filers' own rounding.
  - **Guard.** In the other 5 (3 companies), two stored "half-years" were really the quarter mislabelled: the later revision changed the figure, and the derived Q2 came to 0.05–0.28 of Q1. So it is derived only when it is at least 0.4 × Q1; otherwise TTM stays null. (The third company's H1 matched its revision; its later quarter row is the odd one.)
  - **Also built.** A derived quarter that is not positive is never used. Two different figures for one period in one file are both dropped and counted, instead of first-wins. The basis TTM used is written to `backfill_events.ttm_basis`. The integrated listing is read to its last page, and a listing still short is not checkpointed. **Proposed:** a listed XBRL link that answers a clean 404 is an answer, not a failure: the company is checkpointed with the quarter missing (TTM over it stays null), because 7 such files at 4 companies failed identically on every retry (20 Oct 2026); any other failure is still retried. The four-quarters-versus-full-year check is logged by the `revenue` stage.
- **Q4 derivation** (Decided): `Q4 = FY − 9M`. Most Indian filers publish audited full-year results and never file Q4 as a discrete quarter, so a naive "latest four quarters" rule returns null for a large share of companies exactly when TTM is most needed.
- **Point-in-time TTM** for date D: the sum of the latest four quarterly revenues with `filed_at` ≤ D, all on the same basis. A missing quarter gives null. Never guess.
- Banks, NBFCs and insurers are excluded from order ratios (Default), because their "revenue" means something different. This needs a **sector / industry column on `instruments`** (Decided). **Verified** (Spike A): the announcements API carries `smIndustry`, populated on 1,035 of 1,035 BEL records — but it was `null` for HILINFRA, so coverage is not total and the exclusion still needs a fallback for the names it misses.
- Sanity check: when a full-year figure exists, the four quarters should roughly add up to it. Log mismatches.
- Backfill depth: ~24 months of results, so there are four quarters before the earliest event.

### 5.9 Market data loader
- NSE UDiFF bhavcopy (daily) → `prices` (open, high, low, close, volume, series per ISIN). The bhavcopy is also the only one of these files that carries ISIN, so it is the join key for the other two.
- **PR bundle** — **Verified** (Spike B, 21 Sep 2026). URL pattern:
  `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{ddmmyy}.zip`
  Note the **two-digit year in the URL**, even though the members inside use four digits from 2026 onward. Fetched 200 for 2025-08-06, 2026-03-11 and 2026-09-18; 14 members each.
  - **Member names are not stable across the archive — match case-insensitively on prefix, never on an exact filename** (Changed). In the 2025-08-06 bundle the members are `An060825.txt`, `Pd060825.csv`, `bh060825.csv` and `MCAP06082025.csv`: mixed capitalisation, and `MCAP` uses `DDMMYYYY` while its siblings use `DDMMYY` **in the same zip**. From 2026-03-11 onward everything is lowercase `DDMMYYYY`. A loader keyed on exact filenames would silently find nothing on older bundles.
  - `pd` and `mcap` column sets **match the fixtures exactly** on all three dates. Stable.
- NSE market-cap file (`mcap`, inside the daily PR bundle) → `market_caps`.
  - **Verified** (Step 0, `tests/fixtures/mcap18092026.csv`): the column is `Market Cap(Rs.)` and the values are **plain rupees**, not lakhs or crores. Keyed by Symbol + Series, so it needs the bhavcopy for ISIN. Columns: Trade Date, Symbol, Series, Security Name, Category, Last Trade Date, Face Value, Issue Size, Close Price, Market Cap.
- Nifty 50 daily close (index rows in the PR bundle's `pd` file) → `index_prices`, used for returns relative to the market.
  - **Verified** (Step 0, `tests/fixtures/pd18092026.csv`): index rows carry `MKT=Y` and `IND_SEC=Y`, with `Nifty 50` as the first row. Columns: MKT, SERIES, SYMBOL, SECURITY, PREV_CL_PR, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, NET_TRDVAL, NET_TRDQTY, IND_SEC, CORP_IND, TRADES, HI_52_WK, LO_52_WK. No ISIN, so this too joins via the bhavcopy.
- **Corporate actions** (D21). Bhavcopy and `pd` prices are *unadjusted*, so a split or bonus inside an event window reads as a huge fake loss — and splits and bonus issues are common in exactly the small-caps this study targets. Two signals handle it, both already in the daily files and both free:
  - `CORP_IND` in the `pd` file flags the ex-date directly. **Verified** on 18 Sep 2026: 70 rows `XD`, 2 `XI`, 1 `XO`, 3,741 blank. The full code list is still to confirm (expect `XB` bonus, `XS` split, `XR` rights).
  - **CHANGED — `PrvsClsgPric` is NOT corporate-action adjusted.** v0.4 planned to chain every return through it. Spike B tested that and it is false.
    Evidence, 2025-08-06 (a day the PR bundle flags 18 corporate actions, including `COALINDIA` ex-dividend and `DAVANGERE` ex-rights): `PrvsClsgPric` equals the previous session's close for **all 18 flagged names, and for all 3,093 symbols in the file**. The PR bundle's `PREV_CL_PR` is the same number — it differs from the UDiFF field for **0** symbols that day. Both fields are simply the raw prior close.
    So there is no free adjustment anywhere in the daily files, and the corporate-action problem is real and unsolved by them.
  - **Read on every market row, 20 Oct 2026.** The `pd` parser kept `CORP_IND` only for `MKT=N` rows. BE/ST/BZ series can sit under `MKT=G` (28 rows on 18 Sep 2026), and 74 backfill events touch BE-series prices in their windows. `python -m reg30_radar.market --refresh-corp-ind` re-reads only the flags from the PR bundle, one request a day.
  - **`CORP_IND` still works, but only as a detector, never as an adjustment.** It names the affected securities on the ex-date; it does not carry the ratio needed to adjust a price. Observed values: `XD` (ex-dividend), `XR` (ex-rights), `XO`, and `XI` (ex-interest, only on debt series). `XB` and `XS` are expected but did not appear on the three days sampled.
  - **Phase 1 rule** (Decided): **exclude, do not adjust.** An event is dropped from the study if a capital action (`XB`, `XS`, `XR`, `XO`) is flagged for its ISIN anywhere in its window. Ordinary dividends (`XD`) are recorded and tolerated: they move a price by a fraction of a percent, in one direction, across the whole sample.
    **A reissued ISIN is a capital action too** (Sravanth, 27 Sep 2026). NSDL reissues the ISIN after a split, bonus or consolidation; 38 universe companies got a new one inside the window (BEML on 3 Nov 2025, KOTAKBANK, MCX, …). The study joins a company's prices across every ISIN with the same first nine characters (issuer code + `01`, equity shares; the two never trade on the same day), so its events after the switch still have prices, and marks the first day under the new ISIN as a capital action, because prices are unadjusted across it. NSE flags most switches itself (`XO` or `XB` on 43 of the 57 in the loaded prices); the other 14 carry no flag, which is why the marker is set in code (`NEW_ISIN`, `backfill/study_data.py`).
    This is affordable because capital actions are rare. Across the three sampled days the counts were 1, 1 and 1 out of roughly 3,400 rows — about 0.03% of names per day — whereas `XD` ran 16, 3 and 70. Excluding on `XD` too would cost a large share of the sample for no benefit.
  - Adjusting properly would need NSE's corporate-actions feed for the ratios. That is a Slice 7 option **only if** the exclusion turns out to cost more events than expected; it is not Phase 1 work. Never infer a ratio from the price move — that is guessing a number.
  - Volume ratios (§5.11) are distorted by the same events, and are excluded on the same rule.
- **Band hitters** (D21) — **Verified** (Spike B). The PR bundle's `bh` member lists the securities that hit their price band that day, and is present in all three bundles sampled. Columns are `SYMBOL, SERIES, SECURITY, HIGH/LOW` in 2026; the 2025-08-06 file carries a fifth column, `INDEX FLAG`, which was later dropped — so the loader must tolerate both widths. `HIGH/LOW` is `H` or `L`. The file covers every series, `SM`, `ST`, `BE`, `BZ` and debt included, so it needs filtering to the universe. **Base rate** (Spike B, 18 Sep 2026): 298 band hitters, 181 at the high and 117 at the low, of which only 86 were `EQ` — about 3.6% of the ~2,380 EQ names. On an ordinary day, then, roughly one EQ name in 28 is untradeable at its band, and the rate among the small-caps this study targets will be higher still. This is not an edge case. This is the direct source for the circuit flag, so the band never has to be inferred from the price move: a micro-cap that gates up on an order win is untradeable, and counting that move as return would be fictitious P&L.
- **History depth** (D10): 12 months **+ 30 trading days** for prices, market caps and band hitters, so the −20-day pre-event window and the 20-day average volume have room at the start of the study period. Results stay at 24 months.

### 5.10 Calculator
For each verified order:
- `value_to_ttm` = value_inr ÷ TTM revenue as of the filing time.
- `next12m_to_ttm` = value_inr × min(1, 12 ÷ execution_months) ÷ TTM revenue. This is revenue the order can add in the next 12 months. A 6-month order is not doubled; a 24-month order counts half. Null if execution_months is unknown.
- `value_to_mcap` = value_inr ÷ market cap at the **last close strictly before the event timestamp** (Decided). "Previous trading day" was ambiguous for after-hours filings, where day 0 shifts to the next session: a filing at 22:00 on day D must use D's close, not D−1's.
- GST-inclusive values: ratios use the raw value and show the flag. Don't guess the GST rate.
- Flags:
  - value > 1× TTM revenue → `manual_review` (either the trade of the year or a lakh/crore error);
  - value < ₹1 lakh → `suspect_parse`;
  - missing TTM → ratios null.

### 5.11 Backfill + event study (the go / no-go)
- Scope: 12 months of every announcement (metadata only), PDFs only for the D7 buckets, each deleted after extraction.
- For each verified order-win event:
  - **Day 0** = the filing date if filed before 15:30 IST, otherwise the next trading day. (F&O stocks now stop continuous trading at 15:15 for the closing auction; refine later if it matters.)
  - **Pre-event**: return over −5 and −20 trading days, minus Nifty. Did the news leak or get priced in early?
  - **Post-event**: returns at +1, +3, +5 and +10 trading days, minus Nifty. Measure from day-0 close (conservative) and, for after-hours filings, also from the next day's open.
  - **Volume**: event-day volume ÷ 20-day average volume. Flagged, not used, when a corporate action falls in the window (§5.9). **Muhurat sessions are excluded from the 20-day baseline**: an hour of trading is a fraction of a normal day's volume and would drag the average down, inflating every ratio computed near it.
  - **Muhurat sessions** (D27) count as trading days for day-numbering, because a bhavcopy exists for them and skipping them would desynchronise our trading-day arithmetic from the exchange's own. But an event whose **day 0 lands on one is flagged and reported separately**: a filing that can only be acted on inside a one-hour ceremonial session is not tradeable in the sense §5.11 is trying to measure.
  - **Contamination**: the same ISIN has another non-noise filing within ±3 trading days. Tag it and report it separately.
  - **Corporate action** (D21, revised by Spike B): prices are unadjusted and **stay** unadjusted — neither `PrvsClsgPric` nor `PREV_CL_PR` is adjusted (§5.9). So returns are computed from consecutive closes, and any event whose window contains a capital action (`CORP_IND` in `XB`, `XS`, `XR`, `XO`) for its ISIN is **excluded from the study and reported as excluded**, with the count shown. `XD` is tagged and kept. Excluded events are never silently dropped: an exclusion that quietly removed half the sample would change the verdict without anyone seeing it.
  - **Circuit limits** (D21): Indian stocks trade inside 5 / 10 / 20% price bands. A micro-cap that wins a large order can gate up untradeably, and a measured +10% on a 5%-band stock is fictitious P&L — which matters because the whole question is whether Sravanth can *trade* this. The flag comes straight from the PR bundle's **`bhDDMMYYYY.csv` band-hitter file** (§5.9), not from inferring the band. Tradeable return is reported separately from paper return.
- Buckets (Default, change freely):
  - value_to_ttm: <5%, 5–15%, 15–40%, >40%;
  - market cap: <₹1,000 cr, ₹1,000–10,000 cr, >₹10,000 cr.
- **Per-day reconciliation** (Decided). Every day in the window is reconciled as it is processed, by `src/reg30_radar/backfill/reconcile.py`: the PR bundle is the complete record of what was filed, the API supplies timestamps and PDF links, and the backfill measures how much of the former the latter can actually serve.
  - The unit is **order-filing companies covered**, restricted to the mainboard universe. SME and debt are outside the study and would depress the number for no reason.
  - Matching uses the window **from the previous report date to the report date**, never same-day: the bundle is a *report* covering filings disseminated since the previous report (§5.1). **CHANGED 27 Sep 2026 (night)** from a ±1-day window, which is right only when the previous day was a trading day: after a weekend the report holds Friday evening's and the weekend's filings (RVNL disseminated Saturday 20 Jun 2026 sits in Monday 22 Jun's report, and ±1 matched 0 of that day's 13 order filers). The rule above said a wrong window model must be widened; the first full run showed it, as 86 of 246 days below 95%, 44 of them with a three-day gap to the previous report. A filing dated after the report date is never a match. Companies are matched through the universe ISIN, not the symbol, because the API files a company's whole history under its current symbol (LTIMindtree's under `LTM`) while older reports carry the old one (`LTIM`). The reconciliation emits an offset histogram over the window (read as a shape: it counts every order filing of a matched company, so a company filing on two days appears twice), and a separate list per day of order filers the API holds only under a catch-all category: NSE's two sources can label one filing differently (the report's "Bagging/Receiving of orders/contracts (Sub-para 4-Para B)" is the API's "Updates"), and D7 downloads catch-all filings, but a category match is not proof, so they stay out of the coverage figure.
  - **First full run** (27 Sep 2026, 246 report dates, 1,347 order-filer company-days): **96.6% covered**; 35 days below 95%. Of the 46 unmatched, 35 have a catch-all filing from the same company in the window, 8 are "(Sub-para 4-Para B)" lines repeating an order the API holds from a few days earlier (the §5.3 MASON pattern), and 3 are unexplained (ASIANENE, HBLENGINE, WAAREERTL).
  - A day below **95%** coverage is reported, not dropped. Spike A2's 8/8 was one day, which is a pattern and not a rate — this is what turns it into a rate, measured across the whole window instead of inferred from 17–18 Sep.
- Output: `reports/backfill_<date>.md` plus a CSV, showing per bucket (clean vs contaminated) the event count, median and mean excess return, and hit rate — **and the per-day coverage series**, so a thin sample is visible as a cause rather than discovered as a surprise.
#### Pre-registered verdict rule (D22)

Fixed in writing **before any returns are computed**. Changing it after seeing results means
the result is exploratory, and it must be labelled as such.

**Primary hypothesis.** Verified order wins with `value_to_ttm` ≥ 15%, at companies with market
cap of ₹500–20,000 crore, earn a positive return over Nifty from day-0 close to day +5.
(Band revised 27 Sep 2026 by Sravanth from "below ₹10,000 crore", **before any return was
computed**, so the rule is still pre-registered. Market cap is valued at the last close
strictly before the filing timestamp, §5.10. The full collected universe, market cap
≥ ₹500 crore on 22 Sep 2025 (`config/backfill.yaml`; an earlier draft said ₹200), is also reported so the band's effect is visible.)

**Measurement.** Clean (uncontaminated) events only. Returns from day-0 close. The **median**
excess return is the primary statistic; the mean is secondary.

**GO only if all four hold:**

1. At least **30 clean events** in the primary bucket. Fewer is "insufficient data", not GO.
   **What 30 buys** (`reports/power_analysis_2026-09-22.md`): measured 5-day excess-return noise is σ ≈ 3.7%, so 30 events resolves a median effect of only about **2.4% net of the hurdle** at 80% power — a gross move above 3%. The floor protects against calling a result from a handful of events; it does **not** give the study the resolution to see an edge of the size worth trading. A null result at n ≈ 30 means **underpowered**, and must be reported that way rather than as evidence of no effect. Roughly 170 events are needed to demonstrate a 1% net edge, and ~300 to reach the cost hurdle itself.
   **Measured 20 Oct 2026** (`reports/power_analysis_2026-10-20.md`, 54,081 placebo dates in the primary band, `python -m reg30_radar.backfill.placebo`): σ is **5.75%** raw and **4.43%** robust, larger than the 3.7% estimate, but the median's minimum detectable effect at n = 30 is **2.50%** (bootstrap), close to the earlier 2.37%, because fat tails cost the median little. 170 events resolve 1.05%, 300 resolve 0.78%. The ordinary-day median excess is **−0.44%** (−1.07% in the first half), so D22, which tests against zero, is conservative by about that much. Recorded, not changed: D22 is Decided.
2. Median excess return minus a **0.75% round-trip cost hurdle** is > 0. The +5-day horizon means delivery trades, where STT alone is about 0.2% round trip; brokerage, exchange charges, stamp duty, GST and small-cap impact cost make up the rest.
3. Mean excess return minus the same hurdle is > 0.
4. The sign is the **same in both halves** of the 12 months.

**Everything else is exploratory** — the other value/market-cap cells, the other horizons
(+1, +3, +10), the pre-event windows, and contaminated events. They are reported and labelled
as exploratory. An exploratory result can only become a new hypothesis for forward paper
trading. **It can never produce a GO on this same data.**

### 5.12 Phase 2 (not now)
- Live alerts (Telegram via n8n).
- Google Sheets sync (one-way): an Orders tab (scored orders) and a Daily digest tab.
- Red-flag monitor on held names.
- Intraday reactions via SmartAPI one-minute candles.
- Order-inflow trends by company and sector.
- Backup automation.
- Media sources.

---

## 6. LLM policy: model routing

- **Provider**: OpenAI API, paid from existing account credits. Create a separate OpenAI project with its own API key for Reg30 Radar (`OPENAI_API_KEY` in `.env`), so its spend is isolated and visible. Use the official `openai` Python SDK.
- **Client built** (24 Sep 2026, pulled forward from Slice 5 to back §5.5 Part B's vision OCR): `src/reg30_radar/llm/client.py` is the single entry point this section's rules describe — fails closed on a null cap, computes cost from the price table, logs every call to `llm_calls`, never retries in a loop. Its first and only caller so far is `documents/ocr.py`. Building it surfaced one real bug, now fixed and regression-tested: `common/config.py`'s `env(..., required=False)` returns the literal string `"CHANGEME"` instead of `None` for an unfilled `.env` placeholder (the `CHANGEME` check only runs when `required=True`), so a naive "is the key present" check treated the placeholder as a real key and made one genuine network call to OpenAI during a unit test before this was caught.
- **Routing tiers** (cheapest capable tier first):

| Tier | What | Used for | Cost |
|---|---|---|---|
| T0 | Code: category lookup, keyword prefilter, annexure parser, unit normalizer, number verification | Everything it can handle | $0 |
| T1 | Cheap model (`tier1_model` in config) | Triage of prefiltered catch-all filings; order fields the parser missed | Very low |
| T2 | Stronger model (`tier2_model` in config) | Escalations only (below) | Higher, rare |

- **The parser wins when it verifies** (Decided). The annexure parser is deterministic and reads the table SEBI mandates. If its `value_inr` passes the provenance check in §5.6, **it is the answer** — any model disagreement is logged, not arbitrated. Escalating here would pay a premium model to referee a reliable source against an unreliable one. Escalation is considered only when the **parser's own value fails verification**, or the parser found nothing.

- **Escalate only on objective triggers** (Decided):
  1. The tier-1 output fails schema validation or the provenance check after one retry.
  2. The parser's value fails verification *and* disagrees with tier 1.
  3. A judgment field comes back unknown: `company_is_recipient`. **Narrowed 29 Sep 2026 (Sravanth): an unknown `stage` no longer triggers it.** Stage is not used by D22's verdict, and in the first backfill batch it alone had sent 112 verified values to review; an unknown recipient still does, because the verdict needs the company to have won the order.
     A non-INR currency is **not** a trigger — it is a determinate fact code can already see, and escalating on it would pay a stronger model to re-read something known. Foreign currency is flagged and left unconverted; FX stays Open (§11).
  4. High stakes: `value_to_mcap` ≥ 15%, **or TTM is null**. The escalation model extracts independently, without seeing tier 1's answer. If they disagree on `value_inr` or `company_is_recipient`, the order goes to manual review rather than being marked verified.
     This uses `value_to_mcap` rather than `value_to_ttm` deliberately: market cap is available for essentially every listed company, whereas TTM is not — and the old trigger silently skipped the messiest cases, the ones with missing financials, by never firing on them. Firing when TTM is null closes that gap.

  Never escalate, or accept an answer, because of a model's self-reported confidence. It isn't calibrated.

- **State machine** (Decided). The high-stakes trigger needs a ratio, and the ratio needs a
  value, so extraction and calculation are not a single pass. The loop is explicit and bounded:

  | From | Condition | To |
  |---|---|---|
  | `extracted` | always | `calculated` |
  | `calculated` | `value_to_mcap` < 15% and TTM present | `verified` |
  | `calculated` | `value_to_mcap` >= 15% **or** TTM is null | `recheck_pending` |
  | `recheck_pending` | independent re-extract agrees on `value_inr` and `company_is_recipient` | `verified` |
  | `recheck_pending` | independent re-extract disagrees | `needs_review` |

  Each order carries its state. An order enters `recheck_pending` at most once, so the loop
  cannot run twice. Every transition is logged with the trigger that caused it.

- **Model choice is decided by the Spike D bake-off, not assumed** (Decided). On the 10 labelled PDFs, run four arms and report per-field accuracy, tokens, cost per document, and **every failure**:
  1. the annexure parser alone, with no model at all;
  2. GPT-5 nano;
  3. gpt-4.1-mini;
  4. GPT-5.6 Luna.

  **Hard stop at $0.50** for the whole bake-off.

  The **cheapest model that passes becomes tier 1**. Luna is the escalation model *only* if it beats tier 1 on the hard cases. **If one model is enough, use a single tier** — two tiers plus escalation is a lot of machinery to justify on a bill this size, and its real value is accuracy control, which mostly comes from the parser and the provenance check anyway.
  - Arm 1 also answers the question that sets the entire bill: **the parser's hit rate on its own**. Every field the parser fills is a field no model is paid to read.
  - Exact model IDs and the price table live in `config/llm.yaml`, copied by hand from OpenAI's pricing page, never in code and never from memory. Until Spike D fills them in, the file holds `PLACEHOLDER` and the client fails loudly rather than guessing.

  **Superseded for the first order-extraction run, 24 Sep 2026 (night, continued): Sravanth chose `tier1_model` directly** rather than waiting for the bake-off, to get the first day of live order extraction running now. `gpt-6-luna` at $0.10 / $0.50 per million input/output tokens, given by him in the same session `OPENAI_API_KEY` was filled in - not run through the labelled-PDF bake-off, and not benchmarked against gpt-5-nano or gpt-4.1-mini. Single tier: `tier2_model` stays `PLACEHOLDER`. **27 Sep 2026: Sravanth will name a T2 model** for §6's independent recheck (not a second read by the same model, and not manual review only). Until its id and prices are in `config/llm.yaml`, a `recheck_pending` order goes to `needs_review`, failing closed. **Superseded the same day:** Sravanth set `tier2_model: gpt-6-luna` "for now" (`config/llm.yaml`), so the recheck is a second, blind read by the same model until he names a stronger one. The Spike D bake-off itself is not cancelled - it is still the right way to confirm or revise this choice once ~50 labelled PDFs exist, and until it runs this model choice is Sravanth's call, not a measurement.
- **Cost controls**:
  - Every call logs its tokens and computed cost (tokens × price table) in `llm_calls`.
  - Hard caps: **set 24 Sep 2026 (night, continued), ahead of the Spike D bake-off, by Sravanth directly** — **$1/month each** for `live_usd_per_month` (order-field extraction) and `ocr_usd_per_month` (vision OCR), enforced separately. Estimated cost for the first day's ~124-filing run is under $0.10 at `gpt-6-luna`'s prices, so $1/month leaves real headroom while still being a hard ceiling. `backfill_usd_per_run` **set 27 Sep 2026 by Sravanth: $3 for the complete backfill**, covering every purpose (extraction, recheck and OCR) and measured against `llm_calls` in the backfill database. At a cap, items wait as `pending_llm`; nothing is dropped, and nothing retries in a loop.
  - **A null cap fails closed, never open.** `config/llm.yaml` shipped with every cap null; all three now carry Sravanth's numbers (above), and any cap set back to null refuses again. The client refuses to make a paid call while its cap is null, and says so - this held from the very first call `llm/client.py` ever made (§5.5 Part B), before any cap had a real number.
  - Second guard: set a monthly budget and alert threshold on the OpenAI project in the dashboard.
  - The backfill uses OpenAI's Batch API (half price, results within 24 hours). Live processing uses the standard API. **Exception, 27 Sep 2026 (Sravanth): vision OCR stays on the standard API in the backfill too.** Batching it would mean keeping rendered page images on disk until the batch returns, up to 24 h, against D8. About 3% of documents need OCR, so the saving is cents. Batch cost is computed from explicit Batch prices in `config/llm.yaml`, never by assuming the 50% discount; a model with no Batch price is refused.
  - Prompt layout: fixed instructions and schema first, document text last, which is the right shape for prefix caching. But the **cached-input discount is left out of the cost model** (Decided): it needs a minimum prefix length and byte-identical prefixes, a short rubric may never qualify, and its interaction with the Batch API is unclear. Treat any discount as a pleasant surprise, never as budget.
  - Set a maximum output length on every task.
- **Optional $0 route** (Open: Sravanth's call): OpenAI's data-sharing program gives eligible organizations free daily tokens on the traffic they share. At usage tiers 1–2 that is 250K tokens/day on flagship models and 2.5M/day on small ones.
  - Filings are public, so sharing them costs little privacy-wise. The prompts (our extraction rubric) would be shared too.
  - Sharing can be enabled for this project only.
  - Only listed models qualify. Check the data-sharing settings page for eligibility and the covered models, and pick T1/T2 from that list if going for $0.
  - OpenAI says it gives 30 days' notice before ending the program.
- **Output contract**: request structured output (JSON schema) where the model supports it, and still validate with Pydantic. If the output is invalid, retry once with the error included. After that, a T1 failure escalates to T2; a T2 failure goes to `needs_review`.
- **Verification**: provenance, not substring presence — the model returns the exact quoted span, and code checks the span is in the document and contains the value (§5.6). Models never convert units, scales, currencies or dates, and never compute ratios; code does all of it.
- **Safety**: document text is untrusted data. The system prompt tells the model to ignore any instructions found inside documents.
- **Prompts**: `prompts/<task>_v<N>.md`. The version is stored with every output. Changing a prompt means creating a new file.
- **Evaluation**: `tests/labelled/` holds ~50 hand-labelled order PDFs with expected JSON. `python -m reg30_radar.eval` reports per-field accuracy per tier, the escalation rate and the cost per document. A model or prompt goes live only if the full chain hits ≥ 95% exact `value_inr`.
  This threshold is a **smoke test, not a measurement** (Decided): at n = 50 the confidence interval is roughly ±6%, so 95% and 93% are statistically indistinguishable. It catches something badly broken; it does not certify accuracy.
  **Added 20 Oct 2026:** the eval also scores T0 as production gates it (provenance and suspect checks, `orders.run.t0_value`; a held-back value is an escalation, not an error), and `python -m reg30_radar.eval --stored` scores the full chain's stored answers, found by the labelled PDF's SHA-256 in both databases, with no model call. On 20 Oct: bare T0 9/18, gated T0 9/18 correct with 0 accepted-wrong and 0 invented, stored chain 6/6 where it answered (8 labelled documents were processed by the backfill; the other two are a correct `not_order` and a correct null). BEML's label took D32's lower bound (₹5,400 cr), which its labeller had left "pending decision".

---

## 7. Data model (Postgres, database `tradebot`)

All timestamps `timestamptz`; money `NUMERIC(20,2)`. **Ratios are not money** and get their own type, `NUMERIC(12,6)` — two decimal places would round a 0.4% ratio to zero. Columns abbreviated.

- `raw_announcements`(id, source, source_id, **payload_sha256**, **revision**, exchange_ts, **disseminated_ts**, first_seen_at, symbol, company, isin, industry, category_raw, headline, attachment_url, payload jsonb) — UNIQUE(source, source_id, payload_sha256); append-only. `bse_code` is gone with D26. `disseminated_ts` and `industry` come from the API's `exchdisstime` and `smIndustry` (§5.1). The hash in the key is what stops an exchange revision being silently swallowed (§5.3); `revision` increments for each re-filing of the same source_id.
- `events`(id, isin, bucket, category_norm, para, headline, event_ts, raw_ids, in_universe, status) — `raw_ids` holds every raw row merged into the event (§5.3). The per-exchange `nse_*` / `bse_*` columns are gone with D26.
- `documents`(id, event_id, url, sha256, pages, text, is_scanned, method, extracted_at, pdf_deleted_at, **quality**, **page_report**, **rejected_text**, **ocr_pages**) — `migrations/0004_document_quality.sql`. `quality` (`ok`/`partial`/`unreadable`) is the §5.5 manual-review gate, replacing the char-count `is_scanned` heuristic a garbled-but-plentiful text layer could pass. `page_report` (jsonb) is one entry per page — verdict, method, source, chars, image_fraction, glyphless_font, cid_ratio, common_word_ratio, ocr_attempted — so a quality call is auditable after D8 has deleted the PDF. `rejected_text` holds the best (still-unusable) attempt for pages that did not assess `ok`, kept out of `text` but not thrown away. `is_scanned` is redefined as "any page is a full-page image", a layout fact rather than a guess about the text.
- `orders`(id, event_id, awarding_entity, domestic_or_international, nature_of_order, significant_terms, execution_period_raw, execution_months, consideration_raw, value_inr, **value_span**, value_flags, gst_inclusive, currency, promoter_interest, related_party, receipt_datetime, company_is_recipient, stage, is_follow_up, extractor, prompt_version, **state**, verified, review_status) — `value_span` is the exact quoted text the value came from, which is what the provenance check verifies (§5.6); `state` is the extraction state machine in §6.
- `instruments`(isin PK, nse_symbol, nse_series, name, board, **sector**, **industry**, first_seen, last_seen) — sector/industry carry the bank / NBFC / insurer exclusion in §5.8, which previously had no mechanism.
- `prices`(date, isin, open, high, low, close, **prev_close**, volume, series, **corp_ind**, **band_hit**) — PK(date, isin). `prev_close` is NSE's `PREV_CL_PR`, stored because it is in the file — **it is NOT corporate-action adjusted** (Spike B, §5.9), so returns are never chained through it. `corp_ind` is the ex-date flag and is what drives the exclusion rule in §5.11; `band_hit` comes from the `bh` band-hitter file.
- `index_prices`(date, index_name, close) — PK(date, index_name)
- `market_caps`(date, isin, mcap_inr) — PK(date, isin)
- `financials`(isin, period_end, period_months, basis, revenue_inr, scale, filed_at, source_url) — UNIQUE(isin, period_end, basis)
- `materiality`(order_id, ttm_revenue_inr, ttm_asof, basis, mcap_inr, mcap_date, value_to_ttm, next12m_to_ttm, value_to_mcap, flags) — the three ratios are `NUMERIC(12,6)`.
- `llm_calls`(id, ts, tier, model, prompt_version, purpose, event_id, in_tokens, cached_tokens, out_tokens, cost_usd, batch_id, latency_ms, status, escalation_reason, error) — **built** 24 Sep 2026 (`migrations/0005_llm_calls.sql`), pulled forward from Slice 5 to back §5.5 Part B's vision OCR; `purpose = 'ocr'` is the only value written so far.
- `source_health`(id, source, checked_at, ok, error, **http_status**, **latency_ms**, **records_returned**, **new_records**, **overflow**) — **one row per poll, not one per source**. A single mutable row answers "is it up now?" and nothing else; keeping history is what makes an outage diagnosable afterwards. The last five columns were added in Slice 1 (`migrations/0001_init.sql`) for a reason specific to the live endpoint: it returns only the **20 most recent** filings, so a full page that is entirely new means the page may have rolled over since the last poll and filings in between are gone. `overflow` records each such poll, which is what turns that risk into a measured rate rather than an assumption. **Gap closing (fixed 26 Sep 2026):** an overflow is followed by one date-range query for yesterday and today (`close_gap` in `src/reg30_radar/collector/__main__.py`), recorded as its own `source_health` row with `records_returned` well above 20. The first version re-polled the live endpoint until a page overlapped what was stored; since that page is always the newest 20, it overlapped on the very next poll and never reached a filing that had already rolled off, so every overflow before this fix lost everything beyond the newest ~20.
- `unknown_categories`(exchange, category_raw, first_seen, count)
- `backfill_checkpoints`(job, key, done_at)
- `schema_migrations`(version, applied_at)
- `sheets_sync`(id, run_at, ok, rows_written, first_row, last_row, **last_raw_id**, error) —
  the watermark for the Google Sheets mirror (v1.2, D11, `src/reg30_radar/sheets/`), one row
  per sync run like `source_health`. `last_raw_id` and `last_row` are only ever read back
  from a row where `ok` is true, which is what makes a retried write idempotent: a run
  whose write reaches the Sheet but then fails before this row is recorded leaves the next
  run to redo that chunk, writing the same content to the same sheet rows rather than a
  new position. **The `orders` tab (v1.5) has no equivalent table.** `order_extractions`
  rows are upserted, not append-only, so there is no fixed position to resume into; the
  tab is simply rewritten whole from the current table each cycle, skipped only when a
  content hash (kept in memory, in `src/reg30_radar/sheets/__main__.py`) shows nothing
  changed since the *last cycle of this process*. A fresh process - including a second
  `python -m reg30_radar.sheets --once` right after the first - has no prior hash and always
  rewrites once. This is deliberate, not a gap: the rewrite is idempotent and cheap at
  order-filing volumes (about 10 rows a day), so paying for one extra write on every
  restart was judged simpler than a table whose only job would be caching that write away.

Migrations (Default): plain numbered SQL files in `migrations/` (`0001_init.sql`, …) applied by a small runner. No ORM magic, so every schema change is readable.

---

## 8. Storage and retention

- PDFs: downloaded only for the D7 buckets and deleted right after text extraction (D8). Text is kept; it's a few KB per filing.
- Why keep text: it lets a better parser or prompt re-run over the whole backfill without re-downloading thousands of PDFs from NSE, and any number can be checked against its source later.
- Exception (**confirmed**, D8): the labelled test-set PDFs stay in the repo. They are the ground truth for the Spike D bake-off and the eval set.
- Backfill reports in `reports/` **are committed to git** (Decided). They are small, and the history of what each run concluded is worth keeping.
- Disk guard: log a warning when disk usage passes 80%.
- Docker logs: json-file driver, `max-size: 10m`, `max-file: 3`.
- Backups (D14): nightly `pg_dump` of `tradebot` to Google Drive, in place **before the backfill** — the backfill is weeks of scraping plus LLM spend and is the expensive thing to lose, whereas live use risks little. Mechanism **decided 27 Sep 2026: rclone** to Google Drive (D14).

---

## 9. Deployment and environment

```
reg30-radar/
  CLAUDE.md  ARCHITECTURE.md  WORKLOG.md  .env.example  .gitattributes  .gitignore
  Dockerfile  docker-compose.yml  pyproject.toml
  config/      sources.yaml  category_map.yaml  llm.yaml  documents.yaml  holidays_2026.yaml
  prompts/     triage_v1.md  order_extract_v1.md  ocr_transcribe_v1.md
  migrations/  0001_init.sql ...
  src/reg30_radar/
    common/  (config, db, logging, time, http, migrate)
    collector/  normalizer/  router/  documents/  extractor/  units/
    revenue/  market/  calculator/  backfill/  llm/  eval/  sheets/
  tests/
    fixtures/  (an18092026.txt, pd18092026.csv, mcap18092026.csv, bh18092026.csv;
                BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV — kept as UDiFF column evidence;
                scans/hmt_glyphless.pdf — the garbled-OCR regression fixture, §5.5)
    labelled/  (hand-labelled order PDFs + expected JSON)
    unit/  live/  (live = hits real sites; skipped unless `-m live`)
  spikes/      (throwaway probes; spikes/out/ is gitignored)
  reports/
```

- **Approved dependencies** (Default): requests, feedparser, pdfplumber, pypdf, lxml, psycopg[binary] (v3), pydantic, openai, APScheduler, python-dotenv, PyYAML, pytest,
  **google-auth** (v1.2 — service-account auth for the Sheets mirror in `src/reg30_radar/sheets/`; not `gspread` or `google-api-python-client`, which are not on this list). Ask before adding anything else.
- **Docker Compose** (built 27 Sep 2026: `Dockerfile`, `docker-compose.yml`, runbook in `DEPLOY.md`): one image, **three services**, matching D19 as widened: `collector` (live polling, with a healthcheck that needs a successful poll in the last 30 minutes, `common/health.py`), `orders` (`--follow`: gate, documents, extraction) and `sheets`. One-off jobs such as migrations and catch-ups run with `docker compose run --rm collector ...`. The backfill does not run on the VPS (D19). A `backup` job under the `ops` profile runs `pg_dump` from its own `postgres` container over the database network, so nothing ever `docker exec`s into the shared Postgres after the one-time setup. The image runs as uid 10001 and needs `PYTHONPATH=/app/src` instead of a package install, so `common/config.py`'s `ROOT` resolves to `/app`. In-flight PDFs and live reports live in the `tradebot_data` volume, never in the checkout, so `git pull` always applies. A worker killed at its memory limit cannot restart-loop: `orders/run.py` records each attempt before the work starts, so a filing that crashes the worker stops after three attempts.
- **Network**: join the existing Docker network the Postgres container is on (declared `external: true`). Publish no ports.
- **Memory and CPU**: `mem_limit: 512m` per service, so a bad PDF can't starve n8n, and a `cpus:` limit alongside it (Decided) — pdfplumber is CPU-bound, and without a cap one extraction run holds a core for hours and makes n8n visibly slow on a 2-vCPU box. Actual values are set from the measured headroom in Spike E. A container killed at its memory limit must be recorded as `needs_review`, never left to restart-loop.
- **Database setup** (once, by hand, as the Postgres superuser):
  `CREATE USER tradebot WITH PASSWORD '...'; CREATE DATABASE tradebot OWNER tradebot;`
  The `tradebot` user has no rights on n8n's database.
- **Deploy** (D1): laptop `git push` → VPS `git pull && docker compose up -d --build`.
- **Line endings**: `.gitattributes` with `* text=auto eol=lf`. Windows dev, Linux prod.
- **Viewing data (Phase 1)**: **no SSH tunnel and no change to n8n's containers** (D19). The `tradebot` database is created in the existing Postgres with `docker exec psql`, and queried the same way. This resolves what was a direct conflict between CLAUDE.md's n8n rule (never touch n8n's containers) and the earlier plan to re-bind the Postgres port for DBeaver: if Postgres is part of n8n's stack, changing its port binding *is* touching it. The backfill runs on the laptop against a local Postgres anyway, so the tunnel bought little.
- **Local database** (D19): Postgres on the laptop holds the backfill. The VPS Postgres holds only what the live collector writes. Most tests — units, router, TTM logic, calculator — need no database at all.

---

## 10. Build order

Each slice ends with passing tests and a short plain-language summary for Sravanth.

0. **Spikes** (verify unknowns; write findings back into this file). Throwaway probe code lives in `spikes/`, never in `src/`.
   - *Step 0 done*: scaffold, `.gitignore`/`.gitattributes`, `.env.example`, placeholder `config/llm.yaml`, `pyproject.toml`, passing `pytest`. Findings written into §5.1 and §5.9.
   - ~~**Spike B — historical bulk files**~~ **DONE** (21 Sep 2026). URL patterns and archive depth verified (§5.2, §5.9); robots.txt and terms of use recorded (§3); and the `PREV_CL_PR` return-chaining idea **disproved** rather than proved — the field is not adjusted, so §5.9 now excludes capital actions instead of adjusting for them.
   - ~~**Spike A — announcement endpoint**~~ **DONE** (22 Sep 2026). Record shape, identity and filtering documented in §5.1. `sm_isin` and `smIndustry` found. Left one blocker, below.
   - **Spike A2 — API completeness. Now the first spike, because it can invalidate the study's scope.** The date-range query returns 563 of ~1,229 filings for 18 Sep 2026 and misses whole companies, yet it is the only known source of the filing timestamp and the PDF URL, and that URL is not constructible. Test other `index` values, a pagination parameter, and the CSV export implied by the null `csvName` field. Also collect the canonical category list from the filings-page dropdown, which §5.4 needs. Budget 12 requests.
     **If A2 finds nothing, the 12-month backfill is not possible as specified.** The honest options are then to shrink the study to whatever window the API does serve, or to fall back on D23's forward collection, which costs 12 months of wall-clock time. That is a scoping decision for Sravanth, and it must be settled before any slice is built on the assumption that history is reachable.
   - ~~**Spike C — results XBRL.**~~ **DONE** (27 Sep 2026, 14/14 requests). Parsed four real BEL filings from the older "Financial Results" endpoint (2025 and 2018), fixed two real defects in NSE's own XBRL (§5.8), and confirmed `Q4 = FY − 9M` to the rupee against BEL's own reported Q4. The post-April-2025 "Integrated Filing" endpoint, not found by two analogous guesses, was captured by Sravanth and verified by **Spike C2** (27 Sep 2026, 6/8 requests, §5.8).
   - **Spike D — extraction bake-off.** Four arms on 10 labelled PDFs: parser alone, GPT-5 nano, gpt-4.1-mini, GPT-5.6 Luna. Per-field accuracy, tokens, cost per document, every failure. **Hard stop $0.50.** Sets tier 1, decides whether a second tier is needed at all, and only then sets the spend caps. Also covers the OpenAI data-sharing page: eligibility and covered models.
     **Spike D also counts, split by market cap band (<₹1,000 cr / ₹1,000–10,000 cr / > ₹10,000 cr):** how many PDFs are scanned versus text-layer, and how many orders are in a foreign currency. Those two counts settle the scanned-PDF and FX decisions in §11 with measurements instead of argument — if scanned PDFs are 2% and concentrated in micro-caps the answer is manual review, and if they are 30% it is OCR. The labelled JSON carries `is_scanned` and `currency` for exactly this.
   - **Spike E — VPS preflight.** Read-only: free memory, free disk, swap, the external Docker network name, and how the existing Postgres container is configured. Sets the `mem_limit` and `cpus` values.
   - **Python 3.14 wheels** for every dependency. Windows/cp314 already verified in Step 0; manylinux still to check.

**Slices 1–8 below stand as written for now** (D20). A revised build order is proposed after
Slice 0, from the spike results — not before. Two things already shape that proposal: the
hybrid source plan in §5.1 (the PR bundle cannot carry timestamps or PDF links, so the API is
still needed for order filings), and D23 (a minimal NSE-only live collector starts on the VPS
straight after Slice 0, because `first_seen_at` cannot be backfilled).

1. Collector (NSE live + backfill mode), raw store, source health. — **Live half DONE** (23 Sep 2026): `src/reg30_radar/collector/` polls the announcements endpoint on D6's schedule, stores every filing in `raw_announcements` and every poll in `source_health`, with the trading-day calendar failing loudly per D27. **Backfill mode built 27 Sep 2026**, company-wise (§5.1 as changed): `backfill/announcements.py`, one `symbol=` query per listed company, with per-day reconciliation into `reconcile_days`.
2. Instruments / ISIN map, normalizer, intra-NSE dedup. (Much smaller since D26 removed the BSE collector and cross-exchange dedup.) — **Built 27 Sep 2026**: `instruments` and `instrument_symbols` from each day's bhavcopy (`market/`); the frozen company list (`backfill/universe.py`); events merged on §5.3's exact keys (`backfill/events.py`).
3. Router + unknown-category log; tests from the Fri 18 Sep fixture (§5.4). — **Built 27 Sep 2026**: the full `config/category_map.yaml` (146 categories, Sravanth-approved, with a `leadership` confounder class), case-insensitive matching, `router.orders.bucket_of()`, and `unknown_categories`.
4. Document pipeline (download → text → delete), annexure parser, unit normalizer (test vectors in §5.7). — **Built and tested 24 Sep 2026** (`src/reg30_radar/documents/`: `fetch.py`, `text.py`, `pipeline.py`, `store.py`; `units/money.py`, `extractor/annexure.py` already existed from the extraction baseline). Extended the same day with the per-page quality ladder and dormant vision OCR (`quality.py`, `ocr.py`; see §5.5, changelog v1.4). **Not yet wired to the live collector** — `process_url` exists and is exercised in `tests/unit/` against real labelled PDFs and the HMT regression fixture, but nothing in `src/reg30_radar/collector/` calls it yet, so `order_win`/`order_candidate` filings are not currently downloaded. That wiring, plus the router (§5.4) that decides which filings qualify, is the remaining work in this slice.
5. LLM client (OpenAI SDK): routing tiers and escalation triggers, spend caps, structured output + validation, logging, Batch mode for backfill. Plus labelled-set evaluation. — `src/reg30_radar/llm/client.py` and `llm_calls` (`migrations/0005_llm_calls.sql`) were **pulled forward to Slice 4** to back vision OCR (above); this slice still owed the T0→T1→T2 routing and escalation triggers, the T1/T2 model IDs (Spike D), and Batch mode. **Built 27 Sep 2026**: the Batch path and the single backfill budget (`llm/client.py`, `backfill/batch.py`), and §6's state machine with trigger 4's independent recheck (`backfill/events.py`, `backfill/recheck.py`). T2 is gpt-6-luna for now (Sravanth).
6. Revenue loader + point-in-time TTM. — **Built 27 Sep 2026**: `revenue/ttm.py` (point-in-time, one basis, Q4 = FY − 9M), `revenue/xbrl.py` (period from declared dates, then context dates), and `revenue/load.py` (both results listings, Spike C and C2). Not yet run.
7. Market data loader + calculator. — **Built 27 Sep 2026**: `market/` (UDiFF bhavcopy and PR bundle, the past-date calendar of D27, traded value) and `calculator/materiality.py`.
8. 12-month backfill + event-study report → go / no-go. — **Built 27 Sep 2026**: `backfill/` stages run by `python -m reg30_radar.backfill <stage>`, Batch LLM extraction (`batch.py`), §6's recheck (`recheck.py`), the event study and D22 verdict (`event_study.py`), and the report (`report.py`). Not yet run on the full year.

**Sequencing note for Slice 8** (from the power analysis). Two funnel rates dominate how many clean events the study gets, and they differ in cost. The contamination rate needs **only the PR bundles** — "did this ISIN file anything else non-noise within ±3 trading days" is answerable from company and category alone, with no PDFs, no API, no LLM. So download the bundles for the full candidate window first (~250 requests for 12 months, ~750 for 36), measure the real order-event count and contamination rate from them, and only then choose the window and spend on PDFs and extraction. Extending the window is cheap on the API side, because a `symbol=` query returns a company's whole history in one call regardless of how far back the study reaches — only the bundle downloads scale.

---

## 11. Open decisions

Resolved since v0.2: the model acceptance threshold (§6 — kept at 95%, but recorded as a smoke test), the T2 upgrade path (superseded by the Spike D bake-off), spend cap amounts (set after Spike D), the local dev database (D19), the market-window edges (D6), whether BSE is in Phase 1 (D26), and the trading-day calendar source (D27).

Still open:

- ~~User-Agent: whether to append a contact string.~~ **Decided 23 Sep 2026: no contact string.** The collector sends exactly the browser-like UA already in `config/sources.yaml`, which every spike and the live collector have now proven against Akamai. Sect.3 records the tension — an honest UA is what robots.txt invites and is also what bot management is most likely to refuse — and the call is to keep the proven string rather than risk the hard block D19 exists to avoid. The UA lives in `config/sources.yaml` only; `HTTP_USER_AGENT` has been removed from `.env`/`.env.example`, because it is not a secret and two places to set it invites exactly the rotation D25 forbids.
- ~~Scanned PDFs: local OCR, a vision-capable model, or manual review only.~~ **Decided 24 Sep 2026: a vision-capable OpenAI model (§5.5 Part B), Sravanth's call.** Built and dormant: `documents/ocr.py`, `llm/client.py`, `config/llm.yaml`'s `ocr_model`. Activates once Sravanth supplies the model id, its prices and `caps.ocr_usd_per_month`; until then every image page lands in manual review, never guessed.
- ~~FX source for foreign-currency orders.~~ **Decided for now, 29 Sep 2026 (Sravanth): USD at a fixed ₹94** (`config/fx.yaml`), other currencies unconverted and reviewed. A fixed planning rate, not a dated market rate, so a converted value is approximate; where a filing states its own INR figure the two differ by a few percent (WELCORP: ₹16,920 cr at ₹94 against its stated ~₹17,200 cr).
- Opting into OpenAI data sharing for this project (free daily tokens vs sharing prompts).
- ~~Backup mechanism (rclone or n8n).~~ **Decided 27 Sep 2026: rclone** (D14).
- Event-study bucket edges (§5.11) — *narrowed*: the **primary** bucket is now fixed by D22 (value_to_ttm ≥ 15%, market cap ₹500–20,000 cr as revised 27 Sep, +5 days). The remaining reporting cells stay Default and are exploratory.

Raised by the spikes:

- The full `CORP_IND` code list (XD/XI/XO/XR seen; XB/XS expected). Needed before Slice 7.
- ~~Source of circuit-band membership (5/10/20%), for the tradeable-vs-paper return split (D21). The `bh` file says *who hit a band*, not *what the band was*.~~ **Partly resolved, 27 Sep 2026 (8/8 requests).** Two working sources found, one solved and one not:
  - **Price band: solved and built, 27 Sep 2026 (Sravanth asked for it as part of the per-event detail).** `https://nsearchives.nseindia.com/content/equities/sec_list.csv` gives every symbol's **current** band (columns `Symbol,Series,Security Name,Band,Remarks`) — a snapshot, not history. `https://nsearchives.nseindia.com/content/equities/eq_band_changes_{ddmmyyyy}.csv` is a **daily change log** (`Sr. No,Symbol,Series,Security Name,From,To`), confirmed live for three dates spanning a year and confirmed to answer a clean HTTP 404 (not an empty 200) on a day with no changes — checked on two Sundays. `src/reg30_radar/market/bands.py` reconstructs any symbol's band on any past date by walking the change log backward from the current snapshot, undoing every change dated after the target date; a symbol absent from the current snapshot (delisted since) returns null rather than a guess. `migrations/0013_band_history.sql` (`band_snapshot`, `band_changes`, `band_days`). `EventResult.price_band` (§5.11) is set once per event, as of day 0, by `backfill/__main__.py`'s `study()` after `measure()` runs — a targeted lookup, not a full day-by-day series for the whole window, and kept out of `event_study.py` itself so that module stays a pure function of `Market` with no database of its own. Does not change D22's verdict, since `locked` already comes from the `bh` band-*hit* file; this is the exact 5/10/20% figure for the per-event CSV. The historical fetch (~575 calendar days, one request each, weekends included since a band change is an exchange notice, not tied to a trading day) is a separate loader (`python -m reg30_radar.market.bands --from --to`) on the same archive host as the bhavcopy/PR bundle, run once for the study window.
  - **ASM/GSM stage: current only, no history found.** `https://www.nseindia.com/api/reportASM` and `.../reportGSM` return real current-stage JSON (`asmSurvIndicator`/`gsmStage`, per ISIN, with an `asmTime`/`gsmTime` that looks like an effective date rather than a query parameter), but no equivalent dated-file pattern was found or guessed for history, and the budget was spent confirming the band mechanism instead of guessing further. **Falls back to Sravanth's stated default: null + flag per event**, exactly as if this spike had not found the current-list endpoints at all — recording ASM/GSM history needs either a paid data vendor or manually collected NSE circulars, neither of which this spike attempted.

### Blocked on Sravanth, before the next build phase

Work only he can do:

1. ~~**Git remote.** There is none.~~ **Done.** `origin` is `github.com/sravanth-dev/tradebot_NSE_order_scraper`, `main` tracks `origin/main`, and as of 22 Sep 2026 nothing is unpushed — so the spikes, fixtures and decisions now have an offsite copy and D1's deploy path (laptop push → VPS pull) exists.
2. ~~**Postgres on the laptop**, with `DATABASE_URL` set.~~ **Done and verified end to end, 22 Sep 2026.** PostgreSQL 16.15 running as `postgresql-x64-16` on port 5432; role, database and database owner are all `tradebot`, so the migration runner can create tables — confirmed by creating one, writing to it and rolling back. `NUMERIC(20,2)` returns `Decimal` and `timestamptz` returns a tz-aware datetime. `migrations/` is still empty, so the database has no schema yet: Slice 1 writes `0001_init.sql`.
3. **Ten order PDFs with hand-labelled expected JSON**, which gate Spike D. (~50 later for the eval set.)
4. ~~**`config/holidays_2026.yaml`**, per D27, before the live collector runs.~~ **Done** (22 Sep 2026). Sravanth supplied NSE's official 2026 list and it is committed as `config/holidays_2026.yaml`: sixteen weekday closures from the CM segment, plus the 8 Nov Muhurat as a `special_sessions` entry. One gap remains and is NSE's, not ours — the Muhurat **timings are not published yet**, so `session` is null rather than guessed; fill it in when NSE circulates them.
5. **To activate §5.5 Part B** (vision OCR for unreadable scans), Sravanth supplies `OPENAI_API_KEY` (Reg30 Radar-only project, in `.env`), a vision-capable `ocr_model` id with its input/output prices in `config/llm.yaml`, and `caps.ocr_usd_per_month`. Until then image pages that fail every other extraction attempt go to manual review, never guessed.

Promised before the phases that need them: **VPS numbers** (Spike E — free memory, free disk, swap, the Docker network name, how Postgres is configured) and the **OpenAI model IDs and prices** (Spike D).

Decisions owed, each blocking a slice: ~~FX source~~ (USD at ₹94 for now, 29 Sep 2026) · OpenAI data-sharing opt-in (Spike D) · User-Agent contact string (Slice 1) · ~~backup mechanism~~ (decided 27 Sep 2026: rclone, D14).

---

## 12. Glossary

- **Bucket**: the router's label for a filing (noise, order_win, …).
- **Event**: one real-world announcement. Repeat filings of the same order are merged into one event (§5.3).
- **TTM revenue**: the sum of the last four quarters' revenue.
- **Point-in-time**: using only data that was public at that moment. Prevents look-ahead bias in the backfill.
- **Contamination**: another material filing near an order, which could explain the price move instead.
- **Annexure**: the standard table SEBI requires in order-win filings.
- **UDiFF bhavcopy**: the exchanges' common daily price file format.
- **PR bundle**: NSE's daily zip of reports (announcements, market caps, price data, …).
- **T0 / T1 / T2**: routing tiers. Code, then a cheap model, then a stronger model (escalation only).
- **Escalation trigger**: an objective, checkable reason to send a case to T2. Never a model's own confidence.
