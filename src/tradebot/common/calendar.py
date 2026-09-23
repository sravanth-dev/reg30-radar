"""Is today a trading day, and how often should the collector poll?

D27 splits this by direction. For **past** dates a day is a trading day if an archive
exists for it, which is free and self-maintaining. This module is the **future** half:
the live collector at 08:00 cannot consult a bhavcopy that is published after the close,
so it reads a hand-maintained `config/holidays_<year>.yaml` instead.

The one rule that matters more than any other here: **fail loudly**. A missing or
uncovered calendar must raise, never fall back to "assume every weekday trades". That
fallback fails silently, and a silent failure in the one place the system runs forward
would poison `first_seen_at` for the whole forward-collected sample, which by definition
cannot be re-collected (D23).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from tradebot.common.config import CONFIG_DIR, load_yaml

IST = ZoneInfo("Asia/Kolkata")

_WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday",
                  "saturday", "sunday"]


class CalendarError(RuntimeError):
    """The calendar cannot answer for the date asked. Always fatal for the collector."""


@dataclass(frozen=True)
class SpecialSession:
    """A session outside the regular pattern - a weekend sitting, or a short one."""
    date: date
    name: str
    trades: bool
    full_length: bool


@dataclass(frozen=True)
class TradingCalendar:
    year: int
    regular_week: frozenset[str]
    holidays: dict[date, str]
    special: dict[date, SpecialSession]

    def is_trading_day(self, day: date) -> bool:
        if day.year != self.year:
            raise CalendarError(
                f"no calendar loaded for {day.year}; "
                f"config/holidays_{day.year}.yaml is required before the collector can "
                f"run on that date"
            )
        # A special session wins over both the holiday list and the weekly pattern. That
        # is the whole point of it: Muhurat trades on a Sunday that is also a holiday.
        if day in self.special:
            return self.special[day].trades
        if day in self.holidays:
            return False
        return _WEEKDAY_NAMES[day.weekday()] in self.regular_week

    def describe(self, day: date) -> str:
        if day in self.special:
            s = self.special[day]
            return f"{s.name} (special session, trades={s.trades}, full_length={s.full_length})"
        if day in self.holidays:
            return f"holiday: {self.holidays[day]}"
        return "regular trading day" if self.is_trading_day(day) else "weekend"


def load(year: int) -> TradingCalendar:
    """Load `config/holidays_<year>.yaml`, raising CalendarError on anything unusable."""
    name = f"holidays_{year}.yaml"
    path = CONFIG_DIR / name
    if not path.exists():
        raise CalendarError(
            f"missing {path}. D27 requires this file to be maintained by hand before the "
            f"live collector runs; a template is in config/holidays_{year}.example.yaml"
        )
    try:
        raw = load_yaml(name)
    except Exception as exc:                      # unparseable YAML is fatal, not a warning
        raise CalendarError(f"cannot parse {path}: {exc}") from exc

    if not isinstance(raw, dict) or raw.get("year") != year:
        raise CalendarError(f"{path} does not declare year: {year}")

    week = raw.get("regular_week")
    if not week:
        raise CalendarError(f"{path} has no regular_week")

    holidays: dict[date, str] = {}
    for item in raw.get("holidays") or []:
        day = _as_date(item.get("date"), path)
        holidays[day] = item.get("name", "")

    special: dict[date, SpecialSession] = {}
    for item in raw.get("special_sessions") or []:
        day = _as_date(item.get("date"), path)
        special[day] = SpecialSession(
            date=day,
            name=item.get("name", ""),
            trades=bool(item.get("trades", False)),
            # An hour-long session is not a normal day; Sect.5.11 excludes it from volume
            # baselines and flags events whose day 0 lands on one.
            full_length=bool(item.get("full_length", True)),
        )

    return TradingCalendar(
        year=year,
        regular_week=frozenset(str(d).lower() for d in week),
        holidays=holidays,
        special=special,
    )


def _as_date(value, path) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise CalendarError(f"{path}: expected a date, got {value!r}")


def now_ist() -> datetime:
    return datetime.now(IST)


def in_market_window(moment: datetime, pacing: dict) -> bool:
    """Is this moment inside D6's 08:00-22:00 IST collection window?"""
    start_s, end_s = pacing["market_window_ist"]
    start, end = _as_time(start_s), _as_time(end_s)
    return start <= moment.timetz().replace(tzinfo=None) < end


def poll_seconds(moment: datetime, cal: TradingCalendar, pacing: dict) -> int:
    """The base interval for right now: 60 s inside the window on a trading day, else 10 min.

    Jitter is applied by the caller, never here - a pure function that returns a different
    number every call cannot be tested.
    """
    if cal.is_trading_day(moment.date()) and in_market_window(moment, pacing):
        return int(pacing["market_window_seconds"])
    return int(pacing["off_window_seconds"])


def _as_time(value: str) -> time:
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


def next_year_file_warning(today: date) -> str | None:
    """From 1 December, warn daily until next year's calendar exists (Sect.5.1).

    Without this the collector would fail loudly on 1 January - correct, but late, and on
    a day nobody is watching.
    """
    if today.month != 12:
        return None
    nxt = today.year + 1
    if (CONFIG_DIR / f"holidays_{nxt}.yaml").exists():
        return None
    return (
        f"config/holidays_{nxt}.yaml does not exist yet. The collector will refuse to run "
        f"on 1 Jan {nxt} without it (D27)."
    )
