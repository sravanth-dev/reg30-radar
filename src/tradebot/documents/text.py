"""PDF text extraction: pdfplumber first, pypdf as the fallback (§5.5).

Returns the text plus enough about the extraction to decide `is_scanned`, which is what
§5.5 sends to manual review and what Spike D counts by market-cap band to settle the OCR
question.

This module does not delete anything. D8's delete-after-extraction belongs to the pipeline
that owns the file; the labelled set in `tests/labelled/` is the standing exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Extracted:
    text: str
    pages: int
    method: str
    is_scanned: bool


def _scanned(text: str, pages: int) -> bool:
    """Little or no extractable text means an image scan.

    The threshold scales with page count because a genuine text filing yields hundreds of
    characters per page, while a scan yields a handful of stray ligatures at most.
    """
    n = len(text.strip())
    return n < max(200, 80 * min(pages, 12))


def extract(path: str | Path) -> Extracted:
    path = Path(path)
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            parts = [(p.extract_text() or "") for p in pdf.pages]
        text = "\n".join(parts)
        if text.strip():
            return Extracted(text, pages, "pdfplumber", _scanned(text, pages))
    except Exception:
        pages = 0

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = len(reader.pages)
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        return Extracted(text, pages, "pypdf", _scanned(text, pages))
    except Exception as exc:
        return Extracted("", pages, f"failed:{type(exc).__name__}", True)
