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

*Last updated: 20 Oct 2026 (GATE 1). The live checklist is [STATUS.md](STATUS.md); the
20 Oct snapshot with file:line evidence is [AUDIT.md](AUDIT.md).*

**What this is.** Reg30 Radar Phase 1. Collect NSE corporate announcements (BSE dropped by
D26), classify them, extract order wins, measure order value against revenue and market
cap, and test it on 12 months of history to decide whether order filings move prices
tradeably. Nothing in this repo places trades, and nothing will in Phase 1.

**Where we are.** Sravanth's 20 Oct brief sets two gates. GATE 1 (audit) is passed; the
plan he approved runs Phase 1 fixes, then the backfill to a verdict, then GATE 2, where he
picks hosting. Decisions from the gate (ARCHITECTURE D28-D32):
- The VPS is cancelled.
- The LLM stays on OpenAI under the existing caps.
- Live collection restarts only as one process behind an NSE lock.
- The third documents tier is skipped.
- "over ₹X" counts as a flagged lower bound.

**Backfill database** (`tradebot_backfill`, laptop):
- Universe (1,583 companies), announcements (162,251), market data (388 trading days to
  25 Sep 2026), band history, reconcile (96.6%): all done.
- Documents tier one (2,120) and Batch extraction (1,444 verified / 355 review / 13 owed a
  retry): done.
- `events`: 1,286, all `extracted`.
- `revenue`: 223 of 231 companies.
- **Not yet run:** `calculate`, `recheck`, `study`.
- Defects found in verified values must be fixed and re-applied first (AUDIT §3): 20
  values below ₹1 lakh from ranges and band legends, 22 with no currency marker, 42
  vision-read values with no second read, and the Sep-2025 half-year defect in revenue.

**Live database** (`tradebot`): the collector last polled on **1 Oct 09:31**. The
`first_seen_at` hole since then is permanent. Live restarts only through the planned
`python -m reg30_radar.live` (D30).

**Spend:** backfill $0.45 of $3, live $0.11 (OpenAI).

**Backups:** `python -m reg30_radar.common.backup` (first run 20 Oct). There is no
off-machine copy until rclone is installed.

**Live order ratios are deferred until after the verdict** (Sravanth, 4 Oct). The live
database holds no revenue or market caps.

**Side tool, not a pipeline slice.** `python -m reg30_radar.sheets` mirrors
`raw_announcements` and `order_extractions` into two tabs of one Google Sheet, view-only.
It talks only to Google, not NSE.

**How Sravanth works.** He reviews every change and must be able to explain it, so prefer
plain code and say why, not what. He pushes back hard and specifically, and he is usually
right; several of his corrections are recorded below.
- Before the 20 Oct brief he wanted one step at a time, then stop and wait.
- The brief sets the stops at GATE 1 and GATE 2. Between them, work proceeds item by item,
  committing and pushing after each, with STATUS.md kept current.
- Stop early for a surprise, a blocker, or money beyond the caps.

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

### 25 Sep 2026 (afternoon) — log timestamps were UTC on the laptop; now always IST

Sravanth, running `python -m tradebot.sheets` at about 14:40 IST, saw log lines stamped
09:01 and read it as a hardcoded time. It wasn't: every log line was in **UTC**. Root
cause: `.env` sets `TZ=Asia/Kolkata`, python-dotenv copies it into the environment, and
Windows' C runtime can't parse an IANA zone name. It silently treats it as offset zero, so
`time.localtime()`, which `logging` uses for `%(asctime)s`, returns UTC. Reproduced
exactly: the first local-time read after `load_dotenv` prints `09:39:25 a/K` while true
IST is 15:09. It only shows if the first local-time read happens *after* `.env` is
loaded, which is why a quick check that reads the time first looked fine.

**Stored data was never affected.** A grep for `datetime.now()`, `time.localtime`,
`time.strftime` and `date.today()` in `src/` finds nothing. Every timestamp the code writes
uses `ZoneInfo`/UTC explicitly (D17), so `first_seen_at`, `processed_at` and the collector's
pacing bands were all correct. Only the console log lines were wrong.

Fix: `src/tradebot/common/logs.py`, a shared `configure()` whose formatter converts each
record's time with `ZoneInfo("Asia/Kolkata")`, used by the collector, orders and sheets
entry points in place of their three copies of `basicConfig`. Log time is now IST whatever
the machine thinks, which also covers the VPS, where Docker defaults to UTC. One new test,
218 pass. Checked live with `.env` loaded: log line 15:11:01, true IST 15:11:01.

`TZ=Asia/Kolkata` is left in `.env` because it is harmless now that nothing reads local
time. It remains a trap for any future code that does, so on Windows treat the process's
local time as UTC and never rely on it (CLAUDE.md already forbids naive datetimes).
**Running processes keep the old behaviour until restarted.**

### 26 Sep 2026 (evening) — the overflow catch-up never caught anything up; fixed

Sravanth spotted it from watching the collector: on an overflow it made exactly one extra
poll and stopped, so a burst of more than ~20 filings between polls was not recovered.
He was right, and it was a design error of mine in Slice 1, not a tuning problem.

**Why it failed.** The live endpoint always returns the newest 20 filings. The catch-up
loop re-polled that same endpoint "until a page overlaps what we hold", treating overlap
as proof nothing was lost. But the next page overlaps the 20 the overflowing poll just
stored, so the loop always ended after one extra poll. It recovered only what arrived in
those ~5 seconds and never reached anything that had already rolled off. Evidence in
`source_health`: all 8 overflows recorded so far (23 Sep once, 25 Sep four times, 26 Sep
three times, including the 16:28 restart) are followed by a poll with 0 new and no
overflow. **So every one of those 8 windows may have lost filings beyond the newest 20.**

**Fix** (`src/tradebot/collector/__main__.py`): an overflow now triggers `close_gap`, one
date-range query for yesterday and today (the same `fetch_range` `--catchup` uses), paced
at the backfill gap. It is recorded as its own `source_health` row (`records_returned`
well above 20 marks it). If it fails, a `gap_open` flag retries it on the next ordinary
cycle, with the normal backoff, never in a loop. New `tests/unit/test_collector_gap.py`
(4 tests) includes one that reproduces the old failure. 222 pass. ARCHITECTURE.md §7
`source_health` updated.

**To do by hand:** restart the collector (the running one has the old code), then close
the historical gaps with `python -m tradebot.collector --catchup --from 2026-09-23 --to
2026-09-26` — run while the live collector is stopped, so there's only one request to
NSE at a time.

**Unexplained, noted not chased:** `source_health` rows 557, 561 and 566 (26 Sep, 16:28 to
16:50) are polls 8 to 16 s after the previous one, which one collector process can't
produce on a Saturday's 600 s pacing. Row 566 even flags overflow with 20 hashes new to
the process but 0 new to the database, which only a second process with an older
in-memory `seen` set explains. Only one collector was running when checked at ~17:00. So
most likely a second collector was briefly running alongside it. Two collectors break the
one-request-at-a-time rule; check before starting one.

### 27 Sep 2026 — audit: where Phase 1 stands, and what blocks a VPS deployment

Sravanth asked for the whole repo to be evaluated against ARCHITECTURE §10 and for what
stops V1 end to end, aiming to make it production-grade on the laptop today and then deploy
with `git pull` on the VPS. This entry is the audit; no code changed in it.

**Built and running (the live path).** Slice 1's live half; the order gate, document
pipeline and T0 + T1 extraction (parts of Slices 3, 4 and 5); the two-tab Sheets mirror.
222 tests pass. Since 23 Sep: 3,243 filings, 494 in-scope extractions (42 order-related,
17 verified), 488 documents with every PDF deleted (D8 holds), and $0.081 of LLM spend
this month against the two $1 caps. `orders --follow` is keeping up: no in-scope filing
lacks an `order_extractions` row.

**Not built (the event-study half of Phase 1).** Slice 1's backfill mode; Slice 2
(instruments and ISIN map, `events`, dedup; `normalizer/` is empty, and GENESYS's double
count on 25 Sep is the live symptom); Slice 3's full router and `unknown_categories`;
Slice 5's T2, escalation triggers, §6 state machine and Batch mode; Spike C and Slice 6
(`revenue/` is empty); Slice 7 (`market/` and `calculator/` are empty); Slice 8 (only
`backfill/reconcile.py` exists). Spike E has not started, and D14's backups are not in place.

**Deployment gap.** There is no Dockerfile and no `docker-compose.yml`, although CLAUDE.md's
Commands and §9 both describe them. The Python 3.14 manylinux wheels are still unchecked;
building the image is that check. Docker Desktop is installed on the laptop, but its daemon
was not running.

**Four production defects, found by reading the live data rather than the tests.**

1. **About half the off-window polls fail on a stale keep-alive connection, not on NSE.**
   On 26 Sep, a Saturday, every poll is on the 600 s band, and 34 of 61 failed. Each
   failure came ~600 s after the previous poll with `ConnectionResetError(10054)`, and the
   backoff retry ~30 s later succeeded. The `requests.Session` reuses a pooled TCP
   connection that the far end has already closed for idleness. At the 60 s band the
   connection never sits idle that long, which is why weekdays looked healthy. Each
   occurrence costs an extra request and writes a `source_health` failure that is not an
   outage. `PdfFetcher` has the same pattern after any idle gap. The 17:44-19:53 run of
   `HTTPSConnectionPool` errors that day is a different thing: the hotspot really was down.
2. **`orders --follow` reads the whole of `raw_announcements` every cycle.** Out-of-scope
   filings never get a row, so they are re-classified every 2 minutes indefinitely. At
   about 1,200 filings a day that is roughly 440,000 rows per cycle after a year, inside a
   512 MB container.
3. **`--follow` writes `reports/orders_<date>.md` and `.csv` into the tracked `reports/`
   directory.** That is why `reports/orders_2026-09-25.*` show as modified. On the VPS the
   same writes would make every `git pull` fail with "local changes would be overwritten",
   which breaks D1's deploy path.
4. **The overflow fix is live but uncommitted.** A `git pull` on the VPS today would deploy
   the version that never closed a gap.

**Data-quality defects still open**, recorded earlier and re-checked today: VASCONEQ's
₹660.79 crore is still stored as ₹660.79 and marked verified (the numeral has no scale
word, and the scale is only in the spelled-out words; `units/money.py` already sets a
`no_scale_word` flag that nothing acts on), and `parse_stage` still returns "amendment"
whenever the word appears anywhere in the document (BDL).

**A gotcha for anyone counting processes.** On Windows each command shows as two
`python.exe` processes: the venv's `.venv\Scripts\python.exe` is a launcher that spawns the
base interpreter as its child. Two entries per command is therefore normal. Check
`ParentProcessId` before concluding that something is running twice. This does not explain
the 26 Sep polls 8-16 s apart recorded above, which are timing evidence from the database,
not a process count.

**What "V1 end to end" costs, stated now so it is not discovered later.** The Phase 1
verdict needs Slices 2, 3, the rest of 5, Spike C with 6, 7 and 8. The backfill alone is
many hours of paced traffic: about 250 PR bundles, 280 bhavcopies, 300-600 symbol
queries, several thousand PDFs at ≥3 s each, and the results XBRL. On top of that comes a
Batch-API LLM run that can take 24 h, and D14's backups have to be in place first. That
is several days of work, not one. What can reach production grade today is the live
pipeline on the VPS.

**Sravanth's decisions, same conversation:**

1. **Today: build every remaining slice and test it on the laptop. Deploy to the VPS
   tomorrow.** He chose this over "deploy today, verdict slices later".
2. **All three live processes go to the VPS**: collector, `orders --follow` and `sheets`.
   This widens D19, which had put only the collector there, and ARCHITECTURE.md D19 now
   says so. The reason: without the tunnel D19 rules out, the laptop cannot reach the VPS
   database, so extraction left on the laptop would have no live data.
3. **The laptop's live data moves to the VPS**: one `pg_dump` and restore at cutover, so
   `first_seen_at` since 23 Sep, the extractions and the Sheet's watermark continue
   unbroken.
4. **Backups: rclone to Google Drive.** D14's mechanism is no longer Open. Sravanth
   installs and configures rclone himself.

**Two measurements that shape the backfill, taken from the live data.** About 135
catch-all filings arrive per weekday, and a headline keyword matches only 2-3 of them. Yet
7 of the 29 orders found live were visible only in the PDF body: DHRUV, AASTHA and
POWERGRID (all verified), plus SILVERTUC, ASHOKA, DREDGECORP and HMT. The average PDF is
about 1 MB (median 530 KB). So downloading every catch-all PDF for 12 months is roughly
35,000 files, about 35 GB over the hotspot D19 prescribes, and 35-40 hours of paced
downloads. Order categories plus headline hits is about 1,700 files and 2 GB, but misses
roughly one order in four. Per §10's sequencing note, that choice is put to Sravanth only
after the PR bundles are loaded, when the counts are measured rather than extrapolated
from four live days.

**Second round of decisions, same conversation** (written into §5.1, §6, CLAUDE.md and
`config/llm.yaml`):

5. **The backfill is company-wise over a filtered list**: one `symbol=` query per listed
   company. I had recommended one date-range query per day with gap fill, and Sravanth
   first accepted it, then reversed it before it was recorded here. His reasoning: the
   study measures each company's price response to its own orders, and not every company
   is the goal. On evaluation he is right once the list is predefined. A company's
   `symbol=` history is complete across every category, which is exactly what per-ISIN
   contamination and catch-all orders need. My objection to per-company applied only to
   §5.1's original rule of picking companies by "filed an order category". Two conditions
   were agreed. First, the list is built from **criteria applied to data as of 22 Sep
   2025**, keeping delisted names and leaving out later IPOs, and frozen before any
   return is computed (D22). Second, the listed companies' order count is measured from
   the PR bundles before any PDF is downloaded, because D22 needs ≥30 clean events.
   Sravanth will supply the criteria. For listed companies the PDF scope is order
   categories plus every catch-all filing.
6. **T2: Sravanth will name a model** for §6's independent recheck. He chose this over a
   blind second read by gpt-6-luna and over manual review only. It needs the model id,
   its standard and Batch prices, and gpt-6-luna's Batch price. Until they arrive a
   recheck fails closed to `needs_review`.
7. **Backfill cap: $3 for the complete backfill**, every purpose included. He asked for
   the "half price if the answer isn't needed instantly" option, which is the Batch API
   CLAUDE.md already requires. Batch cost will be computed from explicit Batch prices,
   never from an assumed 50%.
8. **Vision OCR stays on the standard API in the backfill**, a recorded exception to the
   Batch rule. Batching OCR would mean page images waiting up to 24 h on disk against D8,
   to save cents on about 3% of documents.
9. **The backfill gets its own database, `tradebot_backfill`**, on the laptop, so a year of
   history never reaches the live database that moves to the VPS, the Sheet or
   `orders --follow`. The `tradebot` role has no CREATEDB, so Sravanth creates it as
   superuser.

Plan accepted: `C:\Users\srava\.claude\plans\recursive-chasing-wombat.md` (Step 0, Part A
live-path hardening and Docker, Part B verdict slices). Sravanth also asked whether Sonnet
at high effort is enough for the build. My answer: yes for the mechanical bulk, with Opus
kept for (or reviewing) Spike C/TTM, the event study and verdict, and the Batch spend
guards, because mistakes there produce plausible wrong numbers rather than failing tests.

### 27 Sep 2026 (afternoon) — Part A: live-path fixes, and three stored values corrected

Step 0 committed and pushed (`50af31d`): the 26 Sep overflow fix, the audit and both rounds
of decisions. Then the live-path defects from the audit:

- **Stale keep-alive fixed.** `common/http.py`'s `close_if_idle` closes a session's pooled
  connections before any request that follows `pacing.idle_reconnect_seconds` (90 s) of
  idleness. Cookies survive; this was checked against a local server before relying on it
  (a closed `requests.Session` reopens on a new socket, cookies intact). `NseClient` now
  routes its three query types, live, date range and the new `fetch_symbol` for the
  backfill, through one `_get_json`. `PdfFetcher` does the same check before each download.
- **`--follow` bounded.** `follow_cycle` reads only filings first seen in the last
  `orders.follow_lookback_days` (3), instead of the whole table every two minutes.
- **Live reports out of git.** `--follow` writes `data/reports/` (gitignored). Batch runs
  keep writing `reports/`. The untracked 26/27 Sep auto-reports moved there.
- **Health check**: `python -m tradebot.common.health`, exit 1 when no poll has succeeded
  for 30 minutes, for the collector's Docker healthcheck. **Its first real run caught a
  real outage**: all three live processes had stopped at about 12:55 IST, around the time
  the morning's session was interrupted. The laptop had not rebooted. Sunday volume is
  tiny, and the collector's first poll after a restart recovers the gap.

**Two scale bugs, one of them new.** The VASCONEQ fix (`units/money.py`) cross-checks a
bare numeral against a spelled-out amount in the same string. If the words equal the
numeral times a crore or a lakh exactly, they settle the scale. Anything still
unconfirmed and under ₹1 lakh, or contradicted by the words, is flagged `suspect_scale`
and is never verified by T0 or the LLM, whatever provenance says, because provenance
proves origin, not scale. Measuring the fix on the 42 stored order rows before committing
found a **second, unrecorded instance**: LCCPROJECT's "₹58.53/- Crore" was stored as
₹58.53 and marked verified, because the "/-" between numeral and scale word hid the word.
`_scale_after` now reads past "/-". The same measurement caught a bug in my own first
draft, where a lone "crore" was read as a spelled amount of 1 crore; it now needs a number
word as well.

**`parse_stage` fixed.** BDL read "amendment" because almost every filing cites "SEBI
(LODR) Regulations, 2015, (as amended)". That boilerplate is stripped, and amend, revise
and terminate count only within a few words of an order word. "cancel" was deliberately
left out, since AASTHA's "non-cancellable order" would have matched.

**Stored rows corrected** by re-running the fixed T0 path over every T0 order row (script
in the session scratchpad, only changed rows written, OCR cost kept): BDL stage →
contract; LCCPROJECT (23 Sep) stage → L1; LCCPROJECT (25 Sep) ₹58.53 → ₹58.53 crore,
stage → contract; VASCONEQ escalated to T1 exactly as the live path now would, came back
with the full phrase and is verified at ₹660.79 crore. `reports/orders_2026-09-23.*` and
`orders_2026-09-25.*` were regenerated. The hand-written `_detail.md` reports are history
and still describe the bugs as found. Labelled set unchanged at 8/18 (44%) T0, so no
regression. 245 tests pass.

### 27 Sep 2026 (afternoon, cont.) — deploy packaging: Dockerfile, compose, runbook

Built, not yet run: `Dockerfile` (python:3.14-slim, uid 10001, `PYTHONPATH=/app/src` so
`config.ROOT` is `/app`, and a build-time check that `Asia/Kolkata` resolves),
`.dockerignore` (no secrets, tests or docs; `prompts/*.md` kept deliberately),
`docker-compose.yml` (`collector` with a `common/health.py` healthcheck, `orders`,
`sheets`; per-service memory and CPU limits overridable from `.env`; json-file logs
10m×3; external network `${TRADEBOT_DB_NETWORK}`, which fails loudly if unset; an
`ops`-profile `backup` job), `ops/preflight.sh` (Spike E, read-only, never prints container
environment variables) and `ops/backup.sh` (`vps` through compose, `backfill` with the
laptop's pg_dump; 7 kept locally, 30 days on the rclone remote). `DEPLOY.md` is tomorrow's
runbook, including the cutover order. `.env.example` gains `BACKFILL_DATABASE_URL`,
`TRADEBOT_DB_NETWORK`, `TRADEBOT_PG_MAJOR` and `RCLONE_REMOTE`. `.gitignore` gains
`backups/`. `docker compose config --quiet` validates. A plain `config` was avoided
because it prints `.env`'s resolved secrets.

**A §9 gap closed while designing compose.** A worker killed at its memory limit left no
trace of the attempt, because `order_extractions` was only written after the work, so
`restart: unless-stopped` would have fed it the same PDF forever. `_process_one` now writes
the attempt first, as a retryable `download_failed` row with `last_error`
"interrupted: ...", which every normal outcome overwrites. A filing that crashes the worker
therefore stops after three attempts, 15 minutes apart. Test:
`test_a_worker_killed_mid_filing_leaves_a_counted_retryable_row`. 246 tests pass.

**Not yet verified:** the image build and the Linux cp314 wheels (D12), which wait on
Docker Desktop being started on the laptop.

### 27 Sep 2026 (afternoon, cont.) — B1: market-data loader built, not yet run

`src/tradebot/market/`: `parse.py` (pure parsers for the UDiFF bhavcopy, the PR bundle's
`pd`/`mcap`/`bh`/`an`, and member matching by prefix plus date digits),
`fetch.py` (`ArchiveFetcher`: warm-up, ≥3 s jittered gap, idle reconnect, 50 MB cap, and a
request counter that includes warm-ups), `store.py` (one transaction per day; every file is
keyed to ISINs through *that day's* bhavcopy, because a symbol can pass to another company
over time) and `__main__.py` (`python -m tradebot.market --from --to`, backfill database
only, resumable through `archive_days`). `migrations/0007_market_data.sql`: `instruments`,
`instrument_symbols` (every symbol an ISIN traded under, for the symbol-change Verify),
`prices`, `index_prices`, `market_caps`, `bundle_announcements`, `archive_days`,
`backfill_checkpoints`. Plumbing: `connect(url=)`, `backfill_url()`,
`python -m tradebot.common.migrate --backfill`.

**Every parser reproduces a number a spike recorded by hand before it existed**: 1,229
bundle bodies with 23 order filings, 298 band hitters (181 high), CORP_IND XD 70 / XI 2 /
XO 1, BEL's market cap to the paisa, and the Nifty 50 close of 23,346.40. The day loader's
calendar logic is tested with a fake fetcher serving real fixture zips. A clean 404 on the
bhavcopy means no trading, and nothing more is fetched. An error leaves the day undecided,
so it is retried. A trading day whose bundle fails keeps its prices but stays retryable. A
bhavcopy carrying another date is rejected. The SQL has a rollback-only test against
`tradebot_backfill`, which skips until that database exists. 262 tests pass.

**One thing to verify before the full run:** what nsearchives returns for a holiday. The
calendar logic assumes a clean 404. If it answers 403 or a 200 HTML page instead, every
holiday would be retried as an error. One request against a known holiday settles it.

### 27 Sep 2026 (afternoon, cont.) — B2/B3: company universe and company-wise fetch; category-map draft

- `config/backfill.yaml`: window (D10), universe criteria and download scope. **The
  universe is refused while `universe.frozen_on` is null**, which makes D22's "fixed
  before any return" a checked condition rather than a promise. Every build writes the
  criteria and frozen date to `backfill_universe_meta` (migration 0008, with
  `backfill_universe` and `reconcile_days`).
- `backfill/universe.py`: companies from the last trading day on or before
  `universe.as_of` (series, `INE` ISINs only, market-cap bounds in crore), industry
  exclusions applied after the history is fetched, and `expected_counts()`. That last one
  counts the listed companies' order and catch-all filings from the PR bundles alone,
  before any download (§10's sequencing note).
- `backfill/announcements.py`: one `symbol=` query per symbol an ISIN traded under. A
  record under the same symbol with another ISIN is dropped, since that is another
  company that once used the symbol. A company is checkpointed only when all its queries
  succeeded. `reconcile_window()` runs `reconcile.py` per report date on the list and
  stores coverage in `reconcile_days`.
- **Checked on the real NSE archives the spikes left in `spikes/out/`** (six UDiFF zips,
  three PR bundles), not only the fixtures. All parse, including the 2025 bundle with its
  mixed-case, mixed-date-width member names. Corporate-action counts match §5.9 (XD 16 / 3
  / 70). Every NSE UDiFF row is `FinInstrmTp=STK`, so ETFs are excluded by the `INE`
  prefix, not the type. The mainboard company count is 2,134 (Aug 2025) to 2,572
  (Sep 2026).
- **`config/category_map.draft.yaml`**: a full router map drafted from 186 real categories
  (73 live plus the spike dumps), for Sravanth's sign-off under CLAUDE.md rule 5. Not used
  by any code yet. When unsure it picks other_material, not noise, which makes the clean
  sample smaller but never lets a results move be credited to an order. Judgment calls
  are marked `<- CALL`. The main ones: leadership changes kept material; unknown categories
  treated as material but not downloaded, which deviates from §5.4's "unknown ->
  catch_all" because D7's widening would otherwise download them; four additions to
  red_flag.

### 27 Sep 2026 (afternoon, cont.) — B6 (part): backfill document stage and the Batch API path

- `llm/client.py`: `budget="backfill"`, a single $3 cap across every purpose, measured over
  `llm_calls` in the backfill database **plus the worst-case estimate of every uncollected
  Batch**, because that money is committed before any `llm_calls` row exists. Also
  `extraction_body()` (so the live call and a Batch line send byte-identical requests),
  `model_for(tier)`, and `submit_batch` / `retrieve_batch` / `read_file` /
  `log_batch_result`. Batch cost is computed only from `batch_prices` in
  `config/llm.yaml`. That section ships empty, so batching is refused until Sravanth
  copies the prices in, and the 50% discount is never assumed.
- `extractor/llm_extract.py`: `interpret()` and `build_request()` split out, so a Batch
  result is judged by exactly the live call's rules: provenance, suspect scale, unknown
  judgment fields.
- `backfill/documents.py`: the backfill's document stage reuses the live
  `process_pending` unchanged. A `BatchDeferringClient` sends OCR to the real client (the
  recorded exception) and refuses extraction, which the pipeline already records as
  `pending_llm`. `pending_llm` is not retried here, so waiting on a Batch never
  re-downloads a PDF (`retry_statuses`, new in `orders/store.py` and `orders/run.py`).
  `expected()` counts downloads and GB before any are made.
- `backfill/batch.py`: `submit` (one request per `pending_llm` filing, chunked,
  cap-checked first) and `collect` (applies results; one retry with the error fed back,
  then `needs_review`; a failed or expired request is resubmitted at most three times).
  Migration 0009: `llm_batches`, `llm_batch_items`.
- `tests/unit/conftest.py`: a `scratch_conn` fixture that runs every migration into a
  throwaway schema in `tradebot_backfill` and drops it afterwards. Code that commits, as
  the backfill stages do on purpose, can then be tested against real SQL, which a
  rollback-only transaction cannot do. It never touches the live database.

**Not yet run against a real database:** the Batch round-trip tests
(`test_backfill_batch_db.py`) and the market store test skip until `tradebot_backfill`
exists. 265 pass, 4 skipped. The live processes have been down since about 12:55 IST,
waiting on Sravanth to restart them.

### 27 Sep 2026 (evening) — criteria frozen, D22 band revised, market load running

Sravanth did the setup: the three live processes restarted, `tradebot_backfill` created,
Docker Desktop started, the laptop on the phone hotspot. **The `BACKFILL_DATABASE_URL` line
never reached `.env`** (mtime still 24 Sep, the same way the password once failed to save
on 22 Sep). I added it by script, derived from `DATABASE_URL` with only the database name
changed, and never printed it. Migrations 0001-0010 were applied to the backfill
database, and all 269 tests pass, **including the 4 database tests that had been
skipping** (the market store, and the Batch round trip on real SQL in a scratch schema).

**Decisions, same conversation:**
- `tier2_model: gpt-6-luna` "for now"; he will name a stronger model later. So §6's recheck
  is a second, blind read by the same model. `batch_prices` for gpt-6-luna: $0.05 / $0.25
  per million input/output tokens.
- **Universe criteria** (his edit of `config/backfill.yaml`): market cap ≥ ₹200 cr on 22
  Sep 2025, no ceiling (large caps as a low-reaction control), EQ/BE/BZ, INE ISINs, no
  industry exclusions. Plus written rules in `universe.notes`: valuation at the last close
  before the filing, TTM by filing date, per-event liquidity, band and lock fields, Director
  and KMP changes as a separate confounder class, and hard exclusions. **Frozen by him:
  `frozen_on: 2026-09-27`.**
- **D22 revised before any return exists:** the primary band is ₹500–20,000 cr on the
  event's valuation date, replacing "below ₹10,000 cr". ARCHITECTURE D22 and §5.11 say so,
  dated. The full universe is also reported.
- **Locked at a circuit** = in that day's band-hitter file AND close equals the day's high
  (upper) or low (lower).
- **ASM/GSM stage and price band: spike a source today.** NSE's lists are current-only; to
  be run after the market load, keeping one request stream against NSE at a time.

**Consequences implemented:** `prices_from` moved to 2025-03-01, because the 120-trading-day
history exclusion and the 60-day median traded value need about 120 trading days before
the window, where D10 had 30. The bhavcopy's `TtlTrfVal` is now stored as
`prices.traded_value` (migration 0010), rather than approximated as close × volume.

**Probes and loads** (all over the hotspot): the holiday probe (2 Oct 2025) returned a clean
404, 2 requests with the warm-up, which confirms the calendar logic. The trial load of
19-22 Sep 2025 took 7 requests and gave 2 trading days and 2 weekend 404s. Only 458 bundle
lines were parsed for 19 Sep 2025 against 1,229 on 18 Sep 2026, so the bundle was
re-fetched (2 requests): the raw file really has 461 lines, 458 parsed plus the header and
2 wrapped continuation lines. The parser is right and that report is just shorter. **Full
load started**: 1 Mar 2025 to 26 Sep 2026, about 970 requests, log in
`data/market_load.log`.

**Later the same evening:**
- **The list criteria moved twice, both before any return existed.** Sravanth first saved
  ₹500-50,000 cr over his ₹200 cr / no-ceiling values; the build used that and gave 1,391
  companies. Asked which was frozen, he chose: **collect ≥ ₹500 cr with no ceiling;
  analyse ₹500-50,000 cr, primary ₹500-20,000 cr (D22), and report the companies above
  ₹50,000 cr separately as a control.** `config/backfill.yaml` now has separate
  `universe` (collection) and `analysis` sections to say so. The rebuilt list has **1,583
  companies**: 1,229 at ₹500-20,000 cr, 162 at ₹20,000-50,000 cr, and 192 above ₹50,000 cr
  (Reliance down).
- **His IDE save overwrote an edit of mine**: `prices_from: 2025-03-01` went back to
  2025-08-01 while he had the file open. It is restored. The running load was unaffected,
  because it takes its range from the command line. Lesson: when Sravanth has a config file
  open, tell him to reload before saving.
- **D12 closed: Linux cp314 wheels verified.** `docker build` succeeded (image 385 MB,
  Python 3.14.7, uid 10001, `ROOT=/app`, IST resolves, both prompts present). Unit suite
  inside the container: 259 passed, 8 skipped (no database there), 2 failed only because
  the layout test looks for `reports/` and `.env.example`, which `.dockerignore` excludes
  on purpose.
- **Angel One SmartAPI** (Sravanth asked whether it could supply past prices): not for
  this study. The bhavcopy is the exchange's own record and carries market cap,
  CORP_IND, band hits and traded value, which SmartAPI candles do not. Mixing sources
  risks two different "closes" for one day, and §1 keeps broker code out of Phase 1. Its
  real value is one-minute candles for measuring the reaction from the actual filing time,
  which §5.12 already lists as Phase 2.
- Market load running without errors; holidays (10 Apr 2025, Mahavir Jayanti) recognised
  correctly.
- **Category map approved and in force** (Slice 3's map). Sravanth said "Okay" to the
  draft; his rule 4 moves Director/KMP changes into a new `leadership` bucket, a separate
  confounder class reported with and without, instead of other_material. Auditor changes
  stay other_material, since they are not Director/KMP. `config/category_map.yaml` now
  holds 146 categories: order_win 1, order_candidate 1, red_flag 7, catch_all 4, results
  8, other_material 56, noise 52, leadership 17. The draft file is deleted. Matching is now
  case-insensitive, because the live feed has "General updates" 8 times, which the old
  map missed. `bucket_of()` gives any filing's bucket, or "unknown" for an unlisted
  category, which counts as other news for contamination and is never downloaded. **Live
  effect** once processes restart: "General updates" and "Press Release (Revised)"
  filings now reach the order pipeline.

### 27 Sep 2026 (evening, cont.) — calculator and event study built (pure, tested)

- `calculator/materiality.py` (§5.10): `value_to_ttm`, `next12m_to_ttm` (a 24-month order
  counts half, a 6-month one is not doubled), `value_to_mcap`, and flags `manual_review`
  (> 1× TTM), `suspect_parse` (< ₹1 lakh), `missing_ttm` and `missing_mcap`. Ratios are
  quantized to 6 places. `execution_months()` also reads a completion month ("Delivery
  Completion is November, 2026") counted from the filing date, as §5.7 asks.
- `backfill/event_study.py` (§5.11, D22 as revised, Sravanth's rules): day 0 (before 15:30
  on a trading day, else the next); **valuation date = the trading day before day 0**,
  which satisfies both §5.10's "last close strictly before the filing" and his "never the
  event day's own close". Excess returns from the day-0 close against the Nifty 50 at
  +1/+3/+5/+10, and pre-event drift at −5/−20. An after-hours next-open variant, whose
  index leg starts from the prior close because only Nifty closes are stored; that
  approximation is recorded in the code. Hard exclusions (rule 5): no price on day 0, not
  mainboard on day 0, under 120 trading days of history, no price for the window, and
  window incomplete in the loaded data. Capital actions XB/XS/XR/XO in [−20, +10] exclude
  the event and are reported; XD is tagged. Contamination is other news within ±3
  trading days in buckets results, other_material, red_flag, order and catch_all
  categories, or unknown. **Leadership is its own tag, not contamination** (rule 4).
  Other fields: locked upper or lower on day 0..+3 (band hit AND close at the high or
  low); tradeable = entry fillable at the day-0 close; median traded value over 60 days;
  volume ratio (Muhurat days excluded from the baseline); days since the previous order.
  The **verdict is D22 verbatim**: at least 30 clean events in the primary cell, median and
  mean both beating the 0.75% hurdle, and the same sign in both halves. A half with no
  events fails that last check, so it is NO-GO, not GO.
- 20 new tests on a hand-built 200-day market with known answers. 293 pass.
- **Events and the §6 recheck** (migration 0011: `backfill_events`, `event_results`,
  `unknown_categories`). `backfill/events.py` merges verified extractions into events on
  §5.3's exact keys only (the same attachment SHA-256, or the same ISIN and value), never on
  headline similarity. Filings with no value are never merged on value. The event time is
  the earliest filing. Recipient comes from the extraction, or from the category for
  "Bagging/Receiving of orders"; otherwise it is unknown and kept out of the primary cell.
  `next_state()` implements §6 trigger 4: value ≥ 15% of market cap, or market cap or TTM
  unknown, goes to `recheck_pending`. `backfill/recheck.py` runs a blind tier-2 re-read
  through Batch: agree becomes verified, disagree becomes needs_review, and it runs at most
  once plus one retry. The extraction collector now only reads its own batches (purpose
  filter), so the two Batch users never cross. 301 tests pass, including both recheck round
  trips on real SQL.
- **TTM, loader, report and the backfill command.** `revenue/ttm.py` (pure) implements
  §5.8 and rule 1: only results filed before the moment count, one basis only, Q4 = FY −
  9M, four consecutive quarters or None, and a restatement applies only from its filing
  date. `backfill/study_data.py` loads the market and events: point-in-time TTM per
  event; the company's own other filings within ±10 calendar days, with unknown
  categories logged to `unknown_categories`; the previous order's time.
  `backfill/report.py` writes `reports/backfill_<date>.md` with the verdict and D22's four
  checks first, then the power note, sensitivity cells (without leadership, tradeable
  only, the ₹500-50,000 universe, the >₹50,000 control, contaminated), the exploratory
  value × market-cap grid at +1/+3/+5/+10, and every exclusion counted. It also writes
  a per-event CSV. `backfill/__main__.py` runs the stages one pass at a time, from
  `universe` through `study`, plus `status`. The event study's primary cell now also
  requires the company to have **won** the order: I caught that it was missing while
  wiring the loader. Migration 0012: `financials`. `config/backfill.yaml` gains
  `analysis.muhurat_days: [2025-10-21]`, to be checked against the loaded calendar.
- **End-to-end check on real SQL** (scratch schema, one synthetic company): an order worth
  20% of market cap is `calculate`d to `recheck_pending` with TTM ₹1,000 cr, and a quarter
  filed after the event is ignored. `study` writes the report (INSUFFICIENT DATA, n = 1,
  +10.00%). **My first version of this test was wrong and the code was right**: I had
  seeded two quarters filed after the event, and TTM correctly came back unknown.
- **D27 verified on real data: the Muhurat session needs no special case.** 21 Oct 2025
  loads as a trading day with about a fifth of a normal day's traded value (₹19,407 cr
  against about ₹1 lakh cr), which fits a one-hour session. 22 Oct (Balipratipada) is
  correctly closed. `analysis.muhurat_days: [2025-10-21]` is confirmed.
- **Offline findings before Spike C** (no requests):
  - Spike A's saved BEL history shows that results announcements ("Financial Result
    Updates", "Integrated Filing- Financial") attach signed **PDFs**, not XBRL, so the XBRL
    must come from NSE's results API. Their announcement timestamps are the exact
    `filed_at` that point-in-time TTM needs, and the company-wise fetch stores them anyway.
  - The saved PR bundles hold 14 members. Besides the four in use, `bc<date>.csv` is a
    corporate-actions file (SERIES, SYMBOL, RECORD_DT, EX_DT, PURPOSE, with bonus and split
    ratios in the text). That is a better capital-action detector than CORP_IND alone and
    answers §11's open "full CORP_IND code list" item. It is **not used yet**: the Phase 1
    rule stays exclude-not-adjust. Nothing in the bundles carries price bands or ASM/GSM,
    so that spike needs requests.
- `revenue/xbrl.py`: the revenue parser §5.8 asked for. Every revenue fact is read with its
  context's start and end dates and the period length is computed from the day count;
  context names are never trusted (a test uses a deliberately misleading one). The most
  specific revenue element wins and elements are never mixed. A non-INR unit is refused.
  To be checked against real files in Spike C. `spikes/spike_c_results_xbrl.py`: budget 14,
  one persisted counter, warm-ups counted.
- **Keep-alive fix verified live.** The collector restarted at about 14:30 with the fix.
  Every 10-minute poll since then has succeeded: six in a row, 14:39-15:29, 0
  `ConnectionResetError`, against 34 of 61 failures on 26 Sep. `orders --follow` was
  **not** among the restarted processes (collector and sheets only), and Sravanth was asked
  to start it.
- ARCHITECTURE §10 now marks Slices 1 (backfill half), 2, 3, 5 (Batch and §6), 7 and 8 as
  built, and 6 as partly built (TTM and parser; the fetcher waits on Spike C).
  `spikes/spike_band_asm.py` (budget 8) is ready for the price-band and ASM/GSM question.
- **Cutover rehearsed on the laptop with the real image** (DEPLOY.md §3, nothing sent to
  NSE or Google). A throwaway Postgres 16 container on its own network got the same
  one-time setup. `pg_dump` of the live laptop database was 2.6 MB. The restore **through
  compose's `backup` service**, exactly as the runbook says, gave 3,256 filings, 494
  extractions, 488 documents and 129 sheets_sync rows. Then migrate in a `collector`
  container, and the health check inside the container ("healthy", last poll 15:39 IST).
  The **append-only trigger survived the restore** and refused a delete. Everything was
  removed afterwards. Two things learned: (1) migrate applied up to 0010 only, because the
  image predated 0011/0012, so **build before migrating**, which DEPLOY.md already
  orders; (2) my rehearsal script echoed commands, which printed the throwaway passwords
  of the deleted rehearsal container (no real credential; `DATABASE_URL` was never
  printed). `docker-compose.yml`'s `env_file` is now `${TRADEBOT_ENV_FILE:-.env}` so a
  rehearsal can use a throwaway file; production is unchanged.
- **Decision: the laptop collector pauses during the company-wise fetch** (about 1,600
  `symbol=` requests, roughly 2 h), so only one stream at a time hits the announcements API.
  Sravanth stops it and restarts it afterwards; its gap query recovers the evening's filings
  (a Sunday, so few), with the catch-up time as `first_seen_at`. Order of NSE work tonight:
  finish the market load, then Spike C, then the band/ASM spike, then the company-wise
  fetch, one after another.

### 27 Sep 2026 (evening, cont.) — Spike C done: a real XBRL defect found and fixed

Market load finished clean: 575 calendar days, 386 trading days, zero errors, 958
requests, 1.26M price rows.

**Spike C, 14/14 requests, all against the older "Financial Results" endpoint**
(`GET /api/corporates-financial-results?symbol=&period=Quarterly`, confirmed working; real
XBRL links from 2018 onward for BEL, "-" placeholders before that). One untracked pair of
requests (a warm-up and a date-range retry, sent from an ad-hoc script instead of the
tracked one) was caught and folded into the shared counter - the exact mistake the WORKLOG
gotcha about Spike A's budget exists to prevent, repeated and caught in the same session.

**The post-April-2025 "Integrated Filing" API endpoint is still unknown.** Two guesses by
analogy with the announcements endpoint both 404'd (`/api/integrated-filing`,
`/api/corporate-integrated-filing`). Per the BSE lesson (WORKLOG, 22 Sep: "guessing an
undocumented API shape cost two requests for nothing"), a third guess was not spent. Needs
a browser's network tab on NSE's live Integrated Filing page - Sravanth's to do, or to hand
to a session with browser access.

**A real, demonstrated XBRL defect, not a synthetic worry.** `revenue/xbrl.py` originally
read a fact's period from its `<context>` element's own dates only, exactly as §5.8
specified. Real BEL filings break that two distinct ways: a Jan-2025 filing's cumulative
context ("FourD") declares the *same* dates as the discrete quarter's context ("OneD") - a
template copy-paste bug - while its revenue (₹146.19bn) is plainly nine months' worth
against the quarter's ₹57.7bn; and a 2018 filing's revenue facts reference
`contextRef="OneD"/"FourD"` where **no such `<context>` element exists in the file at
all**. Both filings correctly tag `DateOfStartOfReportingPeriod`/
`DateOfEndOfReportingPeriod` facts next to the revenue figure, and those are right in both
cases, so the parser now reads a fact's period from these declared elements first, falling
back to the context's own dates only when neither is present. Also fixed in the same pass:
`NatureOfReportStandaloneConsolidated` was read as one global value for the whole file;
it's a per-context fact, and a filing with both standalone and consolidated contexts would
have stamped every fact with whichever was seen last. Regression tests reproduce both real
defects verbatim (`tests/unit/test_xbrl.py`).

**End-to-end proof, real numbers.** BEL's FY24 Q3 filing gives a real 9-month cumulative
figure (₹117.04bn); its Q4/FY filing gives the real full year (₹202.68bn) and its own
directly-reported Q4 (₹85.64bn). `FY − 9M` = ₹85,640,800,000.00 - **an exact match, to the
rupee**, against BEL's own reported Q4. Point-in-time TTM logic (`revenue/ttm.py`) was
already unit-tested against synthetic data; this is the confirmation that the numbers it
will be fed are read correctly from a real, messy filing. ARCHITECTURE §5.8 and §10
updated. 314 tests pass.

**`revenue/load.py`** (the fetcher `backfill/__main__.py`'s `revenue` stage imports) is
**not yet built** - Spike C answered the parsing question; wiring it to the per-company
fetch, writing `financials` rows and handling the still-unknown Integrated Filing endpoint
is the remaining work.

### 27 Sep 2026 (evening, cont.) — price-band/ASM spike: bands solvable, ASM/GSM not

8/8 requests. `sec_list.csv` gives every symbol's current price band; more usefully,
`eq_band_changes_{ddmmyyyy}.csv` is a **daily change log** ("From","To"), confirmed live
for three dates a year apart (19 Sep 2025, 22 Sep 2025, 1 Sep 2026), all real rows.
Reconstructing history means walking it backward from a known snapshot, one request per
calendar day - not built tonight, since it doesn't block D22's verdict (`locked` already
comes from the `bh` band-*hit* file) and the budget went to confirming the mechanism
generalises rather than guessing further. `reportASM`/`reportGSM` return real current-stage
JSON but no historical file was found; falls back to Sravanth's own default, null + flag
per event. ARCHITECTURE §11 updated with both findings.

**Collector confirmed stopped** before the next step: no tradebot process is running.
Starting the company-wise announcements fetch now (~1,583 symbol= queries, one per company
in the frozen universe, at the backfill pace - a couple of hours).

### 27 Sep 2026 (evening, cont.) — revenue/load.py built; three real bugs caught before running

Built the fetcher `backfill/__main__.py`'s `revenue` stage needs: `revenue/load.py`, one
`corporates-financial-results` listing call per company (the endpoint Spike C confirmed),
one XBRL download per filing with a real link. `NseClient` gains `fetch_results_listing`
and `_get_json` now takes an `endpoint` name instead of always hitting the announcements
URL (`config/sources.yaml` gains `nse.results`).

**Three real bugs caught by re-reading the draft against the actual APIs it calls, before
any request was sent:**
1. `_get_json` was hardcoded to the announcements URL. Calling it with `period=Quarterly`
   would have silently queried the *announcements* endpoint with a stray extra parameter,
   never the results endpoint at all.
2. The draft called `fetcher.fetch(xbrl_url, work_dir=None)` - a `PdfFetcher`-shaped call
   (writes to disk, checks for a `%PDF` magic header) on an `ArchiveFetcher`, which has no
   such method and returns bytes in memory, not a path. An XML file would have failed the
   magic-byte check outright had this been PdfFetcher, or crashed on the wrong method name
   as written.
3. `NseClient` has no minimum-gap pacing of its own (only idle-reconnect) - the caller
   supplies it, as `backfill/announcements.py` already does. The draft's `run()` looped
   over companies with no delay between listing calls at all, which would have hit the
   results endpoint far faster than the backfill pace allows.

All three fixed before the first real request; 7 new offline tests
(`tests/unit/test_revenue_load.py`) exercise the fetch/skip/checkpoint logic with fakes for
both NseClient and ArchiveFetcher. 321 tests pass.

**Announcements fetch running cleanly**: 69/1,583 companies at 0 failures as of 18:20 IST,
on pace for the ~2.5h estimate.

### 27 Sep 2026 (evening, cont.) — review pass on backfill/__main__.py: two real bugs fixed

Used the announcements fetch's runtime to re-read the day's stage wiring end to end rather
than wait idle. Two real issues found and fixed, no new tests skipped:

1. **`study()`'s window filter had an operator-precedence bug.** `if r.day0 and since <=
   r.day0 <= until or r.day0 is None` parses as `(r.day0 and in-range) or (day0 is None)` -
   so an event whose day0 genuinely fell outside the window (correctly resolved, just
   before/after it - the announcement fetch's ±45-day margin exists exactly to catch these)
   was dropped as intended, but an event whose day0 could **not** be resolved was kept
   regardless of whether its underlying filing was ever inside the window at all. Not
   fatal - `primary()`'s own checks mean such an event could never enter the primary cell -
   but it would have inflated the reported event count and confused the exclusion tally.
   Replaced with `events_in_window()`, which filters on the **filing's own timestamp**
   before `measure()` ever runs, so a margin-only filing is dropped outright and an
   in-window filing that fails to resolve a day0 still shows up as a counted exclusion.
2. **The `documents` stage never checked `gate_violations`.** §5.4's hard invariant -
   nothing reaches OCR or the LLM without `llm_allowed` saying so first - is checked and
   enforced (exit 2) on the live path (`orders/__main__.py`) but was silently ignored in
   the backfill's own `documents` stage, even though both call the identical
   `process_pending` and the same `Summary.gate_violations` field. Fixed to log and exit 2,
   with the rest of the summary still printed first so the failure is diagnosable, not just
   flagged.

4 new offline tests (`tests/unit/test_backfill_main.py`). 325 pass.

Announcements fetch still clean: 123/1,583, 0 failures, 18:24 IST.

### 27 Sep 2026 (evening, cont.) — a third real bug found reviewing study_data.py

**Contamination detection was trusting `raw_announcements.isin` alone**, unlike
`backfill/events.py`'s own event-building query, which already falls back to symbol via
`instrument_symbols` because Spike A found `sm_isin` is not 100% populated (null for
HILINFRA). A company's other filing with a null isin would have been silently invisible to
the "another filing within ±3 trading days" check, understating contamination in exactly
the direction that makes a study look cleaner - and therefore more GO-favouring - than it
really is. Fixed: the lookup now matches on isin, falling back to symbol only when a row's
own isin is null. 3 new tests on real SQL (`tests/unit/test_study_data.py`), including one
confirming a null-isin row for a *different* symbol is correctly never matched. 328 pass.

Announcements fetch: 150/1,583, 0 failures, 18:27 IST.

### 27 Sep 2026 (evening, cont.) — richer per-event detail built; a real endpoint capture, still incomplete

**Price band, built end to end** (Sravanth: "let's get the richer per-event detail"):
`src/tradebot/market/bands.py` reconstructs any symbol's exact band (2/5/10/20%) on any past
date, walking NSE's daily `eq_band_changes_{ddmmyyyy}.csv` change log backward from the
current `sec_list.csv` snapshot. Confirmed live that a day with no changes gives a clean
HTTP 404 (checked on two Sundays), not an empty 200 - the loader treats that as "checked,
nothing published," matching D27's own past-date pattern. Migration 0013
(`band_snapshot`, `band_changes`, `band_days`). Wired into `EventResult.price_band`, set
once per event as of day 0 by `study()` after `measure()` runs - a targeted lookup, kept
out of `event_study.py` so that module stays a pure function of `Market` with no database
of its own. 5 new tests, one of which caught a real issue before it ran: `reconstruct()`'s
first draft matched `(symbol, series) = any(...)` in SQL, which needs an array of Postgres
composite rows that a Python list of tuples does not reliably adapt to - fixed to filter by
symbol alone in SQL and narrow to the exact pair in Python. The real fetch is running now
(started 18:49, background, 575 calendar days including weekends since a band change is an
exchange notice, not tied to a trading day; 40 done as of 18:52, 0 errors). 333 tests pass.

**Sravanth sent a real cURL capture for the Integrated Filing endpoint.** It reveals a
genuinely new, previously unknown detail endpoint,
`https://www.nseindia.com/api/corporates-financial-results-data`, which takes a `params`
string and `seq_id` copied directly from a `results` listing row (recorded in
`config/sources.yaml` as `nse.results_detail`, called only with values a listing row
already supplied, never constructed from scratch). **But the captured example was
Reliance's Q3 FY25 (Oct-Dec 2024), filed around January 2025 - before the April 2025
cutover** - so it confirms a detail endpoint exists without yet proving anything reachable
past the cutover. Asked him for one more capture, this time of a quarter filed after April
2025 (Q1 FY26 or later). Deliberately did not test this myself: `corporates-financial-
results`/`-data` are both on `www.nseindia.com`, the same host the announcements fetch is
actively polling right now, and running a second request stream there at the same time
would break the one-request-at-a-time rule the whole night has held to. Verification waits
until either he sends another capture or the announcements fetch finishes and frees the
host.

### 27 Sep 2026 (night) — the fetch stopped with the session; 17% of companies were silently empty

**Both background jobs died when the previous session ended**, with no error logged: the
company-wise announcements fetch at 18:59:59 (495 of 1,583 companies checkpointed) and the
price-band fetch right after it started. Both are resumable from their checkpoints.

**Found before resuming: 85 of the 495 fetched companies (17%) had kept zero filings**,
including HDFCBANK, SBIN, ICICIBANK, SUNPHARMA, HAL and TATASTEEL. The API had returned
data for every one of them (ASTRAL 1,214 rows, JSWSTEEL 2,080); `select_records` threw all
of it away. Cause: **NSE's announcements API tags every filing with the company's
original ISIN, while the bhavcopy (and so the universe) carries the current one**, which
NSDL reissues after a face-value split. JSWSTEEL is `INE019A01020` in announcements and
`INE019A01038` in the bhavcopy. The filter's premise, "another ISIN under the same symbol
is another company", is false for exactly these companies. Measured with no requests,
against the live database: 65 of 65 zero-kept companies that also appear in the live feed
show this mismatch; 294 of 294 working companies match exactly; 0 companies that kept rows
also file under a second ISIN of the same issuer. Of 253 mismatches in the whole live feed,
250 share the first 9 characters (issuer code + `01`, equity shares) and 3 (HUDCO, IREDA,
IRFC) share only the first 7, being the same issuer's bond ISINs. No two universe ISINs
share an issuer code.

**The same mismatch would have broken three later stages, silently**: `events.py` stamped
events with the filing's own ISIN, so prices and market caps (keyed by the current ISIN)
would never be found and every order from these companies would have been excluded as
"no price on day 0"; `study_data.py`'s contamination lookup would have found none of their
other filings; `latest_industry` never set their industry. This reverses ARCHITECTURE
§5.3's "attach ISIN from the announcement's own `sm_isin`" for any join against market
data.

**Fixed, one rule everywhere**: `src/tradebot/common/isin.py` defines "same company" as the
same issuer code, the ISIN's first seven characters (`left(isin, 7)` in SQL). Applied in
`announcements.py` (`select_records`, `latest_industry`), `events.py` (the event takes the
universe's ISIN, by issuer code, or by symbol only when the filing has no ISIN),
`study_data.py` (contamination) and `documents.py` (the industry-exclusion check).
`raw_announcements.isin` is untouched and still stores what NSE sent. The checkpoint's
per-symbol detail now also records `other_issuer`, the rows dropped as another company, so
a filter that empties a company is visible directly next time. 5 new tests, each confirmed
to fail on the old code; 338 pass. ARCHITECTURE §5.3 records the reversal.

**Residual risk, stated**: the live-feed check covers 294 of the 410 companies that kept
rows. The other 116 can't be checked without re-fetching them. Nothing suggests a company
files under two ISINs of its own (0 of 294 did), so they are not re-fetched.

**Resumed 19:21 IST** as detached processes (PIDs 7568 and 30868; logs
`data/announcements_resume.log` and `data/bands_resume.log`), on the `POCO X7` hotspot
(D19). The first re-queued companies now keep what they should: ASTRAL 91 filings,
JSWSTEEL 170, ASIANPAINT 121, where each had 0.

### 27 Sep 2026 (night, cont.) — the results capture again: valid, but pre-cutover

Sravanth sent a cURL capture of `corporates-financial-results-data`. It is the same
request as the evening's: Reliance, `params=01-Oct-202431-Dec-2024Q3UNNNNERELIANCE`,
`seq_id=1189823`, the Oct-Dec 2024 quarter, with the referer
`/companies-listing/corporate-filings-financial-results` (the old "Financial Results"
page). The request shape is correct and matches `nse.results_detail` in
`config/sources.yaml`, but it cannot reach past the cutover, checked offline with no
requests:
- Spike C's saved BEL listing (`spikes/out/spike_c/listing_BEL.json`, 107 rows) **ends at
  Oct-Dec 2024, filed 30 Jan 2025**. The detail endpoint only takes `params`/`seqNumber`
  that a listing row supplies, and every such row already carries an `xbrl` link, so it
  adds nothing the parser doesn't already get.
- **Every event, not most, needs post-cutover quarters**: TTM on 22 Sep 2025 (the window's
  first day) needs Q4 FY25 (via FY − 9M, filed Apr-May 2025) and Q1 FY26 (filed Jul-Aug
  2025). Without the Integrated Filing endpoint, TTM is null for all events. §6 trigger 4
  then sends every event to recheck, and the primary cell (`value_to_ttm` ≥ 15%) is
  empty, so the verdict would be INSUFFICIENT DATA regardless of returns.
- The 61 "Integrated Filing- Financial" announcements stored so far all say `hasXbrl:
  True` but attach PDFs. The XBRL is reachable only from the Integrated Filing page.

The capture's session cookies were not written anywhere. Asked for a capture from the
Integrated Filing page itself, for a quarter from Apr-Jun 2025 onward. Not tested live
either way: the host is busy with the announcements fetch (one stream at a time).

### 27 Sep 2026 (night, 22:00) — fetch nearly done; timeouts and three truncated answers

**Band history finished** at 19:50: 420 days, 0 errors, 421 requests (575 of 575 days
now in `band_days`).

**Announcements, as of 22:00**: 1,121 of the 1,173 re-queued companies processed, 1,487
checkpointed in all. **59 failed**, 55 of them `ReadTimeout` at 45 s plus 2 read timeouts
and 2 connection resets. **No 401/403 at all**, so this is slowness, not a block. They
cluster between 20:30 and 21:20 (12-13 per ten minutes) and then taper off, which points
at the hotspot or NSE's evening load. A failed company is never checkpointed, so
re-running the stage retries exactly these.

**Three companies got a truncated answer that counted as a success**: ABBOTINDIA (the
API returned 0 rows), BAYERCROP (2) and MCX (4), each with `other_issuer: 0`, so the
filter was not the cause. All three have histories of years. They are clear outliers:
the median company returned 675 rows (96 kept) and the next-lowest returned 40
(RNBDENIMS, plausibly a recent listing). They are re-queued by hand. A thin response is
not treated as a failure in code, because there is no objective row count below which a
company's history is "wrong"; the checkpoint's `returned` count is what makes it visible.

### 27 Sep 2026 (night, 22:15) — fetch complete; a second face of the ISIN problem

**Announcements fetch complete.** The retry run (22:06-22:12, 62 requests) fetched all 59
timed-out companies with 0 failures. `backfill status`: 1,583 of 1,583 companies,
162,251 filings, 0 report dates below 95% coverage.

**The three thin companies are empty for real, not truncated.** Re-fetched, they returned
exactly the same counts (ABBOTINDIA 0, BAYERCROP 2, MCX 4, none in the window), and the
PR bundles, NSE's complete daily record, have **no line for any of them in the whole
window**, searched by symbol and by company name. Two independent NSE sources agree. Best
guess, **not verified**: they are listed on BSE and only permitted to trade on NSE, so they
file with BSE (MCX has been BSE-listed since its 2012 IPO). Under D26 they simply
contribute no events. Whether to mark them excluded in `backfill_universe` is Sravanth's
call; left unchanged.

**New: 38 universe companies were issued a new equity ISIN during the window**, e.g. BEML
(`INE258A01016` → `INE258A01024` on 3 Nov 2025), KOTAKBANK (14 Jan 2026), MCX (2 Jan 2026),
CAMS, ANGELONE, NUVAMA, TDPOWERSYS. They are the same issuer and security type (first 9
characters), trading under the same symbol, one ISIN ending the day before the next
begins. This is the market-data side of the 19:00 finding. The universe holds the ISIN
as of 22 Sep 2025, and `study_data` loads prices and market caps by that ISIN, so
**every event after a reissue would find no price and be excluded**, as would any event
whose window reaches past it. These 38 companies filed 27 `Bagging/Receiving of orders`
filings in the window, against D22's floor of 30 clean events, so this is not a rounding
error. (Another 20 same-issuer lines are rights entitlements, `-RE` symbols with security
type `20`, which trade for a week alongside the main ISIN and are not the same thing.)
48 universe ISINs have no price in the data's last week, which is consistent with this
plus a handful of delistings and mergers.

**Not fixed yet, because the fix is a design choice.** The obvious fix is to load a
company's prices across every ISIN with its issuer code and security type `01`. But prices
are unadjusted, so the switch day is exactly a split's price discontinuity, and it is not
known whether `CORP_IND` flags a split on the new ISIN's first day. Merging the series
without also treating the switch as a capital action (excluded under §5.9's
exclude-don't-adjust rule) could turn a 1:2 split into a fake −50% return. Proposed to
Sravanth: merge by the 9-character prefix, and treat the first day of a new ISIN as a
capital action in the window. It only matters at the `study` stage, so nothing before it
is blocked.

### 27 Sep 2026 (night, 23:00) — exclusions, reconcile, Spike C2 and the revenue loader

Sravanth's answers to the 22:15 questions: restart the live processes later (he will);
**yes** to the ISIN-reissue proposal; **exclude** ABBOTINDIA, BAYERCROP and MCX for now;
**run** reconcile. He also sent a capture from the Integrated Filing page.

**Exclusions are config, not a database edit.** `config/backfill.yaml` gains
`universe.exclude_companies` (ISIN -> reason), and `universe.apply_exclusions` (was
`apply_industry_exclusions`) re-applies it with the industry list after every `universe`
and `announcements` run, so a rebuild cannot silently drop it. The three are now excluded
("by hand: ..."). **A latent bug fixed on the way**: the old function read
`exclude_industries` from the `universe:` section, but the config has it under
`analysis:`, so any industry exclusion would have been ignored. The list is empty, so
nothing changed. Lesson from 27 Sep evening still applies: if Sravanth has
`config/backfill.yaml` open, he should reload it before saving.

**Reconcile ran: 86 of 246 report dates below 95%, but mostly our window model, not the
API.** Measured (database only):
- The ±1-day window is wrong after weekends and holidays. The PR bundle for a date covers
  everything since the previous report, so Monday's bundle holds Friday evening and the
  weekend (RVNL disseminated Sat 20 Jun 09:00 and ZAGGLE Fri 19 Jun 17:55, both in
  Monday 22 Jun's bundle, which matched 0 of 13). Spike A2 tested a Friday, where ±1
  happens to be right. With the window "previous report date .. report date", order-filer
  coverage goes from **81.9% to 95.9%** and below-floor days from 86 to 44. 44 of the 86
  failing days had a 3-day gap to the previous report.
- The offset histogram counts every in-window API order filing of a matched company,
  including a separate next-day filing, so its +1 counts (95) do not by themselves mean the
  window is wrong. And it cannot show a too-narrow window at all, since it only sees
  matches inside it.
- **Symbol changes**: the API files a company's whole history under its current symbol
  (LTIM's 153 filings sit under `LTM`, ARISINFRA's under `ARIS`; the old symbol returns 0),
  while older bundles use the old one. Reconcile matches on symbol, so it misses them. This
  answers §5.1's Verify item: the current symbol's query covers filings under earlier ones.
- **Category mismatch between NSE's two sources**: the rest are mostly bundle lines
  "Bagging/Receiving of orders/contracts (Sub-para 4-Para B)" whose API record is
  "Updates"/"Press Release" (CAPACITE "Work order", HGINFRA "declared as L-1 bidder",
  CENTENKA). These are catch-all filings, which D7 downloads and the prefilter catches, so
  they are reachable by the pipeline, just not counted as matches.
- **Fix pending** (next): window from the previous report date, companies matched by ISIN
  rather than symbol, and a separate count of bundle orders found only under a catch-all
  category.

**Spike C2: the Integrated Filing endpoint, 6/8 requests.** `spikes/spike_c2_integrated_filing.py`,
one persisted counter, warm-up counted. `GET /api/integrated-filing-results` answers a
warmed-up script; `issuer` is not needed (identical 8,901 bytes without it); BEL has 12
rows, 31-Mar-2025 to 30-Jun-2026, both bases, all `type_Sub: Original`. The three
consolidated XBRLs downloaded parse unchanged: Q1 FY27 ₹55,469,800,000 (matches
Sravanth's check); FY26 − 9M = ₹102,244,300,000 = the Q4 BEL's own filing states. The
three files are committed as `tests/fixtures/xbrl/` for a permanent regression test.
Sravanth's note said the file was ~300 KB; the XBRL is 19 KB (the ~300 KB is presumably
the iXBRL HTML view).

**`revenue/load.py` rewritten to use both listings**, with three problems in the old
version fixed before it ever ran:
1. It ignored `window.results_from` and would have downloaded every filing back to 2018,
   both bases: about 50 files per company, ~79,000 requests (~66 h) for the universe. Now
   only quarters ending on or after 1 Sep 2024: about 18 requests per company.
2. It counted only the listing call against `--max-requests`, never the XBRL downloads.
   Now every request counts, and a company is not started unless 18 more fit.
3. It checkpointed a company even when some downloads failed, leaving a quarter silently
   missing (TTM null). Now a failed download leaves it to be retried.
Also: a company is queried under its **latest symbol by issuer** (LTIM -> LTM, SABTNL ->
AQYLON), a truncated integrated listing (totalCount > rows) is logged and recorded in the
checkpoint, and a revised filing counts from the later of `broadcast_Date` and
`revised_Date`. **Decision taken, to be confirmed by Sravanth**: only companies with a
backfill event are fetched, since TTM feeds nothing but event ratios; the stage therefore
runs after `events`, as `backfill/__main__.py` already orders it.

### 27 Sep 2026 (night, cont.) — ISIN reissues handled; reconcile corrected to 96.6%

**ISIN reissues (Sravanth: "okay let's do what you have said").** `study_data.load_market`
reads a company's prices and market caps under every ISIN sharing its first nine
characters and files them under the universe ISIN. Checked on the data first: **no company
ever trades under two ISINs on the same day** (0 overlaps), so no tie-break rule is
needed. **NSE flags most switch days itself**: 43 of the 57 switches in the loaded prices
carry `XO` (splits: BEML ₹4,399.80 → ₹2,187.00, KOTAKBANK ₹2,133 → ₹421, MCX, SABTNL) or
`XB` (NAZARA's bonus), both already capital actions. **14 carry no flag** (13 of them
between Mar and Jul 2025, now joined as price history, and INE0Y8W01017 on 23 Apr 2026),
which is why the approved marker matters: the first day under a new ISIN gets `NEW_ISIN`,
added to `event_study.CAPITAL_ACTIONS`. On real data BEML and KOTAKBANK now have all 388
trading days instead of stopping at the switch. Rights entitlements (security type 20)
have a different prefix and are never mixed in. 2 new tests.

**Reconcile corrected** (`reconcile.py`, `announcements.reconcile_window`, migration
0014): the window runs from the previous report date to the report date (a filing dated
after the report is never a match); companies are matched through the universe ISIN via
`company_map` (symbol -> ISIN over every symbol a listed company traded under, ambiguous
symbols left out); and order filers the API holds only under a catch-all category are
listed per day in `catch_all_only_symbols`, not counted as matches. The 95% gate is
unchanged. **Result: 96.6%** (1,301 of 1,347 order-filer company-days), 35 days below
95%, offsets spread over −4..0 as the model predicts. Of the 46 unmatched: 35 have a
catch-all filing from the same company in the window; 8 are "(Sub-para 4-Para B)"
lines repeating an order the API already holds from a few days earlier (MARINE on 23 Jun
and 4 Sep, then Para B lines in the 25 Jun and 8 Sep reports); **3 are unexplained**
(ASIANENE 1 Jul, HBLENGINE 15 Jul, WAAREERTL 7 Aug 2026). 4 new tests from these real
cases. ARCHITECTURE §5.11 records the change and the run, §5.9 the reissue rule, §5.1
the answered symbol-history Verify item.

Migration 0014 was applied to both databases. **The live database also received 0013**
(band history tables) for the first time; they are empty there, which is expected, since
band history is loaded only into the backfill database.

351 tests pass.

### 27 Sep 2026 (night, cont.) — revenue scope confirmed; the documents stage priced

**Decided (Sravanth): the revenue stage fetches event companies only**, as built in
`revenue/load.py`. It therefore cannot run alongside `documents`: the order is
`documents` -> `batch-submit`/`batch-collect` -> `events` -> `revenue`. What can run
alongside `documents` is the live collector (www.nseindia.com versus nsearchives, the same
split as tonight's band fetch next to the announcements fetch); parallel downloads within
`documents` are ruled out by the one-request-per-source rule.

**The download choice deferred on 27 Sep (see the audit entry: every catch-all PDF is ~35
GB and 35-40 h over the hotspot, and ~1 order in 4 was visible only in the PDF body) is
now measured**, database only: 33,784 PDFs to download, of which 1,385 are order
categories (1,258 order_win, 127 order_candidate) and 32,399 catch-all; 753 of the
catch-all have a headline keyword hit. Restricted by company:
- catch-all from companies at ₹500-50,000 cr on 22 Sep 2025: 25,061 (so the >₹50,000 cr
  control group alone accounts for ~7,300); at ₹500-20,000 cr (D22's band): 21,263;
- catch-all from companies that filed any order-category filing in the window: 5,277.
  **Rejected as a filter**: of the 7 live orders found only in a PDF body, it keeps 2
  (SILVERTUC, ASHOKA). DREDGECORP and HMT are in the band and never file under the order
  categories; DHRUV and AASTHA are outside the universe; POWERGRID is in the control group.
Put to Sravanth: everything (~33 GB), everything except the control group's catch-all
(~26 GB), or order categories plus headline hits (~2 GB, missing about one order in four).
Mobile data on the hotspot (D19) is his constraint to judge. Not started.

### 27 Sep 2026 (night, 23:14) — documents stage: option B, tonight's tier running

**Decided (Sravanth): option B, with option C finished tonight.** Built into
`backfill/documents.py`: filings are fetched in tiers - order categories (1,385), then
catch-all with a headline keyword hit (753), then catch-all that only a PDF-body check
could make an order (24,425) - so a run cut short has the most likely orders; and a
body-check-only catch-all filing is left out for a company above ₹50,000 cr on 22 Sep 2025
(7,221 files, the control group). The ceiling is `documents.other_catch_all_max_mcap_crore`
in `config/backfill.yaml`. **Slip caught before running**: my first edit added a second
top-level `documents:` key; YAML silently lets the later one win, so the ceiling read as
null and `expected` reported 0 left out. Merged into the existing section, which also
holds `max_requests_per_run: 3000`, a key nothing reads (the CLI's `--max-requests` is the
real limit). `expected` now reports each tier. 2 new tests on real SQL; 353 pass.

**Launched 23:14 IST, detached** (PID 21200), `--max-requests 2138`, over the `POCO X7`
hotspot, 108 GB free on the laptop. First two minutes: 26 documents (~5 s each, so ETA
~02:15), 8 verified by the T0 parser, 18 waiting on Batch, 1 download failed (retried on
the next run). Two vision-OCR calls so far, both `purpose = 'ocr'`, $0.0017 in all from
the backfill's $3 budget; order extraction stays deferred to Batch as designed.

### 28 Sep 2026 (00:40) — laptop switched off mid-run; nothing lost, restarted

Sravanth switched the laptop off by accident. The `documents` run (PID 21200) died at
00:36:22 with no error logged; `LastBootUpTime` still reads 24 Sep, as Windows Fast
Startup keeps it on a shutdown. Postgres came back by itself.

**Checked, nothing lost:**
- 915 documents and 917 extraction rows committed (391 verified by T0, 525 waiting on
  Batch): 916 of tonight's 2,138 filings, 43% in 82 minutes. Every document has an
  extraction row pointing at it, and no processed extraction lacks a document, so the kill
  did not split a document from its extraction.
- The one filing in flight, RAILTEL (raw 23653), carries `orders/run.py`'s pre-work marker,
  `download_failed` / "interrupted: processing started but did not finish", attempts 1 of
  3. That marker exists for exactly this case, and the next run retries it once 15 minutes
  have passed.
- `data/backfill_work/` is empty: no PDF was left behind, so D8 holds.
- 78 OCR calls ($0.078 so far); the last three (00:35:59-00:36:20) belong to document 914's
  3 OCR pages, which were committed, so no OCR was paid for and lost.
- `raw_announcements` and the market data were untouched (their loads had finished).

**Restarted 00:40** (PID 29820), `--max-requests 1221`: exactly the remaining order
categories (468) plus headline hits (753), 2,138 − 917, still on the POCO X7 hotspot.
RAILTEL was not yet past its retry delay when the queue was built, so a detached waiter
(PID 6836) runs `documents --max-requests 1` after this run exits, which picks it up as
the only tier-one filing left.

**Lesson**: a detached process survives a Claude session ending but not the laptop shutting
down or sleeping. Keep the laptop on mains power with sleep disabled while a backfill stage
runs; every stage resumes from its checkpoints, so an interruption costs time, not data.

### 28 Sep 2026 (00:43) — stopped for the night on Sravanth's word

Sravanth asked to stop everything and resume in the morning session. Killed the RAILTEL
follow-up waiter first (PID 6836, so it could not start a run when the main one exited;
it never did, no log file exists), then the documents run (PID 29820) with its process
tree. State at the stop: 940 documents, 941 filings processed (403 verified by T0, 538
waiting on Batch), 0 orphaned documents, 80 OCR calls ($0.080 in all).

This kill landed right after a download, so unlike the accidental shutdown it left one PDF
in `data/backfill_work/` (APTECHT's, not yet extracted). Confirmed no document row carries
its SHA-256, then deleted it (D8); APTECHT carries the pre-work "interrupted" marker, like
RAILTEL, and is downloaded again on the next run. The work directory is empty.

**Worth knowing for the next stop**: a PDF can survive a kill between download and
extraction. The pipeline does not sweep `data/backfill_work/` on start, so check it is
empty after any interrupted run, and delete what is there only after confirming no
`documents` row has its hash.

### 28 Sep 2026 (10:06) — morning session: documents tier one resumed

Pre-flight: nothing running, `data/backfill_work/` empty, Postgres up, on the POCO X7
hotspot, 118 GB free. **The laptop was on battery at 47%**; Sravanth asked to plug it in.
`expected` gave 444 order categories + 753 headline hits = 1,197, matching last night's
count exactly now that APTECHT and RAILTEL are past their retry delay. Launched detached
(PID 19220), `--max-requests 1197`. First minute: 945 documents, and one of the two
interrupted filings already reprocessed.

### 28 Sep 2026 (11:45) — the documents run crashed on a Windows-only bug; fixed

The morning run (PID 19220) **died at 11:45:30 with a traceback**, not at the end:
`PermissionError: [WinError 32]` deleting `data/backfill_work/e3b0c442...b855.pdf`. That
name is the SHA-256 of an empty file. NSE answered RVNL's 22 May 2026 "Updates"
attachment (listed as 1.32 MB) with an **empty 200**; `documents/fetch.py` correctly judged
it "not a PDF", but called `unlink()` **inside the `with` block that still held the file
open**. Linux deletes an open file; Windows refuses, reporting "used by another process"
even when the holder is the same process. The path had never run on this laptop, and no
test covered it. The same bug sat on the live `orders --follow` path on the laptop (same
fetcher); on the VPS (Linux) it would not have crashed.

**Fixed**: the handle is closed before the delete. New test
(`test_http_idle.py::test_a_response_that_is_not_a_pdf_is_refused_and_leaves_no_file`,
empty body and an HTML page) reproduces the exact WinError 32 on the old code and passes
on the new; 354 pass. The two other Python processes running at the time were the live
collector (restarted by Sravanth at 10:11) and `sheets` (10:16), unrelated.

**State at the crash, nothing lost**: 1,888 documents; 957 of the morning's 1,197 filings
done (~240 left). RVNL carries the pre-work "interrupted" marker and JISLJALEQS a read
timeout from 10:41; both are retried. The leftover 0-byte file was not referenced by any
document and was deleted; `data/backfill_work/` is empty.

**Relaunched 12:01** (PID 14936), `--max-requests 240`, after waiting for RVNL's
15-minute retry delay to pass (12:00:30) so the queue included it: 1 order category + 239
headline hits, exactly the morning's remainder. JISLJALEQS and RVNL both processed on
this run; RVNL's attachment came back as a real PDF, so the empty 200 was transient.

### 28 Sep 2026 (12:20-13:02) — first documents tier finished; batch-submit run

The 12:01 relaunch (240 files) finished cleanly at ~12:20: 240/240 downloaded, 0 failures,
0 not-order, 29 OCR pages. **Tier one of Sravanth's "option B" is complete**: every
order-category and headline-hit filing in the window (2,138 total) is downloaded,
extracted and T0-parsed. Roughly half were verified by the annexure parser alone with no
model involved; the rest needed the LLM step.

**`batch-submit` run at 13:02**: 1,415 `pending_llm` order-related filings became one
Batch (`batch_6aba1814a7188190aefc196d0b620e57`), each request built from
`prompts/order_extract_v1.md` plus that filing's extracted text only - fixed instructions,
document text last, for the prefix-caching shape §6 asks for. `estimate_batch_cost`
(worst case: full output allowance, ~1 token per 3 characters of input, no cached-input
discount assumed) gave $0.440437 against the $3 backfill cap; the client records that as
committed spend until the batch is collected, so a second submission can't double-spend
the same headroom. 0 filings were left for review at this cap check (§6's 3-submission
exhaustion limit not yet hit by anything). Results are due within 24 h; `batch-collect`
will read them back through `llm_extract.interpret` - the same provenance check and
retry-once rule as a live call - and log real cost to `llm_calls`.

Explained to Sravanth in the same conversation: what happens at each remaining stage, and
exactly what a Batch request contains (only the prompt and one filing's text; the model
returns raw quoted values and spans, never a converted number or a computed ratio - §6's
"the model never normalizes" rule, unchanged from the live path).

### 29 Sep 2026 — FILES.md: a one-page map of every file

Sravanth asked for two to three lines on every file in the repo: what it does and how.
Written as `FILES.md` at the root rather than in chat, since it covers ~190 files, grouped
by folder. It was written from each file's own docstring or header comment, and a script
confirmed every tracked file is covered. It is a map, not a spec: it links to
ARCHITECTURE.md and WORKLOG.md and says the code wins if they disagree. **Keep it current**:
when a file is added, removed or changes purpose, update its entry in the same commit.

### 29 Sep 2026 (21:19-21:52) — the first Batch was rejected whole; fixed and resent

`batch-collect` found `batch_6aba1814...` **`failed` with 0 results**. OpenAI's reason,
read from the batch object (our collect did not record it): `token_limit_exceeded`,
"Enqueued token limit reached for gpt-6-luna ... Limit: 2,000,000 enqueued tokens". The
batch was rejected 62 s after submission on 28 Sep, before any request ran, so **nothing
was charged and no filing was read**. The pending set is 1,415 requests, 5.4M characters of
document text: ~3.07M tokens by our estimate (1 per 3 characters), ~2.3M at 1 per 4.

**Two gaps it exposed, both fixed** (`llm/client.py`, `backfill/batch.py`, `recheck.py`,
`config/llm.yaml` `batch.enqueued_token_limit` / `enqueue_share`):
1. Batches were split by count (2,000 requests), never by tokens. Now
   `LlmClient.batch_token_room` allows one uncollected batch per model at a time, filled to
   80% of the limit (the estimate counts message text, not the JSON schema each request
   also carries), and `batch_fit` packs requests up to that. The recheck step shares the
   model and the limit, so it follows the same rule.
2. **A batch rejected whole used up one of a filing's three submissions.** Two more
   rejections would have sent all 1,415 to `needs_review` unread. Now a `failed` batch is
   not counted, in both batch.py and recheck.py.
`collect` now logs OpenAI's reason whenever a batch fails. 3 new tests (real SQL, fake
OpenAI); the two key ones reproduce the faults on the old code (`oe-1-2`; all three
requests in one batch). 357 pass.

**Resent 21:51 IST**: `batch_6abbe57fe3248190b4cbf73e62824924`, 763 requests, worst case
$0.232534, 652 waiting for the next round. Checked at 21:52: `in_progress`, 763 accepted.

### 29 Sep 2026 (22:18-22:40) — batch 1 collected, batch 2 sent; why half went to review

**Batch 1 collected**: 763 answers, 1,311,509 input + 230,640 output tokens, **$0.123**
(Batch price). 246 verified, 140 judged not an order, **369 needs_review**, 8 invalid JSON
(resent once, with the error, in batch 2). **Batch 2 submitted 22:21**: 660 requests (652 +
the 8 retries), worst case $0.21, `in_progress`, nothing left waiting.

**Why 369 went to review**, re-derived offline from the stored answers with the
production functions (`scratchpad` scripts, no requests):
- **112: stage "unknown" and nothing else wrong.** The value was found and passed
  provenance (REFEX Rs. 474.45 Crore, WELCORP Rs 1,600 Crore); the model only could not
  classify the stage (L1/LoA/PO/...). `llm_extract.interpret` sends any "unknown" stage or
  recipient to review, per §6 trigger 3 (Decided: an unknown judgment field escalates; with
  no T2 it lands in review). Stage is not used by D22's verdict. Another ~70 have stage
  unknown on top of another cause.
- **141: no value in the filing** (ZAGGLE and L&T often disclose none). Correct: a
  number is never invented, and such orders cannot enter the primary cell anyway.
- **54: quote "not in text"** - not model error. The PDF's table columns come out
  interleaved in the extracted text: RAILTEL's text reads `Rs.
(in INR); 38,59,27,045/-`,
  HILINFRA's `Rs. 1,96,35,000/- (Rupees One Crore
/contract (s); Ninety Six La...`, the
  label column landing inside the value. The model quotes the value as a reader sees it,
  which is then not one contiguous piece of the text, so `provenance.verify` (the whole
  quote must be verbatim, whitespace aside) fails. Measured alternatives: accepting a
  leading part of the quote rescues 10-11; accepting **any contiguous part of the quote
  that parses to exactly the reported value and appears verbatim** rescues **51 of 54**
  (the other 3: two foreign-currency, one genuine mismatch). The number would still be
  traced to an exact quote from the filing.
- **35: foreign currency** (flagged, never converted - FX is Open, §11). **17 of them
  state the INR equivalent in the filing itself**, e.g. "USD ($) 73.47 million (INR - 651
  Crores)", "3.8 million USD (Rs. 34 crs)".
- **32: not a money value** ("148 MW", "Rs 2.75/kWh", "290.23" with the unit only in a
  table header): correct, never a guessed scale.

**Put to Sravanth, none implemented**: (1) should an unknown stage alone block
verification (§6 trigger 3 is Decided); (2) should provenance accept a contiguous part of
the quote that gives the same value verbatim (§5.6 is Decided); (3) may a filing's own
stated INR equivalent be used for a foreign-currency order (FX is Open). `order_extractions`
stores `consideration_raw`, `value_span`, `company_is_recipient` and `stage`, so whatever
he decides can be re-applied to both batches offline, with no new OpenAI spend.

### 30 Sep 2026 (00:59-01:40) — batch 2 collected; three review rules changed; rejudged

**Batch 2 collected** 00:59: 660 answers, $0.113. 131 verified, 186 not an order, 330
needs_review, 13 invalid (owed one retry). The 8 retries from batch 1 all resolved.
Backfill LLM spend: $0.236 extraction + $0.214 OCR = **$0.45 of $3**.

**Sravanth's decisions (29 Sep, applied 30 Sep)**, answering the three questions in the
29 Sep 22:20 entry:
1. **"Stop blocking by the stage."** `llm_extract.judge` no longer sends an unknown stage
   to review; an unknown recipient still does. ARCHITECTURE §6 trigger 3 narrowed.
2. **"Yes"** to provenance on a verbatim part of the quote: `provenance.verify` accepts any
   continuous run of words from the quote that is verbatim in the text and parses to
   exactly the reported value, whole quote first. §5.6 records it.
3. **"Change the USD to Rs 94 for now, leave the other currencies as usual"**, to compute
   the ratios. New `config/fx.yaml` (`rates_to_inr: USD: 94`); `units/money.py` converts
   USD there and flags `fx_converted`; other currencies stay unconverted. §5.7 and §11
   record it; FX is no longer Open.

**Added with (3), because conversion made it dangerous**: `parse_money` used to take a
string's currency from anywhere in it. With conversion on, "INR 651 Crores (USD 73.47
million)" would have had its crore figure multiplied by 94. The currency is now read beside
the number that was chosen (12 characters before, a crore/lakh scale meaning rupees, 16
after, then the whole string). **Bug found on the way**: neither LLM path (live `_llm_row`,
backfill `_apply`) wrote `order_extractions.currency`, so every LLM-read order had none;
both do now, so "USD with a value_inr" visibly means converted.

**New stage `python -m tradebot.backfill rejudge`**: re-applies `judge` to stored answers
(only those the model judged an order with a usable answer), no model call. Run on the
backfill database: **346 needs_review -> verified**, 377 verified stayed verified, 351
stayed in review. Verified 1,098 -> 1,444; review 701 -> 355; spend unchanged.

**Checked, not assumed**: 101 verified orders are now USD-converted, totalling ~₹1.9 lakh
crore, which looked large. They are genuine dollar deals, mostly IT services quoting deal
value in USD (TCS "US$9.3 billion", HCLTECH "US $ 1.14 Billion", COFORGE, LTM, LTTS), and
no rupee amount was multiplied by 94. Where a filing states its own INR figure, ₹94 lands
within a few percent (WELCORP ₹16,920 cr against its ~₹17,200 cr; RATNAMANI ₹2,688 cr
against ₹2,700 cr).

**What is left in review (353 LLM rows)**: 247 no value stated, 80 non-money figures (MW,
tariffs, a number whose unit is only in a table header), 19 non-USD currency, 7 quotes that
do not back the value. That is the queue working as designed.

Tests: USD conversion, no-rate currency, currency beside the number, the interleaved-table
quote, a verbatim part giving a different number still failing, unknown stage no longer
blocking, currency written by the batch collector, and `rejudge` on real SQL. 362 pass.
**Not rejudged**: the live database's `order_extractions` (the backfill CLI touches only
the backfill database); new live results use the new rules automatically.

### 4 Oct 2026 — revenue and market-cap fetch sized; live ratios deferred

Sravanth asked how long fetching revenue and market caps for the order ratios (§5.10)
takes, how many requests it needs, and whether it needs an LLM, for past and present
orders. Measured on both databases, read-only:

- **Past orders, market cap: nothing to fetch.** `market_caps` in the backfill database
  already holds 388 trading days (3 Mar 2025 to 25 Sep 2026), 1,042,617 rows.
- **Past orders, revenue: ~4,200 requests, ~5 hours.** `revenue/load.py` sends about 18
  requests a company (2 listings + ~16 XBRL files for quarters from Sep 2024, both bases),
  about 80 s each at >=3 s plus jitter. 231 universe companies have a verified order now
  (1,444 verified orders); 226 filed under an order category. About 70 MB in all. Later
  catch-all tiers add companies at the same cost, fetched incrementally because the
  stage checkpoints per company. The whole universe would be ~28,000 requests (~35 h),
  which the 27 Sep decision already rules out.
- **No LLM** for revenue, market cap or the ratios: XBRL and the mcap CSV are parsed in
  code. The only knock-on is §6 trigger 4's independent re-read of high-stakes orders
  (value/mcap >= 15% or null TTM), on Batch under the $3 cap: cents.
- **Present orders: not built.** The live database has no market caps and no financials;
  it held 40 orders with a value from 32 companies (23-29 Sep). Building it would cost 2
  archive downloads per trading day for market cap, ~18 requests per newly seen company
  for revenue (kept until it files new results), and ~600 requests to catch up from
  23 Sep. A filing after 15:30 would wait for that evening's bundle (§5.10), and the
  requests would come from the VPS IP (D19).

**Decided (Sravanth): live ratios wait for the backfill verdict**, since they are only
useful for acting on orders and D18 defers that until the verdict. No code changed.

### 4 Oct 2026 (11:30-11:38) — events built; revenue trial clean; full revenue run started

Sravanth: "okay let's start the revenue backfill". Pre-flight: no Python process running
on the laptop, on the `POCO X7` hotspot, **laptop on battery at 45-47%** (asked to plug in;
the run is resumable per company either way).

**`events`** (database only, rebuildable): 1,444 verified filings -> **1,286 events**, 158
merged as repeats. The 13 `pending_llm` retries are still owed; re-running `events` after
them keeps every existing event's state. 231 event companies, all with a symbol to query.

**Trial, `revenue --max-requests 40`**: 2 companies, 38 requests, 0 failed, 0 unparseable,
~3.9 s a request. PROTEAN 12 filings (53 s), AVANTEL 22 (94 s, incl. revised filings), so
the per-company count varies more than the ~16 estimated. Checked by hand: AVANTEL's TTM
at four event dates equals the sum of the four quarters known then, one of them derived
as FY - 9M because its 26 Apr 2025 filing tagged the quarter as a 6-month fact; a revision
filed 30 Sep 2026 is correctly invisible to every earlier event.

**Gap found: the older `corporates-financial-results` listing returned 0 rows for
PROTEAN** (listed Nov 2024), so its Dec 2024 quarter is missing and its 10 Jan 2026 event
has TTM null (its Aug 2026 event is fine). AVANTEL's older listing returned 4 rows, so the
call works in general. Not investigated yet, to keep the hosts free for the run: after it,
count companies whose checkpoint shows `financial_results.rows = 0` and the events that
lose TTM, then decide whether a probe is worth it. A fix would re-fetch only those
companies.

**Full run started 11:38**: `revenue --max-requests 5000`, 229 companies left, expected
~4.5-5 h. Output in `data/revenue_load.log` / `.out`.

### 4 Oct 2026 (12:07-12:20) — hotspot dropped mid-run; revenue relaunched detached

**The `POCO X7` hotspot lost DNS at ~12:07** ("Failed to resolve 'www.nseindia.com'").
The run did not stop: each remaining company failed at its first listing call and the loop
moved on every ~3.5 s, so **55 companies were marked FAILED in about three minutes** with
no traffic reaching NSE. Then the run, launched as a backgrounded Bash call, was **killed
at ~12:08 by the tool's background time limit**. Nothing lost: 19 companies were
checkpointed (17 + the 2 trial), failed ones are not, and a killed company's partial rows
are skipped on re-insert. Laptop not rebooted; still on battery (36%).

**Relaunched 12:19 as a detached process** (`Start-Process`, PID 7024, `--max-requests
5000`; `data/revenue_resume.log` / `.out`), as the 27-28 Sep runs were. 212 companies
pending; the first came back clean. **Lesson: start any stage longer than a few minutes
detached, never as a backgrounded tool call**, which has a time limit.

**Worth deciding (not changed):** during an outage the loop burns through the list,
failing every company, and exits early. A long drop would end the run having fetched
nothing, needing a manual restart. Stopping after a few consecutive connection failures
would make that explicit; it is a code change, so it is Sravanth's call.

### 4 Oct 2026 (16:30-16:55) — revenue run finished; a quarter-tagging defect found

**The run finished 16:30**: 204 companies fetched, 8 FAILED, 3,869 requests. With the 19
from before, **223 of 231 event companies are done**. The 8 failures are transient (6 lost
1-4 XBRL downloads, 2 connection resets: e.g. INE018A01030, INE248A01017 ITI,
INE287B01021, INE323I01011); none is checkpointed, so `revenue` again fetches only them
(~160 requests, ~12 min). **Not yet re-run: Sravanth is shutting the laptop down.**

**Three integrated listings truncated at one page** (ITI, MCLOUD, AHLUCONT: 20 of 22-23
rows; `size: 20` in `config/sources.yaml`, page 1 only). The rows cut are the oldest
(MCLOUD lost Mar25 standalone, AHLUCONT Mar25 consolidated); harmless where the other
basis is complete. Fix later: ask for `size` 40 or read page 2.

**TTM coverage, measured with `ttm_as_of` per event** (database only): **1,160 of 1,286
events have TTM**; 37 belong to the 8 failed companies; 89 are null across 25 companies:
- 63 at 16 companies whose older `corporates-financial-results` listing returned 0 rows,
  plus ~13 at companies with only 2 rows there: almost all **recent NSE listings**
  (HILINFRA 24 events, MBEL, VIKRAN, ARIS, OSWALPUMPS, PROSTARM, ITCHOTELS, PROTEAN...)
  with fewer than four quarters filed on NSE. Honest nulls under "never guess"; their
  earlier results, if any, are on BSE only (D26).
- **13 from a parser defect** (DBL 6, HBLENGINE 4, RAMKY 2, ONEPOINT 1, and wider; below).

**Defect found: some Q2 (Sep 2025) filings lose their discrete quarter.** In 47 XBRL files
(25 companies) the period ending 30 Sep 2025 has only a 6-month fact and no 3-month one,
always under context `OneD` (the discrete-quarter context). The stored value is the
half-year figure: 6m / the Jun quarter is ~1.8-2.6 for every one checked (HILINFRA,
VIKRAN, SBC, SBGLP, CEIGALL, MAPMYINDIA, PROSTARM, DBL: Q1 2,620.34 + Q2 1,925.89 =
4,546.23 cr stored under OneD). Likely cause, **not yet confirmed against a file**: these
filings declare `DateOfStartOfReportingPeriod` = 1 Apr (the half-year) for the quarter's
context too, so `revenue/xbrl.py`'s "declared dates first" rule labels the quarter and the
half-year both as 6 months, and the `financials` insert's conflict clause keeps only one.
So the quarter is missing and TTM is null from the next quarter on (and, for a company with
another gap, possibly wrong rather than null - unchecked). Also seen: 32 March period ends
(18 companies) carry a 6-month fact, AVANTEL's mislabelled-quarter pattern from the trial;
there Q4 = FY - 9M fills the quarter. **Next step, Sravanth's call**: download one affected
file (DBL's `ING_INDAS_1574277_13112025082832_WEB.xml`, 1-2 requests) to confirm the
cause, then fix the parser's period rule (e.g. prefer the context's own dates when the
declared span is not a 3/6/9/12-month period consistent with the value, or derive Q2 = H1 -
Q1 as Q4 = FY - 9M is derived) and re-parse. The stored `source_url` lets affected files be
re-fetched without re-running the listings.

### 20 Oct 2026 — new brief; GATE 1 audit; decisions D28-D32; first backup

**The brief.** Sravanth asked for five things: an evidence-based audit of how far the
build got, the missing Phase 1 pieces, the backfill finished with a reliable ETA, a
deploy-agnostic setup (the VPS was cancelled in October), and measured results. It has two
gates and strict rules:
- Never open `.env`.
- One NSE process at a time, and a hard stop after 5 consecutive failures.
- Approved dependencies only.

It names an INSTRUCTIONS.md, which does not exist; its rules are applied as written.

**Audit, all read-only** (AUDIT.md). The method:
- Processes and scheduled tasks.
- Both databases through `tradebot.common.db.connect`, sessions set read-only.
- `pytest` with the backfill-DB tests skipped and OpenAI/Google set to placeholders: 337
  passed, 25 skipped.
- The T0 eval: 8/18 (44%, unchanged).
- OpenRouter's public model list.
- Three read-only code-audit agents.

What it found:
- Nothing was running, and no backup had ever been made.
- The live collector had stopped on 1 Oct.
- The backfill sits at `events` (all `extracted`) with revenue at 223/231.
- **Full-chain accuracy for free**: 8 labelled PDFs were also processed by the backfill
  (matched by SHA-256), and 7 of 8 are correct. The eighth is BEML's "over ₹5,400 cr".
- **Defects in verified data:**
  - L&T band disclosures were stored as ₹2,500 in rupees, and two legends gave ₹100 and
    ₹0. Root cause: `parse_money`'s range branch skips the under-₹1-lakh suspect check.
  - Ringgit and dinar amounts were stored as rupees.
  - §5.5 Part C is enforced nowhere: 42 vision-read values had no second read.
  - Provenance passes a dropped digit.
  - CORP_IND is read only for `MKT=N` rows, which affects 45 BE-series events.
- **NSE politeness:**
  - No 5-failure stop exists anywhere. The backfill's 401/403 breaker is dead code: it
    looks for "401" in text that never contains it.
  - There is no process lock, and no 429 backoff outside the live collector.
- One measurement error of mine, corrected before the plan was approved: I first counted
  9 overlapping labelled PDFs; it is 8.

**Decisions at the gate (Sravanth):**
- **D29**: keep OpenAI under the caps. The brief's "free OpenRouter only" line described
  v0.1.
- **D30**: live collection restarts only as one process behind an NSE lock, not the old
  collector + `orders --follow` pair.
- **D31**: skip the third documents tier (24,425 PDFs, ~24 GB, ~37 h). The verdict uses
  tier one and states the undercount.
- **D32**: "over ₹X" gives X plus `lower_bound`; a range gives its low end plus `range`;
  a band-only disclosure gives null plus `band_only`.
- **D28** records the VPS cancellation itself.

**Done today:**
- Committed the pending 4 Oct entry.
- Wrote `common/backup.py`. It runs pg_dump with the password in `PGPASSWORD`, never on the
  command line (unlike `ops/backup.sh`), and prunes per database without the old
  `tradebot_*` / `tradebot_backfill_*` overlap. 5 tests.
- **First backup**: live 5.5 MB, backfill 104 MB in `backups/`.
- ARCHITECTURE v1.6: D28-D32, plus three stale lines fixed.
- AUDIT.md, STATUS.md, FILES.md entries.

**One stray query**: a slow read-only audit query of mine (PID 20092 on
`tradebot_backfill`) kept running after its client was stopped. Cancelling it was not
permitted. It holds only a shared lock and blocks nothing; Sravanth may cancel it.

### 20 Oct 2026 (evening) — Phase 1: NSE guardrails; value rules re-applied to the backfill

**NSE guardrails (commit eaaeae7).** `common/nse_guard.py` is one gate for every NSE
request: `data/nse.lock` (a second process refuses), the gap measured from the end of the
last request on any host (2 s live, 3 s backfill), backoff as a minimum gap that never
compounds a caller's own, and `NseHardStop` on the 5th consecutive failure (a
BaseException, so the clients' `except Exception` cannot swallow it; entry points exit 3
through `nse_guard.run`). Also:
- Warm-ups are paced and checked.
- An unrecognised JSON shape or a renamed announcement field stops at once.
- The backfill's dead 401/403 check now sees the status.
- `bands.py` URLs moved to config.
- Migrations get one transaction per file.
- One Windows trap avoided: `os.kill(pid, 0)` terminates a process there, so the stale-lock
  check uses `OpenProcess`.
- **Proposed:** the live collector now exits after 5 failed polls instead of backing off
  for ever; restarting it is the hosting layer's job.

**Value rules (D32 + Proposed), and the parser change applied to stored data.**
- Root cause of the 20 garbage values: `parse_money`'s range branch returned before the
  under-₹1-lakh check.
- Fixed with: scale-before-number, size legends (`band_only`), lower/upper bounds,
  word-bounded currency markers ("rs" no longer matches inside "orders"; ringgit, dinar
  and riyal are foreign), `no_currency_marker`, and dates/year spans not read as ranges.
- Provenance now matches whole tokens only.
- `is_suspect` is the one gate both judges apply, below ₹1 lakh included.
- Flags are now stored (migration 0015, applied to both databases).
- Reading the full review queue found three general formats that held correct values:
  "Three Million Six Hundred Thousand", "₹400+ Crores" (a lower bound), and
  "12.185 (Rs. In crore)". All added.
- New stage `reparse` re-applies T0 to stored text.

**Run on the backfill database (backup taken first; no network, no model):**
- `reparse` moved 17 T0 values to `pending_llm`: the COCHINSHIP and SWANDEF legends,
  ringgit/dinar/riyal/omani amounts, two ceilings, three quantities or unmarked numbers,
  and one cut-off spelled amount.
- `rejudge` moved 15 LLM values to review (L&T's unscaled bands and the like) and 8 back to
  verified (RITES, ZODIAC and NEWGEN USD amounts confirmed by their words; ARIS, BAJEL "+").
- **Result: 1,420 verified, 0 below ₹1 lakh, 0 without a currency marker; 24 lower
  bounds, 8 ranges, 107 USD-converted; 30 queued for T1 (13 + 17).**
- T0 eval: 8/18 before and after. It scores the raw parser and skips the gates, and
  nothing was tuned to the labels.
- 416 tests pass.

### 20 Oct 2026 (evening, cont.) — §5.5 Part C enforced and run; revenue and CORP_IND fixes built

**Part C (vision-read values need a second read).** New: `extractor/part_c.py`, the
`vision-check` stage, and migrations 0016-0017. The gate is applied on every path that can
mark a value verified.
- **First run** (detached, PID 6212, ~15 min): 39 PDFs downloaded again, all SHA-256
  matches, 43 OCR pages (~$0.04), work directory empty after.
- The first comparison demanded the first read's exact wording, which is a test of
  formatting, not of the value. Changed to "the new transcript gives the same value", and
  the second transcript is now kept.
- **Result: 38 confirmed, 1 unavailable** (RPPINFRA: the second transcript came back
  empty), and 3 turned out not to be vision-sourced (their value sits on a text-layer
  page).

**Revenue: the Q2 defect needed no download to confirm.**
- The 4 Oct note's 47 files are real, counted per file: their quarter context holds the
  half-year, and there is no 3-month revenue in them at all.
- DBL's June 2026 revision gives the true quarter, and H1 − Q1 equals it to the rupee. Of
  45 revised cases, 30 match exactly and 10 within rounding.
- 5 cases (3 companies) are off: two stored "half-years" were the quarter mislabelled, and
  their revisions changed them.
- **Proposed:** Q2 = H1 − Q1, derived only when at least 0.4 × Q1 (good cases 0.53-3.26,
  bad 0.05-0.28).
- Also:
  - A non-positive derived quarter is never used.
  - Two values for one period in one file are both dropped and counted (no more first-wins).
  - `ttm_basis` is written.
  - The integrated listing is read to its last page, and a short one is not checkpointed.
  - The FY-vs-quarters check is logged.

**CORP_IND.**
- The `pd` parser now reads flags on every market row, not only `MKT=N`. BE/ST/BZ rows can
  sit under `MKT=G`, and 74 events touch BE prices in their windows.
- `market --refresh-corp-ind` re-reads only the flags, one request a day.
- On 18 Sep 2026 itself no `G` row carried a flag, so the effect may be small. The re-read
  will say.

439 tests pass. Not yet run against NSE: revenue retry, market tail, CORP_IND re-read.

### 20 Oct 2026 (night) — NSE runs, a DNS outage stopped by the guard, eval views, σ measured

**The detached NSE sequence** (18:11-19:02, then resumed 21:30-22:1x).
- **Revenue retry:** 6 of 10 companies fixed (227/231 now). The other 4 fail on 7 XBRL
  links that answer a clean **404**, the same on every retry: NSE lists the file and does
  not serve it. **Proposed:** a listed-file 404 is an answer, so the company is
  checkpointed with that quarter missing (TTM over it stays null). Every other failure is
  still retried. 13 FY-vs-four-quarters mismatches are logged (the §5.8 sanity check);
  they are not acted on.
- **Market tail:** 26 Sep - 9 Oct loaded, 9 trading days, 23 requests. Prices now run to
  9 Oct.
- **CORP_IND re-read:** the laptop lost DNS at 18:54. The guard did what it was built for:
  4 failed bundles, then the 5th consecutive failure raised `NseHardStop`, exit code 3,
  lock released. The first stretch covered 301 of 397 days and added 10 flags. Resumed
  from 25 May once DNS answered again (exit 0).

**Eval: two new views, 0 LLM calls.**
- **Gated T0** (production's provenance and suspect gate): it found one value production
  would have *accepted wrong*, MCLOUD's "₹44.60 Lakh (Rs. 44,60,400/-)" read as the
  rounded ₹44,60,000. **Proposed fix:** an exact restatement in the same string, within
  half a unit of the rounded figure's last digit, same currency, wins. It changes 0 of the
  2,237 stored order documents.
- **Tried and reverted:** joining a scale word that wraps onto the next line (BEML
  "₹ 5,400/-" / "Crores"). Measured on the stored documents first: 9 new T0 values, and 1
  is wrong, a cumulative "total export order value to ₹1,226 million" in prose (the order
  is ₹266 million). Under §6 the parser's verified answer wins, so T0 must stay precise;
  the LLM already reads all 9 correctly. This is the reason to measure before keeping a
  parser rule.
- **BEML's label** was "null pending decision" on lower bounds; D32 decided it, so its
  value is now ₹5,400 cr, with a note in the label.
- **Scores:** bare T0 9/18. Gated T0 9/18 correct, 9 held back for the LLM, 0 accepted
  wrong, 0 invented. `eval --stored`: 8 labelled documents in the backfill, 6/6 exact
  where the chain answered, plus GREENPOWER as a correct `not_order` (the company placed
  the order) and ZAGGLE as a correct null.

**σ measured** (`python -m tradebot.backfill.placebo`, `reports/power_analysis_2026-10-20.md`).
- 54,081 placebo dates in the primary band, away from real events (±10 days).
- σ is 5.75% raw and 4.43% robust, against the September estimate of 3.7%.
- The median's MDE at 30 events is 2.50% (bootstrap, fat tails included), close to the
  2.37% estimated.
- **Finding for Sravanth:** the ordinary-day median excess is **−0.44%** (−1.07% in the
  first half). D22 tests against zero, so it is conservative by about that much. Recorded
  only; D22 is Decided.

### 20 Oct 2026 (late night) — the single live runner (D30), catch-up, order-path retries

**Built:** `python -m tradebot.live` (one process, poll then orders, under the NSE lock, a
per-cycle budget of 6 filings and a 20 s margin before the next poll) and
`python -m tradebot.catchup` (one date-range request per day, rows marked `catchup`, a
health row per request, suspect answers flagged). Migration 0018 adds
`raw_announcements.collected_via`, applied to both databases.

**Order-path defects from the audit, fixed:**
- An outage (DNS, reset, timeout) no longer uses up a filing's attempts.
- An OpenAI failure is now `LlmProviderError`. The filing waits as `pending_llm`, the
  cycle's order work stops, and on the OCR path the document is no longer marked
  unreadable for good. The PDF is still deleted on that path (D8).
- `pending_llm` is never dropped. It is exempt from the 3-attempt cap (15-minute spacing
  kept), read however old it is, and retried from its stored text with no second download.
- Unknown categories go to catch_all and are logged once per filing (Proposed; this is
  what §5.4 already said).

**Also:** 30 `pending_llm` backfill filings submitted to the Batch API at 22:10
(`batch_6ad799778dc08190a9fbb5d15054aad9`, worst case $0.0092). Collect within 24 h.

**Noticed:** 20 Oct is Dussehra, an NSE holiday. A test fixture that assumed "today
trades" failed for that reason alone. The calendar code was right.

461 tests pass.

### 21 Oct 2026 (early morning) — catch-up drain dropped, batch collected, events, GATE 2 pieces

- **Sravanth: do not process the 1-20 Oct backlog** ("taking too long"). The live runner had
  already stopped: Windows rebooted at 03:52 and it was not restarted. The 7,806 caught-up
  rows stay in `raw_announcements` (append-only, `collected_via = 'catchup'`), but their
  PDFs are not downloaded. If `live` is restarted, its 14-day lookback would pick them up,
  so set `live_lookback_days` low first or let them age out.
- Batch `batch_6ad7997...` collected: 30 results, $0.0059. 1,427 verified extractions.
- `events`: 1,281 events (146 filings merged). `calculate`: 1,024 verified, 257
  `recheck_pending`. The recheck batch `batch_6ad7f3be...` was submitted at 04:35: 257
  requests, worst case $0.08.
- **GATE 2 pieces.** `docker-compose.yml` is now host-agnostic: `live` replaces
  collector + orders (D30), plus `sheets`, `catchup` and `backup`. Two overrides,
  `local-db` and `external-db`. Rehearsed locally with Docker Desktop, which was started
  for this and stopped after: the image builds, 18 migrations apply, and 422 tests pass in
  the image (the 2 known layout failures, D12). The rehearsal containers and volumes were
  removed. README.md has been added with the hosting options. DEPLOY.md is marked
  superseded.
- **Validation before the study (no returns read).**
  - 0 duplicate events, 0 raw filings in two events, 0 same-value repeats within 3 days.
  - 14 unknown categories (166 filings).
  - Reconcile at 96.6% (35 of 246 days below 95%), and prices on all 246 trading days of
    the window.
  - **Spot check, 30 values stratified** (T0, LLM, USD, bounds, high stakes). All 30 pass
    provenance, but reading them found HCC stored as ₹6 crore for "~2.917.6 crore". It is
    now `malformed_number`, no value (1 stored document changed), and is waiting to be sent
    to T1.
  - BAJEL's "between INR 100 Cr and INR 200 Cr" is stored as 100 Cr, the D32 low end, but
    without the `range` flag. This is a known flag gap and was left as it is.
- **Google Sheet** (Sravanth asked whether the data shows there). The mirror had last synced
  on 1 Oct. The first sync since then wrote the 7,806 caught-up raw rows (14,479 in total)
  and rewrote the 99 order rows. A new third tab, `backfill_events` (Proposed, D11
  extension), now holds the 1,281 backfill events, and the study columns fill in after
  `study`. Two latent bugs in `client.clear_from` were fixed: it sent a 400-raising range
  when the data filled the grid exactly, and it cleared only columns A-Z.
- **README rewritten for the public repo** (Sravanth will post it). It covers what the
  project is, a diagram, each pipeline step in plain language, the pre-registered rule,
  measured numbers only (no result claimed before the study), design choices, known
  limitations, how to run it, a repository map, and a note on NSE's terms. The hosting
  options moved to STATUS.md. Full-history secret scan before going public: clean. One hit
  was a documentation placeholder; no sensitive file was ever committed.
