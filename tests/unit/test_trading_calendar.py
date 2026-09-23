"""The trading-day calendar, against the real committed config/holidays_2026.yaml.

The single most important behaviour here is the one that is easiest to regress: the
calendar must FAIL rather than assume. D27 exists because a silent "every weekday trades"
fallback would poison first_seen_at for the forward-collected sample, which cannot be
re-collected.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tradebot.common import calendar as cal

IST = ZoneInfo("Asia/Kolkata")
CAL = cal.load(2026)

PACING = {
    "market_window_ist": ["08:00", "22:00"],
    "market_window_seconds": 60,
    "off_window_seconds": 600,
}


def test_ordinary_weekday_trades():
    assert CAL.is_trading_day(date(2026, 9, 23))       # a Wednesday, no holiday


def test_weekend_does_not_trade():
    assert not CAL.is_trading_day(date(2026, 9, 26))   # Saturday
    assert not CAL.is_trading_day(date(2026, 9, 27))   # Sunday


@pytest.mark.parametrize("day, name", [
    (date(2026, 1, 26), "Republic Day"),
    (date(2026, 3, 3), "Holi"),
    (date(2026, 10, 2), "Mahatma Gandhi Jayanti"),
    (date(2026, 12, 25), "Christmas"),
])
def test_listed_weekday_holidays_do_not_trade(day, name):
    assert not CAL.is_trading_day(day)
    assert name in CAL.describe(day)


def test_muhurat_sunday_does_trade():
    # 8 Nov 2026 is a Sunday AND a Muhurat session. It must beat the weekend rule, which
    # is the failure D27's post-close reconciliation was written to catch.
    day = date(2026, 11, 8)
    assert day.weekday() == 6
    assert CAL.is_trading_day(day)
    assert not CAL.special[day].full_length


def test_weekend_holidays_need_no_holiday_row():
    # Four of NSE's twenty 2026 entries fall on a weekend, so regular_week already closes
    # them. They must still come out as non-trading.
    for day in (date(2026, 2, 15), date(2026, 3, 21), date(2026, 8, 15)):
        assert not CAL.is_trading_day(day)


def test_a_year_with_no_file_raises_rather_than_assuming():
    with pytest.raises(cal.CalendarError):
        CAL.is_trading_day(date(2027, 1, 4))
    with pytest.raises(cal.CalendarError):
        cal.load(2099)


def test_poll_interval_follows_d6():
    trading_morning = datetime(2026, 9, 23, 10, 0, tzinfo=IST)
    trading_late = datetime(2026, 9, 23, 23, 30, tzinfo=IST)
    holiday_midday = datetime(2026, 12, 25, 12, 0, tzinfo=IST)

    assert cal.poll_seconds(trading_morning, CAL, PACING) == 60
    assert cal.poll_seconds(trading_late, CAL, PACING) == 600
    assert cal.poll_seconds(holiday_midday, CAL, PACING) == 600


def test_market_window_edges():
    # D6's window is 08:00 to 22:00 IST, inclusive of the start and exclusive of the end.
    assert cal.in_market_window(datetime(2026, 9, 23, 8, 0, tzinfo=IST), PACING)
    assert cal.in_market_window(datetime(2026, 9, 23, 21, 59, tzinfo=IST), PACING)
    assert not cal.in_market_window(datetime(2026, 9, 23, 7, 59, tzinfo=IST), PACING)
    assert not cal.in_market_window(datetime(2026, 9, 23, 22, 0, tzinfo=IST), PACING)


def test_next_year_warning_only_fires_in_december():
    assert cal.next_year_file_warning(date(2026, 11, 30)) is None
    warning = cal.next_year_file_warning(date(2026, 12, 1))
    assert warning is not None and "holidays_2027.yaml" in warning
