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

*Last updated: 22 Sep 2026*

**What this is.** tradebot Phase 1. Collect NSE corporate announcements (BSE dropped by
D26), classify them, extract order wins, measure order value against revenue and market
cap, and test it on 12 months of history to decide whether order filings move prices
tradeably. Nothing in this repo places trades, and nothing will in Phase 1.

**Where we are.** Slice 0 (spikes). Two of six done, and both reversed a design decision
that had already been written into the spec. **No production code exists yet** —
`src/tradebot/` is thirteen empty packages. Everything so far is scaffold, tests against
fixtures, and throwaway probes in `spikes/`.

| Spike | Status |
|---|---|
| **B** — NSE bulk archives | Done. See 21 Sep entry. |
| **A** — announcements API | Done, but left a blocker. See 22 Sep entry. |
| **A2** — API completeness | Done. **Backfill is viable.** Reconciliation now runs per-day in the backfill. |
| Live-feed reconciliation | **Running** since 22 Sep 14:02 IST; reconcile against the 23 Sep bundle. |
| **C** — results XBRL | Not started |
| **D** — extraction bake-off | Not started. Needs an OpenAI key and 10 labelled PDFs from Sravanth. |
| **E** — VPS preflight | Not started. Needs VPS numbers from Sravanth. |
| Python 3.14 wheels | Windows half verified; manylinux not checked. |

**No longer blocked.** Spike A2 resolved the API-completeness scare: it was two measurement
errors of mine, not a property of the API. The `an<date>.txt` bundle is a *report* covering
filings disseminated since the previous report, so comparing bundle(D) to API(D) was a
category error; and "the symbol query stops at Oct 2025" came from string-sorting
`DD-Mon-YYYY`. Re-measured over a two-day window, **mainboard order coverage is 8 of 8**, and
the symbol query returns a company's whole 22-year history in one call — so the backfill is
one request per company, not per company-day. Caveats in §5.1.

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

---

## Environment

- **Laptop, Windows + Git Bash.** Python 3.14.2 is the only interpreter. Activate with
  `source .venv/Scripts/activate` — `Scripts`, not `bin`.
- All 11 approved dependencies install from cp314 Windows wheels with no source builds.
- Spikes and the eventual backfill run **on the laptop over a phone hotspot, not the campus
  network** (D19). The VPS runs only the live collector.
- **Local database** (D19): PostgreSQL **16** on Windows, service `postgresql-x64-16`,
  `psql` at `C:\Program Files\PostgreSQL\16\bin\psql`, listening on `127.0.0.1:5432`.
  Role and database are both `tradebot`; the password lives only in the gitignored `.env`.
  The venv has `psycopg` 3.3.6. `migrations/` is still empty — there is no schema yet, so a
  successful connection proves the server, not the tables.
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

- ~~**Postgres on the laptop.**~~ **Installed and running, 22 Sep 2026** — PostgreSQL 16,
  service `postgresql-x64-16`, listening on `127.0.0.1:5432`, and the `tradebot` role
  exists. Remaining: the real password still has to be saved into the local `.env`,
  which currently holds the `CHANGEME` placeholder. That file is machine-local and
  gitignored by design, so no later session can confirm this from the repo — if a
  connection fails, check `.env` first.
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
