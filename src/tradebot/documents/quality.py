"""Per-page text quality assessment (§5.5), so noise never reaches the parser or a model.

`empty` / `broken_font` / `garbled` / `ok` — plain enough to explain line by line, and
calibrated against the 41 pages of the 18 labelled PDFs plus the HMT fixture that exposed
the gap this module exists to close (WORKLOG, 24 Sep 2026 evening; `tests/fixtures/scans/
hmt_glyphless.pdf`).

**A finding that changed the design from what was planned.** The plan for this slice
expected a word-readability score alone to separate HMT's garbled page from the accepted
ones, with HMT sitting "far below" the good pages' range. Measured against the real
re-downloaded fixture, that is not true: HMT's readability score (however the word list is
built) lands *inside* the range of pages this project already treats as fine — notably
BEL, whose page carries the same pattern of a garbled bilingual header sitting next to a
clean, correct English body (BEL's actual order value, "Rs.847 Crore", is in that clean
part). No threshold on a whole-page word ratio can flag HMT without also flagging BEL, and
BEL's real, extractable content would then be lost for nothing.

What actually distinguishes them is not how readable the text looks — it is *where it came
from*. BEL, HECPROJECT and HEG are full-page images with real, named embedded fonts
(Helvetica, Times, Calibri): their text was typed into the PDF, not produced by an OCR
engine, so a garbled fragment there is a font-encoding artifact confined to a part of the
page (typically a legacy 8-bit Hindi font) rather than evidence the *content* is unreliable.
HMT's entire page, including the part that reads as ordinary English, comes from one font
literally named `GlyphLessFont` — the invisible text layer a scan-to-searchable-PDF tool
writes, meaning every character on the page is that tool's own OCR guess, not something the
filer typed. We have no independent way to check a third party's OCR, so this module does
not try to score it: **a page sourced entirely from a `glyphless` font is never trusted
as-is**, the same way §5.6 never trusts a number without a provenance check. That single
rule catches HMT and produces zero false alarms on any of the 41 labelled pages, none of
which use such a font. The word-ratio score below stays in as a general safety net for
whatever a whole-page garble looks like when it *isn't* this specific pattern, calibrated
with real headroom under the 41 pages' measured floor (0.250) rather than to fit one file.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Every character/digit run, or a `(cid:NN)` placeholder, counts as one token. Counting a
# cid placeholder as one token (not the characters inside it) matches how the fixtures were
# talked about ("BEML's 26 (cid:NN) placeholders") and keeps the ratio meaningful regardless
# of whether placeholders run together with no separating space.
_CID_PLACEHOLDER_RE = re.compile(r"\(cid:\d+\)")
_TOKEN_RE = re.compile(r"\(cid:\d+\)|[A-Za-z]+|\d+")

# A word list built for breadth, not fitted to any one fixture: common English function
# words plus vocabulary any NSE corporate filing is likely to use. This backs only the
# `garbled` safety net below, never the glyphless rule above, which is what actually catches
# HMT. Measured floor across the 41 labelled pages is 0.250; the threshold sits well under
# that so a real page is never caught by this net, only something considerably worse.
_COMMON_WORDS = frozenset("""
the of to and in is for on with this that company board shall under regulation
regulations disclosure order orders crore crores lakh lakhs limited exchange
national stock securities intimation kindly please find enclosed letter pursuant
dated meeting trading window closure quarter half year ended results financial
annual report date sir madam subject regard above compliance listing
obligations requirements regards yours faithfully sincerely director secretary
authorized authorised signatory note above matter further details annexure
information required schedule act rules ltd inr value contract work bagging
receiving awarding award nature domestic international promoter interest related
party execution period consideration entity name whether not applicable none nil
from department manager corporate services filing india indian private public
sector state government project management chief executive officer managing
chairman submit submission ref reference dear sirs mumbai delhi road office
registered corporate identity number website email phone fax disclosed press
release material event code conduct insider trading are was were will would can
could should shall must may not have has had part whole process system service
services product products supply installation operation maintenance engineering
construction power energy infrastructure technologies software incorporated
companies approved intimate stock exchanges submission this regard requested
record members investors public thanking you regards director
""".split())

_MIN_CHARS = 40
_CID_RATIO_THRESHOLD = 0.25       # BEML's 26 placeholders measure ~0.11; this leaves margin
_GARBLED_MIN_WORD_TOKENS = 30
_GARBLED_RATIO_THRESHOLD = 0.15   # well under the 41 pages' measured floor of 0.250
_FULL_PAGE_IMAGE_FRACTION = 0.90


def normalize(text: str) -> str:
    """Safe normalisation only (§5.5): fixes ligatures (NFKC) and strips control characters.
    Never collapses whitespace runs - `extractor/annexure.py` reads two-plus spaces as a
    table-cell boundary, so doing that here would break table parsing downstream.

    Deliberately leaves `(cid:NN)` placeholders in place: `assess_text` below needs to see
    them to compute `cid_ratio`. They are dropped separately, by `clean_for_storage`, only
    once a page has passed assessment and its text is about to be kept.
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def clean_for_storage(text: str) -> str:
    """Drop `(cid:NN)` placeholders from already-normalized text that passed assessment.

    Called once, on the text a page is about to keep - never on text being scored, which
    still needs the placeholders present to measure `cid_ratio`.
    """
    return _CID_PLACEHOLDER_RE.sub("", text)


@dataclass
class PageFacts:
    """What kind of page this is, independent of which extraction method reads it."""

    image_fraction: float   # largest single image as a fraction of page area
    glyphless_font: bool    # any character rendered through a font named *GlyphLessFont*


def page_facts(page) -> PageFacts:
    """Read layout facts from a pdfplumber Page. Cheap, and done once per page regardless
    of how many extraction methods are tried against it - these are facts about the file,
    not about the attempt (§5.5).
    """
    area = float(page.width) * float(page.height)
    largest = 0.0
    for img in page.images:
        w = float(img.get("x1", 0)) - float(img.get("x0", 0))
        h = float(img.get("bottom", 0)) - float(img.get("top", 0))
        if area > 0:
            largest = max(largest, (w * h) / area)
    glyphless = any("glyphless" in (ch.get("fontname") or "").lower() for ch in page.chars)
    return PageFacts(image_fraction=largest, glyphless_font=glyphless)


def is_full_page_image(image_fraction: float) -> bool:
    return image_fraction >= _FULL_PAGE_IMAGE_FRACTION


@dataclass
class TextAssessment:
    verdict: str                       # "empty" | "broken_font" | "garbled" | "ok"
    text: str                          # normalized (not the original raw string)
    chars: int
    tokens: int
    cid_ratio: float
    common_word_ratio: float | None    # None when too few word tokens to judge


def assess_text(raw_text: str, *, glyphless_font: bool = False) -> TextAssessment:
    """Score one extraction attempt for one page. `glyphless_font` is the page fact from
    `page_facts` - it is what actually catches the HMT failure mode; see the module
    docstring for why a word-ratio score on its own cannot.
    """
    text = normalize(raw_text or "")
    chars = len(text.strip())
    tokens = _TOKEN_RE.findall(text)
    cid_tokens = [t for t in tokens if _CID_PLACEHOLDER_RE.fullmatch(t)]
    cid_ratio = len(cid_tokens) / max(1, len(tokens))
    word_tokens = [t for t in tokens if len(t) >= 3 and t.isalpha()]
    common_ratio = None
    if word_tokens:
        common = sum(1 for t in word_tokens if t.lower() in _COMMON_WORDS)
        common_ratio = common / len(word_tokens)

    if chars < _MIN_CHARS:
        verdict = "empty"
    elif cid_ratio > _CID_RATIO_THRESHOLD:
        verdict = "broken_font"
    elif glyphless_font:
        # An invisible OCR layer over the whole page: we did not produce this text and have
        # no way to check it, so it is never accepted on the strength of looking readable
        # (see module docstring). Caught here regardless of what the ratio below would say.
        verdict = "garbled"
    elif (len(word_tokens) >= _GARBLED_MIN_WORD_TOKENS
          and common_ratio is not None and common_ratio < _GARBLED_RATIO_THRESHOLD):
        verdict = "garbled"
    else:
        verdict = "ok"

    return TextAssessment(
        verdict=verdict, text=text, chars=chars, tokens=len(tokens),
        cid_ratio=round(cid_ratio, 4),
        common_word_ratio=round(common_ratio, 4) if common_ratio is not None else None,
    )


_RANK = {"ok": 3, "broken_font": 2, "garbled": 1, "empty": 0}


def better(a: TextAssessment, b: TextAssessment) -> TextAssessment:
    """Keep the better of two attempts at the same page (§5.5 step 2: pdfplumber vs pypdf).

    Ranked by verdict first (`ok` always wins), then by whichever read more of the page.
    """
    if _RANK[a.verdict] != _RANK[b.verdict]:
        return a if _RANK[a.verdict] > _RANK[b.verdict] else b
    return a if a.chars >= b.chars else b
