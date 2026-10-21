"""Session housekeeping shared by every client that talks to NSE.

One thing lives here: dropping pooled connections that have sat idle long enough for the
far end to have closed them.

Why it exists (WORKLOG, 27 Sep 2026): `requests.Session` keeps a finished connection open
and reuses it for the next request. NSE closes a connection that has been idle for a few
minutes, but the session does not know that, so the next request goes out on a dead
socket and fails with `ConnectionResetError(10054)`. At the collector's 60 s band this
never happens. At the 10-minute band it happened on almost every poll: on 26 Sep, a
Saturday, 34 of 61 polls failed that way, and each one cost a spurious failure row, a
second request and a 30 s backoff. Closing the pool before a request that follows a long
idle gap makes that request open a fresh connection instead.

`Session.close()` only empties the connection pool. The cookies, including the Akamai ones
the warm-up collected, stay on the session, and the next request simply opens a new
socket (checked on this laptop before relying on it).
"""

from __future__ import annotations

import time


def close_if_idle(session, last_request: float | None, idle_after: float) -> bool:
    """Close `session`'s pooled connections if the last request was `idle_after` seconds
    or more ago (both on the `time.monotonic()` clock). Returns whether it closed them.

    `last_request` is None before the first request, when there is nothing to close.
    """
    if last_request is None:
        return False
    if time.monotonic() - last_request < idle_after:
        return False
    session.close()
    return True
