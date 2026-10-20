# tradebot — NSE order-win filings, measured

Phase 1 of a personal research project: collect every NSE corporate announcement, find the
order wins, read the order value out of the filing PDF, set it against the company's
trailing revenue and market cap, and test on 12 months of history whether such filings move
the stock enough to trade. **Nothing in this repo places trades**, and there is no broker
code.

- What it is and why every rule exists: [ARCHITECTURE.md](ARCHITECTURE.md)
- What has been done and learned: [WORKLOG.md](WORKLOG.md); the short resume card:
  [STATUS.md](STATUS.md); the 20 Oct 2026 audit: [AUDIT.md](AUDIT.md)
- Measured results: [RESULTS.md](RESULTS.md) (once the backfill verdict is in)
- Every file, one line each: [FILES.md](FILES.md)

## How it works

```
NSE announcements API ──(one polite process, NSE lock)──► raw_announcements (append-only)
        │
        ├─ router: exchange category → bucket; order categories + catch-all headlines
        ├─ documents: download PDF → SHA-256 → per-page text (pdfplumber → pypdf → vision OCR) → delete PDF
        ├─ extractor: annexure parser (T0, code) → OpenAI gpt-6-luna (T1) only if T0 fails
        │             every value verified against a verbatim quote in the document
        ├─ revenue: XBRL results → point-in-time TTM (Q4 = FY − 9M, Q2 = H1 − Q1)
        ├─ market: bhavcopy + PR bundles → prices, market caps, Nifty, corporate actions, circuit hits
        └─ backfill + event study → pre-registered verdict (D22)
```

## Setup (laptop, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env          # then fill in DATABASE_URL, OPENAI_API_KEY, ...
python -m tradebot.common.migrate
python -m pytest -q             # no network
```

Postgres 16 with two databases, `tradebot` (live) and `tradebot_backfill`, owned by role
`tradebot`.

## The two entry points

```powershell
python -m tradebot.catchup      # after any downtime: one request per day since the last poll
python -m tradebot.live         # the one live process: poll + order pipeline, until stopped
```

Only one process may talk to NSE at a time; `data/nse.lock` makes a second one refuse to
start. `live` exits 2 when `config/holidays_<year>.yaml` is missing and 3 after 5 failed NSE
requests in a row; restarting it is the host's job (below).

## Containers

One image, `live` + `sheets` services, no published ports. Where the database lives is an
override file:

```powershell
copy .env.docker.example .env.docker      # set TRADEBOT_LOCAL_DB_PASSWORD and the keys
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.local-db.yml up -d --build
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.local-db.yml run --rm live python -m tradebot.common.migrate
```

`docker-compose.external-db.yml` instead joins an existing Postgres on a Docker network.
Rehearsed on 21 Oct 2026: the image builds, all 18 migrations apply to the container
Postgres, and the suite passes inside the image (422 passed; the 2 layout checks that look
for docs excluded from the image fail, as expected).

## Hosting (GATE 2: Sravanth's decision, nothing provisioned)

The VPS was cancelled in Oct 2026 (D28). Three options:

| | (a) This laptop + Task Scheduler | (b) A cloud VM | (c) A small always-on box at home |
|---|---|---|---|
| How | `live` at logon, `catchup` daily at 07:30 | Compose with `local-db` | Compose with `local-db` (mini-PC or Raspberry Pi 5) |
| Cost | ₹0 | ~₹400-1,000 / month | ~₹6,000-12,000 once, plus power |
| NSE access | residential / hotspot IP, proven since Sep | **datacenter IP, never tested** against NSE's Akamai layer; a block is likely to be the first finding | residential broadband IP, as now |
| Uptime | stops whenever the laptop sleeps, travels or reboots (it rebooted at 03:52 on 21 Oct and the runner stopped) | high | high |
| first_seen_at quality | gaps whenever it is off; `catchup` recovers the filings, not the timing | continuous, if not blocked | continuous |
| Broker later | no static IP | static IP possible (needed for an Angel One whitelist) | no static IP without an ISP add-on |

Recommendation: (c) if live timing matters for Phase 2, otherwise (a) with the daily
catch-up. (b) only after one test week from that VM, since a block would also put a broker
IP at risk if the two share it.
