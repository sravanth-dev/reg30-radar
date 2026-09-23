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

import requests

from tradebot.common.config import nse as nse_config


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
        self._warm = False

    def warm_up(self) -> None:
        """Pick up the Akamai cookies. The API host will not answer a cold session."""
        self.session.get(self.cfg["warmup_url"], timeout=60)
        self._warm = True

    def poll_announcements(self) -> PollResult:
        """One GET against the live announcements endpoint.

        Returns a PollResult rather than raising, because every outcome - including the
        failures - is a row in source_health, and an exception escaping here would lose
        the record of the failure it was reporting.
        """
        if not self._warm:
            self.warm_up()

        url = self.cfg["announcements"]["url"]
        params = self.cfg["announcements"]["params"]
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
