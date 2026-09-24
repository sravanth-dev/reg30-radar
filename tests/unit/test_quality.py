"""documents/quality.py, verified against real filings (§5.5 Part A).

The two tests that matter most: every page of the labelled set must assess `ok` (no false
alarms - a wrongly-rejected page loses real, extractable content, as documented in
quality.py's module docstring), and the HMT fixture that exposed the original gap must
assess `garbled`. Everything else here is unit coverage of the scoring rules in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from tradebot.documents import quality

LABELLED = Path(__file__).resolve().parents[1] / "labelled"
HMT = Path(__file__).resolve().parents[1] / "fixtures" / "scans" / "hmt_glyphless.pdf"


def _all_labelled_pages():
    for pdf_path in sorted(LABELLED.glob("*.pdf")):
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                facts = quality.page_facts(page)
                assessment = quality.assess_text(
                    page.extract_text() or "", glyphless_font=facts.glyphless_font)
                yield pdf_path.stem, i + 1, assessment, facts


def test_no_false_alarms_on_the_labelled_set():
    """Every one of the 41 labelled pages must assess ok. A wrong rejection here would
    throw away real, extractable content - see quality.py's module docstring for the BEL
    case this specifically guards against.
    """
    bad = [(stem, page, a.verdict) for stem, page, a, _ in _all_labelled_pages()
           if a.verdict != "ok"]
    assert bad == []


def test_at_least_41_pages_were_actually_checked():
    # A protection against the generator silently yielding nothing (e.g. a moved fixtures
    # directory) and the test above passing for the wrong reason.
    assert sum(1 for _ in _all_labelled_pages()) == 41


def test_hmt_fixture_assesses_garbled():
    """The regression fixture for the gap this module exists to close (WORKLOG, 24 Sep
    2026 evening). Caught by the glyphless-font rule, not by a readability score - see
    the module docstring for why a score alone cannot separate this from BEL.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    with pdfplumber.open(HMT) as pdf:
        assert len(pdf.pages) == 1
        page = pdf.pages[0]
        facts = quality.page_facts(page)
        assert facts.glyphless_font is True
        assert facts.image_fraction >= 0.90
        a = quality.assess_text(page.extract_text() or "", glyphless_font=facts.glyphless_font)
        assert a.verdict == "garbled"


def test_bel_full_page_image_with_a_real_font_stays_ok():
    """The specific case that a naive word-ratio threshold would have broken: a full-page
    scan whose real order value sits in a clean, correctly-encoded part of the page, next
    to a garbled bilingual header. BEL_20260731_1 uses Helvetica, not GlyphLessFont.
    """
    with pdfplumber.open(LABELLED / "BEL_20260731_1.pdf") as pdf:
        page = pdf.pages[0]
        facts = quality.page_facts(page)
        assert facts.glyphless_font is False
        assert facts.image_fraction >= 0.90   # it IS a full-page image
        a = quality.assess_text(page.extract_text() or "", glyphless_font=False)
        assert a.verdict == "ok"
        assert "847" in a.text   # the actual order value survives


# --------------------------------------------------------------------- verdict rules

def test_empty_below_min_chars():
    assert quality.assess_text("short").verdict == "empty"
    assert quality.assess_text("").verdict == "empty"


def test_broken_font_on_heavy_cid_placeholders():
    # Comfortably past the threshold, unlike BEML's real 26-placeholder page (~11%),
    # which must NOT trip this (covered by test_no_false_alarms_on_the_labelled_set).
    text = " ".join(["(cid:80)"] * 40 + ["word"] * 10)
    assert quality.assess_text(text).verdict == "broken_font"


def test_garbled_safety_net_on_a_synthetic_low_ratio_page():
    # No glyphless font involved - this exercises the word-ratio fallback on its own.
    gibberish = " ".join(f"xqz{i}zqx" for i in range(40))
    a = quality.assess_text(gibberish, glyphless_font=False)
    assert a.verdict == "garbled"
    assert a.common_word_ratio is not None and a.common_word_ratio < 0.15


def test_glyphless_font_forces_garbled_even_with_readable_words():
    # The rule that actually catches HMT: an invisible third-party OCR layer is not
    # trusted on the strength of looking readable (module docstring).
    readable = "The Company received an order from the National Stock Exchange for the year."
    ok = quality.assess_text(readable, glyphless_font=False)
    forced = quality.assess_text(readable, glyphless_font=True)
    assert ok.verdict == "ok"
    assert forced.verdict == "garbled"


def test_short_page_with_few_word_tokens_is_not_judged_garbled():
    # Fewer than the minimum word-token count for the ratio check to be meaningful; must
    # not be penalised just for being short (that is what `empty` is for).
    text = "Ref: CS/SE/12345  Date: 21/09/2026  Annexure A  Scrip Code: 500191"
    a = quality.assess_text(text)
    assert len(text.strip()) >= 40   # past the `empty` floor
    assert a.verdict == "ok"


# --------------------------------------------------------------------- normalisation

def test_clean_for_storage_drops_cid_placeholders_but_keeps_spacing():
    raw = "Name  (cid:80)(cid:81)  Value  100"
    cleaned = quality.clean_for_storage(quality.normalize(raw))
    assert "(cid:" not in cleaned
    # Table-cell spacing (2+ spaces) must survive - extractor/annexure.py reads it as a
    # column boundary.
    assert "  " in cleaned


def test_normalize_fixes_ligatures_without_collapsing_whitespace():
    text = quality.normalize("ofﬁce   value")   # NFKC-decomposable ligature
    assert "ﬁ" not in text or "fi" in text.replace("ﬁ", "fi")
    assert "   " in text


# --------------------------------------------------------------------- better()

def test_better_prefers_ok_over_any_other_verdict():
    ok = quality.assess_text("word " * 40)
    empty = quality.assess_text("")
    assert quality.better(empty, ok) is ok
    assert quality.better(ok, empty) is ok


def test_better_breaks_ties_on_more_characters():
    short = quality.assess_text("")
    longer = quality.assess_text("x" * 5)
    assert quality.better(short, longer) is longer


# --------------------------------------------------------------------- page_facts

def test_is_full_page_image_threshold():
    assert quality.is_full_page_image(0.95) is True
    assert quality.is_full_page_image(0.5) is False
