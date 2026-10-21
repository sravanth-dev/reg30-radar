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

from reg30_radar.common import nse_guard
from reg30_radar.common.config import nse as nse_config
from reg30_radar.common.http import close_if_idle
# Re-exported: the collector and sheets loops import it from here.
from reg30_radar.common.nse_guard import NseStructureChanged, backoff_seconds  # noqa: F401


@dataclass
class PollResult:
    ok: bool
    http_status: int | None
    latency_ms: int
    rows: list[dict] = field(default_factory=list)
    error: str | None = None
    # `totalCount`, for endpoints that page their answer; lets a caller see a truncated page
    total: int | None = None


class NseClient:
    """A single warmed-up session against NSE. Not thread-safe, and intentionally so:
    the scraping rules allow one request at a time per source."""

    def __init__(self, *, min_gap: float | None = None) -> None:
        """`min_gap` is the floor between any two NSE requests this client sends: the
        live floor by default; the backfill passes its own (>=3 s, CLAUDE.md)."""
        self.cfg = nse_config()
        pacing = self.cfg["pacing"]
        self.min_gap = float(min_gap if min_gap is not None else pacing["live_min_gap_seconds"])
        self.jitter = tuple(float(x) for x in pacing["jitter_seconds"])
        self.session = requests.Session()
        self.session.headers.update({k: str(v) for k, v in self.cfg["headers"].items()})
        self.idle_after = float(pacing["idle_reconnect_seconds"])
        self._warm = False
        self._last_request: float | None = None

    def warm_up(self) -> str | None:
        """Pick up the Akamai cookies. The API host will not answer a cold session.
        Returns None when warmed up, else the reason it failed. Paced like any request,
        so the call that follows still waits its gap."""
        nse_guard.GUARD.before_request(self.min_gap, self.jitter)
        error = None
        try:
            r = self.session.get(self.cfg["warmup_url"], timeout=60)
            if r.status_code != 200:
                error = f"warm-up HTTP {r.status_code}"
        except Exception as exc:
            error = f"warm-up {type(exc).__name__}: {exc}"
        self._last_request = time.monotonic()
        self._warm = error is None
        nse_guard.GUARD.after_request(error is None, error or "warm-up")
        return error

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

    def fetch_results_listing(self, symbol: str) -> PollResult:
        """One company's quarterly results history (Spike C, 27 Sep 2026): a different
        endpoint (`config/sources.yaml`'s `nse.results`), same session and politeness. Only
        the pre-April-2025 "Financial Results" era - see `revenue/load.py`'s module
        docstring for what that does and does not cover."""
        return self._get_json({"symbol": symbol}, endpoint="results")

    def fetch_integrated_results(self, symbol: str, page: int = 1) -> PollResult:
        """One company's "Integrated Filing - Financials" results, from the quarter ended
        31-Mar-2025 on (Spike C2): `config/sources.yaml`'s `nse.integrated_results`. One
        page of 20 rows; `PollResult.total` says whether more pages follow."""
        return self._get_json({"symbol": symbol, "page": page}, endpoint="integrated_results")

    def _get_json(self, extra_params: dict, *, endpoint: str = "announcements") -> PollResult:
        """One GET against `config/sources.yaml`'s `nse.<endpoint>` with its configured
        parameters plus `extra_params`.

        Returns a PollResult rather than raising, because every outcome - including the
        failures - is a row in source_health, and an exception escaping here would lose
        the record of the failure it was reporting.
        """
        if not self._warm:
            error = self.warm_up()
            if error:
                return PollResult(False, None, 0, error=error)
        # A connection idle this long has usually been closed at NSE's end already.
        close_if_idle(self.session, self._last_request, self.idle_after)

        url = self.cfg[endpoint]["url"]
        params = {**self.cfg[endpoint]["params"], **extra_params}
        nse_guard.GUARD.before_request(self.min_gap, self.jitter)
        started = time.monotonic()
        body = None
        try:
            r = self.session.get(url, params=params, timeout=45)
            latency = int((time.monotonic() - started) * 1000)
            if r.status_code in (401, 403):
                # The session has gone stale: warm up again before the next request. The
                # guard counts the failure and backs off.
                self._warm = False
                result = PollResult(False, r.status_code, latency,
                                    error=f"HTTP {r.status_code}: session rejected; will warm up again")
            elif r.status_code != 200:
                result = PollResult(False, r.status_code, latency, error=f"HTTP {r.status_code}")
            else:
                body = r.json()
                result = None
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            result = PollResult(False, None, latency, error=f"{type(exc).__name__}: {exc}")
        self._last_request = time.monotonic()
        if result is not None:
            nse_guard.GUARD.after_request(False, f"{endpoint}: {result.error}")
            return result

        # A 200 with JSON. Only two shapes have ever been seen: a bare list, or an object
        # holding a `data` list. Anything else means NSE changed the endpoint, and storing it
        # as "0 rows" would make a dead source look like a quiet day.
        if isinstance(body, list):
            rows, total = body, None
        elif isinstance(body, dict) and isinstance(body.get("data"), list):
            rows, total = body["data"], body.get("totalCount")
        else:
            shape = sorted(body)[:8] if isinstance(body, dict) else type(body).__name__
            raise NseStructureChanged(f"{endpoint}: unexpected response shape {shape}")
        if endpoint == "announcements":
            check_announcement_fields(rows)
        nse_guard.GUARD.after_request(True, endpoint)
        return PollResult(True, 200, latency, rows=list(rows), total=total)


# Keys collector/records.py reads from an announcement row. A renamed field would otherwise
# be stored as null for ever, silently. Every row must carry the first group; the second may
# be missing on a few very old rows, but a response in which no row carries one means the
# field was renamed.
EVERY_ROW_KEYS = ("symbol", "an_dt", "desc")
SOME_ROW_KEYS = ("seq_id", "sm_isin", "attchmntFile", "exchdisstime")


def check_announcement_fields(rows: list) -> None:
    for row in rows:
        if not isinstance(row, dict):
            raise NseStructureChanged(f"announcements: a row is a {type(row).__name__}")
        missing = [k for k in EVERY_ROW_KEYS if k not in row]
        if missing:
            raise NseStructureChanged(f"announcements: row without {missing}: keys "
                                      f"{sorted(row)[:12]}")
    if rows:
        gone = [k for k in SOME_ROW_KEYS if not any(k in row for row in rows)]
        if gone:
            raise NseStructureChanged(f"announcements: no row carries {gone}")


def jittered(seconds: float, jitter: tuple[float, float]) -> float:
    """Add the configured random delay to a base interval.

    A fixed interval is the clearest bot signature there is (Sect.5.1), so the collector's
    interval is never exactly periodic. `jitter_seconds` in config/sources.yaml is read
    literally as "an extra delay between low and high seconds", which is what keeps two
    consecutive requests from ever being exactly N seconds apart.
    """
    low, high = float(jitter[0]), float(jitter[1])
    return seconds + random.uniform(low, high)
