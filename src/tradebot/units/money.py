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
from functools import lru_cache

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

# Currency markers. INR forms mean rupees; everything else is foreign. A foreign amount is
# converted only at a fixed rate Sravanth has set in config/fx.yaml (USD at Rs 94, 29 Sep
# 2026); any other currency is never converted, because inventing a rate would be guessing
# a number (§11).
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


@lru_cache(maxsize=1)
def fx_rates() -> dict[str, Decimal]:
    """Fixed rupee rates per foreign currency, from config/fx.yaml."""
    from tradebot.common.config import fx
    return {code: Decimal(str(rate)) for code, rate in (fx().get("rates_to_inr") or {}).items()}


def _rate_to_inr(currency: str) -> Decimal | None:
    """1 for rupees; the configured fixed rate for a foreign currency that has one; None for
    a foreign currency without one, which is never converted."""
    return Decimal(1) if currency == "INR" else fx_rates().get(currency)


def _set_value(out: Money, amount: Decimal) -> None:
    """Store an amount read in `out.currency` as rupees: converted at the fixed rate when the
    currency has one, left unset (and flagged) when it does not."""
    rate = _rate_to_inr(out.currency)
    if rate is None:
        out.flags.add("foreign_currency_not_converted")
        return
    if out.currency != "INR":
        out.flags.add("fx_converted")
        amount = (amount * rate).quantize(Decimal("0.01"))
    out.value_inr = amount


# Indian scale words are rupee units by convention, whatever else the string mentions.
INDIAN_SCALES = {"crores", "crore", "crs", "cr", "lakhs", "lakh", "lacs", "lac"}


def _marker_in(window: str) -> str | None:
    for marker, code in FOREIGN.items():
        if marker in window:
            return code
    for marker in INR_MARKERS:
        if marker in window:
            return "INR"
    return None


def _currency_of(text: str, start: int, end: int, scale_word: str | None) -> str:
    """The currency of the one amount that was read, decided beside it, not from the whole
    string. Once a foreign amount converts to a rupee value this matters: "INR 651 Crores
    (USD 73.47 million)" names both, and taking the string's currency would multiply the
    crore figure by the dollar rate. Checked in order: a marker in the 12 characters before
    the number, a crore/lakh scale, a marker in the 16 characters after it, and only then
    the whole string."""
    marked = _marker_in(text[max(0, start - 12):start].lower())
    if marked:
        return marked
    if scale_word in INDIAN_SCALES:
        return "INR"
    return _marker_in(text[end:end + 16].lower()) or detect_currency(text)


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
        # "/-" may sit between the numeral and its scale word: LCCPROJECT printed
        # "₹58.53/- Crore", read as ₹58.53 until 27 Sep 2026.
        if re.match(rf"\s*(?:/-)?\s*{re.escape(word)}\b", tail):
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
            _set_value(out, spelled)
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
            out.currency = _currency_of(text, range_match.start(), range_match.end(),
                                        scale[1] if scale else None)
            rate = _rate_to_inr(out.currency)
            if rate is None:
                out.flags.add("foreign_currency_not_converted")
                return out
            if out.currency != "INR":
                out.flags.add("fx_converted")
                mult = mult * rate
            out.low_inr = lo * mult
            out.high_inr = hi * mult
            # §5.7 leaves which end to use to the caller; the low end is the conservative
            # choice and is what the calculator should see.
            out.value_inr = out.low_inr
            return out

    # Otherwise: take the numeral that carries a scale word, else the largest numeral.
    best: tuple[Decimal, str | None, re.Match] | None = None
    for m in numbers:
        val = _to_decimal(m.group(0))
        if val is None:
            continue
        scale = _scale_after(text, m.end())
        if scale is not None:
            best = (val * scale[0], scale[1], m)
            break
        if best is None or val > best[0]:
            best = (val, None, m)

    if best is None:
        out.flags.add("no_number_found")
        return out

    value, scale_word, chosen = best
    if scale_word is None:
        # A bare numeral with no scale word is taken as rupees, which is what filings mean
        # when they print "INR 65,02,160.50/-".
        out.flags.add("no_scale_word")
        value = _check_against_words(text, value, out.flags)

    out.currency = _currency_of(text, chosen.start(), chosen.end(), scale_word)
    _set_value(out, value)
    return out


# The spelled-out amount a filing often prints beside the numeral. Only runs containing one
# of these count, so a stray "one" or "two" in the text is never read as an amount.
_AMOUNT_SCALE_WORDS = {"thousand", "lakh", "lakhs", "crore", "crores"}
_WORD_TOKEN = re.compile(r"[A-Za-z]+")
# What may sit between two words of one spelled-out amount: "Six Hundred & Sixty",
# "Seventy-Nine", "Crore, Fifty".
_WORD_GAP = re.compile(r"[\s&,\-]*")
# Below this, a bare numeral is too small to be an order value in rupees (§5.10 treats a
# value under ₹1 lakh as a suspect parse).
_ONE_LAKH = Decimal(10) ** 5


def _spelled_amounts(text: str) -> list[Decimal]:
    """Every spelled-out amount in `text`: "Rupees Six Hundred & Sixty Crore and
    Seventy-Nine Lakhs only" -> [6607900000]."""
    amounts = []
    run: list[str] = []
    prev_end = None
    for m in _WORD_TOKEN.finditer(text):
        word = m.group(0).lower()
        numberish = (word in UNITS_WORDS or word in WORD_SCALES
                     or word in ("and", "rupees", "rupee", "only"))
        adjacent = prev_end is None or _WORD_GAP.fullmatch(text[prev_end:m.start()])
        if run and not (numberish and adjacent):
            amounts.append(run)
            run = []
        if numberish:
            run.append(word)
        prev_end = m.end()
    if run:
        amounts.append(run)

    out = []
    for words in amounts:
        # Needs a number word and an amount-sized scale word: the "crore" in "₹653.34
        # crore" alone is a unit, not a spelled-out amount.
        if not _AMOUNT_SCALE_WORDS.intersection(words):
            continue
        if not any(w in UNITS_WORDS for w in words):
            continue
        value = _words_to_decimal(" ".join(words))
        if value is not None and value > 0:
            out.append(value)
    return out


def _check_against_words(text: str, value: Decimal, flags: set[str]) -> Decimal:
    """Cross-check a bare numeral against a spelled-out amount in the same text.

    VASCONEQ printed "Rs. 660.79/- (Rupees Six Hundred & Sixty Crore and Seventy-Nine
    Lakhs only)": the scale is only in the words, so the numeral alone read as ₹660.79,
    ten million times too small, and provenance could not catch it because the span
    re-parses to the same wrong number (WORKLOG, 25 Sep 2026). When the words equal the
    numeral times a crore or a lakh exactly, they settle the scale; nothing is guessed.

    A value still unconfirmed and below ₹1 lakh, or one the words contradict, is flagged
    `suspect_scale`: it is kept for review but never counted as verified. That also
    catches a physical quantity read as money ("Supply of 2 GW" read as ₹2, WAAREEENER).
    """
    words = _spelled_amounts(text)
    for scale, name in ((Decimal(10) ** 7, "crore"), (Decimal(10) ** 5, "lakh")):
        if value * scale in words:
            flags.add("scale_from_words")
            flags.add(f"scale_{name}")
            return value * scale
    if value in words:
        flags.add("words_confirm")
        return value
    if words:
        flags.add("words_mismatch")
        flags.add("suspect_scale")
    elif value < _ONE_LAKH:
        flags.add("suspect_scale")
    return value


def is_suspect(money: Money) -> bool:
    """Whether a parsed value must not be marked verified however well its span checks
    out: provenance proves the value came from the document, not that the scale was read
    right (see `_check_against_words`)."""
    return "suspect_scale" in money.flags


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
