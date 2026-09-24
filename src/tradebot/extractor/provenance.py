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
    """True only if `value_span` occurs verbatim (whitespace aside) in `doc_text` AND
    parsing `value_span` on its own produces exactly `value_inr`.

    A span that exists in the document but parses to a different number fails - that is
    the case a substring-only check would miss, and it is what actually catches a model
    that quotes something real while reporting a number it didn't come from.
    """
    if not value_span or value_inr is None:
        return False
    if _collapse(value_span) not in _collapse(doc_text):
        return False
    span_value = parse_money(value_span).value_inr
    return span_value is not None and span_value == value_inr
