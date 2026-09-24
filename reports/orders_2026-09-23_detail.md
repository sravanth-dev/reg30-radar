# Order-related filings, 23 Sep 2026 — full extraction detail

Generated from `order_extractions` after `python -m tradebot.orders --date 2026-09-23`
(ARCHITECTURE.md §5.4–§5.6). 124 filings were downloaded that day; these are the 10 that
the relevance gate (`router/orders.py`) found order-related, either by NSE's own category
or by a keyword match in a `General Updates`/`Updates`/`Press Release` filing. This file
shows every extracted field per filing; `orders_2026-09-23.md` in this same folder is the
short version with one row per filing.

**How to read `Status`.** `✅ Verified` means the value's exact source span was found
verbatim in the document and re-parsing that span alone produces the same number
(ARCHITECTURE.md §5.6's provenance check) — it is not a claim that the value is correct in
some absolute sense, only that it is traceable to the document rather than guessed.
`⚠️ Needs review` means that check failed, or a field the model itself was unsure about
(who received the order, what stage it's at) came back `unknown` — every such filing is
listed here anyway, so nothing order-related is silently dropped, but the number should be
checked against the source PDF before being used for anything.

**Two things worth knowing before reading the numbers below:**
- **BDL's `stage` reads "amendment", which is very likely wrong.** BDL's own category
  (`Bagging/Receiving of orders/contracts`) and headline are unambiguous that this is a new
  order win, not an amendment. `stage` comes from a simple keyword search over the whole
  document (`extractor/annexure.py`'s `parse_stage`) that checks for the words
  "amend"/"revised"/"revision"/"terminat" *before* checking for anything else — if any of
  those words appear anywhere in the filing (a boilerplate clause, a reference to an
  earlier revision of an unrelated document), it wins regardless of what the filing is
  actually about. This is a known limitation of that heuristic, not something specific to
  BDL; it just happened to be the one T0-only filing where it showed up today.
- **SUBEXLTD's order is in US dollars, and `value_inr` is correctly left blank rather than
  converted.** Foreign-currency orders are flagged, not guessed at — there is no FX source
  configured yet (ARCHITECTURE.md §11) — so `US$ 5 million` stays exactly as printed and
  the ratio calculators later in the pipeline will simply skip this one.

## At a glance

| Time (IST) | Symbol | Value (₹) | Status | Path | Stage |
|---|---|---|---|---|---|
| 10:46 | SKIPPER | 7,97,00,00,000 | ⚠️ Needs review | LLM | unknown |
| 12:47 | SUBEXLTD | — (US$ 5 million) | ⚠️ Needs review | LLM | contract |
| 14:25 | SILVERTUC | — (not extracted) | ⚠️ Needs review | LLM | — |
| 15:46 | AVANTEL | 1,77,35,00,000 | ⚠️ Needs review | LLM | PO |
| 16:57 | GHCL | 5,67,337 | ✅ Verified | T0 parser | LoI |
| 17:18 | ASHOKA | — (not stated) | ⚠️ Needs review | LLM | LoI |
| 17:56 | BCPL | 6,22,00,000 | ✅ Verified | LLM | contract |
| 18:11 | BDL | 8,10,79,00,000 | ✅ Verified | T0 parser | amendment (likely wrong — see above) |
| 19:43 | DHRUV | 3,79,08,000 | ✅ Verified | LLM | LoA |
| 22:55 | GMRAIRPORT | 49,00,00,000 | ✅ Verified | LLM | contract |

Total LLM/OCR cost across all 10: **$0.008236** (8 extraction calls, 3 OCR pages).

---

## 10:46 — SKIPPER (Skipper Limited)

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [skipper_23092026104600_Press_ReleaseOrder.pdf](https://nsearchives.nseindia.com/corporate/skipper_23092026104600_Press_ReleaseOrder.pdf) — 3 pages, text extracted cleanly
- **Value:** ₹797 crore (₹7,970,000,000), quoted as "₹ 797 crores" — span verified in the document
- **Company received the order:** yes
- **Stage:** unknown (the model couldn't tell L1/LoI/LoA/PO/contract from the text)
- **Status: ⚠️ Needs review** — the value's provenance passed, but the unresolved stage is itself an escalation trigger (§6), and there's no second model configured to arbitrate it
- Path: LLM extraction (T0 found nothing to verify) — cost $0.000288

## 12:47 — SUBEXLTD (Subex Limited)

- **Category:** `Awarding of order(s)/contract(s)` → order_candidate
- **Filing:** [SUBEXLTD_23092026124115_Deal_win_announcement23092026.pdf](https://nsearchives.nseindia.com/corporate/SUBEXLTD_23092026124115_Deal_win_announcement23092026.pdf) — 4 pages
- **Value:** not converted — **US$ 5 million**, foreign currency (see note above)
- **Awarding entity:** a major mobile network operator in the Asia Pacific region
- **Execution period:** 5 years
- **Company received the order:** yes · **Stage:** contract
- **Status: ⚠️ Needs review** — foreign currency is never auto-converted, so this always needs a human FX decision
- Path: LLM extraction — cost $0.000297

## 14:25 — SILVERTUC (Silver Touch Technologies Limited)

- **Category:** `General Updates` → caught by the body keyword filter ("order worth"), not the category
- **Filing:** [SILVERTUC_23092026142511_STTL-Investors-Presentation_Q1_FY_2026-27.pdf](https://nsearchives.nseindia.com/corporate/SILVERTUC_23092026142511_STTL-Investors-Presentation_Q1_FY_2026-27.pdf) — a 29-page investor presentation, only partially readable
- **Value:** not extracted
- **Status: ⚠️ Needs review** — the model's response was invalid JSON on both the first attempt and the retry (`"invalid response twice: Expecting value: line 1 column 1 (char 0)"`), most likely because a 29-page investor deck is a very different shape of document from the order-filing template the prompt was written for
- Path: LLM extraction (2 calls, the retry) — cost $0.002093, the most expensive filing of the day

## 15:46 — AVANTEL (Avantel Limited)

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [AVANTEL_23092026154418_OrderIntimation23092026.pdf](https://nsearchives.nseindia.com/corporate/AVANTEL_23092026154418_OrderIntimation23092026.pdf) — 2 pages
- **Value:** ₹177.35 crore (₹1,773,500,000), quoted as "Rs.177.35 Crores (Rupees One Hundred and Seventy-Seven Crores and Thirty-Five Lakhs Only)"
- **Awarding entity:** M/s. Zetwerk Manufacturing Businesses Limited
- **Execution period:** March 2027
- **Company received the order:** yes · **Stage:** PO
- **Status: ⚠️ Needs review** — the quoted span did not verify against the document text on a second, independent check; worth confirming the figure against the PDF directly
- Path: LLM extraction — cost $0.000421

## 16:57 — GHCL (GHCL Limited)

- **Category:** `Awarding of order(s)/contract(s)` → order_candidate
- **Filing:** [GHCL_23092026165707_GHCL_Intimation_Preferred_Bidder_MininingLease_September2026.pdf](https://nsearchives.nseindia.com/corporate/GHCL_23092026165707_GHCL_Intimation_Preferred_Bidder_MininingLease_September2026.pdf) — 2 pages
- **Value:** ₹5,67,337 — a mining-lease preferred-bidder fee, not a contract value in the usual sense; the parser's raw span was "or size of the 6.8797 Hectares Area for Composite license with 5,67,337"
- **Awarding entity:** the Commissioner of Geology and Mining, Government of (Gujarat, truncated in extraction)
- **Company received the order:** yes · **Stage:** LoI (preferred bidder, not yet formally awarded)
- **Status: ✅ Verified** — by the deterministic parser alone, no LLM needed
- Path: T0 parser — cost $0.00

## 17:18 — ASHOKA (Ashoka Buildcon Limited)

- **Category:** `General Updates` → caught by the body keyword filter ("Letter of Intent"), not the category
- **Filing:** [ASHOKA_23092026171617_503_ABL_BSE_NSE_Sakoli_acquisition.pdf](https://nsearchives.nseindia.com/corporate/ASHOKA_23092026171617_503_ABL_BSE_NSE_Sakoli_acquisition.pdf) — 3 pages. This filing is actually about acquiring a project SPV (Sakoli Transmission Power Limited), which came with a Letter of Intent — an order-adjacent event, not a classic order win
- **Value:** not stated in the filing
- **Awarding entity:** REC Power Development and Consultancy Limited
- **Execution period:** 24 months from the date of acquisition of the SPV
- **Company received the order:** yes · **Stage:** LoI
- **Status: ⚠️ Needs review** — no consideration value to verify, so it can't be marked verified; worth a human read to confirm whether this belongs in the order-win study at all, or is closer to an acquisition
- Path: LLM extraction — cost $0.000381

## 17:56 — BCPL (BCPL Railway Infrastructure Limited)

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [BCPL_23092026175604_cantilever23092026.pdf](https://nsearchives.nseindia.com/corporate/BCPL_23092026175604_cantilever23092026.pdf) — 3 pages, a **scanned document**; all 3 pages needed vision OCR to read at all
- **Value:** ₹6.22 crore (₹62,200,000), quoted as "Rs 6.22 crores"
- **Awarding entity:** Eastern Railway
- **Company received the order:** yes · **Stage:** contract
- **Status: ✅ Verified**
- Path: LLM extraction, on the OCR-recovered text (T0's parser can't read the labelled annexure rows in free-form OCR output) — cost $0.003975, of which $0.003768 is the 3-page OCR call and $0.000207 the extraction itself

## 18:11 — BDL (Bharat Dynamics Limited)

- **Category:** `Bagging/Receiving of orders/contracts for SAT SAAW` → order_win
- **Filing:** [BDL_23092026181115_Covorder23092026SE.pdf](https://nsearchives.nseindia.com/corporate/BDL_23092026181115_Covorder23092026SE.pdf) — 2 pages
- **Value:** ₹810.79 crore (₹8,107,900,000), quoted as "or size of the order(s) Rs. 810.79 Crore"
- **Awarding entity:** the order(s) / Indian Air Force (IAF) — extraction is a little rough here (see the raw span), but the number itself checks out
- **Company received the order:** unclear from the text · **Stage:** amendment — **very likely wrong, see the note above the table**
- **Status: ✅ Verified** — the value itself is solid; the stage label next to it isn't
- Path: T0 parser — cost $0.00

## 19:43 — DHRUV (Dhruv Consultancy Services Limited)

- **Category:** `Updates` → caught by the body keyword filter ("Letter of Award"), not the category
- **Filing:** [DHRUV_23092026194306_dhruvRegulation30Letter.pdf](https://nsearchives.nseindia.com/corporate/DHRUV_23092026194306_dhruvRegulation30Letter.pdf) — 2 pages
- **Value:** ₹3.79 crore (₹37,908,000), quoted as "Rs. 3,79,08,000/- (Rupees Three Crore Seventy-Nine Lakh Eight Thousand Only) excluding GST"
- **Awarding entity:** Office of Executive Engineer, Public Works Division, Panvel, Government of Maharashtra
- **Execution period:** 365 days
- **Company received the order:** yes · **Stage:** LoA
- **Status: ✅ Verified**
- Path: LLM extraction — cost $0.000354

## 22:55 — GMRAIRPORT (GMR Airports Limited)

- **Category:** `Bagging/Receiving of orders/contracts` (about GMR Hospitality Limited, its Indian subsidiary) → order_win
- **Filing:** [GMRINFRA_23092026225324_23092026-GHLfBLOIA.pdf](https://nsearchives.nseindia.com/corporate/GMRINFRA_23092026225324_23092026-GHLfBLOIA.pdf) — 1 page
- **Value:** ₹49 crore (₹490,000,000) — the filing actually states a range, "~Rs. 49 crs and ~Rs. 109 crs", and the lower figure is what was extracted and verified
- **Awarding entity:** Delhi International Airport Limited (DIAL)
- **Execution period:** an initial period of up to May 2036, extendable by up to 10 more years
- **Company received the order:** yes · **Stage:** contract
- **Status: ✅ Verified**
- Path: LLM extraction — cost $0.000427
