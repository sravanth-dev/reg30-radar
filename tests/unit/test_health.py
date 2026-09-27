"""The collector healthcheck's freshness rule (common/health.py). No database."""

from datetime import datetime, timedelta, timezone

from tradebot.common.health import is_fresh

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
LIMIT = timedelta(minutes=30)


def test_never_polled_is_unhealthy():
    assert not is_fresh(None, NOW, LIMIT)


def test_recent_success_is_healthy():
    assert is_fresh(NOW - timedelta(minutes=11), NOW, LIMIT)


def test_stale_success_is_unhealthy():
    assert not is_fresh(NOW - timedelta(minutes=31), NOW, LIMIT)
