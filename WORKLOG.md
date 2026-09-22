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
| **A2** — API completeness | **Next. Not run. Blocks the backfill design and possibly the study's scope.** |
| **C** — results XBRL | Not started |
| **D** — extraction bake-off | Not started. Needs an OpenAI key and 10 labelled PDFs from Sravanth. |
| **E** — VPS preflight | Not started. Needs VPS numbers from Sravanth. |
| Python 3.14 wheels | Windows half verified; manylinux not checked. |

**The blocker.** Spike A found that the announcements API returns only a subset of any past
day (563 of ~1,229 filings for 18 Sep 2026, missing whole companies). The API is the only
source of the PDF URL and filing timestamp. Until Spike A2 establishes whether the full day
is reachable, **no backfill design should assume a PDF URL is obtainable for an arbitrary
past order filing**, and the 12-month study cannot be scoped. If A2 finds nothing, the
choice is to shrink the study to whatever window the API serves, or to fall back on D23's
forward collection and wait 12 months of wall-clock time. That is Sravanth's call, not an
implementation detail.

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
- Branch `main`. No remote yet.

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

- **Git remote** (and confirmation that `main` is the branch he wants). Still none: every
  commit lives only on this laptop.
- **Postgres on the laptop**, with `DATABASE_URL` set. D19 puts the backfill there; Slice 1
  cannot store a row without it.
- **`config/holidays_2026.yaml`**, maintained by hand (D27), before the live collector runs.
- **VPS numbers** for Spike E: free memory, free disk, swap, the external Docker network
  name, and how the existing Postgres container is configured.
- **OpenAI model IDs and prices**, copied from the live pricing page. `config/llm.yaml` holds
  `PLACEHOLDER` deliberately; nothing may be guessed here.
- **10 order PDFs with hand-labelled expected JSON** for the Spike D bake-off, and later ~50
  for the eval set.

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
