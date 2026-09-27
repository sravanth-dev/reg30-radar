"""Is the collector alive? Exit 0 if `source_health` has a successful poll recent enough,
1 otherwise. Used as the collector container's Docker healthcheck.

    python -m tradebot.common.health --max-age-minutes 30

A running process is not the same as a working collector: the loop can be alive while
every poll fails (a stale session, a network outage) or stuck. `source_health` records
every poll, so "when did a poll last succeed" is the honest signal. The default of 30
minutes is three of the slowest (10-minute) polls, so one or two failed polls in a row
do not flip the container to unhealthy.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from tradebot.collector.records import SOURCE
from tradebot.common.db import connect

LAST_OK_SQL = "select max(checked_at) from source_health where source = %s and ok"


def is_fresh(last_ok: datetime | None, now: datetime, max_age: timedelta) -> bool:
    return last_ok is not None and now - last_ok <= max_age


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tradebot.common.health")
    parser.add_argument("--max-age-minutes", type=float, default=30)
    args = parser.parse_args(argv)

    try:
        with connect() as conn:
            last_ok = conn.execute(LAST_OK_SQL, (SOURCE,)).fetchone()[0]
    except Exception as exc:
        print(f"unhealthy: database unreachable: {type(exc).__name__}")
        return 1

    now = datetime.now(timezone.utc)
    if is_fresh(last_ok, now, timedelta(minutes=args.max_age_minutes)):
        print(f"healthy: last successful poll {last_ok.isoformat()}")
        return 0
    print(f"unhealthy: last successful poll {last_ok.isoformat() if last_ok else 'never'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
