# FILES.md — what every file in this repo does

A map, as of 29 Sep 2026: two or three lines per file on what it is for and how it does
it. The design and its reasons live in [ARCHITECTURE.md](ARCHITECTURE.md) (the spec) and
[WORKLOG.md](WORKLOG.md) (the history); this file only points at them. If an entry here
disagrees with the code, the code is right and this entry is out of date.

Every folder under `src/tradebot/` has an `__init__.py`, which only marks the folder as a
Python package. All are empty except the top-level one, which carries a one-line
description ("nothing in this package places trades"). The `.gitkeep` files in
`migrations/`, `prompts/`, `reports/`, `spikes/`, `tests/labelled/` and `tests/live/` are
empty too; they exist so git keeps a folder before it has real files.

---

## Root

- **`CLAUDE.md`** — The working rules for anyone changing this repo: one slice at a time,
  the data rules (append-only raw data, `Decimal` money, IST timestamps, never guess a
  number), the LLM and scraping rules, and the command list. Claude Code loads it
  automatically at the start of every session.
- **`ARCHITECTURE.md`** — The specification: the goal, every decision (D1–D27) and its
  status, each component's design, the data model, deployment and build order. Spike
  results are written back into it, so it records what was verified, not only what was
  planned.
- **`WORKLOG.md`** — The running history and handover note. A "Current state" section at
  the top is kept true, followed by one entry per event: what was done, what broke, and
  what was decided. A new session reads it first.
- **`DEPLOY.md`** — The runbook for moving the three live services (collector,
  `orders --follow`, `sheets`) to the VPS with Docker Compose. It covers the one-time
  database setup, copying the laptop's data across with `pg_dump`/restore, migrating,
  starting, and health checks.
- **`FILES.md`** — This map.
- **`pyproject.toml`** — Declares the package (src layout), Python 3.14 and exactly the
  approved dependency list. It also holds the pytest settings, including `-m "not live"`,
  so a plain `pytest` never touches the network.
- **`Dockerfile`** — Builds one image (python:3.14-slim, running as non-root uid 10001)
  that every live process uses. It copies only `src/`, `config/`, `prompts/` and
  `migrations/`, and sets `PYTHONPATH=/app/src` instead of pip-installing, so config paths
  resolve to `/app`.
- **`docker-compose.yml`** — Defines the three VPS services from that image. Each gets
  memory and CPU limits, joins the existing Postgres network, and publishes no ports. It
  also defines the collector's healthcheck, a `tradebot_data` volume for work files, and a
  `backup` job under the `ops` profile.
- **`.env.example`** — The shape of `.env` with placeholders only: the two database URLs,
  the OpenAI key, the Google credentials path and spreadsheet id, and `TZ`. The real
  `.env` holds the secrets and is never committed.
- **`.gitignore`** — Keeps secrets, the venv, caches, downloaded PDFs, spike output and
  `data/` out of git. It un-ignores the two PDF sets that must stay: the labelled set and
  the HMT fixture.
- **`.gitattributes`** — Forces LF line endings in the repo (Windows laptop, Linux VPS).
  Exchange fixture files are stored byte-for-byte, so their SHA-256 matches on both
  machines.
- **`.dockerignore`** — Keeps everything except code, config, prompts and migrations out
  of the Docker image. Secrets reach containers only through `env_file` and a read-only
  key mount.

## config/ — facts about the outside world, and decided settings

- **`sources.yaml`** — Every NSE endpoint, header set, warm-up URL and query parameter,
  plus the pacing rules: the three polling bands, the ≥3 s backfill gap, jitter, and the
  25 MiB PDF cap. Code reads URLs only from here, never from a hardcoded string.
- **`category_map.yaml`** — Maps each of 146 NSE category strings to a bucket: order_win,
  order_candidate, catch_all, red_flag, results, other_material, leadership or noise.
  Sravanth approved it. The order gate and the event study's contamination check both read
  it.
- **`backfill.yaml`** — The backfill's settings: the study window and data ranges, the
  frozen company criteria (≥₹500 cr on 22 Sep 2025, EQ/BE/BZ series), hand exclusions,
  D22's analysis bands, the documents download policy, and Sravanth's written study rules.
- **`llm.yaml`** — Model ids (tier 1, tier 2, OCR) with prices and Batch prices copied by
  hand from OpenAI's page, the spend caps ($1/month live, $1/month OCR, $3 for the whole
  backfill), output limits and bake-off settings. The LLM client refuses to call if a
  value it needs is missing.
- **`documents.yaml`** — Knobs for the document step: the resolution and greyscale setting
  for rendering a page for OCR, and how often `orders --follow` wakes up and how many days
  back it looks.
- **`fx.yaml`** — Fixed rupee rates for foreign-currency order values: USD at ₹94, set by
  Sravanth on 29 Sep 2026 so USD orders get ratios. A currency without a rate here is never
  converted.
- **`sheets.yaml`** — Google Sheets mirror settings: the API address, the names of the raw
  and orders tabs, the 5-minute sync interval with jitter, and the write chunk size. The
  spreadsheet id and key path come from `.env`.
- **`holidays_2026.yaml`** — NSE's 2026 trading holidays for the equity segment plus the
  8 Nov Muhurat session, typed in by hand. The live collector uses it to know trading
  days, and fails loudly if it is missing or does not cover today.
- **`holidays_2026.example.yaml`** — A template showing the calendar file's format, with
  example dates, for writing next year's file.

## migrations/ — the database schema, one numbered change at a time

`python -m tradebot.common.migrate` (add `--backfill` for the laptop's backfill database)
applies these in order. Each runs once and is recorded in `schema_migrations`.

- **`0001_init.sql`** — The collector's tables. `raw_announcements` is append-only (a
  trigger refuses updates and deletes) and unique on source, id and payload hash, so a
  corrected filing becomes a new row. `source_health` gets one row per poll.
- **`0002_sheets_sync.sql`** — `sheets_sync`: one row per Sheets sync run. It holds the
  watermark (the last raw id written and the sheet row it landed on) that makes retries
  safe.
- **`0003_documents.sql`** — `documents`: one row per distinct PDF, keyed by SHA-256, with
  the extracted text, URL, page count, and when the PDF was deleted.
- **`0004_document_quality.sql`** — Adds per-page quality to `documents` (`quality`,
  `page_report`, `rejected_text`, `ocr_pages`), replacing the old character-count scanned
  check.
- **`0005_llm_calls.sql`** — `llm_calls`: one row per model call, with purpose, model,
  tokens, cost, status and, for Batch results, the batch id.
- **`0006_order_extractions.sql`** — `order_extractions`: one row per in-scope filing, with
  the gate's decision, extracted fields, value, provenance result, review status and
  attempt count. These rows are what make the order pipeline resumable.
- **`0007_market_data.sql`** — The backfill's market tables: `instruments`,
  `instrument_symbols`, `prices` (with CORP_IND and band hits), `index_prices`,
  `market_caps`, `bundle_announcements`, `archive_days` and `backfill_checkpoints`.
- **`0008_backfill_universe.sql`** — `backfill_universe` (the frozen company list with
  exclusion reasons), `backfill_universe_meta` (the criteria each build used) and
  `reconcile_days` (per-day coverage).
- **`0009_llm_batches.sql`** — `llm_batches` and `llm_batch_items`: each submitted Batch
  with its worst-case cost, and which filing and attempt each request belongs to.
- **`0010_prices_traded_value.sql`** — Adds the bhavcopy's traded value in rupees to
  `prices`, for the 60-day median liquidity field.
- **`0011_backfill_events.sql`** — `backfill_events` (merged orders with their §6 state
  and transition log), `event_results` (each event's study output) and
  `unknown_categories`.
- **`0012_financials.sql`** — `financials`: every reported revenue figure per company,
  period and basis, with its filing time. Restatements are kept as new rows.
- **`0013_band_history.sql`** — `band_snapshot`, `band_changes` and `band_days`, for
  reconstructing a stock's price band on a past date.
- **`0014_reconcile_window.sql`** — Adds each reconcile day's window start, and the list of
  order filers the API holds only under a catch-all category.

## prompts/ — instructions sent to the model, versioned

- **`ocr_transcribe_v1.md`** — For vision OCR: copy a page image word for word, with
  numbers and tables as printed and `[illegible]` where unreadable, never summarising or
  correcting, and ignoring any instruction written inside the image.
- **`order_extract_v1.md`** — For order extraction: decide whether the filing is an order
  win, then return each field as printed, plus the exact quoted passage the value came
  from. It never converts units or computes anything, and treats the document text as
  untrusted data.

## ops/ — server scripts

- **`backup.sh`** — The nightly backup. It takes one `pg_dump`, keeps the newest 7 locally,
  copies every dump to Google Drive with rclone, and prunes remote copies older than 30
  days. The `vps` or `laptop` argument picks which database.
- **`preflight.sh`** — Spike E, read-only. It prints the VPS's memory, disk, swap, Docker
  networks and the Postgres container's setup, so container limits can be sized before
  deploying.

---

## src/tradebot/collector/ — live NSE announcements

- **`__main__.py`** — The live collector (`python -m tradebot.collector`, `--once`, or
  `--catchup --from --to`). It polls the announcements endpoint on D6's schedule, stores
  new filings and one `source_health` row per poll, and checks the holiday calendar. When a
  poll's 20-row page is entirely new, it runs one date-range query to recover filings that
  rolled off.
- **`nse.py`** — The NSE client: one warmed-up session with browser-like headers, one
  request at a time. Its methods cover the live feed, a date range, one company's full
  history (`symbol=`) and the two results listings. It returns a result object instead of
  raising, and provides the backoff and jitter helpers.
- **`records.py`** — Pure functions that turn one API record into a raw row. They parse
  NSE's timestamps into IST and build the identity key and payload SHA-256, which together
  decide whether a re-poll is a duplicate, a revision or a new filing.
- **`store.py`** — Writes filings to `raw_announcements` with insert-only SQL (a changed
  payload becomes a new revision row) and records each poll in `source_health`.

## src/tradebot/common/ — shared plumbing

- **`config.py`** — The only place configuration is read. It loads `config/*.yaml` and
  `.env`, and gives helpers for the database URLs and the NSE, LLM, Sheets and category
  settings.
- **`db.py`** — One thin helper that opens a psycopg connection to the live or backfill
  database. No ORM, no connection pool.
- **`migrate.py`** — Applies `migrations/*.sql` in filename order, skipping any already
  recorded in `schema_migrations`. `--backfill` targets the laptop's backfill database.
- **`calendar.py`** — Decides whether a future date is a trading day from the hand-kept
  holiday file, and which polling band applies at a given IST time. It raises rather than
  guessing when the file is missing or out of range.
- **`health.py`** — The Docker healthcheck. It exits 0 if `source_health` has a successful
  poll within the last N minutes (default 30), else 1.
- **`http.py`** — Closes a session's pooled connections once they have sat idle long enough
  for NSE to have dropped them. This fixed the `ConnectionResetError` failures on the slow
  10-minute polls.
- **`isin.py`** — Defines "same company" as the same ISIN issuer code (its first 7
  characters). NSE's announcements carry a company's original ISIN, while prices carry the
  one reissued after a split.
- **`logs.py`** — Sets up logging for the long-running commands, with timestamps always
  converted to IST whatever the machine's clock setting.

## src/tradebot/router/

- **`orders.py`** — The order-relevance gate. It maps a category to its bucket, applies the
  headline keyword filter (and a stricter body-text filter after download), and decides
  which filings are downloaded at all. `llm_allowed()` is the single check that lets a
  filing reach OCR or the LLM.

## src/tradebot/documents/ — PDF to text

- **`fetch.py`** — Downloads one PDF politely (shared session, pacing, idle connections
  closed first), streaming with a 25 MiB cap. It names the file by its SHA-256 and rejects
  anything that is not a PDF, such as an empty or HTML response.
- **`text.py`** — Extracts text page by page: pdfplumber first, then pypdf, then vision
  OCR. Only pages that assess "ok" are kept in the text; the best failed attempt is stored
  separately so nothing is silently lost.
- **`quality.py`** — Judges each page's text as empty, broken font (too many `(cid:NN)`
  placeholders), garbled, or ok. Garbled means an invisible OCR layer in a font named
  "GlyphLessFont", or too few common words. The thresholds were calibrated on the labelled
  PDFs and the HMT fixture.
- **`ocr.py`** — A small wrapper that sends a page image to the vision model through the
  LLM client and returns the transcript. It returns `None` when OCR is not configured or is
  refused, so an unreadable page goes to review instead of crashing.
- **`pipeline.py`** — Runs the whole document step for one URL: download, hash, skip if
  already stored, extract, save to `documents`, delete the PDF. It refuses to delete
  anything outside its work folder, and never deletes before the text is committed.
- **`store.py`** — SQL for the `documents` table: insert, look up by SHA-256, read text,
  mark the PDF deleted, and list documents that need review.

## src/tradebot/extractor/ and units/ — reading the order value

- **`extractor/annexure.py`** — The deterministic parser (T0, no model). It finds the rows
  of the SEBI-format order table (consideration, awarding entity, execution period and so
  on) by keyword and returns the raw strings with the passage each came from. It also
  reads recipient, stage and domestic/international.
- **`extractor/llm_extract.py`** — The LLM fallback (T1). It builds the structured-output
  request from `order_extract_v1.md` plus the document text, validates the reply with
  Pydantic, then converts the value in code and checks provenance. An invalid reply is
  retried once.
- **`extractor/provenance.py`** — The one check that decides "verified": some continuous
  part of the quoted passage must appear word for word in the document text and, parsed on
  its own, give back exactly the same value. A part is allowed because PDF tables
  interleave their columns in the extracted text.
- **`units/money.py`** — Turns printed amounts into `Decimal` rupees. It handles ₹/Rs./INR,
  crore/lakh/million/billion, Indian digit grouping, amounts written in words, "approx" and
  GST flags, and ranges. USD converts at the fixed rate in `config/fx.yaml`; other
  currencies are flagged, not converted. Each amount's currency is read beside the number
  itself. It also turns execution periods into months.

## src/tradebot/llm/

- **`client.py`** — The only code that talks to OpenAI. It loads prompts by version,
  refuses when a cap is null or a price is missing, checks spend against the cap before
  each call, and logs every call's tokens and cost to `llm_calls`. It also submits and
  retrieves Batches for the backfill.

## src/tradebot/orders/ — order extraction for live data

- **`__main__.py`** — `python -m tradebot.orders` for one date, a date range, or
  `--follow` (a loop running beside the collector). It picks the filings, runs them
  through `run.py`, and writes the day's report.
- **`run.py`** — The shared processing core. For each filing it classifies, records an
  "attempt started" marker, downloads and extracts the document, runs T0 and then T1 if
  allowed, and writes the outcome. It keeps a summary and an audit that nothing bypassed
  the gate.
- **`store.py`** — SQL for `order_extractions`: upsert a result, find which filings still
  need work, and apply the retry rules (at most 3 attempts, 15 minutes apart).
- **`report.py`** — Writes `reports/orders_<date>.md` and `.csv` from the database, listing
  that day's order-related filings and the totals.

## src/tradebot/sheets/ — view-only Google Sheet

- **`__main__.py`** — `python -m tradebot.sheets` (`--once`, `--rebuild`, or looping every
  5 minutes). It builds one authenticated session and syncs both tabs. It runs apart from
  the collector so a Sheets problem can never stop collection.
- **`client.py`** — A thin wrapper over the Sheets REST API using google-auth's session:
  make sure a tab exists, write rows, write a numeric column, clear from a row.
- **`sync.py`** — Mirrors `raw_announcements` into the raw tab without duplicates. Filing
  N always lands on sheet row N+1, and the watermark is read only from successful runs, so
  a retried chunk overwrites the same rows.
- **`rows.py`** — Pure formatting of one raw filing into a sheet row: IST times, the
  empty-cell rule, and the cell-length cap.
- **`orders.py`** — Builds the orders tab from `order_extractions` (value in ₹ crore,
  flags, status). It rewrites the whole tab, but only when a hash of the content has
  changed.

## src/tradebot/market/ — NSE daily archives (backfill)

- **`__main__.py`** — `python -m tradebot.market --from --to`. For each calendar day it
  fetches the UDiFF bhavcopy (a 404 means no trading that day), then the PR bundle, and
  stores both. It resumes day by day.
- **`fetch.py`** — Downloads archive files from nsearchives with the polite session and a
  ≥3 s jittered gap, counting every request including the warm-up.
- **`parse.py`** — Pure parsers for the bhavcopy (prices, ISIN, traded value) and the PR
  bundle's members: `pd` (Nifty and CORP_IND), `mcap`, `bh` (band hitters) and `an` (the
  announcement report). Member names are matched case-insensitively.
- **`store.py`** — Writes one day into `prices`, `index_prices`, `market_caps`,
  `instruments`, `instrument_symbols` and `bundle_announcements`. Everything is keyed to
  an ISIN through that same day's bhavcopy.
- **`bands.py`** — Reconstructs a stock's price band (2/5/10/20%) on any past date. It
  starts from NSE's current band list and undoes each day's published band changes,
  newest first. It includes its own loader for the change files.

## src/tradebot/revenue/ — quarterly results

- **`load.py`** — For each event company, fetches both results listings (the old
  "Financial Results" one and the post-April-2025 "Integrated Filing" one), downloads the
  XBRL for quarters from Sep 2024 on, and stores every revenue fact with its filing time.
- **`xbrl.py`** — Reads revenue from one results XBRL file. It takes each fact's period
  from its declared start and end dates (falling back to the context's dates) and its
  basis per context, and refuses non-INR units. This makes it robust to the real defects
  found in NSE's templates.
- **`ttm.py`** — Point-in-time trailing-12-month revenue: only results filed before the
  moment, one basis, four consecutive quarters, and Q4 = FY − 9M. It returns `None` rather
  than guessing.

## src/tradebot/calculator/

- **`materiality.py`** — Pure ratios for one order: value ÷ TTM revenue, the next 12
  months' share of the value ÷ TTM revenue, and value ÷ market cap. It also sets flags
  (manual review, suspect parse, missing data) and converts a completion month into months.

## src/tradebot/backfill/ — 12 months of history, and the verdict

- **`__main__.py`** — `python -m tradebot.backfill <stage>`. Each stage runs one pass
  against the backfill database: universe, expected, announcements, reconcile, documents,
  batch-submit/collect, rejudge, events, revenue, calculate, recheck-submit/collect, study
  and status.
- **`universe.py`** — Builds the frozen company list from the criteria as of 22 Sep 2025,
  and refuses if the criteria are not frozen. It applies hand and industry exclusions from
  config, and estimates what the list filed before anything is downloaded.
- **`announcements.py`** — One `symbol=` query per listed company. Filings inside the window
  (matched by ISIN issuer code) are stored through the collector's own code. It also runs
  the per-day reconciliation against the PR bundles.
- **`reconcile.py`** — Pure matching of each day's PR-bundle order filers against API
  filings dated from the previous report to that day, by company. It reports coverage,
  where in the window matches fall, and orders found only under a catch-all category.
- **`documents.py`** — The backfill's document stage. It orders window filings in tiers
  (order categories, then headline hits, then the rest) and skips body-check-only catch-alls
  above ₹50,000 cr. The filings then go through the live pipeline, with LLM extraction held
  back for Batch.
- **`batch.py`** — Sends `pending_llm` filings to OpenAI's Batch API after a worst-case cost
  check, one batch per model sized to OpenAI's queue limit. Later it reads the results back
  through the same checks as a live call, with retries capped at three submissions.
  `rejudge` re-applies the current rules to stored answers without calling the model.
- **`events.py`** — Merges verified extractions into events on exact keys only (the same
  PDF hash, or the same company and value). It implements §6's state machine: extracted,
  then calculated, then verified or recheck.
- **`recheck.py`** — The independent second read, via Batch, for high-stakes events: value
  ≥15% of market cap, or TTM or market cap missing. If both reads agree the event is
  verified; if not, it goes to needs_review.
- **`study_data.py`** — Loads the database into the study's inputs: prices and market caps
  per company (joined across reissued ISINs, with the switch day marked), point-in-time
  TTM per event, and each company's nearby filings for the contamination check.
- **`event_study.py`** — The pure event-study logic. It covers day 0, the valuation date,
  excess returns over Nifty at +1/+3/+5/+10 days and pre-event drift, exclusions (capital
  actions, short history), contamination, circuit locks and liquidity, then the D22
  verdict.
- **`report.py`** — Writes `reports/backfill_<date>.md` and a per-event CSV. The verdict and
  its four checks come first, then the sensitivity and exploratory cells, with every
  exclusion counted.

## src/tradebot/eval/ and normalizer/

- **`eval/__main__.py`** — `python -m tradebot.eval`: scores the T0 parser against the
  hand-labelled JSONs. The headline metric is exact `value_inr`, where a correct null
  counts as correct.
- **`normalizer/__init__.py`** — An empty placeholder for Slice 2's normalizer. That work
  (ISIN matching, merging repeat filings) ended up in `common/isin.py` and
  `backfill/events.py`.

---

## spikes/ — throwaway probes

Each answered one question within a fixed request budget, and the findings were written
into ARCHITECTURE.md. Nothing in `src/` imports these. Their output goes to `spikes/out/`,
which is gitignored.

- **`spike_a_announcements_api.py`** — Probed the announcements API: the record fields,
  what identifies a filing, and how the date-range and `symbol=` queries behave.
- **`spike_a2_offline_gap.py`** — Offline: measured whether the API's missing filings were
  inside the study universe or only SME and debt.
- **`spike_a2_api_completeness.py`** — Tried every plausible parameter (csv, page, index,
  type) to make the API return a whole past day. None did.
- **`spike_b_bulk_archives.py`** — Verified the bhavcopy and PR bundle URL patterns and how
  far back they go, and saved the robots.txt and terms-of-use texts.
- **`spike_b_analyse_offline.py`** — Re-analysed the downloaded archives offline, looking
  for any price adjustment between consecutive days.
- **`spike_b_exdate_test.py`** — On a real ex-date (6 Aug 2025), proved the bhavcopy's
  previous-close field is not corporate-action adjusted.
- **`spike_band_asm.py`** — Found NSE's current band list and daily band-change log (so
  past bands can be rebuilt) and that ASM/GSM history is not published.
- **`spike_c_results_xbrl.py`** — Fetched the old results listing and real BEL XBRL files,
  which exposed two defects in NSE's own templates.
- **`spike_c2_integrated_filing.py`** — Verified the post-April-2025 Integrated Filing
  endpoint and parsed its XBRL; Q4 = FY − 9M matched to the rupee.
- **`spike_f_fetch_hmt_fixture.py`** — One request to re-download the HMT garbled-OCR PDF
  as a permanent test fixture.
- **`spike_labelset_fetch.py`** — Downloaded the candidate order PDFs for the labelled set,
  without printing any value from inside them.
- **`spike_labelset_classify.py`** — Sorted those candidates into edge-case groups, again
  without revealing values, so the labelling stays blind.
- **`spike_live_feed_poll.py`** — Polled the live feed for a day and compared it against
  that evening's PR bundle, to check forward collection is complete.

## reports/ — committed outputs

- **`extraction_baseline_2026-09-24.md`** — The first scoring of the T0 parser on the 18
  labelled PDFs: 44% exact value, with every failure listed.
- **`power_analysis_2026-09-22.md`** — How many clean events the verdict needs to see an
  edge of a given size. 30 events detect only about 2.4% net at 80% power.
- **`orders_2026-09-23.md`** and **`orders_2026-09-23.csv`** — The order-extraction report
  and table for 23 Sep 2026, written by `orders/report.py`.
- **`orders_2026-09-23_detail.md`** — A field-by-field walk through that day's 10
  order-related filings.
- **`orders_2026-09-25.md`** and **`orders_2026-09-25.csv`** — The same report for 25 Sep
  2026.
- **`orders_2026-09-24_25_detail.md`** — Field-by-field detail for the 24–25 Sep catch-up
  run.

---

## tests/fixtures/ — real exchange files, stored byte-for-byte

- **`an18092026.txt`** — NSE's PR-bundle announcement report for 18 Sep 2026 (~1,229
  filings), used by the router and bundle-parser tests.
- **`bundle_bodies_18sep2026.csv`** — The same report pre-split into symbol and body rows,
  for the reconciliation tests.
- **`api_announcements_17_18_sep2026.csv`** — API records for 17–18 Sep 2026 (symbol, time,
  category, ISIN), the other side of the reconciliation tests.
- **`pd18092026.csv`** — The PR bundle's price file for 18 Sep 2026: Nifty rows and each
  security's CORP_IND flag.
- **`mcap18092026.csv`** — The market-cap file for 18 Sep 2026. A test pins that its values
  are plain rupees, not lakhs or crores.
- **`bh18092026.csv`** — The band-hitters file for 18 Sep 2026.
- **`corpaction_20250805_20250806.csv`** — Bhavcopy rows around a real ex-date, proving the
  previous-close field is unadjusted.
- **`BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV`** — A BSE UDiFF bhavcopy, kept as evidence
  that BSE and NSE publish the same column set.
- **`scans/hmt_glyphless.pdf`** — The HMT filing whose invisible OCR layer produced plenty
  of wrong text; the regression fixture for the page-quality check.
- **`xbrl/bel_integrated_2026q1_consolidated.xml`**, **`..._fy26_q3_...`**,
  **`..._fy26_q4_...`** — Real BEL Integrated Filing XBRLs, proving the parser reads the
  new format and that FY − 9M equals the Q4 BEL itself reports.

## tests/labelled/ — hand-labelled ground truth

- **`README.md`** — How to label a filing: one JSON per PDF with the same name, what each
  field means, and the rule that an unstated value is null.
- **`CANDIDATES.md`** — Why each candidate PDF was chosen (market-cap band, edge case), with
  labelling instructions.
- **`_template.json`** — The blank label: the source details plus every order field, all
  null.
- **18 pairs `<SYMBOL>_<date>_1.pdf` + `.json`** (AFFORDABLE, BEL, BEML, CEINSYS, CPL, DBL,
  GKENERGY, GPTINFRA, GREENPOWER, HECPROJECT, HEG, HILINFRA, MCLOUD, NEWGEN, RAILTEL,
  VIVIANA, WAAREEENER, ZAGGLE) — Real order filings and their expected answers.
  `python -m tradebot.eval` scores against them, and many unit tests use the PDFs as real
  inputs. They are the one permanent exception to "delete PDFs after extraction" (D8).

## tests/live/

- **`test_live_marker.py`** — A placeholder for network tests. It exists so a plain
  `pytest` run reports it as deselected, which proves the `live` marker keeps network
  tests out of the default run.

## tests/unit/ — the default suite (no network)

Tests marked "real SQL" run in a throwaway schema of the backfill database and skip if it
is not reachable. The rest use fakes.

- **`conftest.py`** — The shared `scratch_conn` fixture: a throwaway schema in the backfill
  database with every migration applied, dropped after each test.
- **`test_scaffold.py`** — The package imports, the repo layout matches ARCHITECTURE, the
  dependencies equal the approved list, and `.env.example` holds no real secret.
- **`test_collector_records.py`** — The identity key, payload-hash stability and timestamp
  parsing for API records.
- **`test_collector_gap.py`** — When a poll's page is entirely new, the date-range query
  runs and recovers the filings that rolled off.
- **`test_trading_calendar.py`** — Against the real 2026 holiday file: holidays, the
  Muhurat session, the polling bands, and failing loudly when a date is not covered.
- **`test_health.py`** — The healthcheck's freshness rule.
- **`test_http_idle.py`** — Idle connections are closed before the next request in every
  NSE client, and a non-PDF response is refused without leaving a file behind (the Windows
  crash of 28 Sep).
- **`test_logs.py`** — Log timestamps are IST whatever the local clock says.
- **`test_router_orders.py`** — Category buckets, the headline and body keyword filters,
  and above all which filings `llm_allowed` lets through.
- **`test_documents.py`** — The document pipeline on a real labelled PDF: dedup by hash,
  deleting only inside the work folder, and only after the text is saved.
- **`test_text_extraction.py`** — The per-page ladder (pdfplumber, pypdf, OCR) on real PDFs
  and the HMT fixture.
- **`test_quality.py`** — Every labelled page assesses ok, and the HMT page is caught as
  garbled.
- **`test_ocr.py`** — The OCR wrapper stays dormant and returns `None` when not configured
  or refused.
- **`test_money.py`** — The amount parser against ARCHITECTURE §5.7's test vectors: crore,
  lakh, words, GST, approx, ranges and currency.
- **`test_annexure_stage.py`** — The legal phrase "(as amended)" is not read as an order
  amendment (the BDL bug).
- **`test_provenance.py`** — A value is verified only if its passage is in the text and
  parses back to the same number.
- **`test_llm_client.py`** — With a fake OpenAI client: a null cap or missing key refuses,
  every call is logged with its cost, and document content never becomes an instruction.
- **`test_llm_extract.py`** — The T1 fallback retries once and then sends to review, and is
  held to the same provenance check as the parser.
- **`test_orders_run.py`** — The processing core with fakes: the gate, idempotency,
  retries, attempt markers and the gate audit.
- **`test_orders_main.py`** — Command-line parsing for `python -m tradebot.orders`,
  including the `--from/--to` bug.
- **`test_orders_sql_smoke.py`** — Read-only runs of the real orders SQL against the local
  database.
- **`test_sheets.py`** — Sheets row formatting, request shapes, and the property that a
  retried sync never duplicates a row.
- **`test_sheets_orders.py`** — The orders tab: crore formatting, numeric writes, and
  rewriting only when something changed.
- **`test_fixture_units.py`** — Pins the units in the daily files, such as market cap in
  rupees.
- **`test_corporate_actions.py`** — Locks Spike B's finding that the previous-close field is
  unadjusted.
- **`test_market_parse.py`** — The archive parsers against the committed fixtures and
  numbers recorded independently by the spikes.
- **`test_market_load.py`** — The market loader's per-day decisions (a 404 means no
  trading, errors are retried) with a fake fetcher.
- **`test_market_store_db.py`** — The market store's SQL on the real backfill database,
  inside a transaction that is always rolled back.
- **`test_bands.py`** — Parsing NSE's band files, and rebuilding a past band on real SQL.
- **`test_backfill_announcements.py`** — Which records a company keeps (window, issuer-code
  match including original ISINs), the industry field, and checkpointing only when every
  symbol succeeded.
- **`test_backfill_exclusions.py`** — Hand and industry exclusions come from config and
  re-apply cleanly, on real SQL.
- **`test_reconcile.py`** — Reconciliation on real 17–18 Sep data, plus the Monday-report,
  symbol-change and catch-all cases.
- **`test_backfill_documents.py`** — The documents download policy (tier order and the
  ₹50,000 cr ceiling), on real SQL.
- **`test_backfill_batch_db.py`** — The Batch round trip on real SQL with a fake OpenAI
  client: cap check, recording the batch, and applying results.
- **`test_backfill_events.py`** — Merging on exact keys, §6 transitions, recheck agreement
  and disagreement, and events carrying the universe ISIN.
- **`test_backfill_main.py`** — The backfill command's window filter and the documents
  stage's gate-audit exit code.
- **`test_study_data.py`** — The contamination lookup (null ISIN, original ISIN) and prices
  joined across a reissued ISIN with the switch day marked, on real SQL.
- **`test_event_study.py`** — The event study on a hand-built 200-day market: day 0,
  valuation date, returns, exclusions, circuit locks, contamination and the verdict.
- **`test_backfill_study_db.py`** — The `calculate` and `study` stages end to end on real
  SQL for one synthetic company, including writing the report.
- **`test_materiality.py`** — The §5.10 ratios and flags, and execution-period parsing.
- **`test_ttm.py`** — Point-in-time TTM: the filed-before rule, Q4 = FY − 9M, one basis,
  consecutive quarters.
- **`test_xbrl.py`** — The XBRL parser: periods from real dates, basis per context, and
  NSE's two real template defects.
- **`test_revenue_load.py`** — The revenue loader with fakes (both listings, the window
  filter, retries, the request cap), plus the real BEL Integrated Filing XBRLs.
