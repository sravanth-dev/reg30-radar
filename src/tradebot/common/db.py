"""Database access. One connection helper, used by everything that touches Postgres.

Deliberately thin: no ORM, no connection pool, no query builder. The collector makes a
handful of writes a minute against a local database, so a pool would be machinery without
a problem to solve, and an ORM would hide the SQL that the migrations spell out.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from tradebot.common.config import database_url


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Open a connection, commit on success, roll back on any exception."""
    with psycopg.connect(database_url()) as conn:
        yield conn
