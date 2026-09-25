# WORKLOG

Running record of what has actually happened in this repo. Append a new entry at the end
of every working session; edit **Current state** in place so the top of the file is always
true.

**This file is history and orientation, not specification.** The spec is
[ARCHITECTURE.md](ARCHITECTURE.md) and the working rules are [CLAUDE.md](CLAUDE.md). Where
this file and ARCHITECTURE.md disagree, ARCHITECTURE.md wins — and the disagreement is a
bug in this file. Do not restate the design here; link to the section.

Read order for a cold start: CLAUDE.md → this file's **Current state** → ARCHITECTURE.md →
the last session entry below.

---

## Current state

*Last updated: 25 Sep 2026 (later)*

**The live collector is not running right now** (not on 24 Sep, not this morning as of the
last update). `raw_announcements` is caught up through ~10:30 IST on 25 Sep via
`python -m tradebot.collector --catchup --from ... --to ...` (new - see the morning entry),
but nothing is polling live. Start it (`python -m tradebot.collector`) before relying on
this for anything past that point.

**What this is.** tradebot Phase 1. Collect NSE corporate announcements (BSE dropped by
D26), classify them, extract order wins, measure order value against revenue and market
cap, and test it on 12 months of history to decide whether order filings move prices
tradeably. Nothing in this repo places trades, and nothing will in Phase 1.

**Where we are.** Slice 0 (spikes), the live half of Slice 1, and now a first working slice
of Slice 3+4+5 together: a minimal order-relevance gate, the document pipeline, and LLM
extraction, run for real against a full day of live-collected filings. Spikes C and E are
still not started; Spike D (the model bake-off) was superseded for now by Sravanth's direct
model choice (see the night/continued entries below).

| Spike | Status |
|---|---|
| **B** — NSE bulk archives | Done. See 21 Sep entry. |
| **A** — announcements API | Done, but left a blocker. See 22 Sep entry. |
| **A2** — API completeness | Done. **Backfill is viable.** Reconciliation now runs per-day in the backfill. |
| Live-feed reconciliation | **Running** since 22 Sep 14:02 IST; reconcile against the 23 Sep bundle. |
| **C** — results XBRL | Not started |
| **D** — extraction bake-off | **Superseded for now** (24 Sep night, continued): Sravanth chose `tier1_model`/`ocr_model = gpt-6-luna` directly rather than waiting for the bake-off. Arm 1 (parser alone) still stands at **44%** on 18 labelled docs; the full T0+LLM chain reaches **67%** on the same set (a development number, not a bake-off-gated one). The bake-off itself is not cancelled - still the right way to confirm or revise the model choice once ~50 labelled PDFs exist. |
| Order-relevance gate + extraction (§5.4-§5.6) | **Built and run for real** (24-25 Sep, night): `router/orders.py`, `extractor/{provenance,llm_extract}.py`, `orders/` (`run.py`/`store.py`/`report.py`/`__main__.py` - both `--date`/`--from`/`--to` and `--follow` branches share one core). Run live against 23 Sep's 725 filings: 124 downloaded (widened D7 - see below), 10 order-related (3 of them found only via the catch_all keyword prefilter, not by category), 5 verified, real cost $0.008236 (corrected - see below). Reports: `reports/orders_2026-09-23.md`/`.csv` (one row per filing) and `orders_2026-09-23_detail.md` (every extracted field, in prose). `--follow` (the continuous live branch) is built and tested but has not yet been started running. |
| Slice 4 (document pipeline) | **Built and unit-tested** (24 Sep, later): download -> SHA-256 -> extract -> store -> delete-the-PDF, in `src/tradebot/documents/`. Extended (24 Sep, night) with a per-page quality ladder (`quality.py`) and dormant vision OCR (`ocr.py`, `llm/client.py`); **the LLM client is no longer dormant** (24 Sep night, continued) - `config/llm.yaml` carries a real model, prices and $1/month caps. **Now wired to a caller** (`orders/run.py`), gated by `router/orders.py` - the first real download-and-extract traffic in the repo beyond tests. |
| **E** — VPS preflight | Not started. Needs VPS numbers from Sravanth. |
| Python 3.14 wheels | Windows half verified; manylinux not checked. |

**No longer blocked.** Spike A2 resolved the API-completeness scare: it was two measurement
errors of mine, not a property of the API. The `an<date>.txt` bundle is a *report* covering
filings disseminated since the previous report, so comparing bundle(D) to API(D) was a
category error; and "the symbol query stops at Oct 2025" came from string-sorting
`DD-Mon-YYYY`. Re-measured over a two-day window, **mainboard order coverage is 8 of 8**, and
the symbol query returns a company's whole 22-year history in one call — so the backfill is
one request per company, not per company-day. Caveats in §5.1.

**Side tool, not a pipeline slice.** `python -m tradebot.sheets` mirrors
`raw_announcements` **and, since 25 Sep, `order_extractions`** into two tabs of one Google
Sheet, view-only, so Sravanth can browse filings and the order pipeline's output without
writing SQL. Both verified live: raw tab 23 Sep night, orders tab 25 Sep (later). Neither
is running continuously right now - `--once` has been run by hand each time. Live viewing
needs three processes running at once: the collector, `orders --follow`, and `sheets`
(no flags). None of the three is running as of this update.

**How Sravanth works.** One step at a time. Finish a step, report plainly, **stop and wait**.
Do not start the next step unsolicited. He reviews every change and must be able to explain
it, so prefer plain code and say why, not what. He pushes back hard and specifically, and he
is usually right — several of his corrections are recorded below.

---

## Standing gotchas

Things that cost time once. Do not rediscover them.

**Verify before you design on it.** Two designs have now been written into ARCHITECTURE.md
and then reversed by the spike that checked them. Both times the assumption was plausible
and wrong. If a design step depends on a property of external data, the spike that confirms
that property comes first.

**Count every request, including warm-ups.** In Spike A the budget was 12 and 13 were sent,
because two follow-up scripts each opened a fresh session and its warm-up GET was not
counted. Use one shared, persisted counter across every script in a spike.

**NSE needs a session warm-up.** The homepage or the announcements page sets Akamai cookies
(`ak_bmsc`, `bm_sz`, `nsit`, sometimes `_abck`). Archive and API hosts refuse a cold session.
Headers live in [config/sources.yaml](config/sources.yaml), never in code.

**Console encoding.** The Windows console is cp1252 and cannot print `§`, `₹` or `≥`. Prefix
with `PYTHONIOENCODING=utf-8`. Files are always written with `encoding="utf-8"` explicitly;
this only affects stdout.

**Bash heredocs break on some content.** Long Python with ASCII-art, backticks or mixed
quoting fails to parse. Write the script to the scratchpad directory with the Write tool and
run it by path.

**Patch scripts should assert exactly one match.** Every ARCHITECTURE.md edit goes through a
script whose `sub()` asserts `count(old) == 1`. This has already caught a double-apply and
prevents silent partial edits.

**`pytest` exits 5 on an empty collection**, not 0. A "passing empty run" needs at least one
real test.

**Money is `Decimal`, never float. Never guess a number.** If a value cannot be extracted and
verified, store null plus a flag.

**Editing a Windows path (backslashes) through `bash -c "python -c '...'"` goes through two
layers of escaping and silently corrupts it.** A `.env` fix once turned `\t` into a literal
tab character, splitting a filename in two, with no error raised anywhere - the file just
had a wrong value that later failed a completely different way. Write the edit to a real
`.py` file with `pathlib` and run it by path instead; that is one layer of escaping, not two.

**A new PDF fixture outside `tests/labelled/` needs its own `.gitignore` negation, or it
never gets committed.** `.gitignore` ignores `*.pdf` globally and un-ignores only
`tests/labelled/*.pdf` (D8: downloaded PDFs are deleted after extraction; the labelled set
is the one standing exception). Adding `tests/fixtures/scans/hmt_glyphless.pdf` on 24 Sep
2026 night silently matched the global ignore - `git status` showed every other new file
but not it - until a `git status`/`git check-ignore` check caught it and a second negation
line was added. Check `git status` for every new fixture before assuming it will be
committed; a silent miss here means a fresh clone's tests quietly skip instead of failing.

**`env(name, required=False)` does not apply the `CHANGEME` placeholder check - only
`required=True` does.** Building `llm/client.py`'s "missing key must refuse" path with
`required=False` (so a missing key refuses gracefully instead of crashing) meant a
still-`CHANGEME` `.env` value came back as a truthy string, was treated as a real key, and
the test sent it to OpenAI as a real API key - a genuine network call from inside `pytest`,
caught only because it 401'd immediately. Any future `env(required=False)` caller has to
check for the literal `"CHANGEME"` string itself; it is not filtered out for you.

---

## Environment

- **Laptop, Windows + Git Bash.** Python 3.14.2 is the only interpreter. Activate with
  `source .venv/Scripts/activate` — `Scripts`, not `bin`.
- All 11 approved dependencies install from cp314 Windows wheels with no source builds.
- Spikes and the eventual backfill run **on the laptop over a phone hotspot, not the campus
  network** (D19). The VPS runs only the live collector.
- **Local database** (D19) — **connection verified 22 Sep 2026**: PostgreSQL **16.15** on
  Windows, service `postgresql-x64-16`, port 5432, `psql` at
  `C:\Program Files\PostgreSQL\16\bin\psql`. Role, database and database *owner* are all
  `tradebot`, so migrations can create tables — confirmed by actually creating one, writing
  to it and rolling back. `NUMERIC(20,2)` returns `Decimal` and `timestamptz` returns a
  tz-aware datetime, which is what the money and time rules in CLAUDE.md require. The venv
  has `psycopg` 3.3.6. The password lives only in the gitignored `.env`, whose
  `DATABASE_URL` points at `localhost:5432`.
  Two things to know: the server's `timezone` is `Asia/Calcutta`, the deprecated IANA alias
  for `Asia/Kolkata` — the same zone, and harmless because `timestamptz` stores UTC and the
  edges use `ZoneInfo("Asia/Kolkata")` in Python, so it only affects how `psql` prints a
  timestamp. And `migrations/` is still empty, so the database has **no schema**: a working
  connection proves the server, not the tables.
- Branch `main`, tracking `origin/main` at `github.com/sravanth-dev/tradebot_NSE_order_scraper`. **Push after every commit** (Sravanth's standing instruction). A push carrying the 22 MB label set failed once with HTTP 408 over the hotspot and succeeded after `git config http.postBuffer 524288000`.

```bash
source .venv/Scripts/activate
pytest                      # unit + fixture tests, no network
pytest -m live              # hits real sites; none exist yet
PYTHONIOENCODING=utf-8 python spikes/<probe>.py
```

`spikes/out/` holds downloaded archives and is gitignored. `tests/fixtures/` is committed
byte-for-byte (`tests/fixtures/** -text` in `.gitattributes`), so a SHA-256 taken on the
laptop matches one taken on the VPS.

---

## Open questions blocking progress

Needed from Sravanth:

- ~~**Postgres on the laptop, with `DATABASE_URL` set.**~~ **Done and verified end to end,
  22 Sep 2026.** Connected as `tradebot` to database `tradebot` on PostgreSQL 16.15. See
  **Environment** for the details. `.env` is gitignored by design, so a later session cannot
  confirm the password from the repo — if a connection fails, check `.env` before suspecting
  the server.
- ~~`config/holidays_2026.yaml`~~ **supplied 22 Sep 2026** and committed. Still outstanding
  inside it: NSE has not published the 8 Nov Muhurat timings, so `session` is null.
- **VPS numbers** for Spike E: free memory, free disk, swap, the external Docker network
  name, and how the existing Postgres container is configured.
- **OpenAI model IDs and prices**, copied from the live pricing page. `config/llm.yaml` holds
  `PLACEHOLDER` deliberately; nothing may be guessed here.
- **Ten labelled JSONs.** The 19 candidate PDFs are in `tests/labelled/` with
  `CANDIDATES.md` and `README.md`; Sravanth labels ten blind before Spike D runs.

Still open in ARCHITECTURE.md §11: scanned PDFs, FX source, OpenAI data-sharing opt-in,
backup mechanism, and the User-Agent contact string. Spike A2 runs first among the spikes.

---

## Sessions

### 21 Sep 2026 — review, scaffold, Spike B

**Reviewed CLAUDE.md and ARCHITECTURE.md (v0.2) and pushed back.** The substantive findings,
all of which Sravanth accepted:

- Two data-quality landmines absent from the design entirely: **corporate actions**
  (unadjusted prices make a split read as −90%) and **circuit limits** (a measured move on a
  band-locked micro-cap is fictitious P&L, and the study's whole question is tradeability).
- The go/no-go was an unpreregistered search over 24 cells with no threshold and no cost
  hurdle.
- Three of the four LLM escalation triggers were wrong: escalating when the deterministic
  parser disagrees with a cheap model pays a premium model to referee a reliable source
  against an unreliable one; "non-INR currency" is a fact code already knows; and the
  high-stakes trigger keyed on `value_to_ttm`, so it silently never fired on the messiest
  cases, the ones with no financials.
- "Every number must appear in the source text" is not provenance — a document containing
  `13.51` anywhere would pass a value lifted from a date.
- §5.3's dedup on "similar headline" would have merged genuinely distinct same-day order
  wins. The fixture shows 22 order filings from 12 companies in one day; MASON filed 5 times.
- Append-only plus `UNIQUE(source, source_id)` would silently discard NSE's revisions.
- The $10 backfill cap and the escalation policy were arithmetically incompatible.

**Sravanth's decisions** became D19–D25 and a rewritten §6. Notably: the parser wins when its
value verifies; verification became provenance-based (quoted span, checked); the LLM never
normalizes anything; spend caps wait for measurement; and the pre-registered verdict rule in
§5.11 is his wording verbatim.

**Step 0, scaffold.** Directory tree, `.gitignore` (verified in both directions with
`git check-ignore`), `.gitattributes`, `.env.example`, placeholder `config/llm.yaml`,
`pyproject.toml` pinning exactly the approved dependencies with a test that fails if the list
drifts. Verified the three NSE fixtures hash identically in working tree and index.

**Fixture findings, zero requests.** `an18092026.txt` carries company, symbol, category and
description **only** — no timestamp, no attachment URL, no ISIN. `mcap` is in plain rupees
(BEL: 7,309,778,829 × 393.30 = 2,874,936,013,445.70 exactly). `pd` carries `CORP_IND` and
`PREV_CL_PR`.

**Spike B — NSE bulk archives. 12/12 requests, all 200.**

- Verified: `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`
  and `.../archives/equities/bhavcopy/pr/PR{ddmmyy}.zip` (two-digit year in the URL, four
  digits in the members). Depth confirmed Aug 2025 → Sep 2026. UDiFF has 34 columns and an
  **identical column set to the BSE fixture**, so one parser serves both exchanges.
- **Reversed a v0.4 decision: `PrvsClsgPric` is NOT corporate-action adjusted.** v0.4 planned
  to chain every return through it. On 2025-08-06, a day with 18 flagged corporate actions
  including a Coal India ex-dividend and a rights issue, `PrvsClsgPric` equalled the prior
  close for **all 18, and for all 3,093 symbols**. The PR bundle's `PREV_CL_PR` is the same
  number. Both are the raw prior close. Phase 1 rule is now **exclude, not adjust**.
- Two schema drifts that would have failed silently: PR members mix capitalisation *and* mix
  `DDMMYY` with `DDMMYYYY` inside one 2025 zip; the `bh` band-hitter file lost its
  `INDEX FLAG` column between Aug 2025 and Mar 2026.
- Band-hit base rate: 298 hitters on 18 Sep, 86 of them EQ — about 3.6% of EQ names. Circuit
  limits are not an edge case.
- **robots.txt and the terms of use contradict each other.** robots.txt is `Allow: /`; the
  terms prohibit "systematic or automated data collection". Both quoted verbatim in §3.

**Sravanth decided to proceed** (D24), recorded as his call on his own risk rather than a
legal conclusion this repo reached. He also asked to do it "without getting caught"; I
declined to build evasion and recorded the boundary as **D25** — permitted: low fixed rates,
jitter, warm-up, backoff, one consistent User-Agent; not built: proxy or IP rotation, UA
rotation, fingerprint spoofing, CAPTCHA solving. That is also the pragmatic choice, since bot
management scores rotation far harder than a steady session.

Commits: `58252a0`, `ce53c70`, `38578eb`. ARCHITECTURE.md v0.2 → v0.5.

### 22 Sep 2026 — Spike A

**Spike A — announcements API. Budget was 12; I sent 13.** See the gotcha above.

**Verified the record shape.** Twenty fields. Two close long-standing gaps: **`sm_isin`**
carries the ISIN (1,035/1,035 on BEL), and **`smIndustry`** carries the sector §5.8 needed and
had no source for — though it was `null` for HILINFRA, so the bank/NBFC exclusion still needs
a fallback. `an_dt` is the filing time **with time of day**, `exchdisstime` the dissemination
time, and `difference` the lag between them, which hands §5.3 the publication latency it
wanted to measure for free. `attchmntFile` is the PDF URL; `desc` is the category the router
keys on.

**Identity.** `seq_id` is **null on older records** (193 of BEL's 1,035, all pre-2015), so it
cannot be a primary key alone. `(seq_id, an_dt)` was unique across all rows. There is no
`modified`/`revision`/`updated` field and `old_new` was null throughout — the API exposes **no
revision marker**, so payload hashing stays the mechanism.

**Reversed the hybrid plan again.** v0.5 assumed the API was authoritative and the bundle
merely lacked timestamps. The opposite is true:

| Query | Result |
|---|---|
| no parameters | 20 most recent only |
| `symbol=BEL` | 1,035 records, Apr 2005 → **31 Oct 2025**, nothing from 2026 |
| date range, 18 Sep 2026 | **563** records over 392 symbols (bundle has ~1,229) |
| `symbol` + date range | **0** for BEL, **0** for MASON, 1 for HILINFRA |

BEL and MASON are absent from the date-range response although both filed that day. In order
terms: **3 order wins from the API against 22 in the bundle.** Not truncated by time of day
(00:20 → 23:59) and no duplicate `seq_id`s, so it is a subset by a rule not yet known.

Volume was never the obstacle — 23 lookups a day is ~5,750 over twelve months, 5–10 hours of
paced traffic. **Completeness is.**

Added [config/sources.yaml](config/sources.yaml) so endpoints and headers stop living in code.

Commit: `7fb1ba1`. ARCHITECTURE.md v0.5 → v0.6.

### 22 Sep 2026 — this file

Created WORKLOG.md and added a pointer to it from CLAUDE.md, so a new session actually reads
it. No code or design changed.

### 22 Sep 2026 (later) — label set, live-feed poll, reconciliation, power analysis

Remote is live and everything below is pushed.

**Label set (19 PDFs, 22 MB).** Built from URLs already held in saved API responses, so it
cost 20 requests and no new symbol queries. Spans ~₹130 cr to ~₹287,000 cr and covers foreign
currency, value-not-disclosed, LoI, LoA, L1, amendment, GST wording, approximation
qualifiers, both catch-all router cases (`Press Release` = HILINFRA, `General Updates` =
GREENPOWER), one scanned PDF with no text layer (JISLDVREQS), and a 7 MB image-heavy file
(ZAGGLE) that will stress pdfplumber against the 512 MB container limit.
`CANDIDATES.md` states **no extracted values**, so blind labelling stays intact — selection
used metadata and structural signals only. Two gaps stated rather than hidden: no filing with
several distinct orders, and no confirmed company-placed-the-order case.

**Live-feed reconciliation (D23's precondition) is running.** Polls the no-date endpoint
every ~60 s with jitter until 22:00 IST, keeping every distinct record. The headline metric
is `full_page_all_new`: the endpoint returns only the 20 most recent records, so a poll where
all 20 are new means the page rolled over between polls and filings were missed. Started
14:02 IST, so it covers the afternoon and evening only; reconciliation against tomorrow's
bundle is limited to filings timestamped after that.

Two mistakes worth remembering. `nohup ... &` **inside** a backgrounded Bash call spawned the
poller twice, both writing the same files — let the tool background it, do not add `&`. And
the first poll always reports every record as new, which counted as a false overflow until
the metric excluded poll 1.

**Reconciliation is now production code, not a spike finding.**
`src/tradebot/backfill/reconcile.py` with six tests against committed fixtures for 17–18 Sep.
It measures order-filing-company coverage per day over a ±1-day window, emits an offset
histogram to confirm the report-window model, and gates at 95%. One test asserts that
**same-day matching understates coverage** — which is the error that made Spike A2 look fatal,
now locked so it cannot recur silently.

**Power analysis** (`reports/power_analysis_2026-09-22.md`). Measured 5-day excess-return
noise from real bhavcopies: σ ≈ 3.7%. Consequence: **30 clean events resolves only a ~2.4%
net edge**, so D22's floor protects against calling a result from a handful of events but
does not give the study resolution at the size worth trading. Twelve months plausibly yields
36–184 events; ~170 are needed for a 1% net edge and ~300 to reach the 0.75% hurdle itself,
which is a 24–36 month window. The recommendation is to **measure before choosing**: the
contamination rate needs only the PR bundles — no PDFs, no API, no LLM — so download the
bundles first, get the real event count, then spend.

**BSE**: skipped, D26 final.

### 22 Sep 2026 — security scan, Spike A2, ARCHITECTURE.md to v0.9

**Security scan of all six commits: clean.** No secret-shaped file was ever committed (only
`.env.example`, all `CHANGEME`), no secret-shaped string in any commit's content, no broker
references. Largest blob 0.81 MB, `.git` 1.1 MB, nothing near 50 MB. Every `.gitignore` rule
resolves in the intended direction. Safe to add a remote.

**Spike A2 — 14/14 requests. The important entry in this file, because I got it wrong twice
before getting it right.**

Judged against the study universe rather than all 1,229 bodies, as Sravanth asked, the first
measurement looked fatal: 700 of 976 operating-company bodies missing, 462 of 680 companies
wholly absent, 2 of 23 order filings present. A recent day (21 Sep) showed the same 30%, so
not an ageing effect. No parameter reached the full day: `csv=true` returns the same 563 as
`text/csv`, `page=2` is ignored, `type=xbrl` is ignored, `index=equities_xbrl` is empty,
omitting `index` gives `Missing index`.

Then, mining saved responses for candidate PDFs, BEL records dated 2026 appeared —
contradicting Spike A's claim that the symbol query stopped at 31 Oct 2025. **That claim was a
string-sort artifact**: `DD-Mon-YYYY` sorted lexicographically puts `31-Oct-2025` after
`31-Jul-2026`. The query actually spans 22-Sep-2004 to 17-Sep-2026.

Checking BEL's September records exposed the second and larger error. BEL's
`Bagging/Receiving of orders/contracts` is timestamped **17-Sep 16:43**, after the close, and
appears in the **18 Sep** bundle. **`an<date>.txt` is a report for that date covering filings
disseminated since the previous report** — so comparing bundle(D) against API(D) was a
category error, and every "missing" figure above was inflated by it.

Re-measured over 17+18 Sep: bundle coverage 23% -> 44%, and **order-filing symbols found
3/12 -> 8/12, where the 8 are exactly the 8 mainboard issuers**. The 4 missing (MASON,
INNOMET, ENVIRO, MDL) are all SME, which D9 excludes. For the study universe, order coverage
on the day tested is **8 of 8**, and the hybrid is better than designed: one `symbol=` call
returns a company's entire history, making the backfill roughly 300-600 requests rather than
one per company-day.

Caveats now in §5.1: one day proves a pattern, not a rate; the report-window boundary is
unconfirmed; the *live* endpoint's completeness is untested, and D23 depends on it.

**BSE**: two requests against `api.bseindia.com/.../AnnGetData/w` both returned 200 with
`"No Record Found!"` — endpoint live, guessed parameters wrong. Still untested. Guessing an
undocumented API shape cost two requests for nothing; ask for the cURL instead.

**Also delivered**: a corporate-action regression test with a real fixture
(`tests/unit/test_corporate_actions.py`) so no future doc edit can quietly restore the
`PrvsClsgPric` claim; the labelled-order schema, README and template in `tests/labelled/`;
`config/holidays_2026.example.yaml` with a Muhurat entry; and the D27 calendar rules, Muhurat
return handling and Spike D counts in ARCHITECTURE.md.

### 22 Sep 2026 — open-loop audit, ARCHITECTURE.md to v0.7

Sravanth asked what was still open before the next phase. Documentation only; no code.

**Eight self-contradictions found and repaired**, all left behind by the v0.5 and v0.6
reversals in sections not edited at the time. The dangerous one: §7 still described
`prices.prev_close` as "already corporate-action adjusted and what returns chain from" — the
exact claim Spike B disproved — so the data model contradicted §5.9, and Slice 7 would be
built from §7. Also: the labelled-PDF exception read "proposed" in §5.5 and §8 while D8 said
confirmed; §8 had backups before *live use* against D14's before the *backfill*; §11 listed
the local dev database as both resolved and open; §5.1 carried a **Verify** already answered
by Spike A; and D23 sat after D25 in the table.

**New finding — the router's input is ambiguous.** `an<date>.txt` is
`COMPANY NAME SYMBOL : CATEGORY+DESCRIPTION` with **no delimiter** between category and
description, so a category can only be recovered by prefix-matching a known list. The file
parses to exactly 1,229 bodies and only 593 (48%) start with one of the 49 `desc` values the
API returned that day. Since §5.1 makes the bundle the only *complete* record, the router
needs a canonical category dictionary that does not exist. **The order buckets are safe** —
`Bagging/Receiving of orders/contracts` is a distinctive prefix — so this constrains Slice 3,
not the verdict. Spike A2 will collect the list from NSE's filings-page dropdown.

**D26 — BSE dropped from Phase 1.** D9 already made it duplication and it was never probed.
Removes an anti-bot surface, an unanswered Verify, and most of Slice 2. Intra-NSE dedup
stays and still matters: MASON filed five times on 18 Sep, four being Sub-para repeats. The
"which exchange publishes first" question is answered free by the API's `difference` field.

**D27 — trading-day calendar split by direction.** I proposed deriving trading days from
whether an archive exists for that date. Sravanth corrected it: the bhavcopy publishes
*after* the close, so at 08:00 it cannot tell the live collector whether today is a trading
day — that would put a look-ahead dependency in the one place the system runs forward. So
past dates derive from the archives, future dates come from a hand-maintained
`config/holidays_2026.yaml`, and a missing or stale file must fail loudly rather than assume
every day trades.

Also added a fail-closed rule for null spend caps in §6: `config/llm.yaml` ships with nulls
until Spike D, and treating null as unlimited would silently invert D5.

### 22 Sep 2026 (evening) — .env created, 2026 holiday calendar committed

Two housekeeping items, both of which had been sitting on the blocked-on-Sravanth list.

**`.env`.** There was none — only the committed `.env.example`. Created it from that
template with the same five variables. `DATABASE_URL`, `OPENAI_API_KEY` and
`HTTP_USER_AGENT` are left as `CHANGEME`: the first two have no real value yet (the laptop
Postgres and the OpenAI project key are still Sravanth's to create), and the User-Agent
string is still an **Open** decision in ARCHITECTURE §11, so picking one would have been
implementing an open item. `TZ` and `LOG_LEVEL` are filled in. Verified ignored:
`git check-ignore -v .env` matches `.gitignore:2` and `git status` stays clean. Nothing in
`src/` reads it yet — `python-dotenv` is declared in `pyproject.toml` but no module loads it.

**`config/holidays_2026.yaml`.** Sravanth scraped NSE's official 2026 holiday list and
pasted it in. Transcribed the **CM (Capital Market)** segment, which is the equity segment
this project needs. CBM, CMOT, FO, MF, NDM and NTRP carry the identical twenty dates; CD and
IRD carry four extra (19 Feb, 19 Mar, 1 Apr, 26 Aug) and COM one (1 Jan), none of which
apply to equities — so the segment choice is unambiguous rather than a judgment call.

Three things worth recording, because each was a decision rather than a transcription:

1. **Four of the twenty fall on a weekend**, not a weekday: Mahashivratri (Sun 15 Feb),
   Id-Ul-Fitr (Sat 21 Mar), Independence Day (Sat 15 Aug) and Diwali Laxmi Pujan (Sun
   8 Nov). `regular_week` already closes Saturdays and Sundays, so they get no `holidays`
   row — that leaves **16**. They are listed as a comment block in the file so it still
   reconciles line by line against NSE's published list instead of looking like a
   transcription that lost four dates.
2. **8 Nov is the Muhurat session, not a closure.** NSE writes it `Diwali Laxmi Pujan*`, and
   the asterisk is how it flags a Muhurat whose timings come separately. It goes in
   `special_sessions` with `trades: true, full_length: false` — exactly the case D27 and
   §5.11 were written for, and the one ARCHITECTURE §5.1 already names.
3. **The Muhurat timings are not guessed.** The example file carried a placeholder
   `18:15-19:15`; NSE's record has `morning_session` and `evening_session` both null, so the
   hour genuinely is not published yet. `session` is null with a note, per the never-guess-a
   -number rule. Nothing depends on it today — the collector's window is 08:00-22:00 (D6),
   and what the calendar needs from this entry is `trades: true`.

Verified: all twenty dates match the weekday NSE stated for each; the file parses with
`yaml.safe_load`; the sixteen `holidays` rows are all real 2026 weekdays. `pytest` still
passes (24 passed, 1 deselected). ARCHITECTURE §11 blocker 4 marked done.

### 22 Sep 2026 (evening, later) — worklog rule widened

Sravanth's instruction: update this file **every time anything important happens in the
repo**, not only at the end of a session. That is now its own numbered rule in CLAUDE.md,
alongside the existing end-of-session rule rather than replacing it — the end-of-session
entry is still the handover, and the new rule is about not letting an event wait for it.
What counts: a spike result, a reversed assumption, a blocker resolved or discovered, a
config or schema change, a decision he makes in conversation, a budget spent.

The reasoning behind it, worth keeping because it is the failure this guards against: a
session that ends early leaves no trace at all, and writing up an event hours later loses
the detail that made it worth recording in the first place.

Adding that rule renumbered the rules below it (Open/Verify is now 4, "Ask before" 5, the
n8n rule 7, secrets 8). ARCHITECTURE.md §9 referred to "CLAUDE.md's rule 5" for the n8n
containers point and would have silently started pointing at the wrong rule, so it now
refers to it by name instead of by number — a cross-reference that breaks quietly on the
next insertion is not worth keeping.

### 22 Sep 2026 (evening, later still) — label-set JSON skeletons

Created one JSON per PDF in `tests/labelled/`, nineteen in all, each a verbatim copy of
`_template.json` for Sravanth to fill in after reviewing each filing by hand. Spike D needs
ten of them; the rest are a head start on the ~50-file eval set.

**Prefilled only what the filename and the file itself prove**: `_source.symbol`,
`_source.filing_date` (from the `<SYMBOL>_<YYYYMMDD>_<n>` stem) and `_source.pdf_sha256`
(computed from the bytes). `isin`, `category_raw` and `pdf_url` are left blank, and **every
label field is untouched template default**. That restraint is deliberate: `CANDIDATES.md`
states no values by design, so the labels stay independent of anything already seen, and
prefilling a field from a PDF I had read would quietly contaminate the ground truth the
bake-off is graded against. `is_scanned` is left `false` even for JISLDVREQS, which
CANDIDATES.md flags as the scanned one, for the same reason - it is his to confirm.

Written by text substitution on the template rather than `json.dump`, so the blank-line
grouping survives and each file stays diffable against `_template.json`. Verified: all
nineteen parse, every non-`_source` field is byte-identical to the template, each SHA-256 is
64 hex characters, and the stems pair one-to-one with the PDFs with no orphans either way.

### 22 Sep 2026 (night) — laptop Postgres verified, .env password still missing

Sravanth set up Postgres on the laptop and said he had put the connection string into
`.env`. Checked it, and the picture is split.

**What is verified working.** PostgreSQL **16** is installed, the `postgresql-x64-16`
service is running, and something is listening on `127.0.0.1:5432`. The **`tradebot` role
exists** — a deliberate connection attempt came back `FATAL: password authentication failed
for user "tradebot"`, and that error is the evidence: had the role been missing the server
would have said `role "tradebot" does not exist` instead, and had the database been missing
it would have named the database. So the server-side setup is genuinely done. `psycopg`
3.3.6 is in the venv, and `psql` is on PATH at `C:\Program Files\PostgreSQL\16\bin`.

**What did not land.** `.env` still carries `DATABASE_URL=postgresql://tradebot:CHANGEME@...`,
and its mtime is 22:20:12, the moment it was created earlier this session — byte-for-byte
unchanged, one `DATABASE_URL` line, and no second env file anywhere in the tree. So the edit
was never saved to this file. Flagged rather than worked around: asking for the password in
chat would put a secret in a transcript, which CLAUDE.md's secrets rule exists to prevent.

**Why this is worth writing down for a cold session.** `.env` is gitignored by design, so a
later session cannot confirm any of this from the repo — it will only ever see the failure.
If a connection fails, check `.env` before suspecting the server. The connection was **not**
verified end to end, and this entry deliberately does not claim it was.

Also confirmed while looking: `migrations/` is empty. There is no schema, so even a working
connection would reach an empty database — Slice 1 still has to write `0001_init.sql`.

### 22 Sep 2026 (night, cont.) — laptop Postgres connected end to end

The `.env` password saved on the second attempt (file written 23:54), and the connection
now works. **ARCHITECTURE §11 blocker 2 is closed.**

Verified, not assumed:

- **PostgreSQL 16.15**, connected as role `tradebot` to database `tradebot`.
- **`tradebot` owns the database.** Worth checking rather than hoping: PostgreSQL 15 and
  later revoke `CREATE` on the `public` schema from `PUBLIC`, so a role that merely has
  access to a database cannot necessarily create tables in it. Here the schema owner is
  `pg_database_owner` and the database owner is `tradebot`, so the migration runner will
  work. Proved it by creating a table, inserting a row, reading it back, and rolling the
  transaction back — the database is left with zero tables.
- **`NUMERIC(20,2)` round-trips as `Decimal`** and **`timestamptz` comes back tz-aware**,
  which is exactly what the money and time rules in CLAUDE.md demand.

One oddity, noted so nobody spends time on it later: the server's `timezone` is
`Asia/Calcutta`, the deprecated IANA alias for `Asia/Kolkata`. Same zone, same offset, and
harmless — `timestamptz` stores UTC internally and the edges convert with
`ZoneInfo("Asia/Kolkata")` in Python, so the setting only affects how `psql` displays a
timestamp. Not worth changing, but worth recognising rather than re-investigating.

`migrations/` is still empty, so the database has no schema. Slice 1 writes `0001_init.sql`.

### 23 Sep 2026 — Slice 1 live collector: built, verified, running

The live feed is collecting into the laptop Postgres. `python -m tradebot.collector`
polls the announcements endpoint on D6's schedule and writes every filing to
`raw_announcements` and every poll to `source_health`. First production code in the repo.

**Two decisions Sravanth made, both of which were blocking.**

1. **User-Agent: no contact string** (Sect.11 was Open, and named as blocking Slice 1). The
   collector sends exactly the browser-like UA already in `config/sources.yaml`. Sect.3's
   tension is real — an honest UA is what robots.txt invites and what bot management is most
   likely to refuse — and the call is to keep the string every spike has proven rather than
   risk the hard block D19 exists to avoid. Consequence: `HTTP_USER_AGENT` is **gone** from
   `.env` and `.env.example`, because it is not a secret and two places to set it is exactly
   how the rotation D25 forbids happens by accident.
2. **Overflow handling: 60 s base, re-poll on overflow.** The endpoint returns only the **20
   most recent** filings, and ~1,229 arrive a day, concentrated 16:00–21:00. A burst above 20
   between two polls is lost permanently. So D6's 60 s stands as the base rate, and when a
   poll comes back full *and* entirely new the collector re-polls at the backfill pace (3 s)
   until a page overlaps what it holds — the proof nothing fell through. Bounded at 20 extra
   polls so a permanently-full page cannot spin.

**The earlier live-feed spike did not do what this file claimed.** The previous entry said it
was "running since 22 Sep 14:02, reconcile against the 23 Sep bundle". It actually **died at
14:18 after 15 polls**, when the session that started it ended. It was clean while alive — 15
polls, 0 errors, 26 records, no overflow — but the one-day reconciliation never happened, so
the question it existed to answer is still open: does the live endpoint carry the same
completeness as the symbol query? The new collector is the better instrument for it anyway,
because `source_health` now records the overflow signal on every poll.

**A bug found by running it.** The first poll flagged `OVERFLOW` — a false positive, because
from an empty database every record is new by definition. The spike had guarded against this
explicitly and my rewrite dropped the guard. Fixed (cold start is excluded), and the one bad
`source_health` row was corrected in place rather than left to inflate the very rate that
column exists to measure. `raw_announcements` was untouched: those 20 filings are real.

**Verified against the database, not assumed:**

- re-polling an unchanged filing inserts **nothing** (unique on source, source_id, hash);
- an **amended** payload under the same `source_id` lands as **revision 2** rather than being
  silently dropped — the failure Sect.5.3 was written about;
- `UPDATE` and `DELETE` on `raw_announcements` are **refused by a trigger**, so CLAUDE.md's
  append-only rule is a property of the database and not just prose;
- timestamps come back `+05:30` and tz-aware; the collector resumes from stored hashes
  across restarts.

Live numbers from the first minutes: 4 polls, 0 failures, 0 overflows, median latency 132 ms,
22 filings stored, one of them an order win (SKIPPER, `Bagging/Receiving of orders/contracts`).

**What is deliberately not built.** Backfill mode — the other half of Slice 1. No router, no
dedup into events, no document downloads; those are Slices 2–4, and D23 specifies raw store
only for now.

**Known gaps, stated rather than discovered later:**

- **The collector is a background process on the laptop, not a service.** It will die when the
  machine sleeps or reboots — which is exactly how the spike died. D23 puts it on the VPS;
  until then, treat a gap in `source_health` as the expected failure mode and check it.
- **No database-backed tests.** The 45 unit tests cover parsing, hashing, identity and the
  calendar, all without a database. Dedup, revisions and the append-only trigger were verified
  by hand this session. That should become a marked test suite rather than a one-off.
- The `jitter_seconds: [0.4, 1.6]` in config is read literally as an extra delay, so a 60 s
  poll lands at 60.4–61.6 s. It breaks exact periodicity but is small; revisit if NSE's
  behaviour suggests it matters.

### 23 Sep 2026 (afternoon) — first real overflow, and it was caused by the laptop, not NSE

Two hours into collection: 120 polls, 0 failures, 119 filings, average latency 336 ms.
Ordinary polls land 63 s apart, which is D6's 60 s plus jitter plus the request itself.

**One genuine overflow fired, at 13:10:11 — and the cause was on our side.** The previous
poll was at 12:46:15, so the collector had stalled for **1,436 seconds (24 minutes)**, almost
certainly the laptop sleeping. Every other gap in the whole run is 63 s. The endpoint only
ever holds the 20 most recent filings, so a 24-minute silence is exactly the condition that
rolls filings off the page before we ever see them.

**The overflow machinery behaved correctly.** The poll came back full and entirely new, the
flag was set, the catch-up re-poll ran once at the 3 s pace, and the following page overlapped
what we held. But catching up does not recover what already rolled off — it only proves where
the boundary is.

**The measured cost was a two-minute hole, not twenty-four.** The newest filing held from
before the stall is timestamped 12:45:09; the oldest on the recovery page is 12:47:11.
Anything filed strictly between those two is gone. It is a small hole because midday filing
volume is low enough that 20 records still reached back 23 minutes — at 18:00, when the day's
filings are concentrated, the same 24-minute stall would have cost far more.

**What this confirms.** The known gap recorded this morning — "a background process on the
laptop, not a service" — is not theoretical; it cost data on day one. It also shows the
`overflow` column earning its place: without it this hole would be invisible, and the data
would look complete. D23's move to the VPS is the actual fix. Until then, check
`source_health` for gaps before trusting any day's data, and treat a filing count that looks
low as a stall until proven otherwise.

### 23 Sep 2026 (evening) — D6 revised: three pacing bands, not a flat 60 s

Sravanth asked why the collector was still polling every minute at 16:40 when the market
closes at 15:30, and proposed dropping to 10 min after the close. **The premise turned out
to be backwards, and measuring it changed the answer.**

**Filings do not stop at 15:30 — that is roughly when they start.** From the two full-day
API dumps already in `spikes/out/`, and from our own live feed:

| Source | Share of filings after the close |
|---|---|
| 17 Sep 2026 (full day) | **64%** after 16:00 |
| 21 Sep 2026 (full day) | **67%** after 16:00 |
| 23 Sep live feed (to 16:38, day unfinished) | **32%** after 15:30 |

The single busiest hour on both full days is **17:00** (83 and 89 filings) — ninety minutes
after the close. It matters for the study specifically, not just in aggregate: **3 of 11** and
**4 of 9** order filings on those days arrived after 16:00.

**Why 10 minutes was rejected.** The endpoint returns only the 20 most recent filings, so a
10-minute gap holding more than 20 loses the excess permanently. Today's **16:10 window held
23** — that one poll would already have dropped filings, and the 17:00–19:00 peak had not
started. Against the *API dumps* a 10-minute poll looked safe (worst window 18 and 21), but
those dumps are the incomplete date-range query Spike A2 measured, so they understate density.
The live feed is the right instrument and it disagreed.

**Decided: three bands** — 60 s from 08:00 to 15:30, 3 min from 15:30 to 22:00, 10 min
otherwise. That honours the instinct to ease off once trading stops, cuts evening requests
about threefold, and leaves a wide overflow margin: a 3-minute window would need 20+ filings
in 3 minutes, against a measured worst of 23 in 10.

Implementation: `config/sources.yaml` now carries `pacing.bands` instead of a single
window, and `poll_seconds` reads them. Bands are **half-open** so 15:30 belongs to exactly one
of them. Tests went 45 → 54, covering each boundary minute and the case that would otherwise
be easy to get wrong — 17:00 on a holiday must use the off-window rate, not the post-close
rate, because no filings follow a board meeting that did not happen.

Collector restarted on the new schedule and resumed from 347 stored hashes, so the restart
cost nothing. **A general lesson worth keeping:** this file now holds two decisions whose
stated rationale was checked against data for the first time this session, and one of them
was wrong in its premise. Measuring was cheap — the dumps were already on disk.

### 23 Sep 2026 (night) — decision: mirror raw filings to Google Sheets now

Sravanth wants to browse the collected filings like a spreadsheet instead of writing SQL.
He described them as "scraped from n8n"; they are not — the only scraped announcements are
the Python collector's, in the laptop `tradebot` database (709 filings from 537 companies,
23 Sep 09:39–21:55 at the time). He confirmed that is the data he meant.

**Decided: automatic Google Sheets sync, pulled forward from Phase 2.** Chosen over a CSV
export and over pgAdmin (already installed with Postgres 16, and the zero-code fallback).
This brings part of **D11** forward, narrowly: a one-way, view-only **mirror of
`raw_announcements`**. D11's scored-orders tab and daily digest stay in Phase 2.

**Dependency approved: `google-auth`** (pure Python), for service-account auth against the
Sheets REST API through its `AuthorizedSession`. Not `gspread` or
`google-api-python-client` — one small package and plain `requests`-style calls.

Shape, so a cold session does not re-derive it: a separate process
(`python -m tradebot.sheets`), never inside the collector, because a Sheets failure must not
cost forward data; fixed-position writes (sheet row r = the (r−1)-th filing by id) so a
write that lands but times out on the hotspot is retried into the same cells rather than
duplicated; `valueInputOption=RAW` so a filing headline can never become a formula;
Postgres stays the truth and `--rebuild` regenerates the Sheet. Not n8n: it runs on the VPS,
cannot reach the laptop database, and rule 7 keeps us out of it.

**Blocked on Sravanth for the live run only**: a Google Cloud service account, its JSON key
saved outside the repo, a blank Sheet shared with the account's email, and both paths in
`.env`. The code and its tests do not need them.

### 23 Sep 2026 (night, cont.) — Sheets mirror built, tested, migrated; live run still blocked

What changed: `python -m tradebot.sheets`, a new process that mirrors `raw_announcements`
into a Google Sheet — view-only, one-way, Postgres stays authoritative. Why: recorded in
the decision entry just above. New table `sheets_sync` (`migrations/0002_sheets_sync.sql`)
holds one row per sync run and the watermark the retry logic reads back.

**Design point worth keeping**, because it is the part most likely to be gotten wrong on a
naive read of the plan: the watermark is only ever read from a row where `ok = true`. If a
sync's write reaches Google but the process dies before it can record success — plausible
on the hotspot — the *next* run does not know the write happened, and simply redoes the
same chunk. Because every row is pinned to a fixed sheet position
(row *r* = the (*r*−1)-th filing by `raw_announcements.id`), redoing it overwrites the same
cells with the same content rather than appending a duplicate. Verified with a unit test
that forces a write to "land" and then raises before the record step, then reruns the sync
and checks the retry's first write call is byte-for-byte the one the failed run would have
made.

**Verified, not just written:**
- 68 unit tests pass, 14 of them new for this slice: row formatting —
  UTC→IST, `None`→`""`, the 50,000-character cell cap; the Sheets client's request shape —
  `valueInputOption=RAW` always, the A1 range math, grid-growth only when needed; and the
  sync/retry/rebuild behaviour above). No network, no real database — a small in-memory
  fake stands in for the psycopg connection, dispatching on which of the three queries
  sync.py sent.
- `python -m tradebot.common.migrate` applied `0002_sheets_sync` cleanly against the real
  laptop database. Confirmed by reading back the table's columns and confirming
  `raw_announcements`'s row count only changed by ordinary collector activity (709 → 714
  between the two checks) — this migration touches nothing in it.

**Live sync now verified end to end (23 Sep 2026, later the same night).** Sravanth set up
the service account and Sheet and asked for it to be tested.

Two setup problems, both fixed without going back to him:

1. `.env`'s `GOOGLE_SERVICE_ACCOUNT_FILE` pointed at the key's **folder**, not the file -
   an easy mistake since `os.path.exists()` is true for a directory too, which is why the
   plan's own smoke test should have checked `os.path.isfile`, not `os.path.exists`.
   Fixing it in place became its own small lesson: a first attempt via `python3 -c` with a
   Windows path through two layers of shell/string escaping silently corrupted the line -
   a literal tab landed where a backslash should have been, splitting `trade-bot-...` into
   `t` + `rade-bot-...`. Redone as a standalone script using `pathlib`, with the full
   correct path written directly rather than built by string surgery on the corrupted
   value. **Lesson for next time**: never edit a Windows path via an inline shell `-c`
   string; write a small script file and run it, so there is only one layer of escaping
   (Python's), not two.
2. A brand-new Google Sheet's default tab is named `Sheet1`, not `raw_announcements`
   (`config/sheets.yaml`'s `tab_name`). Renamed it via the same `batchUpdate` endpoint the
   client already uses for freezing the header row, rather than sending Sravanth back to
   the UI - a one-line, non-destructive, easily-reversed call.

**One real bug, caught by the live run and not by any test**: `client.py`'s `_properties()`
built the Sheets API `fields` mask as `"sheets.properties,protectedRanges"` when asked for
the protection info. That parses as *two separate top-level* selectors, and
`protectedRanges` only exists per-sheet, not at the spreadsheet's top level - so the API
rejected it with `INVALID_ARGUMENT`. None of the 68 unit tests caught this because the fake
HTTP session in `tests/unit/test_sheets.py` never validated the `fields` parameter's
syntax, only the calls made around it. Fixed to nest correctly: `"sheets(properties,
protectedRanges)"`. **Worth remembering**: a fake that answers *any* well-formed request
verifies the code's control flow, not its wire format - the wire format only gets checked
by hitting the real API at least once.

**Verified against the real Sheet, not assumed:**
- First sync wrote all **719** filings then in `raw_announcements` (max id 722; the id gaps
  are ordinary - Postgres's identity sequence advances even on an `ON CONFLICT DO NOTHING`
  skip, so the count and the max id were never expected to match).
- A second `--once` run wrote **0** new rows and recorded `ok=true` with the same watermark
  - confirmed in `sheets_sync`, not just from the absence of a log line.
- Pulled the header and first two data rows back over the API by hand: correct columns,
  IST-formatted timestamps, real filing text (NTPCGREEN, PILANIINVS).
- The header row is frozen (`frozenRowCount: 1`) and a warning-only protected range exists
  on the tab, both confirmed by reading the Sheet's properties back, not just by the write
  call succeeding.

The Google Cloud project is `trade-bot-509516`; the service account is
`trade-bot@trade-bot-509516.iam.gserviceaccount.com`. Neither the key file's contents nor
the database password were ever read into this session, in either direction - only paths,
booleans and the one non-secret config line (`GOOGLE_SERVICE_ACCOUNT_FILE`'s value, a file
path, not a credential) were inspected while debugging.

**Dependency added**: `google-auth`, for `AuthorizedSession` — a `requests.Session` that
refreshes its own service-account bearer token. Not `gspread` or
`google-api-python-client`. Added to `pyproject.toml` and the pinned set in
`tests/unit/test_scaffold.py`.

ARCHITECTURE.md → v1.2 (D11 narrowed forward, §7 gains `sheets_sync`, §9 gains
`google-auth` and the `sheets/` package). CLAUDE.md's Commands section lists the three
invocations. `.env.example` gains `GOOGLE_SERVICE_ACCOUNT_FILE` / `GOOGLE_SHEET_ID` as
`CHANGEME`. `.gitignore` gains `secrets/` and `*service-account*.json`, since a key file
must never reach the repo even by accident.

### 24 Sep 2026 — first extraction run scored: 44%

Sravanth labelled the 18 candidate PDFs and asked for the first extraction run to be scored
**once**, reported, and nothing changed afterwards. Done, and nothing has been changed.

**8 / 18 — 44% exact `value_inr`.** 43% where the filing states a value (6/14), 50% where it
states none and null is the right answer (2/4). Full write-up in
`reports/extraction_baseline_2026-09-24.md`. §6's gate is ≥ 95% for the whole T0→T1→T2 chain;
this is T0 alone, and on this evidence the parser cannot carry extraction by itself.

There was no extraction code before today — `extractor/`, `units/` and `eval/` were empty
packages. So "the first run" meant building Slice 4's T0 half: `units/money.py`,
`extractor/annexure.py`, `documents/text.py`, and `eval/__main__.py` to score it.

**The discipline that makes the number mean something.** The parser was written from §5.6 and
§5.7 and **committed (`8a24cd5`) before the labels were opened**, tuned only against §5.7's
published vectors, which predate the labelled set. Prior exposure disclosed in the report: the
same PDFs were read once before to classify edge-case *categories* for `CANDIDATES.md`, never
values.

**The failures, worst first.** Two inventions — a number where the label says none. WAAREEENER
reads "Supply of 2 GW Solar modules" and the parser returned **₹2**, reading a physical
capacity as money, because the normalizer defaults to INR when no currency marker is present.
BEML stacked a mis-sliced span on top of a labelling judgement ("over ₹5,400 Crores" labelled
as no stated value). Seven misses: BEL and VIVIANA are press releases with **0 of 7 annexure
rows** — no SEBI table to parse at all — and RAILTEL found the row but the value ran onto the
next line, which the parser does not follow. One near-miss: MCLOUD prints
"₹44.60 Lakh (Rs. 44,60,400/-)" and the parser preferred the scale-word numeral over the exact
parenthetical.

Underneath several of these is one defect: label patterns match **inside longer words**, so
`order value` matches inside "order *valued* at", the slice starts mid-token and can lose the
trailing scale word. That single bug produced both an invention and a wrong number.

**Two caveats recorded so the per-field table is not over-read.** `stage` scored 0/18 but is
mostly a **vocabulary mismatch**: the labels use `purchase_order`, `LOA`, `LOI`, `agreement`;
§5.6 and the labelling README specify `PO`, `LoA`, `LoI`, `contract`. GKENERGY and RAILTEL are
the *same answer* scored wrong on case. Settling that enum is a change, so it has not been
made. `consideration_raw` 0/18 is a convention difference — the parser returns the whole cell,
the label records just the money phrase — which is why `value_inr` is the number to trust.
`company_is_recipient` at **89%** is the genuine bright spot, and it is exactly the judgement
§5.4 built the `order_candidate` bucket around.

**Provenance is unmeasured.** `value_span` is empty on all 18 labels, so §5.6's span check —
the main defence against a model lifting a number from a date — has no ground truth yet.

**This set is now spent as a clean baseline.** Re-scoring these same 18 after fixing the
defects is a *development* number, not an independent one. A fresh set should be held in
reserve for any score that decides something.

### 24 Sep 2026 (later) — §5.5 document pipeline built

Sravanth's instruction: keep the labelling/eval procedure as-is, move on to converting PDFs
to text, checking first whether it already existed. It half did: `documents/text.py` (the
extract-with-pdfplumber-or-pypdf step) was written yesterday as a side effect of building
the eval harness. Everything around it — download, hashing, the `documents` table, the
delete-after-extraction step, tests — did not exist.

Built: `documents/fetch.py` (streamed download reusing the collector's D25 session
discipline, capped at `nse.documents.max_bytes` in `config/sources.yaml` — the worker's
`mem_limit: 512m` alongside n8n makes an oversized file the one download that can OOM-kill
the container, so it is now a recorded refusal instead), `documents/pipeline.py`
(`process_url`, the full download-extract-store-delete sequence), `documents/store.py`
(the `documents` table, dedup on `sha256`). `migrations/0003_documents.sql` adds the table.

Two properties are enforced in code, not left to caller discipline, because both protect
something expensive to lose. The delete step **refuses any path outside its own work
directory**, even through a `..` traversal — `tests/labelled/` is D8's one permanent
exception and a pipeline bug reaching it would destroy the project's only hand-labelled
ground truth, so this is a hard `UnsafeDeletePath` exception, tested. And the PDF is
**deleted only after the text is committed**, never before, so a crash mid-run leaves the
file on disk (visible via `store.undeleted()`) rather than silently losing a filing whose
URL might not stay live.

12 new tests, all offline: a fake fetcher copies a real PDF from `tests/labelled/` into a
tmp work directory, so the real extractor runs against real text with no network and no
Postgres, matching §9's "most tests need none" rule. 101 passing overall.

**Deliberately not done in this pass**: nothing in `src/tradebot/collector/` calls
`process_url` yet. §5.5 only runs for `order_win`/`order_candidate`/LLM-confirmed
`catch_all` (D7), and that routing decision is §5.4's job, which has not been built. Wiring
the pipeline to the collector before the router exists would mean downloading every
filing's PDF, which is exactly what D7 exists to prevent.

Migration `0003_documents` applied to the local Postgres.

### 24 Sep 2026 (evening) — live demo exposes a gap: `is_scanned` misses garbled OCR text

Sravanth asked where extracted text is stored and whether the pipeline can handle a real
live PDF, not just the labelled fixtures. Answered by actually running `process_url`
against a genuine URL captured in Tuesday's live-feed poll (HMT, `General Updates`),
through the real local Postgres. It worked end to end: downloaded, hashed, extracted,
stored as `documents.id=1`, deleted — work directory empty afterward, confirming D8.

**But the extracted text for that file is garbage**, and `is_scanned` said `False` when it
should not have. Diagnosed rather than left alone: both pdfplumber and pypdf independently
produce identical mangled output, which rules out an extraction bug, and the font is named
literally `GlyphLessFont` — a scanned document with an invisible OCR text layer whose
character mapping is corrupted. Plenty of characters are present, so the char-count
heuristic in `documents/text.py` passes it as real text.

**Consequence**: this class of file currently skips the §5.5 manual-review queue it should
land in. Downstream the annexure parser will find nothing and stay silent (the safe
direction), but the document is recorded as a clean, usable extraction when it is not —
which pollutes any later count of "how many filings were readable."

Not fixed yet. This connects to the still-open scanned-PDF/OCR decision in §11, and Spike
D's job of counting scanned-vs-text-layer PDFs by market-cap band (§10) should be widened
to also catch this — a `GlyphLessFont`-style corrupted layer, not just an empty one.
`document_id=1` in the local database is this demo row and is known to be misleading;
harmless since nothing downstream reads it yet.

Diagnostic re-download was to `spikes/out/diag/`, outside the pipeline's own delete path,
and was cleaned up by hand afterward.

### 24 Sep 2026 (night) — per-page quality ladder built, vision OCR built dormant

Executed the plan at `.claude/plans/read-claude-md-and-architecture-md-ethereal-valley.md`
(Parts A, B and C) to close the `is_scanned` gap from the entry above. Built and tested:

- `documents/quality.py` — per-page verdicts `empty` / `broken_font` / `garbled` / `ok`.
- `documents/text.py` — rewritten for a per-page ladder: pdfplumber -> pypdf -> vision OCR
  -> `unreadable`. Only `ok` text reaches `documents.text`; everything else lands in the
  new `rejected_text` column, kept for audit, never fed to the parser or a model.
- `documents/ocr.py` + `llm/client.py` — the single OpenAI entry point CLAUDE.md requires,
  pulled forward from Slice 5. Fails closed on a null cap, logs every call to `llm_calls`,
  never retries. Dormant: `config/llm.yaml`'s `ocr_model` ships `PLACEHOLDER` and
  `caps.ocr_usd_per_month` ships `null`, so every OCR call is refused until Sravanth
  activates it (§11's now-closed scanned-PDF item lists exactly what he needs to supply).
- `prompts/ocr_transcribe_v1.md`, `config/documents.yaml`, migrations `0004_document_quality`
  and `0005_llm_calls` (both applied to the local Postgres).
- Fixture: re-downloaded `HMT_22092026135910_TWC.pdf` (one polite NSE request, via the
  existing `PdfFetcher`) as `tests/fixtures/scans/hmt_glyphless.pdf` — the permanent
  regression fixture for the garbled-OCR gap.
- `eval/__main__.py` now prints each document's `quality` alongside its scan/method flags.
- 35 new tests (`test_quality.py`, `test_text_extraction.py`, `test_llm_client.py`,
  `test_ocr.py`); 136 passing overall, up from 101. `python -m tradebot.eval` re-run:
  headline unchanged at 8/18 (44%), as expected — extraction logic didn't change, only
  which pages reach it, and all 41 labelled pages still assess `ok`.

**A finding that reversed part of the plan, found by actually measuring rather than
trusting the plan's stated numbers.** The plan expected a whole-page word-readability score
to separate HMT's garbled page from the 41 accepted ones, citing a measured range of
0.18-0.58 for the good pages with HMT sitting "far below" it. Rebuilding that measurement
against the real re-downloaded fixture, it does not hold: HMT's readability score — tried
three ways (a broad filing-vocabulary word list, a tight closed-class function-word list,
and a single-character-token ratio) — lands *inside* the accepted range every time, and
specifically inside the range of BEL_20260731_1, a page already in the labelled set with
the exact same pattern: a garbled bilingual header sitting next to a clean, correct English
body that contains BEL's real order value ("Rs.847 Crore"). No threshold on a whole-page
ratio can catch HMT without also catching BEL, and BEL's real, extractable content would
then be lost for nothing — confirmed by direct measurement, not assumed.

What actually separates them is font provenance, not readability: BEL/HECPROJECT/HEG's
full-page-image pages use real, named fonts (Helvetica, Times, Calibri) — the text was
typed into the PDF, and a garbled fragment is a font-encoding artifact (a legacy 8-bit
Hindi font), not evidence the content is unreliable. HMT's entire page, including the part
that reads as ordinary English, comes from one font literally named `GlyphLessFont` — a
third-party OCR tool's own invisible text layer, un-checkable by us. So the shipped rule is:
**a page sourced entirely from a `glyphless` font is never trusted on the strength of
looking readable**, independent of any ratio. Verified against real data: zero false alarms
on the 41 labelled pages (none use such a font) and a correct `garbled` verdict on HMT. Full
reasoning is in `quality.py`'s module docstring, and it is the reason a "recorded, not ruled
on" line in the plan for `GlyphLessFont` was *not* followed as written — the font check
became the primary signal, not a side note, once the readability score demonstrably failed
its one job. The word-ratio score stays in as a general safety net, calibrated well under
the 41 pages' measured floor (0.15 vs. 0.250) so it stays inert on real filings.

**A real bug caught by testing `llm/client.py` for real, not just reasoning about it.**
`common/config.py`'s `env(name, required=False)` returns the literal string `"CHANGEME"`
instead of `None` for an unfilled `.env` placeholder — the CHANGEME check only runs when
`required=True`. The client's first draft used `required=False` (so a missing key refuses
rather than crashes) and treated any non-empty return as a real key, so a "missing key must
refuse" test actually sent `CHANGEME` to OpenAI as a real API key and made one genuine
network call (caught immediately by the 401 response, not by inspection). Fixed by checking
for the literal placeholder explicitly in `llm/client.py`; regression-tested
(`test_missing_api_key_refuses`). Worth remembering for any future `env(required=False)`
caller: the CHANGEME check does not come along for free.

**A second, related network leak, found the same evening once a real key existed.** After
Sravanth added a real `OPENAI_API_KEY` to `.env` (24 Sep, night, continued), the fixed test
above started making genuine calls to OpenAI *again* - this time reaching the API with a
real key and failing only on an unrelated 404 (a fake test model name). Cause:
`test_missing_api_key_refuses` used `monkeypatch.delenv("OPENAI_API_KEY")` to simulate a
missing key, but `common/config.py`'s `_load_env_once()` is cached once per process
(`functools.cache`) and only actually calls `load_dotenv()` the first time `env()` runs
anywhere in that pytest session. If that first call happens *after* the test's
`monkeypatch.delenv`, `load_dotenv()` sees no existing value in `os.environ` and dutifully
fills it back in from the real `.env` - silently undoing the delete. **Lesson: never test a
"missing/invalid secret" path by deleting an env var when the code loads `.env` lazily and
caches that load; the loader can refill the var out from under the test, and whether it does
depends on unrelated test ordering.** Fixed by monkeypatching `env()` itself
(`tradebot.llm.client.env`) instead, which has no dependency on `.env`'s real content or
load order. Every other test in the file was audited and found safe: each one either fails
before the API-key check (a cap or price check) or injects a fake `openai_client`, so the
real SDK constructor is never reached regardless of what `.env` holds.

**Left for a future session, deliberately out of scope for this slice:**
- Part B stays dormant. Activating it needs Sravanth to supply `OPENAI_API_KEY`, a
  vision-capable `ocr_model` id with prices, and `caps.ocr_usd_per_month` (§11).
- `document_id=2` in the local Postgres is a fresh demo row from an end-to-end round-trip
  check (real DB, a byte-modified copy of the HMT fixture to dodge the sha256 dedup on the
  existing `document_id=1` demo row) — confirms `quality`, `page_report` (jsonb),
  `rejected_text` and `ocr_pages` all round-trip correctly. Same status as `document_id=1`:
  known demo data, harmless, nothing downstream reads it yet.
- The document pipeline is still not wired to the collector (§5.4's router doesn't exist
  yet) — unchanged from the entry above.

### 24 Sep 2026 (night, continued) — decisions for the first order-extraction run

The live collector had 725 filings for 23 Sep 2026 in `raw_announcements` by this point, all
with attachment URLs. Sravanth asked to extract them and send only order-related ones to the
LLM, with the LLM structurally unreachable for anything else. Decisions made in that
conversation, ahead of building:

- **Download scope widens D7.** Previously D7 downloaded PDFs only for `order_win`,
  `order_candidate` and LLM-confirmed `catch_all`. Measured on the 725: only 7 sit in the
  order categories (5 Bagging/Receiving, 2 Awarding), but 117 are catch-all
  (`General Updates`/`Updates`/`Press Release`), 52 of them with a generic headline that
  hides whatever the PDF actually says (the same shape as HILINFRA in §5.4). Sravanth chose
  to download all 124 rather than only the 7, so a real order filed as a Press Release isn't
  missed. `Action(s) taken or orders passed` (2 filings) stays out of scope - red flag, never
  order.
- **Model: `gpt-6-luna`**, $0.10 / $0.50 per million input/output tokens, Sravanth's own
  choice, given directly rather than through the Spike D bake-off. Single tier -
  `tier2_model` stays unset. `OPENAI_API_KEY` is filled in in `.env` (checked only that it
  is non-empty and not `CHANGEME`, never what it says).
- **Spend caps: $1/month each for OCR and for extraction**, separately enforced. Estimated
  cost for the 23 Sep run is under $0.10 at these prices.
- **Escalations allowed, order-related filings only:** vision OCR for an unreadable page,
  and LLM field extraction when the parser can't produce a provenance-verified value.
- **Two branches asked for, same processing core:** one that runs over already-scraped data
  for a date or range, and one (`--follow`) that runs continuously next to the live
  collector, so every filing gets processed going forward, not just this one backfill.

Building now, against the plan at
`.claude/plans/we-have-extracted-around-joyful-gizmo.md`.

**Built** (24 Sep 2026, night, continued): `config/category_map.yaml`, `router/orders.py`
(the gate - `classify`, `refine_with_body`, `llm_allowed`, `in_scope`), `extractor/
provenance.py`, `extractor/llm_extract.py` + `prompts/order_extract_v1.md`, `llm/client.py`
extended with a shared `_call` and `extract_json` (structured output, `response_format:
json_schema`, confirmed against the installed SDK the same way the vision call shape was
in the previous session), `migrations/0006_order_extractions.sql`, and `orders/` (`store.py`,
`run.py`'s `process_pending` - the one core both branches call - `report.py`, `__main__.py`
with `--date`/`--from`/`--to`/`--follow`). `config/llm.yaml` now carries Sravanth's model
choice for real: `tier1_model`/`ocr_model: gpt-6-luna`, priced, `live_usd_per_month` and
`ocr_usd_per_month` both $1. Confirmed the model id exists via a free `models.retrieve`
call before anything spent a cent. 72 new tests (`test_router_orders.py`,
`test_provenance.py`, `test_llm_extract.py`, `test_orders_run.py`,
`test_orders_sql_smoke.py`); 186 passing overall, up from 168.

**Two findings from building this, both worth remembering:**

- **The plan called for testing both branches "with a real local Postgres test transaction
  that rolls back" - that mechanism does not work, and would have quietly left permanent
  test rows in `raw_announcements` if built as specified.** The code under test commits
  explicitly and deliberately, more than once per filing (`documents/pipeline.py`'s own
  comment explains why: the PDF must not be deleted before its text is committed) - a
  rollback issued at the end of a test cannot undo a commit that already happened partway
  through it. Worse, `raw_announcements` has a hard append-only trigger
  (`migrations/0001_init.sql`) with no delete path at all, so even a test that avoided
  relying on rollback and tried to clean up afterward could never remove a row it inserted
  there. Fixed by dependency-injecting `documents.pipeline.process_url` and
  `documents.store.get_text` into `orders/run.py` (defaulting to the real functions in
  production), so `test_orders_run.py` runs entirely against in-memory fakes and never
  touches a real database at all - consistent with §9's "most tests need no database"
  rather than an exception to it. `documents.pipeline.process_url` itself already has its
  own real-Postgres-backed coverage from the previous session. A separate, genuinely
  read-only smoke-test file (`test_orders_sql_smoke.py`) checks the hand-written SQL in
  `select_latest_revisions` and the report queries against the real local Postgres, since
  nothing else does - it only ever reads, so there is nothing to clean up.
- **Activating `config/llm.yaml` (real model, real non-null caps) could have silently
  turned an earlier "dormant by default" test into a live network call.**
  `test_ocr.py::test_maybe_transcribe_with_no_configuration_at_all_does_not_raise`
  constructs a bare `LlmClient()` with no injected client, relying on the *real* config
  being inert. Once `ocr_model` and `ocr_usd_per_month` both became real values, the
  "unset model" and "null cap" refusals it relied on stopped firing - it stayed safe only
  because `LlmClient()`'s default `conn=None` still trips `_check_cap`'s separate "cap is
  set but no database connection was given" refusal. That is incidental, not designed-in:
  the moment any code path passes a real `conn` without a real API key, that specific
  safety net is gone. Checked explicitly (grepped every test for a bare `LlmClient()`/
  `maybe_transcribe()` with no `config=`/`client=` override) and re-ran the full suite
  after the config change to confirm nothing else was exposed. Worth checking again the
  next time `config/llm.yaml` moves a value from dormant to live.

**Dry run, real spend, on the 18 labelled PDFs** (plan verification step 5, before touching
the real 23 Sep data): the full T0→LLM chain hit **12/18 exact `value_inr` (67%)**, up from
T0-alone's 44% baseline, at a real cost of **$0.0028** for 9 LLM calls - confirms the
per-document cost estimate. This is a **development number, not a §6 gate measurement**:
Sravanth's model choice skipped the Spike D bake-off (§6, above), so there is no 95%-gate
certification behind it. Below that gate, per the plan: results are exploratory, not
certified - `order_extractions.review_status` already carries this per filing
(`verified` only when provenance passes), so the report is meaningful even without a
gate-level guarantee. Remaining misses, checked one by one: BEML and WAAREEENER are T0
inventing a number where none exists (the "invented a number" failure mode already
recorded against T0 in the original 44%-baseline entry, 24 Sep 2026 later - not something
this session's LLM work introduced); MCLOUD is T0 off by a rounding step (also pre-existing);
GKENERGY (LLM invents), GREENPOWER and NEWGEN (LLM misses a real value) are the LLM's own
imperfection at this un-benchmarked model choice. Confirmed `gpt-6-luna` exists on the
account first via a free `models.retrieve` call, before any of this ran.

**First real run, `python -m tradebot.orders --date 2026-09-23`, refused to start - a real
bug, caught immediately because it fails loudly rather than doing the wrong thing
silently.** `--max-requests` (default 200) was checked against every *pending*
`raw_announcements` row (723 for that day), not the in-scope subset that would actually be
downloaded (~124) - most of a day's filings are `Trading Window`/`Shareholders meeting`/etc.
and never reach a download at all. Fixed by classifying before counting in
`process_pending` (`orders/run.py`): `--max-requests` now guards the number of downloads
the run is about to make, which is what it was always meant to mean. Added
`test_max_requests_counts_only_in_scope_rows_not_every_pending_row` so this specific shape
of bug - a guard counting the wrong population - can't come back unnoticed. 187 tests
passing after the fix. Nothing was downloaded or spent before this was caught; the guard
did its job of stopping before any request went out, just for the wrong reason.

**The real run, `python -m tradebot.orders --date 2026-09-23`, succeeded end to end**: 124
filings downloaded (all - 0 download failures), 10 turned out order-related, 5 verified by
provenance, 5 sent to `needs_review`, 114 correctly resolved as not-an-order, 0 pending, 8
LLM extraction calls + 3 OCR pages, real cost **$0.008236** against the $1/month caps
(reconciled - see the cost-tracking bug below). Gate audit: **0 LLM calls and 0 OCR pages on
a non-order-related filing**, confirmed both in the report and by a direct query of
`order_extractions`/`llm_calls`. `data/orders_work/` was empty after the run (D8). Report at
`reports/orders_2026-09-23.md` and `.csv`, committed.

**The widened D7 scope paid for itself on the first run**: of the 10 order-related filings
found, **3 (ASHOKA, DHRUV, SILVERTUC) were hidden in `catch_all` categories** with no
category-level signal at all - exactly the HILINFRA pattern §5.4 was written about, now
observed for real rather than from one September day's fixture. The old order-only D7 scope
would have missed all three. One extraction is worth reading literally: **SUBEXLTD's order
is in US$, correctly left unconverted** (`value_inr` null, `provenance_ok` False, forced to
`needs_review`) rather than guessed - the FX-stays-Open design (§11) doing exactly its job
on real data for the first time.

**A second real bug, found by reconciling the run's own numbers against `llm_calls` after
it finished.** `Summary.llm_cost_usd` and each filing's stored `order_extractions.
llm_cost_usd` only counted T1 extraction cost, never OCR cost - `documents.ocr.
maybe_transcribe`'s contract is `str | None` (fixed by the previous session's
`documents/text.py`, §5.5 Part A/B), so `orders/run.py` had no way to see what an OCR call
had cost. The report's own total silently undercounted real spend by exactly the OCR
portion: BCPL's one OCR'd filing had a real cost of $0.003975 (3 pages, $0.003768 in OCR
+ $0.000207 extraction) but was stored and reported as $0.000207. Not a safety issue - the
$1 caps are enforced from the real `llm_calls` log regardless of what the summary displays
- but a report whose own numbers don't add up is a "never guess a number" violation on its
own terms. Fixed in `orders/run.py` with `_cost_since(conn, purpose, since)`, which reads
the real cost back from `llm_calls` for the window right after `process_url_fn` runs (calls
are sequential, so this window belongs to exactly one filing) and folds it into both the
per-filing row and the run's `Summary`. Regression-tested
(`test_ocr_cost_is_folded_into_the_filings_reported_llm_cost`). The one already-stored,
already-wrong row (BCPL, raw_announcement_id 458) was corrected by adding the real OCR cost
already logged in `llm_calls` (a targeted `UPDATE` on `order_extractions`, which is not
append-only, unlike `raw_announcements`), and `reports/orders_2026-09-23.md`/`.csv` were
regenerated from the corrected data - the total moved from $0.004468 to the true $0.008236.
188 tests passing.

**A third gap, found by reading the run's own output field by field** (Sravanth asked for a
detailed per-filing write-up of the order-related results, `reports/
orders_2026-09-23_detail.md`, which is what surfaced it): **`company_is_recipient` and
`stage` were always null on the T0 path.** `extractor/annexure.py` already has
`parse_company_is_recipient`/`parse_stage` - `eval/__main__.py`'s `predict()` has used them
since the 44%-baseline session - but `orders/run.py`'s `_t0_row` never called them, so a
filing verified entirely by the deterministic parser (BDL, GHCL) reported both fields as
null while an LLM-escalated one reported real values, for no principled reason. Fixed by
wiring both functions into `_t0_row`; regression-tested
(`test_t0_verified_order_still_fills_company_is_recipient_and_stage`). Re-derived and
corrected the two already-stored rows from their real document text rather than leaving
them null, and regenerated both reports.

**Read the corrected numbers, and one of them exposed a genuine, separate parser
weakness, not a bug in this session's work: BDL's `stage` now reads "amendment", which is
almost certainly wrong** - BDL's own category and headline are unambiguous that this is a
new order win. `parse_stage` checks for `amend|revis(?:ed|ion)|terminat` *before* anything
else in the document, so any occurrence of those words anywhere in the filing (a boilerplate
clause, a reference to an unrelated earlier revision) wins regardless of what the filing is
actually about. This is a pre-existing property of `extractor/annexure.py`'s heuristic,
first exposed by running it live rather than only against the labelled set - recorded here,
not fixed, since fixing `parse_stage`'s priority order is a T0-parser-quality question
outside tonight's scope and deserves its own look against more real examples, not a
one-off patch driven by a single filing. 189 tests passing.

**Detailed per-filing report published:** `reports/orders_2026-09-23_detail.md` - every
extracted field for all 10 order-related filings, in plain prose rather than a table, with
both findings above called out inline next to the filings they affect (BDL, SUBEXLTD).

### 25 Sep 2026 (morning) — catch-up for a live-collector gap, and a real CLI bug

The live collector was not running on 24 Sep or this morning (25 Sep), so `raw_announcements`
had a gap: 23 Sep's data existed, then nothing until whatever the collector next captures
live. Sravanth asked for the order news across that gap, up to ~10:25 IST this morning, to
watch stocks with it.

**Built: `python -m tradebot.collector --catchup --from DATE --to DATE`**
(`collector/nse.py`'s new `NseClient.fetch_range`, a date-range query using Spike A's
verified `from_date`/`to_date` params on the same announcements endpoint; wired into
`collector/__main__.py`). Reuses the exact same `records.to_raw`/`store.insert_announcements`
path the live poller uses, so idempotency and revision handling are identical - the only
difference is where the rows come from. `first_seen_at` is set to the real time of the
catch-up run, not backfilled to look like it was captured live: D23's rule is about never
*fabricating* a real-time observation, not about refusing to record a genuinely late one,
and this is honestly what happened - the collector was down and these were caught up late.

Run for real: `--catchup --from 2026-09-24 --to 2026-09-25` returned **975 filings, all
new** - 944 for 24 Sep (a complete day) and 31 for 25 Sep (up to ~10:27 IST, matching what
Sravanth reported). No unit test was added for `fetch_range` itself, consistent with this
codebase's existing choice not to unit-test `NseClient`'s live-endpoint methods with a
mocked session (nothing does, `poll_announcements` included) - it is exercised live instead,
which this run now doubles as.

**A real CLI bug, caught immediately when this was actually used for the first time.**
`orders/__main__.py --from 2026-09-24 --to 2026-09-25` (no `--date`) failed outright:
"error: one of the arguments --date --follow is required". `--date`/`--follow` were an
argparse `required=True` mutually exclusive group, which can only require *one specific
argument* - it has no way to express "or these two together satisfy the requirement", so
`--from`+`--to` as a standalone mode (exactly what the plan called Branch A's "date range"
form, and what last night's WORKLOG verification list even named as a command) had silently
never actually worked. Not caught earlier because every test and every real run so far had
used `--date` alone. Fixed: the three modes (`--date` / `--from`+`--to` / `--follow`) are
now validated explicitly in `main()` instead of via argparse's group mechanism, and
`tests/unit/test_orders_main.py` (8 tests, new) checks every valid and invalid combination
directly against `main()`, including the exact case that broke. 197 tests passing.

**Results.** `python -m tradebot.orders --from 2026-09-24 --to 2026-09-25`: 166 filings
considered, 165 downloaded (1 `download_failed` - a connection reset, will retry
automatically), 12 order-related, 5 verified, 3 needs-review, 4 correctly reclassified as
not-an-order by the LLM after matching a keyword, real cost $0.0329. Gate audit clean: 0
LLM calls and 0 OCR pages on a non-order-related filing. Detailed write-up:
`reports/orders_2026-09-24_25_detail.md` (the auto-generated `orders_2026-09-25.md` groups
both days under 25 Sep, because the catch-up gave every row the same `first_seen_at` - the
hand-written detail file sorts by actual filing time instead, which is what a same-morning
catch-up needs).

**A real extraction-accuracy bug, found by reading the output, not by a test: VASCONEQ's
order value passed provenance verification while being wrong by a factor of ten million.**
The filing reads "Rs. 660.79/- (Rupees Six Hundred & Sixty Crore and Seventy-Nine Lakhs
only)" - the numeral carries no scale word immediately after it (that's in the spelled-out
parenthetical instead), so `units/money.py`'s scale-word detection fell through to "bare
numeral = rupees" and stored ₹660.79 instead of ₹660.79 **crore**. Because the same wrong
span, re-parsed, reproduces the same wrong number, `extractor/provenance.py`'s check -
correctly, by its own definition - called this `verified`. Provenance proves a value is
traceable to the document; it was never designed to prove the *parse* of that value is
correct, and this is the first real case where that gap actually bit. Not patched under
time pressure (Sravanth was waiting on the report itself); recorded here as a real,
reproducible gap in `units/money.py` - it needs to recognise a scale word inside a nearby
parenthetical spelled-out amount, not only one immediately following the numeral. Flagged
prominently, with the corrected figure, in the detail report.

**Also worth recording: GENESYS's ₹283 crore Ahmedabad contract was filed twice** (a Press
Release, then the formal Reg 30 disclosure, ~7 hours apart) and both landed as separate
order-related rows - the same underlying event counted twice. This is expected given §5.3's
event-merging (same-day repeat filings collapsed into one event) is not built yet
(Slice 2); recorded here as a live example of exactly the gap that slice exists to close,
not a bug in tonight's work.

### 25 Sep 2026 (later) — decision: an `orders` tab in the Google Sheet, live

Sravanth asked, in his own words, for the order-extraction pipeline's output - the
classification into orders vs. general updates vs. out-of-scope, the T0/LLM extraction,
the order value - to reach Google Sheets live, so he can view it online anytime, next to
the existing raw-filings mirror.

**Decided: a second tab, `orders`, in the same Sheet.** Order-related filings only (about
10 a day; 22 so far today out of 290 processed) - the existing raw tab still shows
everything. He starts the three live processes himself (collector, `orders --follow`,
`sheets`); no launcher script. None of the three is running right now, so nothing will
appear online until he starts them.

Shape, so a cold session does not re-derive it: the orders tab is **rewritten each cycle**,
not appended - unlike raw_announcements, `order_extractions` rows change after they're
first written (a `pending_llm` row can become `verified`), so the raw tab's fixed-position,
append-only design does not fit here. A content hash skips the write when nothing changed.
Text cells stay `valueInputOption=RAW` as before (untrusted filing text); the one numeric
Value (₹ cr) column is written separately with `USER_ENTERED` so it sorts as a number, and
only after a new `write_numbers()` helper confirms every value is digits-and-a-decimal-
point - never handed filing text. This is a second, narrow piece of D11 pulled forward,
same as the raw mirror: view-only, no scoring (`value_to_ttm` etc. don't exist yet), and
not D11's Phase 2 scored-orders/digest tab.

### 25 Sep 2026 (later, cont.) — `orders` tab built, tested, run live

What changed: `src/tradebot/sheets/orders.py` (`HEADER`, `ORDERS_SQL`, `to_orders_row`,
`sync_orders`); `client.py` gained `ensure_tab()`, `write_numbers()`, `clear_from()` (and
`clear_data()` is now `clear_from(2)`); `rows.py`'s `_text`/`_ist` became the public
`text_cell`/`ist_cell` so `orders.py` could reuse them instead of duplicating the empty-
cell rule and the 50,000-character cap; `__main__.py` now builds two `SheetsClient`s off
one shared `authorized_session` and syncs both tabs each cycle, each in its own
try/except. `config/sheets.yaml` gained `orders_tab_name: orders`. Why: recorded in the
decision entry just above. 20 new unit tests, all in `tests/unit/test_sheets_orders.py`,
no network and no database - 217 total pass.

**Verified live, not just in tests.** `python -m tradebot.sheets --once`:
- created the `orders` tab from nothing (`ensure_tab`'s first real exercise - no manual
  rename needed this time, unlike the raw tab's first sync on 23 Sep);
- wrote all **22** order-related rows, newest-filed-first;
- read back with `valueRenderOption=UNFORMATTED_VALUE`: BDL's ₹810.79 crore order came
  back as the **number** `810.79` in the Value column (not text) while every other column
  came back as literal text, confirming the RAW/`USER_ENTERED` split actually produced two
  different cell types, not just two different write calls;
- the raw tab, untouched since 23 Sep, caught up from 719 to 1,701 rows in the same run
  (`raw_announcements` had grown to 1,700 via this morning's catch-up backfill - see the
  morning entry - none of it synced to the Sheet until now).

**The orders tab is faithfully showing a bug that already exists upstream, not a new one.**
VASCONEQ's row shows Value = 0 - that's the same known `units/money.py` scale-word bug
recorded in the morning entry above (₹660.79 crore stored as ₹660.79 rupees), correctly
carried through: `0.000066` crore rounds to `0.00`. Confirmed this is the pre-existing bug
and not something introduced here before writing this up, so a future session doesn't
waste time re-diagnosing it from the Sheet.

**One thing the plan got wrong, caught only by running it twice.** The plan's verification
section said "a second `--once`: the orders tab is reported unchanged." It isn't - each
`--once` is a fresh process, `orders_fingerprint` starts `None` every time (nothing
persists it), so every fresh run rewrites all 22 rows once, always. This is not a bug:
it matches the plan's own Design section, which explicitly chose no watermark table for
this tab ("nothing needs resuming, and after a restart the tab is simply written once") -
one contradicted the other and I hadn't reconciled them before running it. Now recorded in
ARCHITECTURE.md §7 as the intended behaviour: the in-memory hash only saves a write
*within* one continuous `python -m tradebot.sheets` process (between its own cycles,
covered by the unit tests), never across a restart. At ~10 rows/day this costs one harmless
extra rewrite per restart, not a real problem - but the plan should not have promised a
check that the design it also specified could never pass, and a live run is what caught it.

**Not started, same as before this session**: none of the three live processes (collector,
`orders --follow`, `sheets` with no flags) is running continuously. Commands are in
CLAUDE.md's Commands section; Sravanth starts them himself, one terminal each, per his
choice recorded above.
