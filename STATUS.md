# STATUS

*Updated 20 Oct 2026, 18:20 IST (session cut off by the usage limit). The short resume card; the history is in [WORKLOG.md](WORKLOG.md),
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

## In progress
- [ ] **A detached NSE sequence was started 18:11 (PowerShell PID 6004)**: revenue retry ->
      market tail 26 Sep-9 Oct -> CORP_IND re-read. Do not start another NSE command until
      `data/nse_runs.out` says `done`. Logs (UTF-16): data/revenue_retry.log,
      data/market_tail.log, data/corp_ind_refresh.log. INE018A01030 failed again (2 XBRL
      downloads); check the reason in the log.
- [ ] Step 1.7: gated T0 score + `eval --stored` NOT built yet (patch attempt failed, reverted)
- [ ] Step 1.4 revenue: code done (Q2 = H1 − Q1 Proposed, basis, pages, conflicts, FY
      check); NSE run pending: 8 failed companies + truncated listings
- [ ] Step 1.5 market: code done (CORP_IND on every row); NSE runs pending: tail
      27 Sep - 9 Oct, CORP_IND re-read of 388 days

## Next (in order)
6. Study and report brought to spec
7. `eval --stored`; σ measured from placebo events
8. A single live runner (`python -m tradebot.live`) and `catchup`; then start live on the
   laptop and catch up from 1 Oct
9. Backfill stages: `batch-submit`/`collect` → `events` → `calculate` → `recheck` →
   `study` → `report`
10. GATE 2 preparation (Compose locally, README, hosting options), then **stop**

## Blockers that need Sravanth
- Off-machine backups: install rclone and run `rclone config` once (D14). Until then the
  dumps live on this laptop only.
- `config/holidays_2027.yaml`, before 1 Jan 2027, once NSE publishes the list.
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
```
Rule: never start an NSE-talking command while another one is running.
