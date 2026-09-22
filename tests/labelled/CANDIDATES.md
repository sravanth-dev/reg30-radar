# Candidate order filings for the labelled set

Nineteen PDFs, one per company, chosen to span the D22 market-cap bands and the extraction
edge cases. Label any ten. Fill `_template.json` per [README.md](README.md), one JSON beside
each PDF with the same stem.

**No values appear below, by design.** The selection was made from filing metadata and from
structural signals in the text (does the document mention a letter of intent, does it use GST
wording, does it have a text layer). Nothing about the amounts is stated here, so your labels
stay independent of anything I have seen.

| File | Cap band | Why it was picked |
|---|---|---|
| `AFFORDABLE_20260917_1.pdf` | <₹1k cr | Value-not-disclosed wording with an approximation qualifier — exercises the "store null and flag" path. |
| `BEL_20260731_1.pdf` | >₹10k cr | Largest cap in the set, defence, standard SEBI annexure. The easy baseline everything else is measured against. |
| `BEML_20260918_1.pdf` | >₹10k cr | Filed under `Awarding of order(s)/contract(s)` — the §5.4 category that does not say whether the company won the order or placed it. |
| `CEINSYS_20260917_1.pdf` | ₹1k–10k cr | Foreign-currency order. FX is still Open, so this tests flag-and-do-not-convert. |
| `CPL_20260917_1.pdf` | <₹1k cr | L1 / lowest-bidder stage, GST wording and an approximation qualifier in one document — three normalizer paths at once. |
| `DBL_20260921_1.pdf` | ₹1k–10k cr | L1 stage with explicit GST treatment, mid-cap infrastructure. |
| `GKENERGY_20260921_1.pdf` | ₹1k–10k cr | Letter of award over four pages with GST stated — tests `stage = LoA`. |
| `GPTINFRA_20260917_1.pdf` | ₹1k–10k cr | L1 with GST wording; also one of the 18 Sep order filers, so it ties back to the reconciliation work. |
| `GREENPOWER_20260917_1.pdf` | ₹1k–10k cr | Filed under `General Updates` — the §5.4 case that read as the company *placing* an EPC order rather than winning one. |
| `HECPROJECT_20260921_1.pdf` | <₹1k cr | Smallest tracked cap in the set (~₹130 cr). Micro-cap document formatting. |
| `HEG_20260918_1.pdf` | unlisted in the 18 Sep mcap file | Amendment / revision wording — tests `stage = amendment`. |
| `HILINFRA_20260918_1.pdf` | <₹1k cr | The §5.4 headline case: a genuine order win that arrives under `Press Release`, which the router sends to `catch_all`. |
| `JISLDVREQS_20260917_1.pdf` | <₹1k cr | **Scanned, no text layer** — the only one in the set. This single file decides the OCR-versus-manual-review question in §11. |
| `MCLOUD_20260921_1.pdf` | ₹1k–10k cr | Plain order, mid-cap. A clean control with no special signal. |
| `NEWGEN_20260921_1.pdf` | ₹1k–10k cr | Foreign currency **and** value-not-disclosed in the same filing — two hard paths combined. |
| `RAILTEL_20260917_1.pdf` | ₹1k–10k cr | Letter of intent — tests `stage = LoI` against a firm order, which matters because an LoI is not yet revenue. |
| `VIVIANA_20260917_1.pdf` | <₹1k cr | LoI and L1 language in one single-page filing — the stage field has to pick one. |
| `WAAREEENER_20260921_1.pdf` | >₹10k cr | Large-cap renewables, plain order. Control at the top of the cap range. |
| `ZAGGLE_20260918_1.pdf` | ₹1k–10k cr | 7 MB for two pages, image-heavy but with a usable text layer. Stresses pdfplumber's memory against the 512 MB container limit in §9. |

## Two gaps, stated rather than papered over

- **Several distinct orders in one filing** — not found in these nineteen. It is a real
  pattern and the schema has `multiple_orders` / `orders` for it, but nothing here exercises
  that path. Worth adding when one appears in the backfill.
- **A filing where the company definitively placed the order** — `BEML` and `GREENPOWER` are
  the candidates *by category*, and that is why they are in the set, but I did not confirm the
  direction from the document text, because doing so and telling you would defeat the point of
  labelling blind. If both turn out to be ordinary wins, `company_is_recipient = false` stays
  untested and needs a deliberate hunt.

Also note `amendment or revision` matched seven files. That signal is loose — it fires on the
word "revised" anywhere, including boilerplate — so treat it as a hint, not a classification.
`HEG` is the one picked deliberately for it.
