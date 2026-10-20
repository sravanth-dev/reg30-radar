# DEPLOY.md — running tradebot's live pipeline on the VPS

> **Superseded (21 Oct 2026).** The VPS was cancelled (D28), and the collector + `orders --follow`
> pair was replaced by one `live` service (D30). Current container instructions and the
> GATE 2 hosting options are in [README.md](README.md). Kept for the external-database
> steps, which `docker-compose.external-db.yml` still follows.

The VPS runs three services from one image (D19, widened 27 Sep 2026): `collector`,
`orders` (`--follow`) and `sheets`. The backfill stays on the laptop. Commands below run
on the VPS in the repo folder unless marked **laptop**.

## 1. Preflight (Spike E, read-only)

```bash
bash ops/preflight.sh
```

From its output, note:
- the **Postgres container name**, which becomes the host in `DATABASE_URL`;
- its **Docker network**, which becomes `TRADEBOT_DB_NETWORK`;
- its **image major version** (e.g. `postgres:16`), which becomes `TRADEBOT_PG_MAJOR`;
- free memory. The three services default to 256m + 512m + 256m. If that doesn't fit next
  to n8n, lower them with the `TRADEBOT_*_MEM` variables in `.env`.

## 2. One-time setup

**Clone** (the repo is private, so use a deploy key or a token):

```bash
git clone https://github.com/sravanth-dev/tradebot_NSE_order_scraper.git ~/tradebot
cd ~/tradebot
```

**Database and role.** This is done once by hand as the Postgres superuser (§9). It is the
only time anything enters the shared Postgres container. Use a password of letters and
digits only (`openssl rand -hex 24`), so it needs no escaping inside `DATABASE_URL`.

```bash
docker exec -it <postgres-container> psql -U <superuser>
```
```sql
CREATE USER tradebot;
\password tradebot
CREATE DATABASE tradebot OWNER tradebot;
\q
```

**`.env`**: copy `.env.example` to `.env` and fill it in:

| Variable | Value on the VPS |
|---|---|
| `DATABASE_URL` | `postgresql://tradebot:<password>@<postgres-container>:5432/tradebot` |
| `OPENAI_API_KEY` | the tradebot project key |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `/app/secrets/<key-file>.json`, the path **inside** the container |
| `GOOGLE_SHEET_ID` | same as the laptop |
| `TRADEBOT_DB_NETWORK`, `TRADEBOT_PG_MAJOR` | from the preflight |
| `RCLONE_REMOTE` | e.g. `gdrive:tradebot-backups` (section 5) |

`BACKFILL_DATABASE_URL` is laptop-only; leave it as `CHANGEME`. Then run `chmod 600 .env`.

**The Google key.** Copy it into `secrets/`. The container runs as uid 10001, so give that
uid, and only that uid, read access:

```bash
# laptop
scp <path-to-key>.json <vps>:~/tradebot/secrets/
# VPS
sudo chown 10001:10001 secrets/<key-file>.json && sudo chmod 400 secrets/<key-file>.json
```

**Build:** `docker compose build`

## 3. Cutover from the laptop

Order matters. There must be only one collector (one request stream to NSE) and only one
Sheets writer (the raw tab is written by fixed position) at any time.

1. **laptop:** stop the three processes (Ctrl+C in each terminal). Note the date.
2. **laptop:** dump the live database. `pg_dump` prompts for the password.
   ```bash
   mkdir -p backups
   "/c/Program Files/PostgreSQL/16/bin/pg_dump" -h localhost -U tradebot --format=custom \
     --file=backups/cutover.dump tradebot
   scp backups/cutover.dump <vps>:~/tradebot/backups/
   ```
3. **VPS:** restore into the empty `tradebot` database, then apply any newer migrations:
   ```bash
   docker compose --profile ops run --rm backup \
     'pg_restore --no-owner --no-privileges --dbname="$DATABASE_URL" /backups/cutover.dump'
   docker compose run --rm collector python -m tradebot.common.migrate
   ```
4. **VPS:** recover what was filed while nothing was collecting. This is one request, and
   `first_seen_at` truthfully records the catch-up time:
   ```bash
   docker compose run --rm collector python -m tradebot.collector \
     --catchup --from <date from step 1> --to <today>
   ```
5. **VPS:** start everything:
   ```bash
   docker compose up -d
   ```
6. **Check**, about 10 minutes later:
   ```bash
   docker compose ps                        # collector shows (healthy)
   docker compose logs --tail 30 collector orders sheets
   docker compose run --rm collector python -m tradebot.common.health
   ```
   The Google Sheet's raw tab gains new rows at the bottom, and nothing above them changes.
7. **laptop:** do not start the live processes there again. The laptop keeps only the
   backfill, in `tradebot_backfill`.

## 4. Updating

```bash
git pull
docker compose build
docker compose run --rm collector python -m tradebot.common.migrate
docker compose up -d
```

`git pull` works because nothing on the VPS writes into the checkout: live reports and
in-flight PDFs live in the `tradebot_data` volume. To read a live report:
`docker compose exec orders ls data/reports`.

## 5. Backups (D14: rclone to Google Drive)

1. Install rclone (`sudo apt install rclone`, or the script at rclone.org), then run
   `rclone config` to create a Google Drive remote.
2. Set `RCLONE_REMOTE` in `.env` (remote name, a colon, then a folder).
3. Test it by hand: `bash ops/backup.sh vps`. A dump lands in `backups/` and in Drive.
4. Add it to cron (`crontab -e`), at 02:30 IST:
   ```
   30 2 * * *  cd /home/<user>/tradebot && bash ops/backup.sh vps >> backups/backup.log 2>&1
   ```

To restore from a dump, repeat step 3 of the cutover with that file.

## 6. When something is wrong

| Symptom | Look at |
|---|---|
| collector `(unhealthy)` | `docker compose logs --tail 100 collector`. The health check needs a successful poll in the last 30 minutes. |
| a service keeps restarting | `docker compose ps`, then its logs. An `orders` crash on one PDF stops after 3 attempts, 15 minutes apart (§9). |
| Sheet not updating | `docker compose logs sheets`, then check the key's path and permissions. |
| stop everything | `docker compose down`. The `tradebot_data` volume and the database are kept. |
