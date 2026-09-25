"""orders/__main__.py's argument parsing, offline (no download, no LLM, no database).

Regression coverage for a real bug: `--from`/`--to` alone (no `--date`) failed with
"one of the arguments --date --follow is required" the first time it was used for a real
run, because `--date`/`--follow` were an argparse `required=True` mutually exclusive group
that had no way to know `--from`+`--to` together also satisfy "a mode was chosen"
(WORKLOG, 25 Sep 2026). Every valid and invalid combination is checked directly against
`main()`'s own validation, not re-implemented here.
"""

from __future__ import annotations

from datetime import date

import pytest

from tradebot.orders import __main__ as orders_main


def test_date_alone_calls_run_batch_for_that_single_day(monkeypatch):
    calls = []
    monkeypatch.setattr(orders_main, "run_batch",
                         lambda **kw: calls.append(kw) or 0)
    assert orders_main.main(["--date", "2026-09-23"]) == 0
    assert calls == [{"since": date(2026, 9, 23), "until": date(2026, 9, 23),
                       "max_requests": 200}]


def test_from_to_alone_calls_run_batch_for_the_range(monkeypatch):
    """The exact case that broke on the first real run: --from/--to with no --date."""
    calls = []
    monkeypatch.setattr(orders_main, "run_batch",
                         lambda **kw: calls.append(kw) or 0)
    assert orders_main.main(["--from", "2026-09-24", "--to", "2026-09-25"]) == 0
    assert calls == [{"since": date(2026, 9, 24), "until": date(2026, 9, 25),
                       "max_requests": 200}]


def test_follow_alone_calls_run_follow(monkeypatch):
    calls = []
    monkeypatch.setattr(orders_main, "run_follow", lambda: calls.append(1) or 0)
    assert orders_main.main(["--follow"]) == 0
    assert calls == [1]


def test_no_mode_at_all_is_an_error():
    with pytest.raises(SystemExit):
        orders_main.main([])


def test_from_without_to_is_an_error():
    with pytest.raises(SystemExit):
        orders_main.main(["--from", "2026-09-24"])


def test_date_and_from_together_is_an_error():
    with pytest.raises(SystemExit):
        orders_main.main(["--date", "2026-09-23", "--from", "2026-09-24", "--to", "2026-09-25"])


def test_follow_and_date_together_is_an_error():
    with pytest.raises(SystemExit):
        orders_main.main(["--follow", "--date", "2026-09-23"])


def test_max_requests_is_passed_through(monkeypatch):
    calls = []
    monkeypatch.setattr(orders_main, "run_batch",
                         lambda **kw: calls.append(kw) or 0)
    orders_main.main(["--date", "2026-09-23", "--max-requests", "5"])
    assert calls[0]["max_requests"] == 5
