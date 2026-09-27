"""market/__main__.py's per-day decisions (D27's past-date calendar, retries), offline:
the fake fetcher serves zips built from the committed fixtures, and the store calls are
recorded instead of reaching a database."""

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from tradebot.common.config import nse as nse_config
from tradebot.market import __main__ as market
from tradebot.market.fetch import Archive

F = Path(__file__).resolve().parents[1] / "fixtures"
DAY = date(2026, 9, 18)


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


UDIFF = _zip({"BhavCopy_NSE_CM_0_0_0_20260918_F_0000.csv":
              (F / "BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV").read_bytes()})
BUNDLE = _zip({
    "an18092026.txt": (F / "an18092026.txt").read_bytes(),
    "pd18092026.csv": (F / "pd18092026.csv").read_bytes(),
    "mcap18092026.csv": (F / "mcap18092026.csv").read_bytes(),
    "bh18092026.csv": (F / "bh18092026.csv").read_bytes(),
})


class FakeFetcher:
    def __init__(self, answers: dict[str, Archive]):
        self.answers = answers
        self.urls: list[str] = []

    def get(self, url):
        self.urls.append(url)
        kind = "udiff" if "BhavCopy" in url else "pr"
        return self.answers[kind]


@pytest.fixture
def recorded(monkeypatch):
    calls = {"save": [], "mark": []}
    monkeypatch.setattr(market.store, "save_day",
                        lambda conn, day, **kw: calls["save"].append((day, kw))
                        or market.store.DayCounts(prices=len(kw["prices"])))
    monkeypatch.setattr(market.store, "mark_day",
                        lambda conn, day, **kw: calls["mark"].append((day, kw)))
    return calls


def test_urls_follow_the_verified_patterns():
    cfg = nse_config()
    assert market.udiff_url(cfg, DAY).endswith("BhavCopy_NSE_CM_0_0_0_20260918_F_0000.csv.zip")
    assert market.pr_url(cfg, DAY).endswith("/PR180926.zip")    # two-digit year


def test_a_clean_404_is_a_non_trading_day_and_nothing_else_is_fetched(recorded):
    fetcher = FakeFetcher({"udiff": Archive(404, error="HTTP 404")})
    market.load_day(None, fetcher, nse_config(), DAY)
    assert len(fetcher.urls) == 1
    assert recorded["mark"] == [(DAY, {"udiff_status": 404, "pr_status": None,
                                       "trading_day": False})]


def test_an_error_leaves_the_day_undecided_so_the_next_run_retries_it(recorded):
    fetcher = FakeFetcher({"udiff": Archive(503, error="HTTP 503")})
    market.load_day(None, fetcher, nse_config(), DAY)
    assert recorded["mark"][0][1]["trading_day"] is None
    assert recorded["save"] == []


def test_a_trading_day_stores_prices_and_every_bundle_member(recorded):
    fetcher = FakeFetcher({"udiff": Archive(200, UDIFF), "pr": Archive(200, BUNDLE)})
    market.load_day(None, fetcher, nse_config(), DAY)
    (day, kw), = recorded["save"]
    assert day == DAY and len(kw["prices"]) == 4973
    assert kw["indices"][0].index_name == "Nifty 50"
    assert len(kw["hits"]) == 298 and len(kw["entries"]) == 1229
    assert recorded["mark"][0][1] == {"udiff_status": 200, "pr_status": 200,
                                      "trading_day": True, "note": None}


def test_a_missing_bundle_keeps_the_prices_but_stays_retryable(recorded):
    fetcher = FakeFetcher({"udiff": Archive(200, UDIFF), "pr": Archive(503, error="HTTP 503")})
    market.load_day(None, fetcher, nse_config(), DAY)
    assert len(recorded["save"][0][1]["prices"]) == 4973
    mark = recorded["mark"][0][1]
    assert mark["trading_day"] is True and mark["pr_status"] == 503


def test_a_bhavcopy_for_another_date_is_rejected(recorded):
    fetcher = FakeFetcher({"udiff": Archive(200, UDIFF)})
    market.load_day(None, fetcher, nse_config(), date(2026, 9, 17))
    assert recorded["save"] == []
    assert "dated" in recorded["mark"][0][1]["note"]
