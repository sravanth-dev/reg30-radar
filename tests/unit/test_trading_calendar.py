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

# Mirrors config/sources.yaml. D6 was revised on 23 Sep 2026 into three bands, after
# measurement showed roughly two thirds of a day's filings arrive after 16:00.
PACING = {
    "bands": [
        {"from": "08:00", "to": "15:30", "seconds": 60},
        {"from": "15:30", "to": "22:00", "seconds": 180},
    ],
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


@pytest.mark.parametrize("hh, mm, expected", [
    (7, 59, 600),    # before the window opens
    (8, 0, 60),      # window opens
    (10, 0, 60),     # continuous trading
    (15, 29, 60),    # last minute of continuous trading
    (15, 30, 180),   # the close: post-close band takes over, slower but not idle
    (17, 0, 180),    # the busiest hour of the day, measured 17 and 21 Sep
    (21, 59, 180),   # last minute of the collection window
    (22, 0, 600),    # window closes
    (23, 30, 600),
])
def test_poll_interval_follows_the_three_bands(hh, mm, expected):
    moment = datetime(2026, 9, 23, hh, mm, tzinfo=IST)   # a Wednesday, trading day
    assert cal.poll_seconds(moment, CAL, PACING) == expected


def test_bands_do_not_apply_on_a_non_trading_day():
    # 17:00 is the busiest filing hour, but on Christmas nothing is trading, so the
    # collector must drop to the off-window rate rather than the post-close rate.
    assert cal.poll_seconds(datetime(2026, 12, 25, 17, 0, tzinfo=IST), CAL, PACING) == 600
    assert cal.poll_seconds(datetime(2026, 9, 26, 17, 0, tzinfo=IST), CAL, PACING) == 600


def test_bands_are_half_open_so_1530_belongs_to_one_band_only():
    # Adjacent bands must not both claim the boundary minute.
    assert cal.band_for(datetime(2026, 9, 23, 15, 30, tzinfo=IST), PACING)["seconds"] == 180
    assert cal.band_for(datetime(2026, 9, 23, 15, 29, tzinfo=IST), PACING)["seconds"] == 60
    assert cal.band_for(datetime(2026, 9, 23, 22, 0, tzinfo=IST), PACING) is None


def test_next_year_warning_only_fires_in_december():
    assert cal.next_year_file_warning(date(2026, 11, 30)) is None
    warning = cal.next_year_file_warning(date(2026, 12, 1))
    assert warning is not None and "holidays_2027.yaml" in warning
