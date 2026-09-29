"""The §5.6 provenance check: a value is trusted only if it can be traced back to an exact
quote in the source document, never on substring presence alone.

Applies identically to the annexure parser and the LLM (§5.6: "both the parser and the
model return the exact quoted span they took the value from"). A document containing
"13.51" anywhere would "verify" a value lifted from a date or an unrelated line item if the
check were substring-only, so it checks two independent things: the span is really in the
document, and parsing the span alone reproduces the same value.
"""

from __future__ import annotations

import re
from decimal import Decimal

from tradebot.units.money import parse_money

_WS = re.compile(r"\s+")


def _collapse(text: str) -> str:
    """Whitespace-insensitive, but not otherwise forgiving: no word is added, dropped or
    corrected. pdfplumber can render the same text with slightly different internal
    spacing between two reads of the same page, which is the only slack this allows.
    """
    return _WS.sub(" ", text or "").strip()


def verify(doc_text: str, value_span: str | None, value_inr: Decimal | None) -> bool:
    """True only if some continuous run of words from `value_span` occurs verbatim
    (whitespace aside) in `doc_text` AND parses, on its own, to exactly `value_inr`.

    The whole span is tried first, then shorter runs. A part is allowed (Sravanth, 29 Sep
    2026) because PDF tables come out with their columns interleaved: RAILTEL's text reads
    "Rs.\\n(in INR); 38,59,27,045/-", the label column inside the value, so a model quoting
    the value as a reader sees it, "Rs. 38,59,27,045/-", quotes something that is not one
    piece of the text. In the first backfill batch that failed 54 correct answers, 51 of
    which pass this rule. It stays strict where it matters: the number still has to come
    verbatim from the document and parse to the same value, so a real passage that parses
    to a different number still fails - the case a substring-only check would miss.
    """
    if not value_span or value_inr is None:
        return False
    doc = _collapse(doc_text)
    words = value_span.split()
    for size in range(len(words), 0, -1):            # longest first: the whole span
        for start in range(len(words) - size + 1):
            piece = " ".join(words[start:start + size])
            if piece in doc and parse_money(piece).value_inr == value_inr:
                return True
    return False
