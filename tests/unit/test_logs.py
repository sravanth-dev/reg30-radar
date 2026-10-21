"""Log timestamps are IST regardless of the process's local-time setting (common/logs.py)."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from reg30_radar.common import logs


def test_log_time_is_ist_even_when_the_record_time_is_utc_midnight():
    # 00:00 UTC is 05:30 IST. A formatter using the machine's local time would print
    # whatever that machine thinks - 00:00 on the laptop, where TZ=Asia/Kolkata in .env
    # silently becomes UTC under Windows' C runtime.
    utc_midnight = datetime(2026, 9, 25, 0, 0, tzinfo=ZoneInfo("UTC")).timestamp()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    record.created = utc_midnight
    record.msecs = 0

    formatter = logging.Formatter(logs.FORMAT)
    formatter.converter = logs._ist_converter

    assert formatter.format(record).startswith("2026-09-25 05:30:00")
