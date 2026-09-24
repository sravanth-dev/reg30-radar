"""Turn the raw consideration string a filing prints into Decimal rupees.

Written from ARCHITECTURE.md §5.7 and its test vectors, deliberately without looking at the
hand-labelled set, so the first score against those labels is a measurement rather than a
fit. See §5.6: the model never normalizes; every conversion happens here where it is
testable.

Money is Decimal throughout (CLAUDE.md). Never float: 13.51 crore as a float is
135099999.99999999, and the provenance check would then reject a correct extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Scale words, longest first so "crores" wins before "crore" and "cr".
SCALES: list[tuple[str, Decimal]] = [
    ("crores", Decimal(10) ** 7),
    ("crore", Decimal(10) ** 7),
    ("crs", Decimal(10) ** 7),
    ("cr", Decimal(10) ** 7),
    ("lakhs", Decimal(10) ** 5),
    ("lakh", Decimal(10) ** 5),
    ("lacs", Decimal(10) ** 5),
    ("lac", Decimal(10) ** 5),
    ("billion", Decimal(10) ** 9),
    ("bn", Decimal(10) ** 9),
    ("million", Decimal(10) ** 6),
    ("mn", Decimal(10) ** 6),
    ("thousand", Decimal(10) ** 3),
]

# Currency markers. INR forms mean rupees; everything else is foreign and is never
# converted, because the FX source is still Open (§11) and guessing a rate would be
# guessing a number.
INR_MARKERS = ("₹", "rs.", "rs", "inr", "rupees", "inr.")
FOREIGN = {
    "usd": "USD", "us$": "USD", "$": "USD", "dollar": "USD",
    "eur": "EUR", "€": "EUR", "euro": "EUR",
    "gbp": "GBP", "£": "GBP",
    "jpy": "JPY", "¥": "JPY",
    "aed": "AED", "sgd": "SGD", "chf": "CHF",
}

APPROX = re.compile(r"\b(approx\.?|approximately|about|circa|around)\b", re.I)

# GST is detected by proximity rather than by one regex over the whole phrase. Filings
# write it as "incl. of GST", "(including GST)", "plus GST" and "excluding GST", and a
# single pattern trying to span all of those kept failing on the abbreviation: after
# "incl." a \b cannot match, because a full stop and a space are both non-word characters.
_GST = re.compile(r"\bGST\b", re.I)
_GST_EXCLUDES = re.compile(r"\bexcl|\bexclusive|\bplus\b|\bbefore\b|\+\s*$", re.I)
_GST_INCLUDES = re.compile(r"\bincl|\binclusive\b|\bwith\b", re.I)


def _gst_flag(text: str) -> str | None:
    """Look just before each mention of GST and decide which way it points."""
    for m in _GST.finditer(text):
        before = text[max(0, m.start() - 40):m.start()]
        if _GST_EXCLUDES.search(before):
            return "gst_exclusive"
        if _GST_INCLUDES.search(before):
            return "gst_inclusive"
    return None

# Indian number words, for filings that spell the amount out.
UNITS_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
WORD_SCALES = {
    "hundred": Decimal(100), "thousand": Decimal(1000),
    "lakh": Decimal(10) ** 5, "lakhs": Decimal(10) ** 5,
    "crore": Decimal(10) ** 7, "crores": Decimal(10) ** 7,
}


@dataclass
class Money:
    """The outcome of reading one consideration string."""

    value_inr: Decimal | None = None
    currency: str = "INR"
    low_inr: Decimal | None = None      # set only for a range
    high_inr: Decimal | None = None
    flags: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return self.value_inr is not None


def _to_decimal(number_text: str) -> Decimal | None:
    """Parse a numeral, tolerating Indian grouping and a trailing '/-'.

    Indian grouping (65,02,160.50) is not three-digit grouping, so commas cannot be
    validated by position — they are simply removed. That is safe here because a comma
    never means a decimal point in these filings.
    """
    cleaned = number_text.replace(",", "").replace("/-", "").replace("/", "").strip()
    cleaned = cleaned.rstrip("-").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _words_to_decimal(text: str) -> Decimal | None:
    """"Thirteen Crore Fifty One Lakh" -> 135100000.

    Indian scale words are multiplicative left to right within a group and additive
    between groups, which is why this accumulates a running group and flushes it on each
    scale word rather than multiplying the whole total.
    """
    tokens = re.findall(r"[a-z]+", text.lower())
    if not tokens:
        return None
    total = Decimal(0)
    group = Decimal(0)
    saw_number = False
    for tok in tokens:
        if tok in UNITS_WORDS:
            group += Decimal(UNITS_WORDS[tok])
            saw_number = True
        elif tok in WORD_SCALES:
            if group == 0:
                group = Decimal(1)
            if tok == "hundred":
                group *= WORD_SCALES[tok]
            else:
                total += group * WORD_SCALES[tok]
                group = Decimal(0)
            saw_number = True
        elif tok in ("and", "only", "rupees", "rupee"):
            continue
        else:
            # An unknown word means this is prose, not a spelled-out amount.
            return None
    if not saw_number:
        return None
    return total + group


def detect_currency(text: str) -> str:
    low = text.lower()
    # Check foreign first: "USD 5 million" also contains no rupee marker, but "Rs" can
    # appear in company names, so an explicit foreign marker is the stronger signal.
    for marker, code in FOREIGN.items():
        if marker in low:
            # "$" is inside "US$", already handled; guard against matching a bare "$" that
            # is really part of a longer token we already matched.
            return code
    for marker in INR_MARKERS:
        if marker in low:
            return "INR"
    return "INR"


def _scale_after(text: str, end: int) -> tuple[Decimal, str] | None:
    """Find the scale word immediately following a numeral, if any."""
    tail = text[end:end + 24].lower()
    for word, mult in SCALES:
        if re.match(rf"\s*{re.escape(word)}\b", tail):
            return mult, word
    return None


def parse_money(raw: str | None) -> Money:
    """Read one consideration string. Returns Money with value_inr None when unreadable."""
    out = Money()
    if not raw or not raw.strip():
        out.flags.add("empty")
        return out

    text = raw.strip()
    out.currency = detect_currency(text)

    if APPROX.search(text):
        out.flags.add("approx")
    gst = _gst_flag(text)
    if gst:
        out.flags.add(gst)

    numbers = list(re.finditer(r"\d[\d,]*(?:\.\d+)?", text))

    if not numbers:
        # No digits: it may still be spelled out in words.
        spelled = _words_to_decimal(text)
        if spelled is not None and spelled > 0:
            out.flags.add("number_in_words")
            if out.currency == "INR":
                out.value_inr = spelled
            else:
                out.flags.add("foreign_currency_not_converted")
            return out
        out.flags.add("no_number_found")
        return out

    # A range: two numerals joined by a dash or "to", both taking the same scale.
    range_match = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d[\d,]*(?:\.\d+)?)", text)
    if range_match:
        lo = _to_decimal(range_match.group(1))
        hi = _to_decimal(range_match.group(2))
        scale = _scale_after(text, range_match.end())
        mult = scale[0] if scale else Decimal(1)
        if lo is not None and hi is not None and hi > lo:
            out.flags.add("range")
            out.low_inr = lo * mult
            out.high_inr = hi * mult
            # §5.7 leaves which end to use to the caller; the low end is the conservative
            # choice and is what the calculator should see.
            if out.currency == "INR":
                out.value_inr = out.low_inr
            else:
                out.flags.add("foreign_currency_not_converted")
            return out

    # Otherwise: take the numeral that carries a scale word, else the largest numeral.
    best: tuple[Decimal, str | None] | None = None
    for m in numbers:
        val = _to_decimal(m.group(0))
        if val is None:
            continue
        scale = _scale_after(text, m.end())
        if scale is not None:
            best = (val * scale[0], scale[1])
            break
        if best is None or val > best[0]:
            best = (val, None)

    if best is None:
        out.flags.add("no_number_found")
        return out

    if best[1] is None:
        # A bare numeral with no scale word is taken as rupees, which is what filings mean
        # when they print "INR 65,02,160.50/-".
        out.flags.add("no_scale_word")

    if out.currency != "INR":
        out.flags.add("foreign_currency_not_converted")
        return out

    out.value_inr = best[0]
    return out


MONTH_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:calendar\s+)?months?\b", re.I), Decimal(1)),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:calendar\s+)?years?\b", re.I), Decimal(12)),
    (re.compile(r"(\d+(?:\.\d+)?)\s*weeks?\b", re.I), Decimal(1) / Decimal(4)),
    (re.compile(r"(\d+(?:\.\d+)?)\s*days?\b", re.I), Decimal(1) / Decimal(30)),
]


def parse_execution_months(raw: str | None) -> Decimal | None:
    """Execution period to months. Anything unclear returns None, never a guess (§5.7).

    Absolute dates ("Delivery Completion is November, 2026") need the filing date as a
    reference and are handled by the caller, which has it; this function only reads
    durations.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    for pattern, mult in MONTH_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                n = Decimal(m.group(1))
            except InvalidOperation:
                return None
            months = n * mult
            return months.quantize(Decimal("0.1")) if months % 1 else months
    return None
