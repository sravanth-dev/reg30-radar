"""llm/client.py, offline with a fake OpenAI client - no network, no real API key.

Covers §6's non-negotiables from the first call this project makes: a null cap refuses
(never "no limit"), a missing key refuses, every call is logged with its tokens and cost,
and the document/image content never becomes part of the prompt sent to the model.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from tradebot.llm.client import LlmClient, LlmRefused

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes-for-a-test"

# A minimal, real config: not what config/llm.yaml ships with (that stays dormant on
# purpose), but what it looks like once Sravanth activates Part B.
ACTIVE_CONFIG = {
    "ocr_model": "gpt-vision-test",
    "prices": {"gpt-vision-test": {"input": 1.0, "output": 2.0}},  # USD per million tokens
    "caps": {"ocr_usd_per_month": 5.0},
    "max_output_tokens": {"ocr_transcribe": 2000},
}


class FakeConn:
    """Just enough of a psycopg connection for the cap check and the call log."""

    def __init__(self, spent_so_far: float = 0.0):
        self.spent_so_far = spent_so_far
        self.logged: list[dict] = []
        self.commits = 0

    def execute(self, sql: str, params=None):
        if "insert into llm_calls" in sql:
            self.logged.append(params)
        return self

    def fetchone(self):
        return (self.spent_so_far,)

    def commit(self):
        self.commits += 1


class FakeOpenAI:
    """Stands in for `openai.OpenAI()`. Records exactly what it was called with, so a test
    can assert the request shape without a real SDK object.
    """

    def __init__(self, content="transcribed text", in_tok=120, out_tok=40, cached=0):
        self.calls: list[dict] = []
        self._content = content
        self._in_tok = in_tok
        self._out_tok = out_tok
        self._cached = cached
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(
            prompt_tokens=self._in_tok, completion_tokens=self._out_tok,
            prompt_tokens_details=SimpleNamespace(cached_tokens=self._cached),
        )
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


# --------------------------------------------------------------------- fails closed

def test_null_cap_refuses():
    cfg = dict(ACTIVE_CONFIG, caps={"ocr_usd_per_month": None})
    client = LlmClient(conn=FakeConn(), config=cfg, api_key="sk-test")
    with pytest.raises(LlmRefused, match="null"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")


def test_unset_model_refuses():
    cfg = dict(ACTIVE_CONFIG, ocr_model="PLACEHOLDER")
    client = LlmClient(conn=FakeConn(), config=cfg, api_key="sk-test")
    with pytest.raises(LlmRefused, match="dormant"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")


def test_missing_price_entry_refuses():
    cfg = dict(ACTIVE_CONFIG, prices={})
    client = LlmClient(conn=FakeConn(), config=cfg, api_key="sk-test")
    with pytest.raises(LlmRefused, match="price"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")


def test_cap_set_but_no_connection_refuses():
    # Cannot check spend-to-date without a database, so it must not spend blind.
    client = LlmClient(conn=None, config=ACTIVE_CONFIG, api_key="sk-test")
    with pytest.raises(LlmRefused, match="no database connection"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")


def test_cap_already_reached_refuses():
    client = LlmClient(conn=FakeConn(spent_so_far=5.0), config=ACTIVE_CONFIG, api_key="sk-test")
    with pytest.raises(LlmRefused, match="cap"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")


def test_missing_api_key_refuses(monkeypatch):
    # NOT monkeypatch.delenv: common/config.py's env() loads .env lazily, cached once per
    # process (_load_env_once). If that load hasn't happened yet in this test run, deleting
    # the var achieves nothing - env()'s own dotenv call immediately refills it from the
    # real .env, which (now that a real key lives there for this session's work) silently
    # turns "missing key" into a genuine authenticated call to OpenAI. Caught by this exact
    # test making a real network call once a real key was added - see WORKLOG. Patching
    # env() itself is what actually makes this deterministic, independent of .env's content.
    import tradebot.llm.client as client_module
    monkeypatch.setattr(client_module, "env", lambda name, required=True: None)
    client = LlmClient(conn=FakeConn(), config=ACTIVE_CONFIG)   # no api_key injected
    with pytest.raises(LlmRefused, match="OPENAI_API_KEY"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")


# --------------------------------------------------------------------- a real call

def test_successful_call_logs_one_row_with_tokens_and_cost():
    conn = FakeConn()
    fake_openai = FakeOpenAI(in_tok=100, out_tok=50, cached=10)
    client = LlmClient(conn=conn, openai_client=fake_openai, config=ACTIVE_CONFIG,
                        api_key="sk-test")

    text = client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")

    assert text == "transcribed text"
    assert len(conn.logged) == 1
    row = conn.logged[0]
    assert row["model"] == "gpt-vision-test"
    assert row["in_tokens"] == 100
    assert row["out_tokens"] == 50
    assert row["cached_tokens"] == 10
    # 100 * $1/M + 50 * $2/M = $0.0001 + $0.0001 = $0.0002
    assert row["cost_usd"] == Decimal("100") * Decimal("1.0") / Decimal(1_000_000) + \
        Decimal("50") * Decimal("2.0") / Decimal(1_000_000)
    assert row["status"] == "ok"
    assert conn.commits >= 1


def test_request_carries_the_image_prompt_version_and_output_cap():
    fake_openai = FakeOpenAI()
    client = LlmClient(conn=FakeConn(), openai_client=fake_openai, config=ACTIVE_CONFIG,
                        api_key="sk-test")
    client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")

    assert len(fake_openai.calls) == 1
    call = fake_openai.calls[0]
    assert call["max_completion_tokens"] == 2000
    messages = call["messages"]
    user_content = messages[-1]["content"]
    assert user_content[0]["type"] == "image_url"
    assert "base64," in user_content[0]["image_url"]["url"]


def test_document_text_never_alters_the_prompt():
    """The system prompt comes only from the versioned prompt file - never built from, or
    concatenated with, anything the image/document might contain (CLAUDE.md's untrusted-
    document-text rule).
    """
    fake_openai = FakeOpenAI()
    client = LlmClient(conn=FakeConn(), openai_client=fake_openai, config=ACTIVE_CONFIG,
                        api_key="sk-test")
    client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")

    from tradebot.common.config import ROOT
    expected = (ROOT / "prompts" / "ocr_transcribe_v1.md").read_text(encoding="utf-8")
    system_message = fake_openai.calls[0]["messages"][0]
    assert system_message["role"] == "system"
    assert system_message["content"] == expected


def test_a_failed_call_is_logged_as_an_error_and_reraised():
    class BoomOpenAI:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            raise RuntimeError("boom")

    conn = FakeConn()
    client = LlmClient(conn=conn, openai_client=BoomOpenAI(), config=ACTIVE_CONFIG,
                        api_key="sk-test")
    with pytest.raises(RuntimeError, match="boom"):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")
    assert len(conn.logged) == 1
    assert conn.logged[0]["status"] == "error"
    assert "boom" in conn.logged[0]["error"]


def test_runs_without_a_database_when_the_call_is_refused():
    # §9: refusal paths need no database at all, only the cap-set-but-checkable path does.
    cfg = dict(ACTIVE_CONFIG, caps={"ocr_usd_per_month": None})
    client = LlmClient(conn=None, config=cfg, api_key="sk-test")
    with pytest.raises(LlmRefused):
        client.transcribe_image(PNG_BYTES, prompt_version="ocr_transcribe_v1")
