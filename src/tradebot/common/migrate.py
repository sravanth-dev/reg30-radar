"""Apply `migrations/*.sql` in filename order, once each.

Plain numbered SQL files and a small runner (ARCHITECTURE Sect.7): every schema change is
readable in the diff, and nothing is generated from Python objects.

Run with:  python -m tradebot.common.migrate              the live database
           python -m tradebot.common.migrate --backfill   the laptop's tradebot_backfill
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tradebot.common.config import ROOT
from tradebot.common.db import backfill_url, connect

MIGRATIONS_DIR = ROOT / "migrations"


def pending(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Migrations on disk that the database has not recorded as applied."""
    # The very first migration creates schema_migrations, so the table may not exist yet.
    exists = conn.execute(
        "select to_regclass('public.schema_migrations') is not null"
    ).fetchone()[0]
    applied: set[str] = set()
    if exists:
        applied = {row[0] for row in conn.execute("select version from schema_migrations")}

    files = sorted(p for p in migrations_dir.glob("*.sql"))
    return [p for p in files if p.stem not in applied]


def apply_all(url: str | None = None, *, conn=None,
              migrations_dir: Path | None = None) -> list[str]:
    """Apply every pending migration, each in its own committed transaction, so a
    failure leaves every earlier file applied and recorded. `conn` and `migrations_dir` are
    for tests."""
    if conn is None:
        with connect(url) as own:
            return apply_all(conn=own, migrations_dir=migrations_dir)
    done: list[str] = []
    todo = pending(conn, migrations_dir or MIGRATIONS_DIR)
    # pending()'s reads opened an implicit transaction; end it, or every
    # `conn.transaction()` below would only be a savepoint inside it.
    conn.commit()
    for path in todo:
        sql = path.read_text(encoding="utf-8")
        with conn.transaction():
            conn.execute(sql)
            conn.execute("insert into schema_migrations (version) values (%s)", (path.stem,))
        done.append(path.stem)
        print(f"applied {path.stem}")
    if not done:
        print("nothing to apply; database is up to date")
    return done


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m tradebot.common.migrate")
    parser.add_argument("--backfill", action="store_true",
                        help="migrate BACKFILL_DATABASE_URL instead of DATABASE_URL")
    args = parser.parse_args()
    sys.exit(0 if apply_all(backfill_url() if args.backfill else None) is not None else 1)
