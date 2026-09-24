"""Score the T0 extractor against the hand-labelled set. `python -m tradebot.eval`

This is Spike D arm 1: the annexure parser and unit normalizer alone, with no model. Arm 1
answers the question that sets the whole LLM bill, because every field the parser fills is a
field no model is paid to read (§10).

The headline number is §6's acceptance metric: the share of documents where `value_inr`
matches the label exactly. Getting a *null* right counts as correct — a filing that does not
disclose a value must not produce a number, and inventing one there is the worst failure mode
this pipeline has (CLAUDE.md: never guess a number).
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tradebot.documents.text import extract
from tradebot.extractor.annexure import (
    parse_annexure,
    parse_bool,
    parse_company_is_recipient,
    parse_domestic,
    parse_stage,
)
from tradebot.units.money import parse_execution_months, parse_money

LABELLED = Path(__file__).resolve().parents[3] / "tests" / "labelled"

# Fields scored as exact matches after normalising case and whitespace.
STRING_FIELDS = ["consideration_raw", "execution_period_raw", "awarding_entity",
                 "nature_of_order"]
EXACT_FIELDS = ["domestic_or_international", "stage", "currency",
                "company_is_recipient", "gst_inclusive", "is_scanned"]


def norm(s) -> str | None:
    if s is None:
        return None
    return re.sub(r"\s+", " ", str(s)).strip().lower().strip(" .:-–—")


def as_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def predict(pdf: Path) -> dict:
    """Run the T0 chain over one PDF and return the same field names the labels use."""
    doc = extract(pdf)
    ann = parse_annexure(doc.text)
    consideration = ann.raw("consideration_raw")
    money = parse_money(consideration)
    period = ann.raw("execution_period_raw")
    return {
        "consideration_raw": consideration,
        "value_inr": money.value_inr,
        "value_span": ann.span("consideration_raw"),
        "currency": money.currency,
        "gst_inclusive": True if "gst_inclusive" in money.flags
                         else (False if "gst_exclusive" in money.flags else None),
        "execution_period_raw": period,
        "execution_months": parse_execution_months(period),
        "awarding_entity": ann.raw("awarding_entity"),
        "nature_of_order": ann.raw("nature_of_order"),
        "domestic_or_international": parse_domestic(ann.raw("domestic_or_international")),
        "promoter_interest": parse_bool(ann.raw("promoter_interest")),
        "related_party": parse_bool(ann.raw("related_party")),
        "stage": parse_stage(doc.text),
        "company_is_recipient": parse_company_is_recipient(doc.text),
        "is_scanned": doc.is_scanned,
        "_rows_found": ann.rows_found,
        "_pages": doc.pages,
        "_method": doc.method,
        "_chars": len(doc.text.strip()),
        "_quality": doc.quality,
    }


def main() -> int:
    pairs = []
    for label_path in sorted(LABELLED.glob("*.json")):
        if label_path.name == "_template.json":
            continue
        pdf = label_path.with_suffix(".pdf")
        if pdf.exists():
            pairs.append((pdf, json.loads(label_path.read_text(encoding="utf-8"))))

    if not pairs:
        print("no labelled pairs found")
        return 1

    print(f"Spike D arm 1 - annexure parser + unit normalizer, no model")
    print(f"{len(pairs)} labelled documents\n")

    rows = []
    for pdf, label in pairs:
        got = predict(pdf)
        rows.append((pdf.stem, label, got))

    # --- the headline: value_inr ------------------------------------------------------
    value_hits = value_null_hits = value_null_total = 0
    value_disclosed_hits = value_disclosed_total = 0
    invented = []
    missed = []
    wrong = []
    for stem, label, got in rows:
        want = as_decimal(label.get("value_inr"))
        have = got["value_inr"]
        if want is None:
            value_null_total += 1
            if have is None:
                value_hits += 1
                value_null_hits += 1
            else:
                invented.append((stem, have))
        else:
            value_disclosed_total += 1
            if have is not None and have == want:
                value_hits += 1
                value_disclosed_hits += 1
            elif have is None:
                missed.append(stem)
            else:
                wrong.append((stem, want, have))

    n = len(rows)
    print("=" * 74)
    print("HEADLINE - exact value_inr match (Sect.6's acceptance metric)")
    print("=" * 74)
    print(f"  overall                  {value_hits}/{n}  ({value_hits/n:.0%})")
    print(f"  where a value is stated  {value_disclosed_hits}/{value_disclosed_total}"
          f"  ({value_disclosed_hits/value_disclosed_total:.0%})"
          if value_disclosed_total else "")
    print(f"  where none is stated     {value_null_hits}/{value_null_total}"
          f"  ({value_null_hits/value_null_total:.0%})" if value_null_total else "")
    print(f"\n  Sect.6 gate is >= 95% for the full T0->T1->T2 chain. This is T0 alone.")

    if invented:
        print(f"\n  INVENTED a number where the filing states none ({len(invented)}) "
              f"- the worst failure mode:")
        for stem, have in invented:
            print(f"     {stem:<28} produced {have}")
    if missed:
        print(f"\n  found nothing where a value exists ({len(missed)}):")
        for stem in missed:
            print(f"     {stem}")
    if wrong:
        print(f"\n  wrong number ({len(wrong)}):")
        for stem, want, have in wrong:
            ratio = (have / want) if want else None
            hint = f"  ({ratio:.6g}x)" if ratio else ""
            print(f"     {stem:<28} want {want}  got {have}{hint}")

    # --- per field --------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("PER FIELD")
    print("=" * 74)
    print(f"  {'field':<28}{'correct':>9}{'of':>4}{'rate':>7}   {'filled by parser':>17}")
    for fname in STRING_FIELDS + EXACT_FIELDS + ["execution_months"]:
        scored = correct = produced = 0
        for stem, label, got in rows:
            want = label.get(fname)
            have = got.get(fname)
            if fname == "execution_months":
                w, h = as_decimal(want), have
                ok = (w is None and h is None) or (w is not None and h is not None and w == h)
            elif fname in STRING_FIELDS:
                ok = norm(want) == norm(have)
            else:
                ok = want == have
            scored += 1
            correct += bool(ok)
            produced += have is not None and have != ""
        print(f"  {fname:<28}{correct:>9}{scored:>4}{correct/scored:>7.0%}"
              f"{produced:>17}")

    # --- what the parser could even see ----------------------------------------------
    print("\n" + "=" * 74)
    print("EXTRACTION REACH - annexure rows located per document (of 7)")
    print("=" * 74)
    for stem, label, got in sorted(rows, key=lambda r: r[2]["_rows_found"]):
        flag = "  SCANNED" if got["is_scanned"] else ""
        quality_flag = f"  quality={got['_quality']}" if got["_quality"] != "ok" else ""
        print(f"  {stem:<28} {got['_rows_found']}/7 rows   {got['_pages']} pages, "
              f"{got['_chars']:>6} chars, {got['_method']}{flag}{quality_flag}")

    spans = sum(1 for _, label, _ in rows if label.get("value_span"))
    print(f"\nprovenance not scored: value_span is filled on {spans}/{n} labels, so the "
          f"Sect.5.6 span check has no ground truth yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
