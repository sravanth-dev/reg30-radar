"""Locks Spike B's corporate-action finding against regression.

ARCHITECTURE.md v0.4 stated that NSE's `PrvsClsgPric` is corporate-action adjusted, and
planned to chain every event-study return through it. Spike B disproved that, and v0.7 had
to repair a copy of the claim still sitting in the data model three versions later.

These tests make the claim impossible to restore quietly: they assert the *data*, not the
prose. Any future code that chains returns through `PrvsClsgPric` will be building on a
fact this file shows to be false.

Fixture: `corpaction_20250805_20250806.csv`, real UDiFF rows for five names the PR bundle
(`pd060825.csv` inside `PR060825.zip`) flagged with a corporate action on 2025-08-06.

A note on scope. Sravanth asked for a split or bonus. Neither appeared on any day sampled
in Spike B, so this uses the capital action that did: DAVANGERE's rights issue (`XR`), which
falls in the same exclusion class as `XB` and `XS` in §5.9. The four `XD` ex-dividends
exercise the tolerated path. When a split or bonus turns up in the backfill, add it here.
"""

import csv
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "corpaction_20250805_20250806.csv"

PRIOR, EX = "2025-08-05", "2025-08-06"

# From the PR bundle's CORP_IND column for 2025-08-06. XR is a capital action and is
# excluded (§5.11); XD is an ordinary dividend and is tagged but kept.
FLAGS = {
    "DAVANGERE": "XR",
    "COALINDIA": "XD",
    "GESHIP": "XD",
    "RAMCOCEM": "XD",
    "BLUEDART": "XD",
}
CAPITAL_ACTIONS = {"XB", "XS", "XR", "XO"}


def _rows():
    with FIXTURE.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _by_symbol():
    out = {}
    for r in _rows():
        out.setdefault(r["TckrSymb"], {})[r["TradDt"]] = r
    return out


def test_fixture_covers_every_flagged_name():
    by = _by_symbol()
    assert set(by) == set(FLAGS)
    for sym, days in by.items():
        assert {PRIOR, EX} <= set(days), f"{sym} is missing one of the two sessions"


@pytest.mark.parametrize("symbol", sorted(FLAGS))
def test_prvsclsgpric_is_not_corporate_action_adjusted(symbol):
    """The central fact. On an ex-date NSE repeats the prior close verbatim.

    If this ever fails, NSE changed the file and §5.9 must be re-derived from evidence —
    not from an assumption that it "should" be adjusted.
    """
    days = _by_symbol()[symbol]
    prior_close = Decimal(days[PRIOR]["ClsPric"])
    stated_prev = Decimal(days[EX]["PrvsClsgPric"])
    assert stated_prev == prior_close, (
        f"{symbol}: PrvsClsgPric {stated_prev} != prior close {prior_close}. "
        "If NSE now adjusts this field, §5.9 needs re-deriving from data."
    )


def test_rights_issue_is_excluded_not_adjusted():
    """A capital action must drop the event, because no adjustment is available.

    DAVANGERE went ex-rights on 2025-08-06. Its quoted previous close is unadjusted, so a
    return computed from it is not merely imprecise, it is wrong by the entitlement value —
    and nothing in the daily files carries the ratio needed to correct it. §5.11 therefore
    excludes the event and reports the exclusion.
    """
    assert FLAGS["DAVANGERE"] in CAPITAL_ACTIONS
    assert should_exclude(FLAGS["DAVANGERE"]) is True


def test_ordinary_dividend_is_tagged_but_kept():
    # Excluding on XD as well would cost a large share of the sample for no benefit:
    # on the three days Spike B sampled, XD ran 16, 3 and 70 against 1, 1 and 1 capital
    # actions.
    for sym, flag in FLAGS.items():
        if flag == "XD":
            assert should_exclude(flag) is False, sym


def should_exclude(corp_ind: str | None) -> bool:
    """§5.11's rule, kept here until `src/reg30_radar/market/` exists to hold it.

    Move it there in Slice 7 and import it back, rather than letting two copies drift.
    """
    return bool(corp_ind) and corp_ind.strip().upper() in CAPITAL_ACTIONS
