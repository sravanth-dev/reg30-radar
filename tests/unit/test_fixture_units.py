"""Unit sanity checks on the NSE daily files.

A silent factor-of-100,000 in the market-cap file would corrupt every `value_to_mcap`
while still looking plausible, so the unit is pinned here against a known row rather
than trusted. Money is Decimal throughout (CLAUDE.md data rules); never float.
"""

import csv
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MCAP = FIXTURES / "mcap18092026.csv"
PD = FIXTURES / "pd18092026.csv"


def _rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield {(k.strip() if k else k): (v.strip() if v else v) for k, v in row.items()}


def _mcap_row(symbol):
    for row in _rows(MCAP):
        if row["Symbol"] == symbol:
            return row
    pytest.fail(f"{symbol} not in {MCAP.name}")


def test_market_cap_is_plain_rupees():
    # Bharat Electronics, 18 Sep 2026: 7,309,778,829 shares at 393.30 is about
    # 2.87 lakh crore. In rupees that is ~2.87e12; were the file in lakhs it would
    # read ~2.87e7. The exponent alone distinguishes the two.
    bel = _mcap_row("BEL")
    mcap = Decimal(bel["Market Cap(Rs.)"])
    assert Decimal("1e12") < mcap < Decimal("1e13"), f"unexpected scale: {mcap}"


def test_market_cap_equals_issue_size_times_close():
    # Exact, not approximate: this is how NSE computes the column, so any drift means
    # we are reading the wrong field.
    bel = _mcap_row("BEL")
    shares = Decimal(bel["Issue Size"])
    close = Decimal(bel["Close Price/Paid up value(Rs.)"])
    assert shares * close == Decimal(bel["Market Cap(Rs.)"])


def test_pd_file_carries_previous_close_for_return_chaining():
    # Returns are chained from PREV_CL_PR, which NSE sets to the *adjusted* previous
    # close on an ex-date, so splits and bonuses do not read as huge fake losses.
    for row in _rows(PD):
        if row["SYMBOL"] == "BEL" and row["SERIES"] == "EQ":
            assert Decimal(row["PREV_CL_PR"]) > 0
            assert Decimal(row["CLOSE_PRICE"]) == Decimal("393.30")
            return
    pytest.fail("BEL EQ not found in pd fixture")


def test_corporate_action_indicator_is_present_and_used():
    # CORP_IND flags the ex-date directly. On 18 Sep 2026 there were 73 flagged rows.
    flagged = [r["CORP_IND"] for r in _rows(PD) if r.get("CORP_IND")]
    assert flagged, "CORP_IND column is empty; corporate-action detection would silently fail"
    assert set(flagged) <= {"XD", "XI", "XO", "XB", "XS", "XR"}, set(flagged)


def test_band_hitter_file_shape():
    # The bh file is the circuit-limit source (Sect.5.9). It covers every series, so the
    # loader must filter to the universe rather than assume EQ.
    BH = FIXTURES / "bh18092026.csv"
    rows = list(_rows(BH))
    assert {"SYMBOL", "SERIES", "SECURITY", "HIGH/LOW"} <= set(rows[0])
    assert {r["HIGH/LOW"] for r in rows} <= {"H", "L"}
    # Not an EQ-only file: on 18 Sep 2026 fewer than a third of the hitters were EQ.
    assert len([r for r in rows if r["SERIES"] == "EQ"]) < len(rows) / 2
