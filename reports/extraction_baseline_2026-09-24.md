# First extraction run — T0 parser alone, scored once

24 Sep 2026. Spike D arm 1: the annexure parser and unit normalizer, no model.
18 hand-labelled documents. Scored once, with nothing changed afterwards.

## The number

**8 / 18 — 44% exact `value_inr` match.**

| Split | Correct | Rate |
|---|---|---|
| Overall | 8 / 18 | **44%** |
| Where the filing states a value | 6 / 14 | 43% |
| Where it states none (null is the right answer) | 2 / 4 | 50% |

§6's gate is ≥ 95% for the full T0 → T1 → T2 chain. This is T0 on its own, which is what
sets how much work the paid tiers have to do. On this evidence the parser cannot carry the
extraction by itself, and the LLM tier is doing real work rather than mopping up edges.

The headline is measured on numbers, so it is unaffected by the two scoring caveats below.

## How it failed, in order of seriousness

**Two inventions — a number where the label says none.** This is the worst failure mode this
pipeline has, and it is the one CLAUDE.md's "never guess a number" exists to prevent.

- `WAAREEENER` — the filing's consideration row reads *"Supply of 2 GW Solar modules"*. The
  parser returned **₹2**. It read a physical capacity as money. There is no rupee marker
  anywhere in that string, and the normalizer defaults to INR when no marker is found.
- `BEML` — text reads *"…valued at over ₹ 5,400/- Crores"*, the label says null. Two separate
  problems stacked: the parser mis-sliced the span (below), and the label treats *"over X"*
  as not a stated value, which is a judgement the parser has no rule for.

**Seven misses — a value exists and the parser found nothing.** `BEL`, `CEINSYS`, `DBL`,
`GREENPOWER`, `NEWGEN`, `RAILTEL`, `VIVIANA`. Two distinct causes:

- `BEL` and `VIVIANA` located **0 of 7 annexure rows**. They are press-release style
  documents with no SEBI table at all, so there is nothing for a row parser to match.
  `BEL`'s value (`Rs.847 Crore`) is in prose.
- `RAILTEL` found the right row but the value ran onto the **next line**. The parser took
  only the same-line tail — `"or size of order(s)/contract(s) The Estimated Size of Order as
  per LoI is"` — and stopped before the digits.

**One wrong number, and it is a near-miss worth understanding.** `MCLOUD`: the filing prints
`₹44.60 Lakh (Rs. 44,60,400/-)`. The parser took the first numeral carrying a scale word and
returned 4,460,000. The label took the exact parenthetical figure, 4,460,400. Both readings
are defensible; the exact one is right, and the parser's rule of "prefer the numeral with a
scale word" is what chose wrong.

**A span-boundary bug underlies several of these.** Label patterns match inside longer words —
`(?:order|contract)\s+value` matches *"order value"* inside *"order **valued** at"* — so the
value slice begins mid-token (`"d at over ₹ 5,400/"`) and, in `BEML`'s case, lost the scale
word `Crores` off the end. That single defect produced both an invention and a wrong number.

## Per field

| Field | Correct | Rate | Filled by parser |
|---|---|---|---|
| `company_is_recipient` | 16 / 18 | 89% | 16 |
| `is_scanned` | 16 / 18 | 89% | 18 |
| `currency` | 15 / 18 | 83% | 18 |
| `gst_inclusive` | 13 / 18 | 72% | 2 |
| `execution_months` | 12 / 18 | 67% | 0 |
| `domestic_or_international` | 11 / 18 | 61% | 5 |
| `nature_of_order` | 7 / 18 | 39% | 11 |
| `execution_period_raw` | 5 / 18 | 28% | 0 |
| `awarding_entity` | 3 / 18 | 17% | 12 |
| `consideration_raw` | 0 / 18 | 0% | 15 |
| `stage` | 0 / 18 | 0% | 18 |

`company_is_recipient` at 89% is the standout: §5.4's whole reason for the `order_candidate`
bucket is that the category does not say who won, and a prose heuristic gets it right on 16
of 18. `execution_months` scores 67% while the parser filled **zero** — every one of those is
a case where the label is also null, so the field is untested rather than solved.

## Two caveats that make some of these numbers harsher than the parser deserves

**`stage` 0% is mostly a vocabulary mismatch, not a parse failure.** The labels use
`order`, `purchase_order`, `work_order`, `agreement`, `LOA`, `LOI`, `L1`, `contract`.
§5.6 and `tests/labelled/README.md` specify `L1 / LoI / LoA / PO / contract / amendment /
unknown`. So `GKENERGY` label `LOA` against parser `LoA`, and `RAILTEL` label `LOI` against
parser `LoI`, are the same answer scored as wrong on case; `MCLOUD` label `purchase_order`
against parser `PO` is the same concept under a different name. The enum needs settling
before this field means anything — **and settling it is a change, so it has not been made.**

**`consideration_raw` 0% is a convention difference.** The parser returns the whole cell
following the label; the labels record just the money phrase. The strings rarely match
exactly even when the parser found the right row, which is why `value_inr` at 44% is the
number to trust and `consideration_raw` at 0% is not a second, worse measurement of the same
thing.

**Provenance is unscored.** `value_span` is empty on all 18 labels, so §5.6's span check has
no ground truth. That check is the main defence against a model lifting a number from a date
or an unrelated line, and it is currently unmeasured.

## Extraction reach

Fourteen of 18 documents gave up 5 or more of the 7 annexure rows; four gave up 1 or 0. All
18 extracted a usable text layer via pdfplumber, and none needed the pypdf fallback. Two
labels mark the document scanned where the parser's threshold did not — `is_scanned` is the
gate that sends a filing to manual review under §5.5, so that disagreement matters more than
its 89% suggests.

| Rows found | Documents |
|---|---|
| 0 / 7 | BEL, VIVIANA |
| 1 / 7 | BEML, GKENERGY, HILINFRA, MCLOUD |
| 5 / 7 | AFFORDABLE, GPTINFRA, GREENPOWER, NEWGEN, WAAREEENER |
| 6 / 7 | CEINSYS, CPL, DBL, HECPROJECT, HEG, RAILTEL, ZAGGLE |

## Method, for the record

The parser and normalizer were written from §5.6 and §5.7 and committed (`8a24cd5`) **before**
the labels were opened, so this is a measurement rather than a fit. They were tuned only
against §5.7's published vectors, which predate the labelled set. Prior exposure to disclose:
the same 18 PDFs were read once before, to classify edge-case *categories* for
`CANDIDATES.md` — never values.

**This set is now spent as a clean baseline.** Any later score on these same 18 documents,
after fixing the defects above, measures the fix against data it was tuned on. The honest next
step is to fix the defects, re-score here as a *development* number, and keep a fresh set of
labelled filings in reserve for the number that decides anything.
