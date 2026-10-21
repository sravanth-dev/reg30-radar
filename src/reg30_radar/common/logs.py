"""Log setup shared by every long-running command (collector, orders, sheets).

Log timestamps are always IST, whatever the machine's clock settings say. By default
`logging` stamps records in the process's *local* time, and that turned out to be wrong on
the laptop: `.env` sets `TZ=Asia/Kolkata`, python-dotenv copies it into the environment,
and Windows' C runtime cannot parse an IANA zone name. It silently falls back to UTC, so a
14:31 IST log line printed as 09:01 (WORKLOG, 25 Sep 2026). A Docker container on the VPS
defaults to UTC as well. Converting each record's timestamp with ZoneInfo makes log time
match the IST used everywhere else (D17), independent of either.
"""

from __future__ import annotations

import logging
from datetime import datetime

from reg30_radar.common.calendar import IST

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _ist_converter(timestamp: float):
    return datetime.fromtimestamp(timestamp, IST).timetuple()


def configure(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(FORMAT)
    formatter.converter = _ist_converter
    handler.setFormatter(formatter)
    logging.basicConfig(level=level.upper(), handlers=[handler])
