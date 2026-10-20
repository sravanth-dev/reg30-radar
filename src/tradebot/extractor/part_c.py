"""§5.5 Part C: a number this pipeline read with its own vision OCR is not verified on the
span check alone.

On a `vision` page the document text *is* the model's transcript, so finding the quote in
that text proves only that the extractor copied the transcript, not that the transcript
matches the image. A value read from such a page therefore needs a second, independent
read that agrees on it before it counts as verified, or it goes to review (ARCHITECTURE
§5.5 Part C, §5.6). Until 20 Oct 2026 nothing enforced this: 42 verified backfill values
came from documents with vision pages (AUDIT.md §3).

What counts as vision-sourced is decided conservatively. The value's quote is located in
the stored text, and the page it sits on is worked out from the page report (kept pages are
joined by a blank line, and each page's character count is recorded). If any occurrence is
on a page whose text came from the PDF itself, the value stands on that page. If the pages
cannot be told apart (the counts do not add up for a few documents), the value is treated
as vision-sourced.

The second read is `backfill/vision_check.py`: the PDF is downloaded again by URL (its
SHA-256 must match), the page is rendered as before and transcribed blind, and the value
must verify against the new transcript. The result is stored with the value it confirmed
(`second_read`, `second_read_inr`), so a later change of value needs a fresh read.
"""

from __future__ import annotations

from decimal import Decimal

from tradebot.extractor.provenance import occurrences


def has_vision_page(page_report) -> bool:
    return any(p.get("source") == "vision" and p.get("verdict") == "ok"
               for p in page_report or [])


def page_spans(text: str, page_report) -> list[tuple[int, int, str]] | None:
    """(start, end, source) of each kept page within `text`, or None when the recorded
    character counts do not reproduce the text's length."""
    kept = [p for p in page_report or [] if p.get("verdict") == "ok"]
    if not kept:
        return None
    spans, start = [], 0
    for p in kept:
        end = start + int(p.get("chars") or 0)
        spans.append((start, end, p.get("source")))
        start = end + 2                        # the "\n\n" between kept pages
    return spans if start - 2 == len(text or "") else None


def vision_sourced(text: str, page_report, value_span: str | None,
                   value_inr: Decimal | None) -> bool:
    """Whether the value rests only on this pipeline's own vision OCR."""
    if not has_vision_page(page_report):
        return False
    spans = page_spans(text, page_report)
    found = occurrences(text, value_span, value_inr)
    if spans is None or not found:
        return True
    for offset in found:
        for start, end, source in spans:
            if start <= offset < end and source != "vision":
                return False
    return True


def gate(status: str, *, vision: bool, second_read: str | None,
         second_read_inr: Decimal | None, value_inr: Decimal | None) -> tuple[str, str | None]:
    """(review_status, second_read) after Part C. A vision-sourced value stays verified
    only when a second read agreed on this very value; otherwise it waits in review."""
    if status != "verified" or not vision:
        return status, second_read
    if second_read == "agrees" and second_read_inr == value_inr:
        return "verified", "agrees"
    if second_read in ("disagrees", "unavailable") and second_read_inr == value_inr:
        return "needs_review", second_read
    return "needs_review", "pending"
