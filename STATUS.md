# STATUS

*Updated 20 Oct 2026, 22:35 IST (checkpoint before the night). The short resume card; the history is in [WORKLOG.md](WORKLOG.md),
the GATE 1 snapshot in [AUDIT.md](AUDIT.md).*

## Where we are

**GATE 1 passed** (Sravanth approved the plan, 20 Oct 2026). Working through Phase 1, then
the backfill to a verdict, then GATE 2 (hosting is Sravanth's decision).

Decisions from the gate (ARCHITECTURE D28-D32):
- The VPS is gone.
- The LLM stays on OpenAI under the existing caps.
- Live collection restarts only as one process behind an NSE lock.
- The third documents tier is skipped.
- Stated bounds count as flagged lower bounds.

## Done
- [x] Phase 0 audit (AUDIT.md): runtime state, both databases, tests (337 passed / 25
      skipped read-only), T0 eval 8/18 (44%), the full-chain overlap 7/8, three code audits
- [x] Pending 4 Oct WORKLOG entry committed
- [x] First-ever backup: `backups/tradebot_20261020_170957.dump` (5.5 MB),
      `backups/tradebot_backfill_20261020_170958.dump` (104 MB)

- [x] Step 0: AUDIT.md, STATUS.md, ARCHITECTURE v1.6 (D28-D32), 367 tests, commit `725b82c`
- [x] Step 1.1 NSE guardrails: `common/nse_guard.py` (lock, cross-host gap, backoff, stop
      after 5 failures, exit code 3), structure checks, `bands.py` URLs to config,
      migrations one transaction per file. 390 tests pass

- [x] Step 1.2 value correctness: range/legend/bound/currency rules (D32 + Proposed),
      token-bounded provenance, flags stored (migration 0015, both DBs), `reparse` stage.
      Applied to the backfill DB with no network or model: 1,420 verified (0 below Rs 1
      lakh, 0 without a currency marker; 24 lower bounds, 8 ranges), 30 queued for T1
      (13 old retries + 17 T0 values that no longer verify). T0 eval unchanged at 8/18.
      416 tests pass

- [x] Step 1.3 §5.5 Part C: enforced on every path; second read run on the backfill: 38
      confirmed, 1 unavailable, 3 not vision-sourced (39 downloads, 43 OCR pages, ~$0.04)

- [x] Step 1.6 study/report to spec: Muhurat day 0 out of the primary cell; undercount (D31),
      coverage series + CSV, TTM/mcap drop counts, lower-bound count, clean vs
      contaminated and tradeable tables, full-universe line; CSV has ttm_basis/value_flags

- [x] Step 1.4 revenue: 228 of 231 event companies. The last 3 fail only on 7 listed XBRL
      links NSE answers 404 for (Proposed: a 404 is an answer; their quarters stay null)
- [x] Step 1.5 market: prices to 9 Oct 2026; CORP_IND re-read on all 397 days, 14 flags
      added. A DNS outage at 18:54 tripped the 5-failure hard stop (exit 3) as designed;
      resumed from 25 May
- [x] Step 1.7 offline measurements: gated T0 eval and `eval --stored` (T0 9/18 gated, 0
      accepted wrong; stored chain 6/6 where it answered); MCLOUD exact-restatement rule
      (0 stored values change); line-wrap rule tried and reverted (1 wrong in 9). σ from
      54,081 placebos: 5.75% raw, 4.43% robust, MDE(median, n=30) 2.50%; ordinary-day
      median excess -0.44% (`reports/power_analysis_2026-10-20.md`). 448 tests pass

- [x] Step 1.8: `tradebot.live` + `tradebot.catchup` built (commit `388075b`), migration
      0018 on both DBs, order-path retries fixed. 461 tests pass. Catch-up 1-20 Oct:
      7,806 new filings, no failed or flagged day

## In progress (running unattended)
- [ ] **`python -m tradebot.live` is running detached** (started 22:30, python PID 8316,
      log `data/live.log`, holds `data/nse.lock`). It is draining the catch-up backlog: 1,894
      in-scope PDFs at 6 per cycle (about 2 days at the off-window pace). It needs no input.
      It stops by itself on 5 NSE failures in a row (exit 3) or a calendar problem (exit 2);
      restart it with the command below. While it runs, no other NSE command can start
      (the lock refuses), which is intended.
- [ ] Batch `batch_6ad799778dc08190a9fbb5d15054aad9` (30 pending backfill filings,
      submitted 22:10, worst case $0.0092): collect after it completes (<= 24 h)

## Next (in order)
9. Backfill stages: `batch-submit`/`collect` → `events` → `calculate` → `recheck` →
   `study` → `report`
10. GATE 2 preparation (Compose locally, README, hosting options), then **stop**

## Blockers that need Sravanth
- Off-machine backups: install rclone and run `rclone config` once (D14). Until then the
  dumps live on this laptop only.
- `config/holidays_2027.yaml`, before 1 Jan 2027, once NSE publishes the list.
- Note (for the verdict, not a blocker): ordinary days have a median +5-day excess of
  -0.44%, so D22, which tests against zero, is conservative by about that much. D22 is
  Decided; it is recorded, not changed.
- Cancel the stray read-only query PID 20092 on `tradebot_backfill` if it is still running.
  It is harmless: it is a slow audit query of mine, and its client is gone.

## Resume after an interruption (PowerShell, from the repo root)
```powershell
.venv\Scripts\Activate.ps1
git status; git log --oneline -5          # what landed last
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select ProcessId, CommandLine   # anything running?
python -m tradebot.backfill status       # backfill counters
python -m pytest -q                      # must be green before any commit
python -m tradebot.common.backup         # before any stage that writes to a database
# live runner: is it up? restart it if it exited
Get-Content data\live.log -Tail 20
Start-Process cmd.exe -ArgumentList '/c','.venv\Scripts\python.exe -m tradebot.live 2>> data\live.log' -WindowStyle Hidden
python -m tradebot.backfill batch-collect   # once the 20 Oct batch is done
```
Rule: never start an NSE-talking command while another one is running.

## GATE 2: hosting options (moved from the old README, 21 Oct 2026; Sravanth's decision)

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
