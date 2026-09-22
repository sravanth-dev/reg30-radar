"""Reconciliation against the real 17-18 Sep 2026 data.

These lock the two things Spike A2 established, so a future change that breaks either one
fails here rather than in a twelve-month backfill:

  - the bundle is a report covering filings disseminated since the previous report, so a
    +/-1 day window is required and same-day matching is wrong;
  - within the mainboard universe, every order-filing company in the bundle is reachable
    through the API.
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from tradebot.backfill.reconcile import (
    ApiRecord,
    BundleEntry,
    Coverage,
    coverage_is_acceptable,
    parse_bundle_line,
    reconcile,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPORT_DATE = date(2026, 9, 18)

# The eight mainboard issuers that filed an order on the 18 Sep report (Spike A2). The four
# excluded here - MASON, INNOMET, ENVIRO, MDL - are SME, which D9 keeps out of the universe.
MAINBOARD_ORDER_FILERS = {
    "BEL", "BEML", "CPL", "GPTINFRA",
    "JISLDVREQS", "JISLJALEQS", "UNIVASTU", "ZAGGLE",
}


def _bundle() -> list[BundleEntry]:
    with (FIXTURES / "bundle_bodies_18sep2026.csv").open(newline="", encoding="utf-8") as fh:
        return [BundleEntry(symbol=r["symbol"], body=r["body"]) for r in csv.DictReader(fh)]


def _api() -> list[ApiRecord]:
    out = []
    with (FIXTURES / "api_announcements_17_18_sep2026.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            # an_dt looks like "18-Sep-2026 10:17:50"
            from datetime import datetime
            try:
                d = datetime.strptime(r["an_dt"][:11], "%d-%b-%Y").date()
            except ValueError:
                continue
            out.append(ApiRecord(symbol=r["symbol"], filed_on=d, desc=r["desc"]))
    return out


def test_parse_bundle_line_keeps_category_and_description_together():
    line = ("Bharat Electronics Limited BEL : Bagging/Receiving of orders/contracts "
            "BEL : Bharat Electronics Limited has informed the Exchange")
    entry = parse_bundle_line(line)
    assert entry.symbol == "BEL"
    assert entry.is_order
    # There is no delimiter to split on, so the body legitimately carries both (§5.4).
    assert entry.body.startswith("Bagging/Receiving of orders/contracts")


def test_parse_bundle_line_ignores_blanks():
    assert parse_bundle_line("") is None
    assert parse_bundle_line("   ") is None


def test_same_day_window_understates_coverage():
    """Why the +/-1 window exists at all.

    BEL's order filing is timestamped 17 Sep 16:43, after the close, and is reported on
    18 Sep. Matching same-day would call it missing.
    """
    cov = reconcile(REPORT_DATE, _bundle(), _api(),
                    window_days=0, universe=MAINBOARD_ORDER_FILERS)
    assert cov.order_symbol_coverage is not None
    assert cov.order_symbol_coverage < 1.0, (
        "same-day matching should miss after-close filings; if it no longer does, the "
        "report-window model in §5.1 needs re-deriving"
    )


def test_mainboard_order_coverage_is_complete_over_the_report_window():
    cov = reconcile(REPORT_DATE, _bundle(), _api(),
                    window_days=1, universe=MAINBOARD_ORDER_FILERS)
    assert cov.bundle_order_symbols == MAINBOARD_ORDER_FILERS
    assert cov.unmatched_order_symbols == set(), (
        f"unreachable order filers: {sorted(cov.unmatched_order_symbols)}"
    )
    assert cov.order_symbol_coverage == 1.0
    assert coverage_is_acceptable(cov)


def test_offsets_land_on_the_report_day_or_the_one_before():
    cov = reconcile(REPORT_DATE, _bundle(), _api(),
                    window_days=1, universe=MAINBOARD_ORDER_FILERS)
    assert cov.offset_histogram, "no matched order filings to measure"
    assert set(cov.offset_histogram) <= {0, -1}, (
        f"unexpected report-window offsets: {sorted(cov.offset_histogram)}"
    )


def test_coverage_gate_flags_a_thin_day():
    thin = Coverage(report_date=REPORT_DATE, window_days=1)
    thin.bundle_order_symbols = {"AAA", "BBB", "CCC", "DDD"}
    thin.matched_order_symbols = {"AAA"}
    assert thin.order_symbol_coverage == pytest.approx(0.25)
    assert not coverage_is_acceptable(thin)


def test_coverage_gate_passes_a_day_with_no_orders():
    quiet = Coverage(report_date=REPORT_DATE, window_days=1)
    assert quiet.order_symbol_coverage is None
    assert coverage_is_acceptable(quiet), "a day with no order filings is not a failure"
