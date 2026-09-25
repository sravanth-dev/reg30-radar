# Order-related filings, 24–25 Sep 2026 — full extraction detail

Generated from a catch-up run: the live collector was not running on 24 Sep or this
morning, so this covers a date-range query for both days
(`python -m tradebot.collector --catchup --from 2026-09-24 --to 2026-09-25`, followed by
`python -m tradebot.orders --from 2026-09-24 --to 2026-09-25`), rather than the normal
live-collector path. 975 filings were pulled, 166 were in scope for download (order
categories + catch-all), and these 12 are the ones the relevance gate found order-related.
Ordered by actual filing time (`exchange_ts`), not by when we happened to catch up on them
— everything below was genuinely filed on the date its section says.

**Read the flags below before the numbers — two real problems in this batch, both
important for watching stocks:**

1. **VASCONEQ's stored value is wrong by a factor of ten million, and it passed the
   verification check anyway.** The filing states "Rs. 660.79/- (Rupees Six Hundred &
   Sixty Crore and Seventy-Nine Lakhs only)" — the scale word ("Crore") is only in the
   spelled-out parenthetical, not attached to the numeral itself. The parser read
   "660.79/-" as a bare rupee figure (₹660.79) because there was no "Crore" *immediately
   next to* the number, and — because that misreading is self-consistent (the same wrong
   span, re-parsed, gives the same wrong number) — it passed the provenance check and came
   back `✅ verified`. It is not verified in any sense that matters: **the real order value
   is ₹660.79 crore (₹6,60,79,00,000), not ₹660.79.** This is a real gap in the parser
   (`units/money.py` doesn't yet look at a spelled-out amount in parentheses when the
   numeral itself has no scale word) — recorded in WORKLOG for a proper fix, not patched
   here under time pressure. Trust the corrected figure below, not what the system would
   report on its own for this one.
2. **GENESYS's ₹283 crore Ahmedabad contract appears twice** — once as a Press Release at
   10:02 and again as the formal SEBI Regulation 30 disclosure at 17:12, both on 24 Sep.
   This is **one order, reported through two separate filings**, not two different orders.
   The system doesn't merge same-event filings yet (that's a later slice, §5.3); until
   then, treat any pair of same-company, same-value filings close together as one event.

## At a glance

| Time (IST) | Symbol | Value (₹) | Status | Note |
|---|---|---|---|---|
| 24 Sep, 08:48 | KPIL | 20,25,00,00,000 | ⚠️ Needs review | stage unknown |
| 24 Sep, 10:02 | GENESYS | 2,83,00,00,000 | ✅ Verified | same order as 17:12 below |
| 24 Sep, 11:10 | AASTHA | 25,00,00,000 | ✅ Verified | — |
| 24 Sep, 16:52 | LCCPROJECT | 6,53,34,00,000 (incl. GST) | ✅ Verified | L-1 bidder, not yet awarded |
| 24 Sep, 17:12 | GENESYS | 2,83,00,00,000 | ✅ Verified | same order as 10:02 above |
| 24 Sep, 23:17 | STEAMHOUSE | — (unreadable) | ⚠️ Needs review | scanned, OCR couldn't recover it |
| 25 Sep, 07:36 | VASCONEQ | **6,60,79,00,000** (system shows 660.79 — wrong, see note 1) | ✅ "Verified" (don't trust) | LoI, not yet a firm order |
| 25 Sep, 08:28 | WELCORP | — (USD 412.5 million, ~₹4,000 cr) | ⚠️ Needs review | foreign currency, not converted |

Total LLM/OCR cost across all 12 order-related filings: **$0.0329** (7 extraction calls +
OCR attempts). 4 more filings matched a keyword but turned out not to be about an order
after all (BLACKBUCK, VPRPL, SAURASHCEM, LASERPOWER) — see the note at the bottom.

---

## 24 September

### 08:48 — KPIL (Kalpataru Projects International Limited)

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [KALPATPOWR_24092026084832_SEIntimationPR24092026.pdf](https://nsearchives.nseindia.com/corporate/KALPATPOWR_24092026084832_SEIntimationPR24092026.pdf)
- **Value:** ₹2,025 crore, quoted as "approx. ₹2,025 Crores" — verified against the document
- **Company received the order:** yes · **Stage:** unknown
- **Status: ⚠️ Needs review** — the value's provenance passed, but the model couldn't tell what stage the order is at, which is itself an escalation trigger (§6) with no second model configured to arbitrate it
- Path: LLM extraction — cost $0.000360

### 10:02 — GENESYS (Genesys International Corporation Limited) — Press Release

- **Category:** `Press Release` → caught by the headline keyword filter ("contract"), not the category
- **Filing:** [GENESYS_24092026100224_GENESYS_finalpress.pdf](https://nsearchives.nseindia.com/corporate/GENESYS_24092026100224_GENESYS_finalpress.pdf)
- **Value:** ₹283 crore, quoted as "₹283 crore" — verified
- **Execution period:** two-and-a-half years, then five years of operation and maintenance
- **Company received the order:** yes · **Stage:** contract
- **Status: ✅ Verified**
- Path: LLM extraction — cost $0.000349
- **This is the same Ahmedabad 3D Digital Twin contract as the 17:12 filing below** — the press announcement of the win, ahead of the formal disclosure

### 11:10 — AASTHA (Aastha Spintex Limited)

- **Category:** `General Updates` → caught by the body keyword filter, not the category
- **Filing:** [9081535400_24092026110916_Aastha_Intimation_Sign__1_.pdf](https://nsearchives.nseindia.com/corporate/9081535400_24092026110916_Aastha_Intimation_Sign__1_.pdf)
- **Value:** ₹25 crore (₹25,00,00,000), quoted as "₹25,00,00,000/-"
- **Company received the order:** yes · **Stage:** contract
- **Status: ✅ Verified** — by the deterministic parser alone, no LLM needed
- Path: T0 parser — cost $0.00

### 16:52 — LCCPROJECT (LCC Projects Limited)

- **Category:** `Updates` → caught by the headline keyword filter ("L-1"), not the category
- **Filing:** [LCCPROJECTS_24092026164937_Reg30_L1_2409.pdf](https://nsearchives.nseindia.com/corporate/LCCPROJECTS_24092026164937_Reg30_L1_2409.pdf)
- **Value:** ₹653.34 crore, including GST, for a Rajasthan irrigation EPC project (Chhoti Kalisindh)
- **Awarding entity:** the Chief Engineer, Water Resources Zone (state government body)
- **Company received the order:** unclear from the text · **Stage:** the system says "amendment", which is **very likely wrong** — this is an L-1 (lowest bidder) announcement for a new project, not an amendment. This is the same `parse_stage` keyword-priority weakness flagged for BDL on 23 Sep (WORKLOG): the word "revised"/"amend" appearing anywhere in the document wins over everything else.
- **Status: ✅ Verified** — the value itself is solid; the stage label isn't
- Path: T0 parser — cost $0.00
- **Note:** L-1 (lowest bidder) is an early stage — this is not yet a confirmed, awarded order.

### 17:12 — GENESYS (Genesys International Corporation Limited) — formal disclosure

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [GENESYS_24092026171029_Ahemdabad_Reg_30_order_intimation.pdf](https://nsearchives.nseindia.com/corporate/GENESYS_24092026171029_Ahemdabad_Reg_30_order_intimation.pdf)
- **Value:** ₹283 crore, inclusive of taxes, quoted as "Rs. 283 crore (inclusive of taxes)"
- **Awarding entity:** Ahmedabad Municipal Corporation (AMC)
- **Company received the order:** yes · **Stage:** contract
- **Status: ✅ Verified** — by the deterministic parser alone
- Path: T0 parser — cost $0.00
- **Same order as the 10:02 Press Release above** — this is the formal Reg 30 disclosure of the same ₹283 crore win.

### 23:17 — STEAMHOUSE (Steamhouse India Limited)

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [CAVAIBHAVGATTANI_24092026231657_Announcement.pdf](https://nsearchives.nseindia.com/corporate/CAVAIBHAVGATTANI_24092026231657_Announcement.pdf) — 2 pages, scanned
- **Value:** not recovered — both pages went to vision OCR and **still came back unreadable**
- **Status: ⚠️ Needs review** — a genuine order win by category, but the system could not read what it says. **Worth checking this PDF by hand** if STEAMHOUSE matters to you; nothing was guessed
- Path: OCR attempted, no usable text — cost $0.002620 (the OCR attempt itself)

---

## 25 September (up to ~10:30 IST)

### 07:36 — VASCONEQ (Vascon Engineers Limited)

- **Category:** `Awarding of order(s)/contract(s)` → order_candidate
- **Filing:** [VASCONEQ_25092026073623_24092026LetterofIntent_V3_Changes_Sd.pdf](https://nsearchives.nseindia.com/corporate/VASCONEQ_25092026073623_24092026LetterofIntent_V3_Changes_Sd.pdf)
- **Value: ₹660.79 crore (₹6,60,79,00,000) — corrected; the system itself stored ₹660.79. See note 1 at the top.**
- **Awarding entity:** Qualcomm India Private Limited
- **Company received the order:** yes · **Stage:** LoI (Letter of Intent — not yet a firm, signed order)
- **Status:** the system marked this "✅ verified", but **do not trust that label here** — see the correction above
- Path: T0 parser — cost $0.00
- **Headline says it directly:** "receives Letter of Intent for Development of Office Facility Ground + 12 Floors at Bengaluru... amounting to Rs. 660.79 Crore"

### 08:28 — WELCORP (Welspun Corp Limited)

- **Category:** `Bagging/Receiving of orders/contracts` → order_win
- **Filing:** [WELCORP_25092026082837_SEDisclosureUSOrdersigned.pdf](https://nsearchives.nseindia.com/corporate/WELCORP_25092026082837_SEDisclosureUSOrdersigned.pdf)
- **Value:** not converted — **USD 412.5 million (~₹4,000 crore per the filing itself)**, foreign currency
- **Execution period:** during FY28 and FY29
- **Company received the order:** yes · **Stage:** unknown
- **Status: ⚠️ Needs review** — foreign currency is never auto-converted, so this always needs a human FX decision; the filing's own parenthetical (~₹4,000 crore) is a reasonable estimate but not what the system verified
- Path: LLM extraction — cost $0.000325

---

## Matched a keyword, turned out not to be an order (cost real money, correctly filtered)

Four filings passed the keyword prefilter and were sent to the LLM, which correctly
determined they are not actually about an order after all:

- **BLACKBUCK** (24 Sep, 17:36) — an ESOP Trust Deed filing that happened to contain "L 1" somewhere in a 28-page scanned document. Cost $0.001176.
- **VPRPL** (24 Sep, 18:39) — an AGM corrigendum, 128 pages, that mentioned "work order" somewhere in passing. Cost **$0.015717** — the single most expensive item in this batch, worth noting since a large document that isn't actually an order still burns real budget.
- **SAURASHCEM** (24 Sep, 20:35) — an insider-trading disclosure referencing a tax "order" from a regulator, not a business order. Cost $0.012052 (10 pages needed OCR).
- **LASERPOWER** (24 Sep, 21:12) — a land allotment letter mentioning "LOI" in an unrelated sense. Cost $0.000260.

These are working as intended — the keyword filter is deliberately generous, and the LLM
triage is what catches false positives before they'd ever reach `verified`. The two
expensive ones (VPRPL, SAURASHCEM) are a real cost signal worth watching if this becomes a
daily habit: very large or heavily-scanned documents can cost disproportionately more to
rule out than to confirm.
