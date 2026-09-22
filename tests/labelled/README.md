# Labelled order set — how to fill one in

Ground truth for the Spike D bake-off and later `python -m tradebot.eval`. Ten PDFs gate
Spike D; about fifty eventually feed the eval set.

One pair per filing, sharing a stem:

```
tests/labelled/<SYMBOL>_<YYYYMMDD>_<n>.pdf     the filing, kept permanently (D8 exception)
tests/labelled/<SYMBOL>_<YYYYMMDD>_<n>.json    what a correct extraction returns
```

`<n>` is `1` unless a company filed more than once that day. Copy `_template.json`.

## The two rules that matter most

**Write what the document says, not what it means.** If the PDF prints `₹ 13.51 Crs`, then
`consideration_raw` is exactly `"₹ 13.51 Crs"`. Do not tidy the spacing, expand `Crs`, or
convert to rupees. The extractor is graded on reproducing the string; the unit normalizer is
graded separately on turning it into `value_inr`. Labelling the converted number only would
hide which of the two is broken.

**`null` means the document does not say.** It is not "I could not find it" and not
"unknown". If a field is genuinely absent from the filing — many are — write `null`. If the
document states something you cannot interpret, put the raw text in the field and add a note
in `labeller_notes`. Never guess a number (CLAUDE.md).

## Fields

`value_inr` and `execution_months` are the two computed fields you also record, because they
grade the unit normalizer (§5.7). Everything else is verbatim.

| Field | Type | Convention |
|---|---|---|
| `awarding_entity` | string \| null | The customer, as printed. Keep "Ltd."/"Limited" as written. |
| `domestic_or_international` | `"domestic"` \| `"international"` \| null | Only if the filing says so, or the awarding entity is plainly foreign. |
| `nature_of_order` | string \| null | One line, as printed (e.g. `"Supply of electronic fuzes"`). |
| `significant_terms` | string \| null | Verbatim, trimmed. Long clauses may be truncated with `…`. |
| `execution_period_raw` | string \| null | Exactly as printed: `"10 Months from Work Order"`. |
| `execution_months` | number \| null | What §5.7 should compute. `"2 Years"` → `24`. `"60 days"` → `2`. An absolute date → months from the filing date, rounded to one decimal. Unclear → `null`. |
| `consideration_raw` | string \| null | **Verbatim.** `"Approx. ₹2.89 Crores"`, `"INR 65,02,160.50/-"`. |
| `value_inr` | string \| null | Expected rupees as a **decimal string**, not a number: `"28900000.00"`. A string keeps the value exact through JSON — a float would not. `null` when the filing does not disclose a value. |
| `value_span` | string \| null | The exact substring of the PDF text containing the value. Usually equals `consideration_raw`; differs when the value sits mid-sentence. This is what the provenance check verifies (§5.6). |
| `gst_inclusive` | `true` \| `false` \| null | `true` only if the filing says "incl. GST" or similar; `false` only if it says "excluding GST"; otherwise `null`. |
| `currency` | string | ISO code: `"INR"`, `"USD"`, `"EUR"`. Default `"INR"` when a rupee marker is present. |
| `promoter_interest` | boolean \| null | Whether promoters have an interest in the awarding entity. |
| `related_party` | boolean \| null | Whether this is a related-party transaction. |
| `receipt_datetime` | string \| null | ISO 8601 with offset if stated: `"2026-09-18T15:40:00+05:30"`. Date only → `"2026-09-18"`. |
| `reporting_delay_reason` | string \| null | Verbatim if given. |
| `company_is_recipient` | `true` \| `false` | **Always answer.** `true` = the filer won the order. `false` = the filer placed it. This is the field that catches BEML-style filings, and it is never `null`. |
| `stage` | enum | One of `L1`, `LoI`, `LoA`, `PO`, `contract`, `amendment`, `unknown`. `unknown` is allowed here — the document often genuinely does not say. |
| `is_follow_up` | boolean | `true` if this repeats or clarifies an earlier filing. Code decides this in production (§5.6); label it so the deterministic rule can be graded. |
| `multiple_orders` | boolean | `true` if the filing covers several distinct orders. |
| `orders` | array \| null | Only when `multiple_orders` is `true`: one object per order with `nature_of_order`, `consideration_raw`, `value_inr`, `value_span`. The top-level `value_inr` is then the **sum**, and `consideration_raw` is the aggregate string if the filing prints one, else `null`. |
| `is_scanned` | boolean | `true` if the PDF has no usable text layer. Counted in Spike D to settle the OCR question. |
| `labeller_notes` | string \| null | Anything odd. Read during the bake-off when a model disagrees with you. |

## Edge cases and what to do

- **Value not disclosed.** `consideration_raw: null`, `value_inr: null`, `value_span: null`.
  These are real and must be in the set — an extractor that invents a number here is the
  worst failure mode we have.
- **Foreign currency.** Record `currency` and the raw string. Leave `value_inr` **null** —
  §5.7 flags and does not convert, because the FX source is still Open.
- **A range** (`"₹10–12 crore"`). Put the range in `consideration_raw`, set `value_inr` to
  the **low** end, and say so in `labeller_notes`.
- **GST-inclusive.** Record the raw value; do not net it down. `value_inr` is the printed
  number.
- **Amendment or termination.** `stage: "amendment"`. If the filing states a revised total,
  that is `value_inr`; if it states only a delta, put the delta and note it.
- **Scanned PDF.** Set `is_scanned: true` and fill whatever you can read. Leave the rest
  `null` rather than transcribing.
