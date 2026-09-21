# ARCHITECTURE.md — tradebot, Phase 1: announcements → order signals

Version 0.4 · 21 Sep 2026 · Owner: Sravanth

Change log:
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
1. **Collector**: every corporate announcement from NSE and BSE, with the exchange timestamp and our first-seen timestamp.
2. **Category lookup (router)**: route each filing to a bucket using the exchange's own category. No LLM.
3. **Order extractor**: pull order details from the filing PDF and normalize the value to rupees.
4. **Revenue loader**: point-in-time trailing-12-month (TTM) revenue from NSE quarterly results (XBRL).
5. **Calculator**: order value vs TTM revenue and vs market cap.
6. **Backfill + event study**: run 1–5 over 12 months of history and measure price moves after order wins.

We collect and classify everything, but act only on order wins.

### Not in Phase 1
Order placement or any broker code · media sources (Moneycontrol etc.) · live alerts · Google Sheets sync · intraday prices · SME-platform companies · everything in §5.12.

---

## 2. Decisions

| # | Topic | Decision | Status |
|---|---|---|---|
| D1 | Development | Claude Code on the Windows laptop → private GitHub repo → VPS pulls | Decided |
| D2 | Runtime | Docker Compose services on the Hetzner CX22, next to n8n | Decided |
| D3 | Database | New database `tradebot` inside the existing Postgres; never touch n8n's database | Decided |
| D4 | LLM | OpenAI API on existing credits, with model routing: code first (T0), a cheap model (T1), a stronger model only on escalation (T2) | Decided |
| D5 | LLM budget | As close to zero as possible: hard spend caps, with a queue that waits at the cap (cap amounts in §6 are Default) | Decided |
| D6 | Polling | 60 s, jittered, from 08:00 to 22:00 IST on trading days; jittered 10 min otherwise. The window runs to 22:00 because a large share of Indian filings arrive after the board meeting ends, between 16:00 and 21:00 | Decided |
| D7 | PDFs downloaded | Only for order-win, order-candidate and LLM-confirmed catch-all items; links only for the rest | Decided |
| D8 | PDF retention | Delete each PDF after text extraction; keep text, URL and SHA-256. The `tests/labelled/` PDFs stay in the repo permanently — **exception confirmed** | Decided |
| D9 | Universe | NSE mainboard only; BSE filings used only for companies also listed on NSE | Decided |
| D10 | Backfill | 12 months of announcements. Prices, market caps and band hitters: 12 months **+ 30 trading days**, so the −20-day pre-event window and 20-day average volume have room at the start. Results: 24 months, so four quarters precede the earliest event | Decided |
| D11 | Google Sheets | Phase 2: scored orders + daily digest, one-way (view-only) | Decided |
| D12 | Python | Same version on laptop and VPS: 3.14. **Windows/cp314 verified** in Step 0 — all 11 approved deps installed from wheels on 3.14.2, no source builds. manylinux still to check (Step 1) | Default |
| D13 | Secrets | `.env` on each machine only; `.env.example` committed | Default |
| D14 | Backups | Nightly `pg_dump` of `tradebot` to Google Drive, in place **before the backfill**, not before live use: the backfill is weeks of scraping plus LLM spend and is the expensive thing to lose | Default (mechanism Open) |
| D15 | LLM logging | Every call logged: model, prompt version, tokens, status | Default |
| D16 | Raw data | Append-only; never edited | Default |
| D17 | Time | `timestamptz` everywhere; Asia/Kolkata at the edges; no naive datetimes | Default |
| D18 | Alerts | Deferred until after the backfill verdict | Default |
| D19 | Where code runs | Spikes and the 12-month backfill run on the **laptop, over a phone hotspot — not the campus network** — into a local Postgres. The VPS runs only the live collector, writing to a `tradebot` database created in the existing Postgres via `docker exec psql`. No SSH tunnel and no change to n8n's containers in Phase 1 | Decided |
| D20 | Build order | §10 stays as written for now. A revised build order is proposed **after** Slice 0, from the spike results | Decided |
| D21 | Price data quality | Corporate actions and circuit limits are handled in Phase 1, not deferred (§5.9, §5.11) | Decided |
| D22 | Verdict | The go/no-go rule is pre-registered in §5.11 and fixed before any returns are computed | Decided |
| D23 | Live collection | Not deferred to Phase 2. After Slice 0, a **minimal NSE-only live collector** runs on the VPS: raw store only, no BSE, no dedup, no health dashboard. Rationale: `first_seen_at` cannot be backfilled, and forward-collected data is the only honest test for anything found by exploration (§5.11) | Decided |

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
- **Volume** (one ordinary day, NSE only, Fri 18 Sep 2026): ~1,229 announcements from ~881 companies, of which 22 were order-win filings from 12 companies.

---

## 4. System overview

```
[collector]  NSE + BSE announcements   (60 s in market window / 10 min otherwise)
      |
      v
raw_announcements  (append-only)
      |
      v
[normalizer]  attach ISIN → keep NSE-mainboard universe → merge NSE/BSE copies into one event
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
  - NSE corporate announcements: the JSON endpoint the NSE announcements page calls (find it in browser dev tools → Network). NSE also publishes an official RSS feed for announcements; use it as a cross-check and fallback. **Verify**: live query, date-range query, and which fields exist (sequence ID, symbol, ISIN, category, attachment URL, industry).
  - BSE corporate announcements: the JSON endpoint behind BSE's announcements page. **Verify** the same things.
- **Modes**:
  - `live`: poll on the schedule below.
  - `backfill`: date range, resumable (checkpoint per source per day), slow pacing (Default ≥3 s between requests).
- **Schedule** (D6): trading days 08:00–22:00 IST every 60 s **with jitter**; all other times every 10 min, also jittered. A fixed interval from a datacentre IP is the clearest bot signature there is, so the interval is never exactly periodic. Holiday calendar in `config/holidays_2026.yaml` (source is Open).
- **Idempotent**: unique on (source, source_id); re-polling never creates duplicates.
- **Politeness**: one request at a time per source; exponential backoff with jitter on errors; on 401/403, refresh the session once, then back off; consistent User-Agent.
- **Health**: update `source_health` on every poll. Log a warning if a source has no successful poll for 10 minutes inside the market window.
- **Stored** (raw): source (NSE|BSE), source_id, exchange_ts, first_seen_at, symbol or BSE scrip code, company name, ISIN if present, raw category string, headline/description, attachment URL, full payload (jsonb).
- **Verified** (Slice 0 Step 0, from `tests/fixtures/an18092026.txt`, 1,265 lines): the PR bundle's announcement file carries **company name, symbol, category and description text — and nothing else**. It has no per-filing timestamp, no attachment URL and no ISIN.
  Consequences: (a) the PR bundle **cannot** drive the backfill on its own, because day-0 determination and point-in-time discipline need the exchange timestamp, and the document pipeline needs the PDF link — both must come from the JSON endpoint or the per-filing page; (b) the file **is** sufficient to test the router (§5.4), which only reads the category string; (c) it is a good completeness cross-check on whatever the JSON endpoint returns for the same day.
- **Hybrid backfill plan** (follows from the above). Two sources, each doing only what it is good for:
  1. **Daily PR bundle** — prices, market caps, Nifty, band hitters, and a daily index of *who filed what category*. One archive download per trading day, no anti-bot surface.
  2. **Announcements API** — called **only** for filings the bundle's index already routed to `order_win` or `order_candidate`, purely to fetch the exchange timestamp and the attachment URL.
  This keeps API traffic proportional to order filings (roughly 22 a day) rather than to all filings (roughly 1,229 a day) — about a 55× reduction against paginating the API for the full history.

### 5.2 Instruments and ISIN map
Purpose: one identity per company (ISIN) across NSE symbols and BSE scrip codes. This also defines the universe.

- NSE side: the daily UDiFF bhavcopy (`BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`) gives ISIN, symbol and series.
- BSE side: the BSE UDiFF bhavcopy is used **only as a mapping table** (`FinInstrmId` = BSE scrip code → `ISIN`; e.g. ABB is 500002). It is never a price source.
- Universe rule (D9): the ISIN has an NSE mainboard listing (series other than SM/ST). BSE filings for ISINs outside the universe are stored raw and not processed.
- Store but don't act on in Phase 1: NSE series (EQ vs BE/BZ), ASM/GSM membership. These become trade-time filters later.

### 5.3 Normalizer and dedup
- Attach ISIN: NSE via symbol/ISIN; BSE via the scrip-code map.
- Normalize the category string: trim, collapse spaces, strip a trailing `-XBRL`. Keep suffixes like `(Sub-para 4-Para B)` as a separate `para` attribute.
- **Dedup** (Decided): merge only on an **exact** key — the same attachment SHA-256, or the same (ISIN, `value_inr`). Never on "similar headline". Two reasons: NSE and BSE headlines for one filing often differ substantially, and companies routinely file several *different* order wins on the same day (18 Sep 2026: 22 order filings from 12 companies), so a fuzzy rule would collapse real, distinct events. A merged `event` holds both raw rows and both exchange timestamps; event time = earliest exchange timestamp. Prefer the NSE copy's PDF; don't download the BSE duplicate.
- **Revisions** (Decided). `raw_announcements` is append-only *and* unique on (source, source_id), which on its own would silently discard NSE's corrections — the same ID returns with amended text or a new attachment and `ON CONFLICT DO NOTHING` drops it with no trace. So the uniqueness key includes a **payload hash**, and a changed payload for an existing source_id is stored as a **new revision row** rather than ignored. If the source turns out to have no stable ID (Spike A), the synthesised key must be built from fields that do not change on a revision.
- Keeping both timestamps answers, with data, which exchange publishes first.

### 5.4 Router (category lookup)
- `config/category_map.yaml`: (exchange, normalized category) → one bucket from {`noise`, `order_win`, `order_candidate`, `catch_all`, `red_flag`, `other_material`, `results`}.
- Unknown category → bucket `catch_all` (safe default) and a row in `unknown_categories` for weekly review.
- **Keyword prefilter** (catch_all only). A filing becomes an LLM-triage candidate if its headline matches order / contract / award / letter of award / LoA / LoI / work order / purchase order / L1 / lowest bidder. It is suppressed if it matches orders passed / income tax / assessment / NCLT / court. Only candidates reach the LLM.
- **Rules from the Fri 18 Sep 2026 NSE file** (these become router tests):
  - `Declaration of NAV`, `Shareholders meeting`, `Analysts/Institutional Investor Meet/Con. Call Updates`, `Analyst/Investor Meet Para A`, `Trading Window`, `Copy of Newspaper Publication` → `noise`. Together these were ~40% of the day's filings.
  - `Bagging/Receiving of orders/contracts` (with or without `(Sub-para 4-Para B)`) → `order_win`.
  - `Awarding of order(s)/contract(s)` → `order_candidate`. The category doesn't say whether the company won or gave the order (BEML filed under it). The PDF decides.
  - `Action(s) taken or orders passed`, `Actions initiated/taken or orders passed` → `red_flag`, never `order_win`. The word "order" is misleading here.
  - `Amendment or termination of orders/contracts` → `red_flag`.
  - `General Updates`, `Updates`, `Press Release` → `catch_all`. That day, a real order win arrived as a Press Release (HILINFRA: ₹220.66 crore toll-operations contract; market cap ~₹315 crore). An EPC contract under General Updates read as the company *placing* an order (GREENPOWER). A tax-appeal "order" came under Updates (KNRCON).
  - Assert on category → bucket mappings, not exact totals. The rough parse found ~1,229 filings, but multi-line entries can shift counts.

### 5.5 Document pipeline
- Runs only for `order_win`, `order_candidate` and LLM-confirmed `catch_all` items (D7).
- Steps: download PDF → SHA-256 → extract text (pdfplumber; fallback pypdf) → save text in `documents` → **delete the PDF** (D8).
- Scanned PDFs (little or no extractable text): set `is_scanned`. Until this is decided, send them to manual review. (Open: local OCR costs CPU/RAM on the CX22; a vision-capable model costs tokens.)
- Keep URL, SHA-256, page count, text, extraction method and timestamps. If a later re-run needs the PDF, re-download it from the URL and check the hash matches.
- Exception (proposed, needs Sravanth's confirmation): PDFs in the labelled test set (`tests/labelled/`) stay in the repo permanently.

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
4. **Normalize** with the unit normalizer (§5.7).

**The model never normalizes** (Decided). It returns raw strings and spans only. Every conversion — units, scale, currency, dates, ratios — happens in code, where it is testable and reviewable. This also removes a whole class of silent error: a model that "helpfully" converts crore to rupees cannot be checked against the source text, because the converted number is not in it.

### 5.7 Unit normalizer (pure functions, heavily unit-tested)
- Output is `Decimal` rupees. Never float.
- Handles:
  - currency markers: ₹, Rs., Rs, INR;
  - units: crore (cr, crs, crores), lakh (lac, lakhs), million (mn), billion (bn);
  - Indian digit grouping (65,02,160.50) and a trailing "/-";
  - "approx"/"approximately"/"about" → `approx` flag;
  - "incl./including GST" → `gst_inclusive`;
  - ranges → low/high values plus a flag;
  - foreign currency → flagged and **not converted**; FX remains Open, and a foreign-currency order is flagged for review rather than guessed at;
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
- Source: NSE quarterly financial results in XBRL. Since April 2025 NSE takes these through "Integrated Filing – Financial"; earlier quarters are under the older "Financial Results" filings. Both use SEBI's in-capmkt taxonomy, so one parser should handle both. **Verify** download paths and parse one filing of each type in Slice 0.
- Extract per ISIN per quarter: revenue from operations, period end, period length, basis (consolidated/standalone), unit/scale, `filed_at` (exchange timestamp), source URL.
- Basis (Default): consolidated if filed, else standalone. Record which one was used.
- **Discrete vs cumulative contexts** (Decided). The in-capmkt taxonomy carries both discrete-quarter and cumulative (H1, 9M, FY) contexts. Picking the wrong one double-counts silently, which is the single most likely source of quietly wrong TTM. The parser selects on the context's period length explicitly and records which it used; Spike C must demonstrate both on real filings.
- **Q4 derivation** (Decided): `Q4 = FY − 9M`. Most Indian filers publish audited full-year results and never file Q4 as a discrete quarter, so a naive "latest four quarters" rule returns null for a large share of companies exactly when TTM is most needed.
- **Point-in-time TTM** for date D: the sum of the latest four quarterly revenues with `filed_at` ≤ D, all on the same basis. A missing quarter gives null. Never guess.
- Banks, NBFCs and insurers are excluded from order ratios (Default), because their "revenue" means something different. This needs a **sector / industry column on `instruments`** (Decided) — the exclusion currently has no mechanism, since nothing in the data model identifies a sector. Spike A sources it, ideally from the `industry` field the announcements API is expected to carry.
- Sanity check: when a full-year figure exists, the four quarters should roughly add up to it. Log mismatches.
- Backfill depth: ~24 months of results, so there are four quarters before the earliest event.

### 5.9 Market data loader
- NSE UDiFF bhavcopy (daily) → `prices` (open, high, low, close, volume, series per ISIN). The bhavcopy is also the only one of these files that carries ISIN, so it is the join key for the other two.
- NSE market-cap file (`mcapDDMMYYYY.csv`, inside the daily PR bundle) → `market_caps`. **Verify** archive depth; 12 months is what the event study needs, 24 was over-stated.
  - **Verified** (Step 0, `tests/fixtures/mcap18092026.csv`): the column is `Market Cap(Rs.)` and the values are **plain rupees**, not lakhs or crores. Keyed by Symbol + Series, so it needs the bhavcopy for ISIN. Columns: Trade Date, Symbol, Series, Security Name, Category, Last Trade Date, Face Value, Issue Size, Close Price, Market Cap.
- Nifty 50 daily close (index rows in the PR bundle's `pd` file) → `index_prices`, used for returns relative to the market.
  - **Verified** (Step 0, `tests/fixtures/pd18092026.csv`): index rows carry `MKT=Y` and `IND_SEC=Y`, with `Nifty 50` as the first row. Columns: MKT, SERIES, SYMBOL, SECURITY, PREV_CL_PR, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, NET_TRDVAL, NET_TRDQTY, IND_SEC, CORP_IND, TRADES, HI_52_WK, LO_52_WK. No ISIN, so this too joins via the bhavcopy.
- **Corporate actions** (D21). Bhavcopy and `pd` prices are *unadjusted*, so a split or bonus inside an event window reads as a huge fake loss — and splits and bonus issues are common in exactly the small-caps this study targets. Two signals handle it, both already in the daily files and both free:
  - `CORP_IND` in the `pd` file flags the ex-date directly. **Verified** on 18 Sep 2026: 70 rows `XD`, 2 `XI`, 1 `XO`, 3,741 blank. The full code list is still to confirm (expect `XB` bonus, `XS` split, `XR` rights).
  - `PREV_CL_PR` is set by NSE to the *adjusted* previous close on an ex-date. So returns are computed as `CLOSE_PRICE / PREV_CL_PR - 1`, never against the previous row's close, and a mismatch between the two is an independent corporate-action detector.
  - Volume ratios (§5.11) are distorted by the same events; flag rather than adjust them.
  - **Spike B must prove this on a real ex-date** before Slice 7 depends on it: take one known split or bonus in the window, chain the return through `PREV_CL_PR`, and show it comes out near zero rather than near −50% or −90%.
- **Band hitters** (D21). The PR bundle's `bhDDMMYYYY.csv` lists the securities that hit their price band that day (SYMBOL, SERIES, SECURITY, HIGH/LOW). This is the direct source for the circuit flag, so the band does not have to be inferred from the price move. A micro-cap that gates up on an order win is untradeable, and counting that move as return would be fictitious P&L.
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
  - **Volume**: event-day volume ÷ 20-day average volume. Flagged, not used, when a corporate action falls in the window (§5.9).
  - **Contamination**: the same ISIN has another non-noise filing within ±3 trading days. Tag it and report it separately.
  - **Corporate action** (D21): tag any event whose window contains a `CORP_IND` flag or a `PREV_CL_PR` mismatch. Returns always come from `CLOSE_PRICE / PREV_CL_PR - 1`, so they are already adjusted; the tag exists so a bad adjustment can be found later.
  - **Circuit limits** (D21): Indian stocks trade inside 5 / 10 / 20% price bands. A micro-cap that wins a large order can gate up untradeably, and a measured +10% on a 5%-band stock is fictitious P&L — which matters because the whole question is whether Sravanth can *trade* this. The flag comes straight from the PR bundle's **`bhDDMMYYYY.csv` band-hitter file** (§5.9), not from inferring the band. Tradeable return is reported separately from paper return.
- Buckets (Default, change freely):
  - value_to_ttm: <5%, 5–15%, 15–40%, >40%;
  - market cap: <₹1,000 cr, ₹1,000–10,000 cr, >₹10,000 cr.
- Output: `reports/backfill_<date>.md` plus a CSV, showing per bucket (clean vs contaminated) the event count, median and mean excess return, and hit rate.
#### Pre-registered verdict rule (D22)

Fixed in writing **before any returns are computed**. Changing it after seeing results means
the result is exploratory, and it must be labelled as such.

**Primary hypothesis.** Verified order wins with `value_to_ttm` ≥ 15%, at companies with market
cap below ₹10,000 crore, earn a positive return over Nifty from day-0 close to day +5.

**Measurement.** Clean (uncontaminated) events only. Returns from day-0 close. The **median**
excess return is the primary statistic; the mean is secondary.

**GO only if all four hold:**

1. At least **30 clean events** in the primary bucket. Fewer is "insufficient data", not GO.
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

- **Provider**: OpenAI API, paid from existing account credits. Create a separate OpenAI project with its own API key for tradebot (`OPENAI_API_KEY` in `.env`), so its spend is isolated and visible. Use the official `openai` Python SDK.
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
  3. A judgment field comes back unknown: `company_is_recipient` or `stage`.
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
- **Cost controls**:
  - Every call logs its tokens and computed cost (tokens × price table) in `llm_calls`.
  - Hard caps: **set after the Spike D bake-off**, once the parser hit rate and the escalation rate are measured (Decided). The earlier defaults of $2/month and $10/backfill were arithmetic guesses, and at any meaningful escalation rate the $10 backfill cap and the escalation policy are not compatible: ~5,500 order events at ~8K input tokens is already ~$4.40 on Batch at the cheapest tier, before a single escalation. The cap follows the measurement, not the other way round. At a cap, items wait as `pending_llm`; nothing is dropped, and nothing retries in a loop.
  - Second guard: set a monthly budget and alert threshold on the OpenAI project in the dashboard.
  - The backfill uses OpenAI's Batch API (half price, results within 24 hours). Live processing uses the standard API.
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
- **Evaluation**: `tests/labelled/` holds ~50 hand-labelled order PDFs with expected JSON. `python -m tradebot.eval` reports per-field accuracy per tier, the escalation rate and the cost per document. A model or prompt goes live only if the full chain hits ≥ 95% exact `value_inr`.
  This threshold is a **smoke test, not a measurement** (Decided): at n = 50 the confidence interval is roughly ±6%, so 95% and 93% are statistically indistinguishable. It catches something badly broken; it does not certify accuracy.

---

## 7. Data model (Postgres, database `tradebot`)

All timestamps `timestamptz`; money `NUMERIC(20,2)`. **Ratios are not money** and get their own type, `NUMERIC(12,6)` — two decimal places would round a 0.4% ratio to zero. Columns abbreviated.

- `raw_announcements`(id, source, source_id, **payload_sha256**, **revision**, exchange_ts, first_seen_at, symbol, bse_code, company, isin, category_raw, headline, attachment_url, payload jsonb) — UNIQUE(source, source_id, payload_sha256); append-only. The hash in the key is what stops an exchange revision being silently swallowed (§5.3); `revision` increments for each re-filing of the same source_id.
- `events`(id, isin, bucket, category_norm, para, headline, event_ts, nse_raw_id, bse_raw_id, nse_ts, bse_ts, in_universe, status)
- `documents`(id, event_id, url, sha256, pages, text, is_scanned, method, extracted_at, pdf_deleted_at)
- `orders`(id, event_id, awarding_entity, domestic_or_international, nature_of_order, significant_terms, execution_period_raw, execution_months, consideration_raw, value_inr, **value_span**, value_flags, gst_inclusive, currency, promoter_interest, related_party, receipt_datetime, company_is_recipient, stage, is_follow_up, extractor, prompt_version, **state**, verified, review_status) — `value_span` is the exact quoted text the value came from, which is what the provenance check verifies (§5.6); `state` is the extraction state machine in §6.
- `instruments`(isin PK, nse_symbol, nse_series, bse_code, name, board, **sector**, **industry**, first_seen, last_seen) — sector/industry carry the bank / NBFC / insurer exclusion in §5.8, which previously had no mechanism.
- `prices`(date, isin, open, high, low, close, **prev_close**, volume, series, **corp_ind**, **band_hit**) — PK(date, isin). `prev_close` is NSE's `PREV_CL_PR`, which is already corporate-action adjusted and is what returns chain from (§5.9); `corp_ind` is the ex-date flag; `band_hit` comes from the `bh` band-hitter file.
- `index_prices`(date, index_name, close) — PK(date, index_name)
- `market_caps`(date, isin, mcap_inr) — PK(date, isin)
- `financials`(isin, period_end, period_months, basis, revenue_inr, scale, filed_at, source_url) — UNIQUE(isin, period_end, basis)
- `materiality`(order_id, ttm_revenue_inr, ttm_asof, basis, mcap_inr, mcap_date, value_to_ttm, next12m_to_ttm, value_to_mcap, flags) — the three ratios are `NUMERIC(12,6)`.
- `llm_calls`(id, ts, tier, model, prompt_version, purpose, event_id, in_tokens, cached_tokens, out_tokens, cost_usd, batch_id, latency_ms, status, escalation_reason, error)
- `source_health`(id, source, checked_at, ok, error) — **one row per poll, not one per source**. A single mutable row answers "is it up now?" and nothing else; keeping history is what makes an outage diagnosable afterwards.
- `unknown_categories`(exchange, category_raw, first_seen, count)
- `backfill_checkpoints`(job, key, done_at)
- `schema_migrations`(version, applied_at)

Migrations (Default): plain numbered SQL files in `migrations/` (`0001_init.sql`, …) applied by a small runner. No ORM magic, so every schema change is readable.

---

## 8. Storage and retention

- PDFs: downloaded only for the D7 buckets and deleted right after text extraction (D8). Text is kept; it's a few KB per filing.
- Why keep text: it lets a better parser or prompt re-run over the whole backfill without re-downloading thousands of PDFs from NSE, and any number can be checked against its source later.
- Exception (proposed): the labelled test-set PDFs stay in the repo. They are the ground truth for judging free models.
- Backfill reports in `reports/` **are committed to git** (Decided). They are small, and the history of what each run concluded is worth keeping.
- Disk guard: log a warning when disk usage passes 80%.
- Docker logs: json-file driver, `max-size: 10m`, `max-file: 3`.
- Backups (D14): nightly `pg_dump` of `tradebot` to Google Drive, in place before any live use. Mechanism is Open: rclone, or an n8n workflow.

---

## 9. Deployment and environment

```
tradebot/
  CLAUDE.md  ARCHITECTURE.md  .env.example  .gitattributes  .gitignore
  Dockerfile  docker-compose.yml  pyproject.toml
  config/      sources.yaml  category_map.yaml  llm.yaml  holidays_2026.yaml
  prompts/     triage_v1.md  order_extract_v1.md
  migrations/  0001_init.sql ...
  src/tradebot/
    common/  (config, db, logging, time, http, migrate)
    collector/  normalizer/  router/  documents/  extractor/  units/
    revenue/  market/  calculator/  backfill/  llm/  eval/
  tests/
    fixtures/  (NSE an18092026.txt, pd18092026.csv, mcap18092026.csv; BSE BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV)
    labelled/  (hand-labelled order PDFs + expected JSON)
    unit/  live/  (live = hits real sites; skipped unless `-m live`)
  reports/
```

- **Approved dependencies** (Default): requests, feedparser, pdfplumber, pypdf, lxml, psycopg[binary] (v3), pydantic, openai, APScheduler, python-dotenv, PyYAML, pytest. Ask before adding anything else.
- **Docker Compose** (Default): one image, two services:
  - `collector`: live polling;
  - `worker`: router, documents, extractor, calculator, and scheduled revenue/market jobs.
  - Backfill runs as a one-off: `docker compose run --rm worker python -m tradebot.backfill ...`.
- **Network**: join the existing Docker network the Postgres container is on (declared `external: true`). Publish no ports.
- **Memory and CPU**: `mem_limit: 512m` per service, so a bad PDF can't starve n8n, and a `cpus:` limit alongside it (Decided) — pdfplumber is CPU-bound, and without a cap one extraction run holds a core for hours and makes n8n visibly slow on a 2-vCPU box. Actual values are set from the measured headroom in Spike E. A container killed at its memory limit must be recorded as `needs_review`, never left to restart-loop.
- **Database setup** (once, by hand, as the Postgres superuser):
  `CREATE USER tradebot WITH PASSWORD '...'; CREATE DATABASE tradebot OWNER tradebot;`
  The `tradebot` user has no rights on n8n's database.
- **Deploy** (D1): laptop `git push` → VPS `git pull && docker compose up -d --build`.
- **Line endings**: `.gitattributes` with `* text=auto eol=lf`. Windows dev, Linux prod.
- **Viewing data (Phase 1)**: **no SSH tunnel and no change to n8n's containers** (D19). The `tradebot` database is created in the existing Postgres with `docker exec psql`, and queried the same way. This resolves what was a direct conflict between CLAUDE.md's rule 5 (never touch n8n's containers) and the earlier plan to re-bind the Postgres port for DBeaver: if Postgres is part of n8n's stack, changing its port binding *is* touching it. The backfill runs on the laptop against a local Postgres anyway, so the tunnel bought little.
- **Local database** (D19): Postgres on the laptop holds the backfill. The VPS Postgres holds only what the live collector writes. Most tests — units, router, TTM logic, calculator — need no database at all.

---

## 10. Build order

Each slice ends with passing tests and a short plain-language summary for Sravanth.

0. **Spikes** (verify unknowns; write findings back into this file). Throwaway probe code lives in `spikes/`, never in `src/`.
   - *Step 0 done*: scaffold, `.gitignore`/`.gitattributes`, `.env.example`, placeholder `config/llm.yaml`, `pyproject.toml`, passing `pytest`. Findings written into §5.1 and §5.9.
   - **Spike B — historical bulk files. First among the network spikes** (Decided). Archive depth for the UDiFF bhavcopy and the PR bundle (`pd`, `mcap`, `bh`, `an`) across 12 months + 30 trading days. Prove return chaining through `PREV_CL_PR` on one known split or bonus ex-date. Record **NSE's robots.txt and terms-of-use position** as a written finding, so scraping is a decision rather than an accident.
   - **Spike A — announcement endpoints.** NSE and BSE: live query, date-range query, available fields. Must answer: is there a stable `source_id`, does a revision reuse it, and is there a sector/industry field to carry the bank/NBFC/insurer exclusion (§5.8)?
   - **Spike C — results XBRL.** Parse one Integrated Filing – Financial and one older Financial Results filing. Must show **both** a discrete-quarter and a cumulative context, and demonstrate the Q4 = FY − 9M derivation.
   - **Spike D — extraction bake-off.** Four arms on 10 labelled PDFs: parser alone, GPT-5 nano, gpt-4.1-mini, GPT-5.6 Luna. Per-field accuracy, tokens, cost per document, every failure. **Hard stop $0.50.** Sets tier 1, decides whether a second tier is needed at all, and only then sets the spend caps. Also covers the OpenAI data-sharing page: eligibility and covered models.
   - **Spike E — VPS preflight.** Read-only: free memory, free disk, swap, the external Docker network name, and how the existing Postgres container is configured. Sets the `mem_limit` and `cpus` values.
   - **Python 3.14 wheels** for every dependency. Windows/cp314 already verified in Step 0; manylinux still to check.

**Slices 1–8 below stand as written for now** (D20). A revised build order is proposed after
Slice 0, from the spike results — not before. Two things already shape that proposal: the
hybrid source plan in §5.1 (the PR bundle cannot carry timestamps or PDF links, so the API is
still needed for order filings), and D23 (a minimal NSE-only live collector starts on the VPS
straight after Slice 0, because `first_seen_at` cannot be backfilled).

1. Collector (NSE live + backfill mode), raw store, source health.
2. Instruments / ISIN map, BSE collector, normalizer, dedup.
3. Router + unknown-category log; tests from the Fri 18 Sep fixture (§5.4).
4. Document pipeline (download → text → delete), annexure parser, unit normalizer (test vectors in §5.7).
5. LLM client (OpenAI SDK): routing tiers and escalation triggers, spend caps, structured output + validation, logging, Batch mode for backfill. Plus labelled-set evaluation.
6. Revenue loader + point-in-time TTM.
7. Market data loader + calculator.
8. 12-month backfill + event-study report → go / no-go.

---

## 11. Open decisions

Resolved since v0.2: the model acceptance threshold (§6 — kept at 95%, but recorded as a smoke test), the T2 upgrade path (superseded by the Spike D bake-off), spend cap amounts (set after Spike D), the local dev database (D19), and the market-window edges (D6).

Still open:

- Scanned PDFs: local OCR, a vision-capable model, or manual review only.
- FX source for foreign-currency orders.
- NSE holiday calendar source.
- Opting into OpenAI data sharing for this project (free daily tokens vs sharing prompts).
- Backup mechanism (rclone or n8n).
- Local dev database (§9).
- Event-study bucket edges (§5.11) — *narrowed*: the **primary** bucket is now fixed by D22 (value_to_ttm ≥ 15%, market cap < ₹10,000 cr, +5 days). The remaining reporting cells stay Default and are exploratory.

Raised by Slice 0 Step 0:

- The full `CORP_IND` code list (XD/XI/XO seen; XB/XS/XR expected). Needed before Slice 7.
- Source of circuit-band membership (5/10/20%), for the tradeable-vs-paper return split (D21).
- Repo remote and branch name. The `user.email` typo is fixed and `reports/` is committed.

---

## 12. Glossary

- **Bucket**: the router's label for a filing (noise, order_win, …).
- **Event**: one real-world announcement, merging its NSE and BSE copies.
- **TTM revenue**: the sum of the last four quarters' revenue.
- **Point-in-time**: using only data that was public at that moment. Prevents look-ahead bias in the backfill.
- **Contamination**: another material filing near an order, which could explain the price move instead.
- **Annexure**: the standard table SEBI requires in order-win filings.
- **UDiFF bhavcopy**: the exchanges' common daily price file format.
- **PR bundle**: NSE's daily zip of reports (announcements, market caps, price data, …).
- **T0 / T1 / T2**: routing tiers. Code, then a cheap model, then a stronger model (escalation only).
- **Escalation trigger**: an objective, checkable reason to send a case to T2. Never a model's own confidence.
