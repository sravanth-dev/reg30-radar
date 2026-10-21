"""Local backup of both databases with pg_dump (D14). `python -m reg30_radar.common.backup`

Written because no backup had ever been made (audit, 20 Oct 2026), and the backfill
database is the expensive thing to lose: weeks of polite fetching plus paid LLM answers.
ops/backup.sh does the same job for the VPS, but it passes the full DATABASE_URL to
pg_dump as `--dbname`, so the password shows in any process list while the dump runs.
Here the URL is read through common.config, split into its fields, and the password
travels only in the child process's PGPASSWORD.

Dumps go to backups/ (gitignored), the newest 7 per database kept. This protects against
a bad migration or a mistaken delete, not against losing the disk: the off-machine copy
(rclone to Google Drive, D14) still needs rclone installed and `rclone config` run once.

    python -m reg30_radar.common.backup              both databases
    python -m reg30_radar.common.backup --only live  or --only backfill
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from reg30_radar.common.calendar import IST
from reg30_radar.common.config import ROOT, backfill_database_url, database_url

BACKUP_DIR = ROOT / "backups"
# The Windows installer's location, used when pg_dump is not on PATH (it isn't, on the
# laptop). PG_DUMP overrides both.
WINDOWS_PG_DUMP = Path(r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe")


def find_pg_dump() -> Path:
    if os.environ.get("PG_DUMP"):
        return Path(os.environ["PG_DUMP"])
    on_path = shutil.which("pg_dump")
    if on_path:
        return Path(on_path)
    if WINDOWS_PG_DUMP.exists():
        return WINDOWS_PG_DUMP
    raise FileNotFoundError("pg_dump not found: set PG_DUMP or put it on PATH")


def build_command(url: str, pg_dump: Path, out: Path) -> tuple[list[str], dict[str, str]]:
    """The pg_dump argv and environment for one database. The password, if any, goes in
    the environment only."""
    info = conninfo_to_dict(url)
    argv = [str(pg_dump), "--format=custom", "--no-password", "--file", str(out)]
    for key, flag in (("host", "--host"), ("port", "--port"), ("user", "--username"),
                      ("dbname", "--dbname")):
        if info.get(key):
            argv += [flag, str(info[key])]
    env = dict(os.environ)
    env.pop("PGPASSWORD", None)
    if info.get("password"):
        env["PGPASSWORD"] = str(info["password"])
    return argv, env


def prune(directory: Path, prefix: str, keep: int = 7) -> list[Path]:
    """Delete all but the newest `keep` dumps named `<prefix>_<YYYYMMDD>_<HHMMSS>.dump`.
    Matching on the exact shape, not a glob, so `tradebot` never matches
    `tradebot_backfill_...` (ops/backup.sh had that bug)."""
    mine = []
    for path in directory.glob(f"{prefix}_*.dump"):
        rest = path.stem[len(prefix) + 1:]
        parts = rest.split("_")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            mine.append(path)
    mine.sort(key=lambda p: p.name, reverse=True)
    removed = mine[keep:]
    for path in removed:
        path.unlink()
    return removed


def dump(name: str, url: str, pg_dump: Path) -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"{name}_{stamp}.dump"
    argv, env = build_command(url, pg_dump, out)
    # stderr is passed through: pg_dump's own messages never contain the password.
    result = subprocess.run(argv, env=env)
    if result.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump of {name} failed with exit code {result.returncode}")
    prune(BACKUP_DIR, name)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m reg30_radar.common.backup")
    parser.add_argument("--only", choices=["live", "backfill"])
    args = parser.parse_args()
    pg_dump = find_pg_dump()
    targets = [("tradebot", database_url), ("tradebot_backfill", backfill_database_url)]
    if args.only == "live":
        targets = targets[:1]
    elif args.only == "backfill":
        targets = targets[1:]
    for name, url_fn in targets:
        out = dump(name, url_fn(), pg_dump)
        print(f"{name}: {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
