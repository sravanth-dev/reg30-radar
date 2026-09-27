"""The NSE announcements client: one session, one request at a time, polite on errors.

D25 fixes what this is allowed to do. Permitted and used here: a session warm-up, browser-
like headers taken once from the page itself, a single consistent User-Agent, a low rate
with jitter, and exponential backoff. Not here and not to be added: proxy or User-Agent
rotation, fingerprint spoofing, or anything else whose purpose is to defeat the Akamai
layer rather than to reduce load.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import date

import requests

from tradebot.common.config import nse as nse_config
from tradebot.common.http import close_if_idle


@dataclass
class PollResult:
    ok: bool
    http_status: int | None
    latency_ms: int
    rows: list[dict] = field(default_factory=list)
    error: str | None = None


class NseClient:
    """A single warmed-up session against NSE. Not thread-safe, and intentionally so:
    the scraping rules allow one request at a time per source."""

    def __init__(self) -> None:
        self.cfg = nse_config()
        self.session = requests.Session()
        self.session.headers.update({k: str(v) for k, v in self.cfg["headers"].items()})
        self.idle_after = float(self.cfg["pacing"]["idle_reconnect_seconds"])
        self._warm = False
        self._last_request: float | None = None

    def warm_up(self) -> None:
        """Pick up the Akamai cookies. The API host will not answer a cold session."""
        self.session.get(self.cfg["warmup_url"], timeout=60)
        self._last_request = time.monotonic()
        self._warm = True

    def poll_announcements(self) -> PollResult:
        """One GET against the live announcements endpoint: the 20 most recent filings."""
        return self._get_json({})

    def fetch_range(self, from_date: date, to_date: date) -> PollResult:
        """A date-range query against the same endpoint (Spike A, ARCHITECTURE.md §5.1),
        for catching up after a collector outage and for closing an overflow gap.

        Spike A2 measured it as a *partial* view of a whole past day, with the shortfall in
        SME, debt, funds and window edges; the mainboard order filings came back 8/8. Good
        enough to close a short gap after the live collector was down. The 12-month
        backfill uses `fetch_symbol` instead (§5.1, company-wise).
        """
        return self._get_json({
            "from_date": from_date.strftime("%d-%m-%Y"),
            "to_date": to_date.strftime("%d-%m-%Y"),
        })

    def fetch_symbol(self, symbol: str) -> PollResult:
        """One company's entire filing history, every category (Spike A: BEL returned
        1,035 records from 2004 to the previous day). The backfill's one request per
        listed company (§5.1). Combining `symbol` with a date range returns nothing
        (Spike A), so the caller filters to its window."""
        return self._get_json({"symbol": symbol})

    def _get_json(self, extra_params: dict) -> PollResult:
        """One GET against the announcements endpoint with the configured parameters plus
        `extra_params`.

        Returns a PollResult rather than raising, because every outcome - including the
        failures - is a row in source_health, and an exception escaping here would lose
        the record of the failure it was reporting.
        """
        if not self._warm:
            self.warm_up()
        # A connection idle this long has usually been closed at NSE's end already.
        close_if_idle(self.session, self._last_request, self.idle_after)

        url = self.cfg["announcements"]["url"]
        params = {**self.cfg["announcements"]["params"], **extra_params}
        started = time.monotonic()
        try:
            r = self.session.get(url, params=params, timeout=45)
            latency = int((time.monotonic() - started) * 1000)

            if r.status_code in (401, 403):
                # The session has gone stale. Refresh it once; the caller applies backoff.
                self._warm = False
                return PollResult(False, r.status_code, latency,
                                  error="session rejected; will warm up again")
            if r.status_code != 200:
                return PollResult(False, r.status_code, latency,
                                  error=f"HTTP {r.status_code}")

            body = r.json()
            rows = body if isinstance(body, list) else body.get("data", [])
            return PollResult(True, 200, latency, rows=list(rows))
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            return PollResult(False, None, latency, error=f"{type(exc).__name__}: {exc}")
        finally:
            self._last_request = time.monotonic()


def backoff_seconds(consecutive_failures: int, *, cap: float = 600.0) -> float:
    """Exponential backoff with jitter. Never a tight retry loop (CLAUDE.md)."""
    if consecutive_failures <= 0:
        return 0.0
    base = min(cap, 30.0 * (2 ** (consecutive_failures - 1)))
    return base * random.uniform(0.7, 1.3)


def jittered(seconds: float, jitter: tuple[float, float]) -> float:
    """Add the configured random delay to a base interval.

    A fixed interval is the clearest bot signature there is (Sect.5.1), so the collector's
    interval is never exactly periodic. `jitter_seconds` in config/sources.yaml is read
    literally as "an extra delay between low and high seconds", which is what keeps two
    consecutive requests from ever being exactly N seconds apart.
    """
    low, high = float(jitter[0]), float(jitter[1])
    return seconds + random.uniform(low, high)
