#!/usr/bin/env bash
# Nightly backup (D14, decided 27 Sep 2026: rclone to Google Drive). One custom-format
# pg_dump, the newest 7 kept locally, every dump copied to the rclone remote, remote
# copies older than 30 days pruned.
#
#   bash ops/backup.sh vps        on the VPS: dumps the live tradebot database through
#                                 compose's `backup` service (never docker exec into the
#                                 shared Postgres container)
#   bash ops/backup.sh backfill   on the laptop (Git Bash): dumps tradebot_backfill with the
#                                 local pg_dump, while the backfill runs
#
# Needs rclone installed and a remote configured once by hand (`rclone config`), named in
# .env as RCLONE_REMOTE, e.g. gdrive:tradebot-backups. Cron line for the VPS, 02:30 IST:
#   30 2 * * *  cd /path/to/tradebot && bash ops/backup.sh vps >> backups/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
mode="${1:?usage: ops/backup.sh vps|backfill}"

# Read single values from .env without executing it: .env holds secrets, and sourcing it
# would run anything that happened to be written there.
env_value() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-; }

remote="$(env_value RCLONE_REMOTE)"
[ -n "$remote" ] && [ "$remote" != "CHANGEME" ] || { echo "RCLONE_REMOTE is not set in .env" >&2; exit 1; }

mkdir -p backups
stamp="$(date +%Y%m%d_%H%M%S)"

case "$mode" in
  vps)
    docker compose --profile ops run --rm backup
    prefix="tradebot_"
    ;;
  backfill)
    url="$(env_value BACKFILL_DATABASE_URL)"
    [ -n "$url" ] || { echo "BACKFILL_DATABASE_URL is not set in .env" >&2; exit 1; }
    pg_dump="${PG_DUMP:-pg_dump}"
    "$pg_dump" --format=custom --dbname="$url" --file="backups/tradebot_backfill_${stamp}.dump"
    prefix="tradebot_backfill_"
    ;;
  *)
    echo "unknown mode: $mode (vps|backfill)" >&2; exit 1 ;;
esac

# Keep the newest 7 dumps of this kind on local disk (disk is the VPS's binding constraint, §3).
ls -1t backups/"${prefix}"*.dump 2>/dev/null | tail -n +8 | while read -r old; do rm -- "$old"; done

rclone copy backups/ "$remote" --include "${prefix}*.dump"
rclone delete "$remote" --min-age 30d --include "${prefix}*.dump"
echo "$(date -Is) backup ok: $mode -> $remote"
