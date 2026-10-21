"""The shared NSE gate (common/nse_guard.py): one process at a time, one clock across hosts,
non-compounding backoff, and a hard stop after 5 consecutive failures (brief, 20 Oct 2026).
No network: the guard is driven directly, with a controlled clock and recorded sleeps."""

import json
import os

import pytest

from reg30_radar.common import nse_guard
from reg30_radar.common.nse_guard import NseBusy, NseGuard, NseHardStop


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


def make(tmp_path, clock, **kw):
    slept = []

    def sleep(s):
        slept.append(s)
        clock.now += s

    return NseGuard(tmp_path / "nse.lock", sleep=sleep, **kw), slept


def test_the_fifth_consecutive_failure_stops_the_run(tmp_path, clock):
    g, _ = make(tmp_path, clock)
    for n in range(4):
        g.before_request(0)
        g.after_request(False, f"fail {n}")
    g.before_request(0)
    with pytest.raises(NseHardStop, match="5 consecutive"):
        g.after_request(False, "fail 4")
    # and nothing more may be sent after the stop
    with pytest.raises(NseHardStop):
        g.before_request(0)


def test_a_success_resets_the_count(tmp_path, clock):
    g, _ = make(tmp_path, clock)
    for n in range(4):
        g.before_request(0)
        g.after_request(False, "x")
    g.before_request(0)
    g.after_request(True, "ok")
    for n in range(4):
        g.before_request(0)
        g.after_request(False, "y")
    assert g.consecutive_failures == 4          # not stopped: the run was interrupted by a success


def test_a_hard_stop_gets_past_except_exception(tmp_path, clock):
    # The clients catch Exception to record failures; the stop must not be swallowed.
    g, _ = make(tmp_path, clock, failure_limit=1)
    g.before_request(0)
    with pytest.raises(NseHardStop):
        try:
            g.after_request(False, "boom")
        except Exception:                        # noqa: BLE001 - exactly what clients do
            pytest.fail("NseHardStop was caught by `except Exception`")


def test_the_gap_is_kept_from_the_end_of_the_last_request(tmp_path, clock):
    g, slept = make(tmp_path, clock)
    g.before_request(3.0)
    clock.now += 10                              # a slow 10-second download
    g.after_request(True, "pdf")
    g.before_request(3.0)                        # a different client, same process
    assert slept == [pytest.approx(3.0)]


def test_backoff_is_a_minimum_gap_not_an_extra_sleep(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(nse_guard.random, "uniform", lambda a, b: 1.0 if a == 0.7 else 0.0)
    g, slept = make(tmp_path, clock)
    g.before_request(3.0)
    g.after_request(False, "reset")
    clock.now += 30                              # the caller already slept its own 30 s backoff
    g.before_request(3.0)
    assert slept == []                           # nothing added on top
    g.after_request(False, "reset again")
    g.before_request(3.0)                        # straight away: the guard enforces 60 s
    assert slept == [pytest.approx(60.0)]


def test_a_second_process_is_refused_while_the_first_is_alive(tmp_path, clock):
    lock = tmp_path / "nse.lock"
    lock.write_text(json.dumps({"pid": 4242, "started": "x", "command": "backfill documents"}))
    g, _ = make(tmp_path, clock, alive=lambda pid: pid == 4242)
    with pytest.raises(NseBusy, match="pid 4242"):
        g.before_request(0)
    assert json.loads(lock.read_text())["pid"] == 4242      # the holder's lock is untouched


def test_a_stale_lock_from_a_dead_process_is_replaced(tmp_path, clock):
    lock = tmp_path / "nse.lock"
    lock.write_text(json.dumps({"pid": 4242}))
    g, _ = make(tmp_path, clock, alive=lambda pid: False)
    g.before_request(0)
    assert json.loads(lock.read_text())["pid"] == os.getpid()
    g.release()
    assert not lock.exists()


def test_release_never_deletes_another_process_lock(tmp_path, clock):
    lock = tmp_path / "nse.lock"
    g, _ = make(tmp_path, clock)
    g.acquire()
    lock.write_text(json.dumps({"pid": 4242}))   # somebody replaced it
    g.release()
    assert lock.exists()


def test_this_process_is_alive_and_a_bogus_pid_is_not():
    assert nse_guard.pid_alive(os.getpid())
    assert not nse_guard.pid_alive(0)
    assert not nse_guard.pid_alive(None)


def test_a_process_that_has_exited_is_not_alive():
    # Exercises the real OS call (ctypes on Windows), not a fake.
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not nse_guard.pid_alive(p.pid)
