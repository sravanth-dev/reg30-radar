"""Apply `migrations/*.sql` in filename order, once each.

Plain numbered SQL files and a small runner (ARCHITECTURE Sect.7): every schema change is
readable in the diff, and nothing is generated from Python objects.

Run with:  python -m tradebot.common.migrate
"""

from __future__ import annotations

import sys
from pathlib import Path

from tradebot.common.config import ROOT
from tradebot.common.db import connect

MIGRATIONS_DIR = ROOT / "migrations"


def pending(conn) -> list[Path]:
    """Migrations on disk that the database has not recorded as applied."""
    # The very first migration creates schema_migrations, so the table may not exist yet.
    exists = conn.execute(
        "select to_regclass('public.schema_migrations') is not null"
    ).fetchone()[0]
    applied: set[str] = set()
    if exists:
        applied = {row[0] for row in conn.execute("select version from schema_migrations")}

    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    return [p for p in files if p.stem not in applied]


def apply_all() -> list[str]:
    """Apply every pending migration. Each one runs in its own transaction."""
    done: list[str] = []
    with connect() as conn:
        for path in pending(conn):
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "insert into schema_migrations (version) values (%s)", (path.stem,)
                )
            done.append(path.stem)
            print(f"applied {path.stem}")
    if not done:
        print("nothing to apply; database is up to date")
    return done


if __name__ == "__main__":
    sys.exit(0 if apply_all() is not None else 1)
