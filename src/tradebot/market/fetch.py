"""Download one archive file from nsearchives, politely (D25).

Same discipline as the collector and the PDF fetcher: one warmed-up session with the
headers from config/sources.yaml, one request at a time, at least the backfill gap
(>=3 s, jittered) between requests, idle connections closed first (common/http.py). Every
request is counted, the warm-up included, because Spike A overran its budget by exactly
the warm-ups nobody counted (WORKLOG, 22 Sep).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import requests

from tradebot.common.config import nse as nse_config
from tradebot.common.http import close_if_idle

# A UDiFF zip is about 0.5 MB and a PR bundle a few MB; anything far larger is not one.
MAX_BYTES = 50 * 1024 * 1024


@dataclass
class Archive:
    status: int | None
    content: bytes | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.content is not None


class ArchiveFetcher:
    def __init__(self) -> None:
        self.cfg = nse_config()
        pacing = self.cfg["pacing"]
        self.min_gap = float(pacing["backfill_min_gap_seconds"])
        self.jitter = tuple(float(x) for x in pacing["jitter_seconds"])
        self.idle_after = float(pacing["idle_reconnect_seconds"])
        self.session = requests.Session()
        self.session.headers.update({k: str(v) for k, v in self.cfg["headers"].items()})
        self.requests = 0
        self._warm = False
        self._last: float | None = None

    def _pace(self) -> None:
        if self._last is not None:
            wait = self.min_gap + random.uniform(*self.jitter) - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        close_if_idle(self.session, self._last, self.idle_after)
        self._last = time.monotonic()

    def warm_up(self) -> None:
        self._pace()
        self.requests += 1
        self.session.get(self.cfg["warmup_url"], timeout=60)
        self._warm = True

    def get(self, url: str) -> Archive:
        """Returns an Archive rather than raising: every outcome is recorded by the caller,
        and a clean 404 (no file for a non-trading day) is an answer, not an error."""
        if not self._warm:
            try:
                self.warm_up()
            except Exception as exc:
                return Archive(None, error=f"warm-up failed: {type(exc).__name__}: {exc}")
        self._pace()
        self.requests += 1
        try:
            with self.session.get(url, timeout=90, stream=True) as r:
                if r.status_code in (401, 403):
                    self._warm = False      # warm up again before the next request
                    return Archive(r.status_code, error=f"HTTP {r.status_code}")
                if r.status_code != 200:
                    return Archive(r.status_code, error=f"HTTP {r.status_code}")
                chunks, size = [], 0
                for block in r.iter_content(chunk_size=64 * 1024):
                    size += len(block)
                    if size > MAX_BYTES:
                        return Archive(200, error=f"larger than {MAX_BYTES} bytes; refused")
                    chunks.append(block)
                return Archive(200, content=b"".join(chunks))
        except Exception as exc:
            return Archive(None, error=f"{type(exc).__name__}: {exc}")
