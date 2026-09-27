"""Database access. One connection helper, used by everything that touches Postgres.

Deliberately thin: no ORM, no connection pool, no query builder. The collector makes a
handful of writes a minute against a local database, so a pool would be machinery without
a problem to solve, and an ORM would hide the SQL that the migrations spell out.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from tradebot.common.config import backfill_database_url, database_url


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection]:
    """Open a connection, commit on success, roll back on any exception. `url` defaults
    to the live database; the backfill passes `backfill_url()`."""
    with psycopg.connect(url or database_url()) as conn:
        yield conn


def backfill_url() -> str:
    return backfill_database_url()
