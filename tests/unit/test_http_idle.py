"""Idle pooled connections are closed before the next request (common/http.py).

The failure these pin down: on 26 Sep 2026 almost every 10-minute poll went out on a
connection NSE had already closed and failed with ConnectionResetError. No network here:
a fake session records what the clients do, and the clock is controlled.
"""

from datetime import date
from pathlib import Path

import pytest

from tradebot.collector import nse
from tradebot.common.http import close_if_idle
from tradebot.documents.fetch import PdfFetcher


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr("time.monotonic", c)
    return c


class FakeResponse:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code = status
        self._body = body if body is not None else []
        self._content = content

    def json(self):
        return self._body

    def iter_content(self, chunk_size):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Records the order of requests and pool closes."""

    def __init__(self, content=b""):
        self.calls: list[str] = []
        self.params: list[dict] = []
        self.content = content

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append("get")
        self.params.append(params or {})
        return FakeResponse(content=self.content)

    def close(self):
        self.calls.append("close")


class Closable:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_nothing_to_close_before_the_first_request(clock):
    s = Closable()
    assert close_if_idle(s, None, 90) is False
    assert s.closed == 0


def test_recent_connection_is_kept(clock):
    s = Closable()
    assert close_if_idle(s, clock.now - 60, 90) is False
    assert s.closed == 0


def test_idle_connection_is_closed(clock):
    s = Closable()
    assert close_if_idle(s, clock.now - 600, 90) is True
    assert s.closed == 1


def test_collector_closes_the_pool_before_a_poll_after_a_long_gap(clock):
    client = nse.NseClient()
    client.session = FakeSession()

    client.poll_announcements()          # warm-up + poll, back to back
    assert client.session.calls == ["get", "get"]

    clock.now += 600                     # the 10-minute band
    client.poll_announcements()
    assert client.session.calls[-2:] == ["close", "get"]


def test_collector_keeps_the_pool_at_the_trading_band(clock):
    client = nse.NseClient()
    client.session = FakeSession()
    client.poll_announcements()

    clock.now += 60                      # the 60 s band: reuse has always worked
    client.poll_announcements()
    assert "close" not in client.session.calls


def test_symbol_and_range_queries_share_the_request_path(clock):
    client = nse.NseClient()
    client.session = FakeSession()
    client.fetch_symbol("BEL")
    client.fetch_range(date(2026, 9, 25), date(2026, 9, 26))
    symbol_params, range_params = client.session.params[1], client.session.params[2]
    assert symbol_params == {"index": "equities", "symbol": "BEL"}
    assert range_params == {"index": "equities", "from_date": "25-09-2026",
                            "to_date": "26-09-2026"}


def test_pdf_fetcher_closes_the_pool_after_an_idle_gap(clock, tmp_path: Path):
    fetcher = PdfFetcher()
    fetcher.session = FakeSession(content=b"%PDF-1.4 test")

    assert fetcher.fetch("https://example.invalid/a.pdf", tmp_path).ok
    assert "close" not in fetcher.session.calls

    clock.now += 300                     # --follow waits minutes between cycles
    assert fetcher.fetch("https://example.invalid/b.pdf", tmp_path).ok
    assert fetcher.session.calls[-2:] == ["close", "get"]


def test_a_response_that_is_not_a_pdf_is_refused_and_leaves_no_file(clock, tmp_path: Path):
    # 28 Sep 2026: NSE answered a 1.32 MB attachment with an empty 200. The rejection
    # deleted the file while its read handle was open, which Windows refuses (WinError 32),
    # and the backfill crashed. Runs on the laptop, so it fails there if that comes back.
    fetcher = PdfFetcher()
    for body in (b"", b"<html>Access Denied</html>"):
        fetcher.session = FakeSession(content=body)
        got = fetcher.fetch("https://example.invalid/c.pdf", tmp_path)
        assert not got.ok and got.error == "response is not a PDF"
        assert list(tmp_path.iterdir()) == []
