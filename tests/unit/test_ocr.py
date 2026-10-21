"""documents/ocr.py's dormant-by-default wrapper (§5.5 Part B)."""

from __future__ import annotations

from reg30_radar.documents.ocr import maybe_transcribe
from reg30_radar.llm.client import LlmClient, LlmRefused


class RefusingClient:
    """Stands in for the real LlmClient before Sravanth configures Part B: every call is
    refused, matching config/llm.yaml as shipped (ocr_model: PLACEHOLDER, null cap).
    """

    def transcribe_image(self, *args, **kwargs):
        raise LlmRefused("ocr_model is unset")


class WorkingClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def transcribe_image(self, png_bytes, *, prompt_version, **kwargs):
        self.calls += 1
        assert prompt_version == "ocr_transcribe_v1"
        return self.text


def test_maybe_transcribe_returns_none_when_the_client_refuses():
    assert maybe_transcribe(b"fake-png", client=RefusingClient()) is None


def test_maybe_transcribe_returns_the_transcript_on_success():
    client = WorkingClient("Dear Sir/Madam, ...")
    assert maybe_transcribe(b"fake-png", client=client) == "Dear Sir/Madam, ..."
    assert client.calls == 1


def test_maybe_transcribe_with_no_configuration_at_all_does_not_raise():
    # The real default path: config/llm.yaml ships with ocr_model: PLACEHOLDER, so a real
    # LlmClient() refuses on its own with no injected fake - this must still return None,
    # not raise, and must not touch the network.
    assert maybe_transcribe(b"fake-png") is None
