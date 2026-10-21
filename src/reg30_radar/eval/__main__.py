"""Score the T0 extractor against the hand-labelled set. `python -m reg30_radar.eval`

This is Spike D arm 1: the annexure parser and unit normalizer alone, with no model. Arm 1
answers the question that sets the whole LLM bill, because every field the parser fills is a
field no model is paid to read (§10).

The headline number is §6's acceptance metric: the share of documents where `value_inr`
matches the label exactly. Getting a *null* right counts as correct — a filing that does not
disclose a value must not produce a number, and inventing one there is the worst failure mode
this pipeline has (CLAUDE.md: never guess a number).

Two more views, added 20 Oct 2026 (GATE 1 audit), because the bare parser score is not what
production does:
- **T0 as production gates it.** Production accepts the parser's value only when it passes
  provenance and is not suspect (`orders.run.t0_value`); anything else goes on to the LLM. So a
  gated null where the label has a value is an escalation, not an error, and the number that
  matters is how often a value production would *accept* is wrong.
- **`--stored`**: the full chain's own stored answers, found by the labelled PDF's SHA-256 in
  both databases. No model is called; this scores what the T0 -> T1 -> recheck chain already
  produced on the labelled documents it happened to process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from reg30_radar.documents.text import extract
from reg30_radar.extractor.annexure import (
    parse_annexure,
    parse_bool,
    parse_company_is_recipient,
    parse_domestic,
    parse_stage,
)
from reg30_radar.orders.run import t0_value
from reg30_radar.units.money import parse_execution_months, parse_money

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
    *_, gate_ok = t0_value(doc.text)
    return {
        "consideration_raw": consideration,
        "value_inr": money.value_inr,
        "gated_value_inr": money.value_inr if gate_ok else None,
        "value_flags": sorted(money.flags),
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


def score_gated(rows) -> dict:
    """Score T0 as production uses it: (stem, label, got) rows -> outcome lists.
    `escalated` is a value the gate held back for the LLM; `accepted_wrong` and `invented` are
    values production would have stored as verified, and are the failures that count."""
    out = {"correct": [], "escalated": [], "accepted_wrong": [], "invented": []}
    for stem, label, got in rows:
        want, have = as_decimal(label.get("value_inr")), got["gated_value_inr"]
        if have == want:
            out["correct"].append(stem)
        elif have is None:
            out["escalated"].append(stem)
        elif want is None:
            out["invented"].append((stem, have))
        else:
            out["accepted_wrong"].append((stem, want, have))
    return out


def judge_stored(want: Decimal | None, status: str | None, have: Decimal | None) -> str:
    """One labelled document against the chain's stored answer. Only a `verified` value
    is an answer; review and pending rows are the chain declining to answer."""
    if status is None:
        return "not processed"
    if status != "verified":
        return f"no answer ({status})"
    if have == want:
        return "correct"
    return "invented" if want is None else "wrong"


STORED_SQL = """
select oe.review_status, oe.value_inr, oe.path, oe.value_flags
from documents d join order_extractions oe on oe.document_id = d.id
where d.sha256 = %s
order by oe.id desc limit 1
"""


def stored_main(pairs) -> int:
    from reg30_radar.common.db import backfill_url, connect

    print("Full chain, stored answers - found by SHA-256, no model called\n")
    results = []
    for name, url in (("live", None), ("backfill", backfill_url())):
        with connect(url) as conn:
            conn.read_only = True
            for pdf, label in pairs:
                sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
                row = conn.execute(STORED_SQL, (sha,)).fetchone()
                if row:
                    results.append((pdf.stem, name, label, row))
    seen = set()
    counts = {}
    for stem, db, label, (status, value, path, flags) in results:
        want = as_decimal(label.get("value_inr"))
        verdict = judge_stored(want, status, value)
        counts[verdict] = counts.get(verdict, 0) + 1
        seen.add(stem)
        print(f"  {stem:<26} {db:<9} {verdict:<24} want {want}  stored {value}"
              f"  [{path}{'; ' + ','.join(flags) if flags else ''}]")
    print(f"\n  labelled documents found: {len(seen)}/{len(pairs)} "
          f"(rows: {len(results)}, a document in both databases counts twice)")
    for k, v in sorted(counts.items()):
        print(f"    {k:<24} {v}")
    answered = counts.get("correct", 0) + counts.get("wrong", 0) + counts.get("invented", 0)
    if answered:
        print(f"  exact value_inr where the chain answered: {counts.get('correct', 0)}/{answered}")
    print("\n  Too few documents for a rate; read it as a check, not a measurement (§6).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reg30_radar.eval")
    parser.add_argument("--stored", action="store_true",
                        help="score the full chain's stored answers (both databases, no LLM)")
    args = parser.parse_args(argv)
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
    if args.stored:
        return stored_main(pairs)

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

    g = score_gated(rows)
    print(f"\n  T0 as production gates it (provenance + suspect check, orders.run.t0_value):")
    print(f"    correct {len(g['correct'])}/{n}; held back for the LLM {len(g['escalated'])};"
          f" accepted but wrong {len(g['accepted_wrong'])}; invented {len(g['invented'])}")
    for stem, want, have in g["accepted_wrong"]:
        print(f"     ACCEPTED WRONG {stem:<22} want {want}  got {have}")
    for stem, have in g["invented"]:
        print(f"     INVENTED       {stem:<22} got {have}")

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
