"""One gate that every request to NSE passes through, whichever client sends it.

Three clients talk to NSE: the announcements/results API client (`collector/nse.py`), the
archive fetcher (`market/fetch.py`) and the PDF fetcher (`documents/fetch.py`). Each used
to pace only against its own last request, so the first XBRL download in `revenue` went
out right after a listing call, and nothing stopped a run when NSE kept failing: on 4 Oct
2026 a DNS outage marked 55 companies failed in three minutes. Sravanth's 20 Oct brief
(ARCHITECTURE D30, CLAUDE.md scraping rules) sets rules that only a shared gate can keep:

1. **One process at a time.** The first request of a process takes `data/nse.lock` and a
   second process refuses to start sending (`NseBusy`). A lock left by a process that died
   is noticed and replaced.
2. **One clock for every host.** The gap is measured from the end of the previous NSE
   request, whichever client sent it.
3. **Backoff after a failure**, exponential with jitter. It is the minimum gap since the
   last request, not an extra sleep on top, so it never compounds with a caller's own
   backoff (the collector sleeps its own; the guard then has nothing left to add).
4. **A hard stop after 5 consecutive failures** (`NseHardStop`), so an outage ends a run
   in minutes with a clear message instead of burning through the work list.

A clean 404 for an archive file is an answer (no file for a non-trading day), not a
failure. The clients decide what counts as ok; this module only keeps the score.

Both exceptions derive from BaseException on purpose. The clients and the loops catch
`Exception` everywhere to turn a failure into a recorded outcome; a hard stop must get
past all of them and end the process, as KeyboardInterrupt does.
"""

from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from reg30_radar.common.config import ROOT

log = logging.getLogger("nse")

FAILURE_LIMIT = 5
LOCK_PATH = ROOT / "data" / "nse.lock"


class NseHardStop(BaseException):
    """End the process: NSE has failed too often in a row, or answered in a shape the
    code does not understand. Never caught by `except Exception`."""


class NseBusy(NseHardStop):
    """Another live process holds the NSE lock."""


class NseStructureChanged(NseHardStop):
    """NSE answered with a body whose shape the parser does not recognise. Stops at once:
    retrying cannot fix it, and storing it as "0 rows" would hide it."""


def backoff_seconds(consecutive_failures: int, *, cap: float = 600.0) -> float:
    """Exponential backoff with jitter: about 30, 60, 120, 240 s. Never a tight loop."""
    if consecutive_failures <= 0:
        return 0.0
    base = min(cap, 30.0 * (2 ** (consecutive_failures - 1)))
    return base * random.uniform(0.7, 1.3)


def pid_alive(pid: int | None) -> bool:
    """Whether a process with this id is running. Not `os.kill(pid, 0)`: on Windows that
    call does not probe, it terminates the process."""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied still means the process exists; anything else means it doesn't.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class NseGuard:
    def __init__(self, lock_path: Path = LOCK_PATH, *, sleep=time.sleep,
                 failure_limit: int = FAILURE_LIMIT, alive=pid_alive) -> None:
        self.lock_path = Path(lock_path)
        self.sleep = sleep
        self.failure_limit = failure_limit
        self.alive = alive
        self.consecutive_failures = 0
        self.last_failure: str | None = None
        self.requests = 0
        self._last_end: float | None = None
        self._locked = False

    # --- the lock ------------------------------------------------------------------------

    def acquire(self) -> None:
        """Take the machine-wide lock, or raise NseBusy naming the process that holds it.
        Called by the first request; an entry point may call it earlier to fail fast."""
        if self._locked:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = self._holder()
                pid = holder.get("pid") if holder else None
                if pid and pid != os.getpid() and self.alive(pid):
                    raise NseBusy(
                        f"another process is talking to NSE (pid {pid}, since "
                        f"{holder.get('started')}: {holder.get('command')}). Only one may at "
                        f"a time. If no such process is running, delete {self.lock_path}.")
                log.warning("removing a stale NSE lock left by pid %s", pid)
                self.lock_path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(),
                           "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "command": " ".join(sys.argv)[:200]}, fh)
            self._locked = True
            atexit.register(self.release)
            return
        raise NseBusy(f"could not take the NSE lock at {self.lock_path}")

    def release(self) -> None:
        if not self._locked:
            return
        holder = self._holder()
        if holder and holder.get("pid") == os.getpid():
            self.lock_path.unlink(missing_ok=True)
        self._locked = False

    def _holder(self) -> dict | None:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # --- pacing, backoff and the breaker ---------------------------------------------------

    def before_request(self, min_gap: float, jitter: tuple[float, float] = (0.0, 0.0)) -> None:
        """Call immediately before every NSE request, warm-ups included. Takes the lock on
        the first call, then waits until the gap since the last request has passed."""
        self.acquire()
        if self.consecutive_failures >= self.failure_limit:
            raise NseHardStop(self._stop_message())
        gap = float(min_gap) + random.uniform(*jitter)
        if self.consecutive_failures:
            gap = max(gap, backoff_seconds(self.consecutive_failures))
        if self._last_end is not None:
            wait = gap - (time.monotonic() - self._last_end)
            if wait > 0:
                self.sleep(wait)
        self.requests += 1

    def after_request(self, ok: bool, what: str) -> None:
        """Record one request's outcome. The 5th failure in a row raises NseHardStop."""
        self._last_end = time.monotonic()
        if ok:
            self.consecutive_failures = 0
            return
        self.consecutive_failures += 1
        self.last_failure = what
        log.warning("NSE request failed (%d in a row): %s", self.consecutive_failures, what)
        if self.consecutive_failures >= self.failure_limit:
            raise NseHardStop(self._stop_message())

    def _stop_message(self) -> str:
        return (f"stopping: {self.consecutive_failures} consecutive failed NSE requests "
                f"(last: {self.last_failure}). Nothing is lost: every stage resumes from its "
                f"checkpoints. Check the connection before running again.")


# The process-wide guard. Clients look it up at call time (`nse_guard.GUARD`), so tests can
# swap in one with a fake clock and a temporary lock file.
GUARD = NseGuard()


def run(main, *args) -> int:
    """Run an entry point's main(). A hard stop ends it with one clear log line and exit
    code 3 instead of a traceback, and the lock is always given back."""
    try:
        return main(*args)
    except NseHardStop as stop:
        log.error("%s: %s", type(stop).__name__, stop)
        return 3
    finally:
        GUARD.release()
