"""Vision OCR for a page every other method failed to read (§5.5 Part B).

Dormant until Sravanth supplies `OPENAI_API_KEY`, a vision-capable `ocr_model` id, its
prices and an OCR spend cap in `config/llm.yaml`. Until then `maybe_transcribe` always
returns None: image pages land as `unreadable` -> manual review, and nothing crashes or
guesses (§5.5).
"""

from __future__ import annotations

from tradebot.llm.client import LlmClient, LlmRefused

PROMPT_VERSION = "ocr_transcribe_v1"


def maybe_transcribe(png_bytes: bytes, *, client: LlmClient | None = None) -> str | None:
    """Try to transcribe one rendered page. Returns None - never raises - when OCR is not
    configured or refuses for any other reason (§6: a null cap, an unset model, a missing
    key); the caller (documents/text.py) treats None exactly like "OCR wasn't available".
    """
    client = client or LlmClient()
    try:
        return client.transcribe_image(png_bytes, prompt_version=PROMPT_VERSION)
    except LlmRefused:
        return None
