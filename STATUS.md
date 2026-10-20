# STATUS

*Updated 20 Oct 2026, 18:45 IST. The short resume card; the history is in [WORKLOG.md](WORKLOG.md),
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

## In progress
- [ ] Step 1.2 value correctness

## Next (in order)
2. Value correctness: range suspect check, band legends, bounds (D32), currencies,
   token-bounded provenance, a judge guard below ₹1 lakh; then `rejudge` and a T0 re-parse
3. §5.5 Part C: a second read for the 42 vision-sourced values
4. Revenue: the Q2 defect (H1 − Q1, Proposed), basis recorded, the 8 failed companies,
   truncated listings
5. Market: the 27 Sep – 6 Oct tail; CORP_IND for every market row
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
