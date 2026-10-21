"""Reconciliation against the real 17-18 Sep 2026 data.

These lock the two things Spike A2 established, so a future change that breaks either one
fails here rather than in a twelve-month backfill:

  - the bundle is a report covering filings disseminated since the previous report, so
    same-day matching is wrong and the window starts at the previous report date;
  - within the mainboard universe, every order-filing company in the bundle is reachable
    through the API.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest

from reg30_radar.backfill.reconcile import (
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
                    window_from=REPORT_DATE, universe=MAINBOARD_ORDER_FILERS)
    assert cov.order_symbol_coverage is not None
    assert cov.order_symbol_coverage < 1.0, (
        "same-day matching should miss after-close filings; if it no longer does, the "
        "report-window model in §5.1 needs re-deriving"
    )


def test_mainboard_order_coverage_is_complete_over_the_report_window():
    cov = reconcile(REPORT_DATE, _bundle(), _api(),
                    window_from=REPORT_DATE - timedelta(days=1),
                    universe=MAINBOARD_ORDER_FILERS)
    assert cov.bundle_order_symbols == MAINBOARD_ORDER_FILERS
    assert cov.unmatched_order_symbols == set(), (
        f"unreachable order filers: {sorted(cov.unmatched_order_symbols)}"
    )
    assert cov.order_symbol_coverage == 1.0
    assert coverage_is_acceptable(cov)


def test_offsets_land_on_the_report_day_or_the_one_before():
    cov = reconcile(REPORT_DATE, _bundle(), _api(),
                    window_from=REPORT_DATE - timedelta(days=1),
                    universe=MAINBOARD_ORDER_FILERS)
    assert cov.offset_histogram, "no matched order filings to measure"
    assert set(cov.offset_histogram) <= {0, -1}, (
        f"unexpected report-window offsets: {sorted(cov.offset_histogram)}"
    )


def test_coverage_gate_flags_a_thin_day():
    thin = Coverage(report_date=REPORT_DATE, window_from=REPORT_DATE)
    thin.bundle_order_symbols = {"AAA", "BBB", "CCC", "DDD"}
    thin.matched_order_symbols = {"AAA"}
    assert thin.order_symbol_coverage == pytest.approx(0.25)
    assert not coverage_is_acceptable(thin)


def test_coverage_gate_passes_a_day_with_no_orders():
    quiet = Coverage(report_date=REPORT_DATE, window_from=REPORT_DATE)
    assert quiet.order_symbol_coverage is None
    assert coverage_is_acceptable(quiet), "a day with no order filings is not a failure"


# Monday 22 Jun 2026's report, from the backfill (27 Sep 2026): the previous report was
# Friday 19 Jun, so the report holds Friday evening's and the weekend's filings.
MONDAY, FRIDAY = date(2026, 6, 22), date(2026, 6, 19)
ORDER = "Bagging/Receiving of orders/contracts"


def test_a_monday_report_reaches_back_to_the_previous_report_date():
    bundle = [BundleEntry("RVNL", f"{ORDER} Disclosure under Regulation 30"),
              BundleEntry("ZAGGLE", f"{ORDER} ZAGGLE : Zaggle Prepaid")]
    api = [ApiRecord("RVNL", date(2026, 6, 20), ORDER),       # Saturday 09:00
           ApiRecord("ZAGGLE", FRIDAY, ORDER)]                # Friday 17:55, after the close
    assert reconcile(MONDAY, bundle, api).matched_order_symbols == set()     # day before only
    cov = reconcile(MONDAY, bundle, api, window_from=FRIDAY)
    assert cov.matched_order_symbols == {"RVNL", "ZAGGLE"}
    assert cov.offset_histogram == {-2: 1, -3: 1}


def test_a_filing_dated_after_the_report_is_not_a_match():
    bundle = [BundleEntry("BEL", f"{ORDER} BEL : Bharat Electronics")]
    api = [ApiRecord("BEL", MONDAY + timedelta(days=1), ORDER)]
    assert reconcile(MONDAY, bundle, api, window_from=FRIDAY).unmatched_order_symbols == {"BEL"}


def test_a_company_is_matched_across_a_symbol_change():
    # The API files LTIMindtree's whole history under its current symbol, LTM; the older
    # reports say LTIM. Matched through the company, not the symbol.
    bundle = [BundleEntry("LTIM", f"{ORDER} LTIM : LTIMindtree Limited")]
    api = [ApiRecord("LTM", MONDAY, ORDER)]
    assert reconcile(MONDAY, bundle, api, window_from=FRIDAY).matched_order_symbols == set()
    cov = reconcile(MONDAY, bundle, api, window_from=FRIDAY,
                    company_of={"LTIM": "INE214T01019", "LTM": "INE214T01019"})
    assert cov.matched_order_symbols == {"LTIM"}


def test_an_order_the_api_holds_only_under_a_catch_all_category_is_counted_apart():
    # CAPACITE, 15 Jul 2026: the report says "Bagging/Receiving ... (Sub-para 4-Para B)",
    # the API calls the same "Work order" filing "Updates". Likely the same, not proof.
    bundle = [BundleEntry("CAPACITE", f"{ORDER}  (Sub-para 4-Para B) CAPACITE INFRAPROJECTS"),
              BundleEntry("HGINFRA", f"{ORDER}  (Sub-para 4-Para B) H.G. Infra")]
    api = [ApiRecord("CAPACITE", date(2026, 7, 14), "Updates")]
    cov = reconcile(date(2026, 7, 15), bundle, api, window_from=date(2026, 7, 14))
    assert cov.matched_order_symbols == set()
    assert cov.catch_all_only_symbols == {"CAPACITE"}
    assert cov.order_symbol_coverage == 0
