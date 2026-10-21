"""PDF text extraction, per page: pdfplumber, then pypdf, then vision OCR (§5.5 Part A/B).

Each page is scored by `documents.quality` and only text that assesses `ok` is ever kept in
`documents.text`. A page that fails every attempt is excluded and its best (still-bad)
attempt is kept separately in `rejected_text`, so noise never reaches the annexure parser or
an LLM but nothing is silently thrown away either - the classifier's calls stay auditable
without re-downloading the PDF (D8 already deleted it by then).

This module does not delete anything. D8's delete-after-extraction belongs to the pipeline
that owns the file; the labelled set in `tests/labelled/` is the standing exception.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from reg30_radar.documents import quality
from reg30_radar.llm.client import LlmProviderError

# A page's vision transcript is fetched by calling this with rendered PNG bytes. None means
# Part B is dormant (no OpenAI key/model/cap configured yet) - every page needing OCR then
# comes out `unreadable` rather than crashing or guessing (§5.5 Part B).
OcrFn = Callable[[bytes], "str | None"]


@dataclass
class PageResult:
    page: int
    verdict: str              # "ok" | "unreadable" - the FINAL outcome, after every attempt
    text: str                 # kept text; "" when verdict is "unreadable"
    rejected_text: str        # the best attempt's text; "" when verdict is "ok"
    method: str                # "pdfplumber" | "pypdf" | "vision"
    source: str                 # "text_layer" | "ocr_overlay" | "vision" (§5.6 Part C)
    chars: int
    image_fraction: float
    glyphless_font: bool
    cid_ratio: float
    common_word_ratio: float | None
    ocr_attempted: bool


@dataclass
class Extracted:
    text: str                       # kept ("ok") pages' text, joined with a blank line
    pages: int
    method: str                     # method of the first ok page, "mixed", or "none"
    is_scanned: bool                # any page is a full-page image (a fact, not a guess)
    quality: str = "ok"             # "ok" | "partial" | "unreadable" - document-level
    rejected_text: str = ""         # unreadable pages' best attempt, joined, for audit
    ocr_pages: int = 0              # pages routed to vision OCR, attempted or not
    page_report: list[dict] = field(default_factory=list)


def render_page_png(page, *, dpi: int, grayscale: bool = True) -> bytes:
    """Render one page as a PNG for vision OCR (§5.5 Part B).

    Uses pdfplumber's own `page.to_image()`, never a direct import of pypdfium2 or Pillow -
    those stay outside the approved dependency list (§9); this only calls methods on the
    object pdfplumber already returns.
    """
    rendered = page.to_image(resolution=dpi)
    image = rendered.original
    if grayscale:
        image = image.convert("L")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class _OcrBudget:
    """How many more pages of *this document* may still be sent to vision OCR.

    A per-document cap (`ocr_max_pages_per_document` in config/llm.yaml, §5.5 Part B) so one
    pathological PDF - hundreds of image pages - cannot trigger unbounded spend. Pages beyond
    the cap simply skip the OCR attempt and land as `unreadable`, the same outcome as when
    Part B is dormant.
    """

    def __init__(self, limit: int) -> None:
        self.remaining = limit

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _assess_page(
    pdfplumber_page, pypdf_page, *, ocr: OcrFn | None, dpi: int, ocr_budget: _OcrBudget,
) -> PageResult:
    facts = quality.page_facts(pdfplumber_page)
    a1 = quality.assess_text(pdfplumber_page.extract_text() or "", glyphless_font=facts.glyphless_font)
    method, best = "pdfplumber", a1

    if best.verdict != "ok" and pypdf_page is not None:
        try:
            pypdf_text = pypdf_page.extract_text() or ""
        except Exception:
            pypdf_text = ""
        a2 = quality.assess_text(pypdf_text, glyphless_font=facts.glyphless_font)
        chosen = quality.better(best, a2)
        if chosen is a2:
            method, best = "pypdf", a2

    ocr_attempted = False
    if best.verdict != "ok" and ocr is not None and ocr_budget.take():
        ocr_attempted = True
        png = render_page_png(pdfplumber_page, dpi=dpi)
        transcript = ocr(png)
        if transcript:
            # A fresh transcript from our own controlled call, not a third party's invisible
            # layer - so it is judged purely on the text-quality checks, never auto-rejected
            # the way a `glyphless_font` page is (§5.6 Part C: `source` records the
            # difference, and only `vision` pages carry the extra verification rule).
            a3 = quality.assess_text(transcript, glyphless_font=False)
            if a3.verdict == "ok":
                method, best = "vision", a3

    if best.verdict == "ok":
        kept = quality.clean_for_storage(best.text)
        source = "vision" if method == "vision" else (
            "ocr_overlay" if quality.is_full_page_image(facts.image_fraction) else "text_layer")
        return PageResult(
            page=0, verdict="ok", text=kept, rejected_text="",
            method=method, source=source, chars=best.chars,
            image_fraction=facts.image_fraction, glyphless_font=facts.glyphless_font,
            cid_ratio=best.cid_ratio, common_word_ratio=best.common_word_ratio,
            ocr_attempted=ocr_attempted,
        )

    source = "vision" if method == "vision" else (
        "ocr_overlay" if quality.is_full_page_image(facts.image_fraction) else "text_layer")
    return PageResult(
        page=0, verdict="unreadable", text="", rejected_text=quality.clean_for_storage(best.text),
        method=method, source=source, chars=best.chars,
        image_fraction=facts.image_fraction, glyphless_font=facts.glyphless_font,
        cid_ratio=best.cid_ratio, common_word_ratio=best.common_word_ratio,
        ocr_attempted=ocr_attempted,
    )


def extract(
    path: str | Path, *, ocr: OcrFn | None = None, dpi: int = 200, max_ocr_pages: int = 10,
) -> Extracted:
    """Run the full per-page ladder over one PDF.

    `ocr` is dependency-injected rather than imported directly, so this module (and its
    tests) never need a real OpenAI client: `pipeline.py` passes the real thing only once
    Part B is configured, and passes nothing otherwise (§5.5 Part B stays dormant safely).
    """
    path = Path(path)
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            pypdf_pages: list = []
            try:
                from pypdf import PdfReader
                pypdf_pages = list(PdfReader(str(path)).pages)
            except Exception:
                pypdf_pages = []

            budget = _OcrBudget(max_ocr_pages)
            results: list[PageResult] = []
            for i, page in enumerate(pdf.pages):
                pypdf_page = pypdf_pages[i] if i < len(pypdf_pages) else None
                r = _assess_page(page, pypdf_page, ocr=ocr, dpi=dpi, ocr_budget=budget)
                r.page = i + 1
                results.append(r)
    except LlmProviderError:
        # The OCR provider failed, not the PDF: the caller retries later. Before this, one
        # OpenAI error marked the whole document unreadable for good (GATE 1 audit).
        raise
    except Exception as exc:
        return Extracted(
            text="", pages=0, method=f"failed:{type(exc).__name__}", is_scanned=True,
            quality="unreadable", rejected_text="", ocr_pages=0, page_report=[],
        )

    ok_pages = [r for r in results if r.verdict == "ok"]
    bad_pages = [r for r in results if r.verdict != "ok"]

    if not results:
        doc_quality = "unreadable"
    elif not bad_pages:
        doc_quality = "ok"
    elif not ok_pages:
        doc_quality = "unreadable"
    else:
        doc_quality = "partial"

    methods = {r.method for r in ok_pages}
    if not ok_pages:
        method = results[0].method if results else "none"
    elif len(methods) == 1:
        method = next(iter(methods))
    else:
        method = "mixed"

    return Extracted(
        text="\n\n".join(r.text for r in ok_pages),
        pages=len(results),
        method=method,
        is_scanned=any(quality.is_full_page_image(r.image_fraction) for r in results),
        quality=doc_quality,
        rejected_text="\n\n".join(r.rejected_text for r in bad_pages),
        ocr_pages=sum(1 for r in results if r.ocr_attempted),
        page_report=[
            {
                "page": r.page, "verdict": r.verdict, "method": r.method, "source": r.source,
                "chars": r.chars, "image_fraction": round(r.image_fraction, 4),
                "glyphless_font": r.glyphless_font, "cid_ratio": r.cid_ratio,
                "common_word_ratio": r.common_word_ratio, "ocr_attempted": r.ocr_attempted,
            }
            for r in results
        ],
    )
