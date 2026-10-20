# AUDIT — where tradebot Phase 1 stood on 20 Oct 2026 (GATE 1)

This is a snapshot taken for Sravanth's 20 Oct 2026 brief, before any Phase 1 fix landed.
It is not kept up to date: [STATUS.md](STATUS.md) is the live checklist and
[WORKLOG.md](WORKLOG.md) the history. The spec is [ARCHITECTURE.md](ARCHITECTURE.md),
and decisions D28–D32 come from this gate.

How it was measured. All of it was read-only:
- Running processes and scheduled tasks.
- Both databases, through `tradebot.common.db.connect`, with each session set read-only.
- `pytest`, with the backfill-DB tests skipped and OpenAI and Google set to placeholders.
- `python -m tradebot.eval`, which uses no model.
- OpenRouter's public model list, which needs no key.
- Three read-only code-audit agents, one per module group.
No request was sent to NSE.

## Decisions taken at the gate (Sravanth, 20 Oct 2026)

| # | Decision |
|---|---|
| D28 | The VPS is cancelled. D1/D2 are void until GATE 2; D19's live half and D23 run nowhere meanwhile |
| D29 | The LLM stays on the OpenAI API under the existing caps, and no credits are bought. The brief's "free OpenRouter only" line described v0.1 |
| D30 | Live collection restarts only as one process (collector + orders in one loop) behind an NSE lock |
| D31 | The third documents tier (24,425 body-check-only catch-all PDFs) is skipped. The verdict uses tier one, and the report states the undercount |
| D32 | "over ₹X" gives X plus `lower_bound`; a range gives low/high, with value = low plus `range`; a band-only disclosure gives null plus `band_only`, sent to review |

## 1. Runtime state

- **Nothing is running.** There is no python process. Postgres 16.15 has been up since
  16:03 (the laptop rebooted). Docker Desktop 29.7.2 is installed, but its engine is stopped
  and there are no containers. No scheduled tasks exist, for the collector or for backups.
- **The live collector stopped on 1 Oct 2026.** Last poll 09:31, last filing first seen
  09:20. The `first_seen_at` hole since then cannot be backfilled (D23).
- **No backup had ever been made.** `backups/` was empty, rclone is not installed, and
  nothing was scheduled. The first dumps were taken at the end of this gate:
  `python -m tradebot.common.backup`, 5.5 MB live and 104 MB backfill.

| | live `tradebot` | backfill `tradebot_backfill` |
|---|---|---|
| migrations applied | 0001–0014 (all 14 files) | 0001–0014 (all 14 files) |
| raw_announcements | 6,673; first_seen 23 Sep 10:51 → 1 Oct 09:20 | 162,251 from 1,583 companies; exchange_ts 8 Aug 2025 → 27 Sep 2026 |
| documents | 1,041 (876 ok / 114 partial / 51 unreadable) | 2,120 (2,092 ok / 26 partial / 2 unreadable) |
| order_extractions | 1,051: 51 verified, 22 needs_review, 975 not_order, 3 download_failed | 2,138: 1,444 verified, 355 needs_review, 326 not_order, 13 pending_llm |
| backfill_events | — | 1,286, all `extracted` (952 order_win, 244 catch_all, 90 order_candidate; 93 USD) |
| financials | — | 6,523 rows, 229 ISINs; checkpoints for 223 of 231 event companies |
| prices / market caps / Nifty | — | 1,257,859 / 1,042,617 / 50,633; 388 trading days, 3 Mar 2025 → 25 Sep 2026 |
| archive_days / band_days | — | 575 each (1 Mar 2025 → 26 Sep 2026) |
| reconcile_days | — | 246; mean coverage 96.6%, 35 days below 95% |
| llm_calls | 106 (85 extraction, 21 OCR), $0.110, 25 Sep → 1 Oct | 1,647 (1,423 extraction, 224 OCR), $0.450, 27 → 30 Sep |
| llm_batches | — | 3 (2 completed, 1 rejected whole for OpenAI's enqueued-token limit) |
| backfill_checkpoints | — | 1,806 (announcements 1,583, revenue 223); first 27 Sep 18:13, last 4 Oct 16:30; **0 in the last hour** |
| source_health | 1,008 polls (912 ok, 96 failed), 20 overflows, 12 gap queries | — |
| unknown_categories | 0 (the live path never writes it) | 0 (only `calculate`/`study` write it, and neither has run) |
| event_results | — | 0 (`study` never run) |
| size | 28 MB | 893 MB |

Other facts:
- Disk has 116 GB free.
- Sleep on mains power is disabled.
- Only 3 of the 6,673 live rows are revisions, and all 3 are genuine `exchdisstime`
  changes. So the gap and catch-up queries hash filings identically to the live poll.
- Secrets: `.env` is gitignored (`.gitignore:2`) and appears in no commit
  (`git log --all -- .env` is empty).
- Nothing in `src/` logs environment values, connection strings, cookies or keys. One risk:
  `ops/backup.sh:39`, `docker-compose.yml:77` and `DEPLOY.md:84` put the full
  `DATABASE_URL` on a command line.

## 2. Tests and accuracy, as found

- **pytest:** 337 passed, 25 skipped (the backfill scratch-DB tests, held back so the audit
  wrote nothing), 1 deselected (`live`). 337 + 25 = 362, the count WORKLOG last recorded.
- **`python -m tradebot.eval`** (T0 only, 0 LLM calls): **8/18 = 44% exact `value_inr`**,
  the same as the 24 Sep baseline.
  - It invents a value twice. BEML gives 5400: `annexure.py:44` matches inside "valued",
    the line is cut before "Crores", and there is no "over" rule. WAAREEENER gives 2: "2 GW"
    is read as rupees because `money.py:220` defaults to INR.
  - Near misses. MCLOUD takes "44.60 Lakh" over the exact "Rs. 44,60,400/-"
    (`money.py:288-299`). NEWGEN converts the USD figure at ₹94 where the label holds the
    company's own INR figure.
  - The eval scores the bare parser and skips production's provenance and suspect gates
    (`orders/run.py:123-127`), so 44% is not the production accuracy.
- **Full chain, 0 new calls.** 8 labelled PDFs were also processed by the backfill
  (matched on `documents.sha256`), and 7 are correct:
  - Correct: BEL, GPTINFRA, HEG, HILINFRA, RAILTEL, ZAGGLE (no value, so review is right),
    and GREENPOWER (the company placed the order, so "not an order" is right).
  - BEML: "over ₹5,400 cr" was stored as ₹5,400 cr without a flag. That is correct under
    D32 once the flag is added.
  - Of the other 10, six are dated 21 Sep, after the window (`announcements_to` is
    2026-09-18), and four are outside the universe (AFFORDABLE, CEINSYS, CPL, VIVIANA).
- **Label gaps:**
  - No real scan is labelled; JISLDVREQS was never added.
  - `value_span` is filled on 0/18.
  - HEG is a full-page image labelled `is_scanned: false`.
  - The stage labels use words outside the enum.
  - For USD, three sources disagree: the label README says null, the labels use the
    company's own rate, and §5.7 says ×94.
- **Power analysis, still open.** σ ≈ 3.7% rests on one day's cross-section (16 → 17 Jul
  2026, two bhavcopies), scaled by √5, with the Nifty σ and correlation assumed rather than
  measured. It can now be measured from the 388 loaded days with placebo events through
  `study_data.load_market` and `event_study.measure`.
- **OpenRouter check.** `gpt-6-luna` (the id `config/llm.yaml` uses for tier 1, tier 2 and
  OCR) is not an OpenRouter id. `openai/gpt-6-luna` is listed there, and it is paid. Of 470
  listed models, 20 are free, limited to 20 req/min and 50 req/day for accounts that have
  bought under $10 of credits ever (1,000/day otherwise). Moot under D29.

## 3. Defects in values already marked "verified" (backfill database)

| Defect | Count | Cause |
|---|---|---|
| Values below ₹1 lakh | **20**: 15 L&T band disclosures read as ₹1,000–15,000 in rupees; COCHINSHIP ₹100 ×3 and SWANDEF ₹0 ×2 from a size legend | `parse_money`'s range branch (`money.py:262-286`) returns before the under-₹1-lakh suspect check, so `is_suspect` is false and both judges (`orders/run.py:127`, `llm_extract.py:113`) verify it |
| No currency marker | 22, e.g. "RM 6,465,400.80" (ringgit) and "KWD 875,000" stored as rupees, "2,00,000 Numbers of" stored as ₹2 lakh | the INR default (`money.py:220`); RM and KWD are not in `FOREIGN` |
| Lower bounds ("over ₹X") / ranges | 31 / 37 | no rule existed; D32 now gives one |
| Vision-read values with no second read (§5.5 Part C) | 42 | nothing outside `documents/` reads `page_report`, so `verified` is decided on text alone (`orders/run.py:123-127`, `llm_extract.py:103-122`, `backfill/batch.py:155-203`) |
| Provenance passes a dropped digit | latent | `provenance.py:49` is a raw substring test, so "13.51 Crs" verifies inside "113.51 Crs" |
| A date parses as a range | latent | the unanchored range regex (`money.py:263-286`): "dated 01-02-2026" gives ₹1 |
| Sep-2025 quarter stored as the half-year | 47 XBRL files, 25 companies, ~13 events without TTM | the declared-dates rule (`xbrl.py:109-116`) plus the first-wins insert (`0012_financials.sql:18`, `load.py:160`); the cause is still to be confirmed against one file |
| TTM basis silently switched | unknown | `ttm.py:59-67` falls back to standalone on a consolidated gap; `ttm_basis` (0011:25) is never written |
| CORP_IND lost for non-`N` market rows | 45 events on BE-series stocks | `market/parse.py:154` reads CORP_IND only where `MKT == "N"`; BE/ST rows sit under `MKT = G` |

TTM: 1,160 of the 1,286 events have it. Of the 126 without: 37 belong to the 8 companies
whose revenue fetch failed, ~13 come from the Q2 defect, and ~76 are honest nulls (recent
listings with fewer than four quarters on NSE).

## 4. Slice by slice

Status: **done**, **partial**, **missing**, or **diverges** (code differs from the spec).

### Slice 1 — collector (live) and backfill fetch: partial
| Item | Status | Evidence |
|---|---|---|
| D6 bands | done | `common/calendar.py:131-158`; jitter is only 0.4–1.6 s (`collector/nse.py:138-147`) |
| D27 fails loudly at start | done | `calendar.py:73-92`, `collector/__main__.py:163` |
| D27 at year rollover | diverges | with no `holidays_2027.yaml`, the error at `__main__.py:215-220` is caught at `:175-183`, so from 1 Jan it polls every ~61 s forever |
| Next-year warning from 1 Dec | partial | checked once at start only (`__main__.py:166-168`) |
| Post-close calendar reconciliation | missing | — |
| 10-minute no-success warning | missing | — |
| Payload-hash key, revision rows, append-only trigger | done | `0001_init.sql:45,55-69`; `collector/store.py:17-37` |
| Overflow gap closing | done | `__main__.py:105-143`; it reaches back only to yesterday |
| Multi-day catch-up | partial | `--catchup` sends one unsplit date-range request, with no truncation check and no health row (`__main__.py:234-262`) |
| Endpoints in config only | partial | `market/bands.py:28-29` hardcodes URLs |

### NSE politeness against the brief's rules: not met
- **No 5-consecutive-failure hard stop anywhere.**
  - The backfill's 401/403 breaker never fires: it looks for "401"/"403" in text that
    doesn't contain them (`backfill/announcements.py:143` against `collector/nse.py:113`).
  - `revenue/load.py:200-212` and `market/bands.py:158-177` never stop.
  - `market/__main__.py:118-124` and `orders/run.py:360-368` stop only after two 401/403s.
  - On 4 Oct a DNS outage marked 55 companies failed in three minutes.
- **429 backoff exists only in the live collector**; the backfill loops keep their 3 s pace.
- **The 3 s gap isn't kept across clients.** The first XBRL download follows the listing
  call immediately (`load.py:125-144`). A warm-up is followed by the request with no gap
  (`nse.py:98-107`, `documents/fetch.py:58,66-67`).
- **There is no process lock.** Compose runs the collector and `orders` side by side by
  design.
- **Structure changes pass silently.** `body.get("data", [])` records a successful poll with
  0 rows (`nse.py:120`), and renamed fields become nulls (`records.py:82-97`).
- The PDF fetcher never re-warms after a 401/403 (`documents/fetch.py:95-97`).

### Slice 2 — instruments, normalizer, dedup: done for the backfill
- ISIN by issuer code, exact-key merge: `backfill/events.py:41-67,95-110`.
- `normalizer/` is empty. The live path keeps the raw `sm_isin` and builds no events.
- The `para` suffix is discarded (`router/orders.py:26-37`).

### Slice 3 — router: diverges
- 146 categories in 8 buckets.
- An unknown category goes to `out_of_scope`, not `catch_all` as §5.4 says
  (`router/orders.py:92,110`), and the live path never logs it.
- `unknown_categories.count` grows on every `calculate`/`study` (`study_data.py:70-72`).
- The prefilter, body check and `llm_allowed` gate are done (`router/orders.py:64-133`).
- T1 triage (`prompts/triage_v1.md`) is not built; D7's download-and-body-check superseded
  it.

### Slice 4 — documents: done, with gaps
- Streamed download, SHA-256, size cap, dedup, per-page ladder, and `UnsafeDeletePath`
  are done (`documents/fetch.py:90-119`, `pipeline.py:53-138`, `text.py:91-215`).
- One OCR provider error escapes and stores the whole document as unreadable with no text
  (`ocr.py:22-25`, `text.py:155-177`). That is permanent once the PDF is deleted.
- OCR at the cap is stored as unreadable, not left waiting.
- "PDF deleted only after commit" has no database-backed test.

### Slice 5 — LLM: partial
- Done: a single provider entry point (`llm/client.py:167,373`); null caps fail closed; every
  call is logged; JSON schema + Pydantic with one retry carrying the error; Batch for the
  backfill and the standard API for OCR; prompts that say to ignore instructions in
  documents; the model never normalizes.
- Missing: §5.5 Part C (above), and triggers 1–3 escalating to T2 (failures go to
  `needs_review`).
- Tier 2 is the same model as tier 1 ("for now", Sravanth, 27 Sep).
- Gaps:
  - `llm_calls.event_id` and `escalation_reason` are always null.
  - LLM rows never store `gst_inclusive` (`orders/run.py:156-170`, `backfill/batch.py:186-202`).
  - The recheck retries without the error (`recheck.py:56`).
  - The gate audit can never fire (`orders/run.py:70`).
  - A provider error during extraction makes the filing download again (`llm_extract.py:154`).
  - The §6 evaluation (per-tier accuracy, escalation rate, cost per document) is missing:
    `eval/` scores T0 only.

### Slice 6 — revenue and TTM: built, run for 223 of 231 companies
- Done:
  - Declared period dates first, context dates as fallback (`xbrl.py:109-116`).
  - Q4 = FY − 9M (`ttm.py:47-53`).
  - Point-in-time, four quarters, null on a gap (`ttm.py:36-67`).
- Gaps:
  - The Q2 defect (§3).
  - The basis is not recorded.
  - No FY-vs-four-quarters check.
  - No positivity check on a derived Q4.
  - Facts that collide are silently dropped.
  - Truncated listings are checkpointed as done (`load.py:170`).
  - 8 companies failed.
- The bank/NBFC/insurer exclusion is deliberately empty (`config/backfill.yaml:58-60`,
  Sravanth, 27 Sep).

### Slice 7 — market data and calculator: built; prices end 25 Sep
- Done:
  - Bhavcopy and PR-bundle parsing, member names matched by case-insensitive prefix, and
    the band-hitter width tolerated (`market/parse.py:74-193`).
  - The capital-action exclusion with `NEW_ISIN` (`event_study.py:40,228-237`).
  - Band history (`market/bands.py:91-132`).
  - The three ratios with their flags in Decimal (`calculator/materiality.py:40-64`).
- Gaps:
  - CORP_IND only for `MKT=N` rows.
  - `mcap_trade_date` is never checked (`parse.py:208`).
  - `band_days` coverage is never checked.
  - The calculator has never run.
- An after-hours filing on 18 Sep has day 0 on 21 Sep. Its +5 needs 28 Sep and its +10
  needs 6 Oct, so the price tail must be loaded.

### Slice 8 — backfill stages, event study, report: built, never run end to end
- Done:
  - The D22 verdict logic (`event_study.py:296-341`).
  - Day 0, the windows, the volume ratio with Muhurat excluded, and contamination at ±3
    trading days (`event_study.py:92-269`).
  - The §6 state machine and trigger 4 (`events.py:148-162`, `recheck.py`).
- Diverges: a Muhurat day-0 event stays in the primary cell and is only counted
  (`event_study.py:301-309`).
- Missing from the report:
  - The full collected-universe line.
  - The per-day coverage series.
  - Clean-vs-contaminated statistics.
  - Tradeable-vs-paper outside the primary cell.
  - Counts of events dropped for missing TTM or market cap.
  - The GST flag.
  (`report.py:71-126`)
- Rebuilding events keeps the stale state (`events.py:133-139`).
- `status` doesn't show revenue or TTM progress.
- The migration runner applies every pending file in one outer transaction, because
  `pending()` opens it before `conn.transaction()` (`common/migrate.py:39-47`). A failure
  undoes migrations it had already printed as applied.

## 5. Remaining backfill work (under D31)

| Work | NSE requests | LLM calls |
|---|---|---|
| Revenue: 8 failed companies, re-read of truncated listings | ~200 | 0 |
| Q2 defect: confirm with one file, then derive H1 − Q1 from stored rows | 1–2 | 0 |
| Market tail, 27 Sep – 6 Oct | ~17 | 0 |
| CORP_IND re-read over the BE events' windows | ≤388 | 0 |
| §5.5 Part C second read | ≤42 | ≤~60 (OCR) |
| 13 pending retries | 0 | 13 (Batch) |
| §6 trigger-4 recheck | 0 | ~100–300 (Batch) |
| **Total** | **≤~650, ≤~50 min at ≥3 s** | **~175–375, about $0.10–0.20** |

$2.55 of the $3 backfill cap remains. Elapsed time is about 2–3 days, set by two Batch
turnarounds. For comparison, tier 3 would have been 24,425 PDFs, ~24 GB, ~37 h and
~1,000–1,500 more calls.

## 6. What the VPS cancellation breaks

- D1/D2: the git-pull deploy and Compose next to n8n.
- D19: the cutover; the VPS's three live services.
- D23: live collection.
- D14: the VPS nightly dump.
- §3's CX22 limits and the whitelisted Angel One IP. A future broker connection needs a new
  static, whitelisted IP.
- §9:
  - `docker-compose.yml:79-82` requires an external network and has no Postgres service.
  - The `backup` job dumps over that network (`:67-77`).
  - The memory/CPU limits are sized for the CX22 (`:40-63`).
- `DEPLOY.md`, all of it.
- `ops/preflight.sh` (Spike E).
- `ops/backup.sh vps`, whose `tradebot_*` prune pattern also matches backfill dumps
  (`:47,50`).
- CLAUDE.md's VPS commands, and `.env.example`'s `TRADEBOT_DB_NETWORK` and
  `TRADEBOT_PG_MAJOR`.
- The Dockerfile bakes `config/` into the image, so a new holidays file needs a rebuild.

## 7. Not going to be built in Phase 1 (no verdict impact)

- T1 headline triage: D7's download-and-body-check replaced it.
- Escalation triggers 1–3 to T2: T2 is the same model, and the failures already go to review.
- §7's `events`/`orders`/`materiality` table names: the code uses `backfill_events` and
  `order_extractions`.
- The `para` attribute.
- `is_follow_up`, `significant_terms`, `receipt_datetime`, `reporting_delay_reason`: the
  exact-key merge covers repeat filings.
