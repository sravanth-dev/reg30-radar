"""The 12-month backfill and event study, stage by stage (ARCHITECTURE §5.1, §5.11, §6).
Runs on the laptop over the phone hotspot (D19), against BACKFILL_DATABASE_URL only.

    python -m reg30_radar.market --from 2025-03-01 --to 2026-09-26   prices, caps, bundles
    python -m reg30_radar.backfill universe          build the frozen company list
    python -m reg30_radar.backfill expected          what the list filed, before downloading
    python -m reg30_radar.backfill announcements     one symbol= query per listed company
    python -m reg30_radar.backfill reconcile         per-day coverage against the PR bundles
    python -m reg30_radar.backfill documents         download, extract, T0 (LLM deferred)
    python -m reg30_radar.backfill batch-submit      T1 extraction through the Batch API
    python -m reg30_radar.backfill batch-collect     apply finished Batch results
    python -m reg30_radar.backfill rejudge           re-apply changed rules to stored answers
    python -m reg30_radar.backfill reparse           re-apply T0 to stored text (no network)
    python -m reg30_radar.backfill vision-check      §5.5 Part C: second read of vision values
    python -m reg30_radar.backfill events            merge verified extractions into events
    python -m reg30_radar.backfill revenue           results XBRL -> financials (Spike C)
    python -m reg30_radar.backfill calculate         §6: verified | recheck_pending
    python -m reg30_radar.backfill recheck-submit    blind T2 re-read of high-stakes events
    python -m reg30_radar.backfill recheck-collect
    python -m reg30_radar.backfill study             event study, D22 verdict, report
    python -m reg30_radar.backfill status            where every stage stands

Each stage does one pass and exits; the network stages are resumable and bounded by
--max-requests. None retries in a loop.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone

from reg30_radar.backfill import (
    announcements, batch, documents, event_study, events, recheck, report, study_data,
    universe,
)
from reg30_radar.market import bands as band_history
from reg30_radar.common.calendar import IST
from reg30_radar.common.config import load_yaml
from reg30_radar.common.db import backfill_url, connect
from reg30_radar.common.logs import configure as configure_logging
from reg30_radar.llm.client import LlmClient

log = logging.getLogger("backfill")


def _window(cfg) -> tuple[date, date]:
    w = cfg["window"]
    return (date.fromisoformat(str(w["announcements_from"])),
            date.fromisoformat(str(w["announcements_to"])))


def _muhurat(cfg) -> set[date]:
    return {date.fromisoformat(str(d)) for d in cfg["analysis"].get("muhurat_days") or []}


def _market_for(conn, cfg, evs):
    w = cfg["window"]
    return study_data.load_market(
        conn, sorted({e.isin for e in evs}), date.fromisoformat(str(w["prices_from"])),
        date.today(), _muhurat(cfg))


def calculate(conn, cfg) -> dict:
    """§6's first step for every `extracted` event: measure it, then log `calculated`
    and either `verified` or `recheck_pending` with the trigger."""
    evs = study_data.load_events(conn, states=("extracted",))
    market = _market_for(conn, cfg, evs)
    counts = {"verified": 0, "recheck_pending": 0}
    for ev in evs:
        r = event_study.measure(ev, market)
        m = r.materiality
        # §5.8: "Record which one was used" - ttm_as_of falls back to standalone when the
        # consolidated quarters have a gap, so the basis can differ event by event.
        conn.execute("update backfill_events set ttm_revenue_inr = %s, ttm_basis = %s,"
                     " value_to_mcap = %s where id = %s",
                     (ev.ttm_revenue_inr, ev.ttm_basis, m.value_to_mcap if m else None,
                      ev.event_id))
        events.log_transition(conn, ev.event_id, "calculated", "materiality computed")
        state, trigger = events.next_state(m.value_to_mcap if m else None,
                                           ev.ttm_revenue_inr is not None)
        events.log_transition(conn, ev.event_id, state, trigger)
        counts[state] += 1
    conn.commit()
    return counts


def events_in_window(evs, since: date, until: date):
    """`load_events` pulls every verified event regardless of date, because filings just
    outside [since, until] are fetched anyway for the announcement margin (contamination,
    follow-up detection). Keep only events whose own filing is in the real study window -
    by the filing's own timestamp, not by whether day0 could later be resolved, so a filing
    inside the window with no resolvable day0 still shows up as an excluded event in the
    report, while a filing genuinely outside the window (margin only) is dropped entirely
    rather than diluting the funnel with something never meant to be studied."""
    return [ev for ev in evs if since <= ev.event_ts.astimezone(IST).date() <= until]


def study(conn, cfg) -> dict:
    evs = study_data.load_events(conn, states=("verified",))
    market = _market_for(conn, cfg, evs)
    since, until = _window(cfg)
    results = [event_study.measure(ev, market) for ev in events_in_window(evs, since, until)]
    # Price band (Sravanth's rule 3, §11) - a targeted lookup for exactly the
    # (symbol, series, day0) each event actually resolved to, not a full day-by-day
    # series for the whole window; band_history.reconstruct() never guesses a value it
    # cannot derive, so an event outside the loaded band-change window or for a
    # delisted symbol simply keeps price_band = None.
    band_pairs = [(r.symbol, r.series, r.day0) for r in results if r.day0 and r.series]
    band_lookup = band_history.reconstruct(conn, band_pairs)
    for r in results:
        if r.day0 and r.series:
            r.price_band = band_lookup.get((r.symbol, r.series, r.day0))
    split = date.fromordinal(since.toordinal() + (until.toordinal() - since.toordinal()) // 2)
    band = tuple(cfg["analysis"]["primary_mcap_crore"])
    v = event_study.verdict(event_study.primary(results, band), split)

    run_at = datetime.now(timezone.utc)
    import json
    for r in results:
        conn.execute("insert into event_results (run_at, event_id, result) values (%s,%s,%s)",
                     (run_at, r.event_id, json.dumps(report.row(r), default=str)))
    conn.commit()

    ctx = {
        "run_date": date.today().isoformat(),
        "primary_band": band,
        "universe_band": tuple(cfg["analysis"]["universe_mcap_crore"]),
        "funnel": status(conn),
        "coverage": conn.execute("select report_date, coverage from reconcile_days"
                                 " order by report_date").fetchall(),
        "data": {"halves split at": split.isoformat(),
                 "window": f"{since} to {until}"},
    }
    md, csv_path = report.write(results, v, ctx)
    return {"verdict": v.decision, "events": len(results), "primary_n": v.overall.n,
            "report": str(md), "csv": str(csv_path)}


def status(conn) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]   # noqa: E731
    return {
        "trading days loaded": q("select count(*) from archive_days where trading_day"),
        "companies listed": q("select count(*) from backfill_universe where excluded_reason is null"),
        "companies fetched": q("select count(*) from backfill_checkpoints where job = 'announcements'"),
        "filings stored": q("select count(*) from raw_announcements"),
        "report dates below 95% coverage": q("select count(*) from reconcile_days where not acceptable"),
        "documents extracted": q("select count(*) from documents"),
        "order-related filings": q("select count(*) from order_extractions where order_related"),
        "verified extractions": q("select count(*) from order_extractions"
                                  " where order_related and review_status = 'verified'"),
        "waiting on Batch": q("select count(*) from order_extractions where review_status = 'pending_llm'"),
        "revenue: event companies fetched": q(
            "select count(*) from backfill_checkpoints where job = 'revenue'"),
        "revenue: event companies": q("select count(distinct isin) from backfill_events"),
        "events": q("select count(*) from backfill_events"),
        "events with TTM (after calculate)": q(
            "select count(*) from backfill_events where ttm_revenue_inr is not null"),
        "values waiting for a second read (§5.5 Part C)": q(
            "select count(*) from order_extractions where second_read = 'pending'"),
        "events verified": q("select count(*) from backfill_events where state = 'verified'"),
        "events in recheck": q("select count(*) from backfill_events where state = 'recheck_pending'"),
        "events needing review": q("select count(*) from backfill_events where state = 'needs_review'"),
        "LLM spend so far (USD)": q("select coalesce(sum(cost_usd), 0) from llm_calls"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reg30_radar.backfill")
    parser.add_argument("stage", choices=[
        "universe", "expected", "announcements", "reconcile", "documents", "batch-submit",
        "batch-collect", "rejudge", "reparse", "vision-check", "events", "revenue", "calculate", "recheck-submit",
        "recheck-collect", "study", "status"])
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    cfg = load_yaml("backfill.yaml")
    since, until = _window(cfg)

    exit_code = 0
    with connect(backfill_url()) as conn:
        client = lambda: LlmClient(conn=conn, budget="backfill")   # noqa: E731
        if args.stage == "universe":
            out = {"companies": universe.build(conn, cfg),
                   "excluded": universe.apply_exclusions(conn, cfg)}
        elif args.stage == "expected":
            out = {**universe.expected_counts(conn, since, until),
                   "documents (after the announcements stage)":
                       documents.expected(conn, since, until, cfg)}
        elif args.stage == "announcements":
            out = announcements.run(conn, cfg["window"], max_requests=args.max_requests)
            universe.apply_exclusions(conn, cfg)
        elif args.stage == "reconcile":
            out = announcements.reconcile_window(conn, since, until)
        elif args.stage == "documents":
            s = documents.run(conn, since, until, max_downloads=args.max_requests, cfg=cfg)
            out = {"considered": s.considered, "downloaded": s.downloaded,
                   "download_failed": s.download_failed, "order_related": s.order_related,
                   "verified_by_T0": s.verified, "waiting_on_batch": s.pending_llm,
                   "not_order": s.not_order, "ocr_pages": s.ocr_pages,
                   "stopped_early": s.stopped_early}
            if s.gate_violations:
                # §5.4's hard invariant, checked here exactly as orders/__main__.py checks
                # it on the live path: nothing may reach OCR or the LLM without llm_allowed
                # having said so first. A non-empty list is a bug, never a filing to shrug at.
                # Still printed below with everything else, so the failure is diagnosable,
                # not just flagged.
                log.error("GATE VIOLATION: LLM/OCR reached a non-order-related filing: %s",
                         s.gate_violations)
                out["gate_violations"] = s.gate_violations
                exit_code = 2
        elif args.stage == "batch-submit":
            out = batch.submit(conn, client())
        elif args.stage == "batch-collect":
            out = batch.collect(conn, client())
        elif args.stage == "rejudge":
            out = batch.rejudge(conn)
        elif args.stage == "reparse":
            out = batch.reparse(conn)
        elif args.stage == "vision-check":
            from reg30_radar.backfill import vision_check
            out = vision_check.run(conn, client=client(), max_requests=args.max_requests)
        elif args.stage == "events":
            out = events.build(conn)
        elif args.stage == "revenue":
            from reg30_radar.revenue import load as revenue_load
            out = revenue_load.run(conn, cfg, max_requests=args.max_requests)
        elif args.stage == "calculate":
            out = calculate(conn, cfg)
        elif args.stage == "recheck-submit":
            out = recheck.submit(conn, client())
        elif args.stage == "recheck-collect":
            out = recheck.collect(conn, client())
        elif args.stage == "study":
            out = study(conn, cfg)
        else:
            out = status(conn)
    for k, v in out.items():
        print(f"{k}: {v}")
    return exit_code


if __name__ == "__main__":
    from reg30_radar.common import nse_guard
    sys.exit(nse_guard.run(main))
