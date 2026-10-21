"""documents/text.py's per-page ladder: pdfplumber -> pypdf -> vision OCR (§5.5 Part A/B).

Uses the real labelled PDFs and the HMT fixture - no synthetic PDFs, so the ladder is
exercised against real extraction quirks, not a hand-built stand-in for one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reg30_radar.documents.text import extract

LABELLED = Path(__file__).resolve().parents[1] / "labelled"
HMT = Path(__file__).resolve().parents[1] / "fixtures" / "scans" / "hmt_glyphless.pdf"
SAMPLE = LABELLED / "RAILTEL_20260917_1.pdf"


def test_a_normal_filing_extracts_ok_with_no_ocr_needed():
    got = extract(SAMPLE)
    assert got.quality == "ok"
    assert got.pages == 2
    assert got.ocr_pages == 0
    assert len(got.text.strip()) > 500
    assert got.page_report[0]["verdict"] == "ok"
    assert got.page_report[0]["source"] == "text_layer"


def test_hmt_is_unreadable_with_ocr_dormant():
    """§5.5 Part B dormant (`ocr=None`, the default): the page is routed nowhere, comes
    out unreadable, and its garbage lands in rejected_text - never in text.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    got = extract(HMT)
    assert got.quality == "unreadable"
    assert got.text == ""
    assert got.rejected_text != ""
    assert got.ocr_pages == 0                    # never attempted - OCR is dormant
    assert got.page_report[0]["ocr_attempted"] is False
    assert got.is_scanned is True                 # still a fact, independent of quality


def test_hmt_routes_to_ocr_when_configured_and_a_good_transcript_is_kept():
    """Part B active: a page every other method failed on gets rendered and sent to the
    injected `ocr` callable. A transcript that passes assessment is kept, sourced `vision`.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")

    calls = []

    def fake_ocr(png_bytes: bytes) -> str:
        calls.append(len(png_bytes))
        return ("Dear Sir/Madam, Sub: Closure of Trading Window for the quarter and half "
                "year ended 30th September 2026. Pursuant to the provisions of SEBI "
                "Regulations, the trading window shall remain closed until further notice "
                "for all insiders including Designated Persons of the Company.")

    got = extract(HMT, ocr=fake_ocr)
    assert len(calls) == 1
    assert calls[0] > 0   # a real PNG was rendered and handed over
    assert got.quality == "ok"
    assert got.ocr_pages == 1
    assert got.page_report[0]["method"] == "vision"
    assert got.page_report[0]["source"] == "vision"
    assert "Trading Window" in got.text


def test_hmt_with_ocr_configured_but_a_bad_transcript_stays_unreadable():
    """OCR was tried but its own output still fails assessment - the page must not be
    accepted just because *some* model produced *some* text (§5.6's provenance principle,
    applied one step earlier).
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")

    def bad_ocr(png_bytes: bytes) -> str:
        return "xqz zzz qxz zzq xzq " * 10   # passes as non-empty, fails the word-ratio net

    got = extract(HMT, ocr=bad_ocr)
    assert got.quality == "unreadable"
    assert got.text == ""
    assert got.page_report[0]["ocr_attempted"] is True


def test_ocr_returning_none_is_treated_like_ocr_being_unavailable():
    """This is exactly what `documents.ocr.maybe_transcribe` returns when Part B is
    dormant (a null cap, an unset model, a missing key) - it must never crash the ladder.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    got = extract(HMT, ocr=lambda png: None)
    assert got.quality == "unreadable"
    assert got.page_report[0]["ocr_attempted"] is True


def test_max_ocr_pages_caps_attempts_per_document():
    """A spend guard (config/llm.yaml's ocr_max_pages_per_document): once the budget for
    this document is spent, remaining unreadable pages skip the OCR attempt rather than
    calling out indefinitely.
    """
    if not HMT.exists():
        pytest.skip("tests/fixtures/scans/hmt_glyphless.pdf not present")
    calls = []
    got = extract(HMT, ocr=lambda png: calls.append(1) or None, max_ocr_pages=0)
    assert calls == []
    assert got.page_report[0]["ocr_attempted"] is False


def test_missing_file_fails_without_raising():
    got = extract(LABELLED / "does_not_exist.pdf")
    assert got.text == ""
    assert got.quality == "unreadable"
    assert got.method.startswith("failed:")
    assert got.is_scanned is True
