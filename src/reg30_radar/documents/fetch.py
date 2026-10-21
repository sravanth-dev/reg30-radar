"""Download one filing PDF, politely and with a size ceiling.

Reuses the collector's session discipline (D25): one warmed-up session, browser-like
headers from `config/sources.yaml`, one request at a time, jittered pacing, backoff on
failure. Nothing here rotates anything.

The size ceiling is not decoration. The worker runs under `mem_limit: 512m` beside n8n on a
2-vCPU box (Sect.9), and pdfplumber holds a page's objects in memory while parsing, so an
unexpectedly huge file is the one download that can take the container down. Streaming with
a cap turns that into a recorded refusal instead.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from reg30_radar.common import nse_guard
from reg30_radar.common.config import nse as nse_config
from reg30_radar.common.http import close_if_idle


@dataclass
class Fetched:
    ok: bool
    path: Path | None = None
    sha256: str | None = None
    size_bytes: int = 0
    http_status: int | None = None
    error: str | None = None


class PdfFetcher:
    """A warmed-up session for attachment downloads.

    Separate from NseClient because the two have different jobs and different rates: the
    collector polls one JSON endpoint on a schedule, this pulls files from the archive host
    at the backfill pace. Sharing one session would make the slower job's backoff interfere
    with the faster job's schedule.
    """

    def __init__(self) -> None:
        self.cfg = nse_config()
        docs = self.cfg.get("documents", {})
        self.max_bytes = int(docs.get("max_bytes", 25 * 1024 * 1024))
        self.chunk = int(docs.get("chunk_bytes", 64 * 1024))
        pacing = self.cfg["pacing"]
        self.min_gap = float(pacing["backfill_min_gap_seconds"])
        self.jitter = tuple(float(x) for x in pacing["jitter_seconds"])
        self.idle_after = float(pacing["idle_reconnect_seconds"])
        self.session = requests.Session()
        self.session.headers.update({k: str(v) for k, v in self.cfg["headers"].items()})
        self._warm = False
        self._last = 0.0

    def warm_up(self) -> str | None:
        """Pick up the Akamai cookies. Returns None when warmed up, else why not."""
        nse_guard.GUARD.before_request(self.min_gap, self.jitter)
        error = None
        try:
            r = self.session.get(self.cfg["warmup_url"], timeout=60)
            if r.status_code != 200:
                error = f"warm-up HTTP {r.status_code}"
        except Exception as exc:
            error = f"warm-up {type(exc).__name__}: {exc}"
        self._last = time.monotonic()
        self._warm = error is None
        nse_guard.GUARD.after_request(error is None, error or "warm-up")
        return error

    def _pace(self) -> None:
        """Never faster than the backfill gap, never exactly periodic (Sect.5.1), and
        measured against every NSE request in the process, not only this client's
        (common/nse_guard.py)."""
        nse_guard.GUARD.before_request(self.min_gap, self.jitter)
        self._last = time.monotonic()

    def fetch(self, url: str, dest_dir: Path) -> Fetched:
        """Stream one PDF into `dest_dir`, hashing as it goes.

        Hashing during the stream rather than re-reading the file afterwards means the hash
        describes exactly the bytes received, which is what the Sect.5.5 re-download check
        compares against later.

        Returns a Fetched rather than raising: a failed download is a recorded outcome, and
        an exception escaping here would lose the record of what went wrong.
        """
        if not self._warm:
            error = self.warm_up()
            if error:
                return Fetched(False, error=error)
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Between --follow cycles this session sits idle for minutes, long enough for
        # NSE to close the pooled connection (common/http.py). Checked before _pace()
        # moves the clock forward.
        close_if_idle(self.session, self._last or None, self.idle_after)
        self._pace()

        got = self._download(url, dest_dir)
        self._last = time.monotonic()
        # A file over the size cap is a fact about that file, not a sign NSE is failing, so
        # it does not count towards the 5-in-a-row stop. Every other refusal does.
        ok = got.ok or (got.error or "").startswith("exceeds max_bytes")
        nse_guard.GUARD.after_request(ok, f"PDF {url}: {got.error}")
        return got

    def _download(self, url: str, dest_dir: Path) -> Fetched:
        digest = hashlib.sha256()
        size = 0
        tmp = dest_dir / f"download-{int(time.time() * 1000)}.part"
        try:
            with self.session.get(url, timeout=90, stream=True) as r:
                if r.status_code != 200:
                    if r.status_code in (401, 403):
                        self._warm = False      # warm up again before the next request
                    return Fetched(False, http_status=r.status_code,
                                   error=f"HTTP {r.status_code}")
                with tmp.open("wb") as fh:
                    for block in r.iter_content(chunk_size=self.chunk):
                        if not block:
                            continue
                        size += len(block)
                        if size > self.max_bytes:
                            fh.close()
                            tmp.unlink(missing_ok=True)
                            return Fetched(
                                False, http_status=r.status_code, size_bytes=size,
                                error=f"exceeds max_bytes ({self.max_bytes}); refused")
                        digest.update(block)
                        fh.write(block)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return Fetched(False, error=f"{type(exc).__name__}: {exc}")

        sha = digest.hexdigest()
        # Name the file by its hash: two events sharing one attachment (Sect.5.3's dedup
        # case) then collide on disk instead of downloading twice.
        final = dest_dir / f"{sha}.pdf"
        tmp.replace(final)

        with final.open("rb") as fh:
            is_pdf = fh.read(4) == b"%PDF"
        if not is_pdf:
            # A 200 that is not a PDF is usually an Akamai interstitial, or an empty body
            # (RVNL's 1.32 MB attachment came back as 0 bytes, 28 Sep 2026). Keep nothing.
            # Deleted only after the read handle is closed: Windows refuses to delete an
            # open file, and doing it inside the `with` crashed the backfill that day.
            final.unlink(missing_ok=True)
            return Fetched(False, sha256=sha, size_bytes=size, http_status=200,
                           error="response is not a PDF")

        return Fetched(True, path=final, sha256=sha, size_bytes=size, http_status=200)


def sha256_of(path: Path) -> str:
    """Hash a file already on disk, for the Sect.5.5 re-download check."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
