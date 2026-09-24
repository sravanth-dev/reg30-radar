"""Deterministic annexure parser: the T0 half of §5.6, with no model involved.

SEBI's circular of 13 Jul 2023 fixes the disclosure format for order wins, so most filings
carry the same seven labelled rows. This finds those rows and returns the **raw strings plus
the span each came from** — it never converts anything, because §5.6 puts every conversion in
code that can be unit-tested (`tradebot.units.money`) and because the provenance check needs
the untouched span.

Written from the spec, not from the labelled set, so the first score is a measurement rather
than a fit. §5.6 warns that labels vary in wording and even in spelling ("Board commercial
consideration" for "Broad…"), so matching is on distinctive keywords, never on a whole label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each field maps to the keyword patterns that identify its row. Order matters within a
# field: the more specific pattern is tried first.
LABELS: dict[str, list[str]] = {
    "awarding_entity": [
        r"name\s+of\s+the\s+entity\s+awarding",
        r"entity\s+awarding\s+the\s+(?:order|contract)",
        r"name\s+of\s+the\s+(?:awarding\s+)?(?:entity|party|customer|client)",
        r"awarded\s+by",
    ],
    "domestic_or_international": [
        r"whether\s+domestic\s+or\s+international",
        r"domestic\s+or\s+international",
        r"domestic\s*/\s*international",
    ],
    "nature_of_order": [
        r"nature\s+of\s+(?:the\s+)?(?:order|contract|work)",
        r"brief\s+description\s+of\s+the\s+(?:order|contract)",
    ],
    # §5.6: match loosely on "consideration". The misspelling "Board commercial
    # consideration" is real and is why the word alone carries the match.
    "consideration_raw": [
        r"broad\s+consideration",
        r"board\s+(?:commercial\s+)?consideration",
        r"consideration",
        r"size\s+of\s+the\s+(?:order|contract)",
        r"(?:order|contract)\s+value",
        r"value\s+of\s+the\s+(?:order|contract)",
    ],
    "promoter_interest": [
        r"promoter\s*/?\s*promoter\s+group",
        r"promoter",
    ],
    "related_party": [
        r"related\s+part(?:y|ies)",
    ],
    "execution_period_raw": [
        r"time\s*period\s+for\s+execution",
        r"(?:period|timeline|time)\s+(?:of|for)\s+(?:execution|completion)",
        r"execution\s+(?:period|time)",
        r"completion\s+(?:period|time|schedule)",
    ],
}

# A label row usually ends in a separator before its value. Two or more spaces also count,
# because pdfplumber renders a table cell boundary as a run of spaces.
_SEPARATOR = re.compile(r"\s*(?::|-|–|—|–|\t| {2,})\s*")


@dataclass
class Field:
    value: str | None = None
    span: str | None = None     # the exact source text the value was taken from (§5.6)
    label_seen: str | None = None


@dataclass
class Annexure:
    fields: dict[str, Field] = field(default_factory=dict)
    rows_found: int = 0
    is_tabular: bool = False

    def raw(self, name: str) -> str | None:
        f = self.fields.get(name)
        return f.value if f else None

    def span(self, name: str) -> str | None:
        f = self.fields.get(name)
        return f.span if f else None


def _clean(value: str) -> str:
    value = value.replace(" ", " ")
    value = re.sub(r"\s+", " ", value).strip()
    # Drop a trailing label fragment left behind when two cells run together.
    return value.strip(" .:-–—|")


def _value_after(lines: list[str], index: int, match_end: int) -> tuple[str, str] | None:
    """Take the value that follows a label, from the same line or the next useful one.

    Returns (value, span) where span is the untouched source text, which is what the
    provenance check in §5.6 verifies against the document.
    """
    line = lines[index]
    tail = line[match_end:]
    sep = _SEPARATOR.match(tail)
    if sep:
        tail = tail[sep.end():]
    tail_clean = _clean(tail)
    if tail_clean:
        return tail_clean, tail.strip()

    # The label occupies the whole line, so the value is on a following line. Skip blanks,
    # and stop rather than swallow the next label.
    for j in range(index + 1, min(index + 4, len(lines))):
        candidate = lines[j]
        if not candidate.strip():
            continue
        if _looks_like_label(candidate):
            return None
        cleaned = _clean(candidate)
        if cleaned:
            return cleaned, candidate.strip()
    return None


def _looks_like_label(line: str) -> bool:
    low = line.lower()
    return any(re.search(p, low) for pats in LABELS.values() for p in pats)


def parse_annexure(text: str) -> Annexure:
    """Pull the labelled rows out of one filing's extracted text."""
    out = Annexure()
    if not text or not text.strip():
        return out

    lines = text.splitlines()
    out.is_tabular = sum(1 for l in lines if re.search(r" {2,}\S", l)) > len(lines) * 0.2

    for name, patterns in LABELS.items():
        found: Field | None = None
        for pattern in patterns:
            rx = re.compile(pattern, re.I)
            for i, line in enumerate(lines):
                m = rx.search(line)
                if not m:
                    continue
                got = _value_after(lines, i, m.end())
                if got:
                    found = Field(value=got[0], span=got[1], label_seen=m.group(0))
                    break
            if found:
                break
        out.fields[name] = found or Field()

    out.rows_found = sum(1 for f in out.fields.values() if f.value)
    return out


BOOL_YES = re.compile(r"\b(yes|true)\b", re.I)
BOOL_NO = re.compile(r"\b(no|nil|none|not\s+applicable|n\.?a\.?|false)\b", re.I)


def parse_bool(raw: str | None) -> bool | None:
    """Yes/No rows. Returns None when the filing does not say, never a guess."""
    if not raw:
        return None
    # "No" is checked first: "Not applicable" contains neither a bare yes nor a bare no in
    # some renderings, and a stray "yes" inside a longer sentence should not win.
    if BOOL_NO.search(raw):
        return False
    if BOOL_YES.search(raw):
        return True
    return None


DOMESTIC = re.compile(r"\bdomestic\b", re.I)
INTERNATIONAL = re.compile(r"\binternational|\boverseas|\bexport", re.I)


def parse_domestic(raw: str | None) -> str | None:
    if not raw:
        return None
    if INTERNATIONAL.search(raw):
        return "international"
    if DOMESTIC.search(raw):
        return "domestic"
    return None


STAGE_PATTERNS = [
    ("amendment", r"\bamend|\brevis(?:ed|ion)|\bterminat"),
    ("LoA", r"letter\s+of\s+award|\bLoA\b|\bLOA\b"),
    ("LoI", r"letter\s+of\s+inten|\bLoI\b|\bLOI\b"),
    ("L1", r"\bL-?1\b|lowest\s+bidder|lowest\s+evaluated"),
    ("PO", r"purchase\s+order|\bP\.?O\.?\b|work\s+order"),
    ("contract", r"\bcontract\b|\bagreement\b"),
]


def parse_stage(text: str) -> str:
    """Order stage from the whole document. `unknown` when nothing matches (§5.6)."""
    if not text:
        return "unknown"
    for stage, pattern in STAGE_PATTERNS:
        if re.search(pattern, text, re.I):
            return stage
    return "unknown"


# The company placed the order rather than won it. §5.4's BEML and GREENPOWER cases.
PLACED = re.compile(
    r"\b(?:has\s+)?(?:awarded|placed|issued)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:work\s+|purchase\s+)?(?:order|contract|LoA|LoI)\s+(?:to|on|in\s+favour\s+of)\b", re.I)
RECEIVED = re.compile(
    r"\b(?:has\s+)?(?:received|secured|bagged|been\s+awarded|won|awarded\s+with)\b", re.I)


def parse_company_is_recipient(text: str) -> bool | None:
    """True when the filer won the order, False when it placed one, None when unclear.

    §5.6 makes this a required judgment, and §6's escalation trigger 3 fires when it comes
    back unknown — so returning None here is a real answer, not a failure to try.
    """
    if not text:
        return None
    placed = PLACED.search(text)
    received = RECEIVED.search(text)
    if placed and not received:
        return False
    if received and not placed:
        return True
    if placed and received:
        # Both readings present: the earlier statement usually frames the filing.
        return received.start() < placed.start()
    return None
