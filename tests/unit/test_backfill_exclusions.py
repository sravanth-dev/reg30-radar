"""backfill/universe.py's apply_exclusions, on real SQL (scratch schema): companies taken out
by hand and by industry both come from config, and re-applying clears what config no
longer lists."""

from tradebot.backfill import universe


def _seed(conn):
    for isin, symbol, industry in (("INE358A01014", "ABBOTINDIA", "Pharmaceuticals"),
                                   ("INE263A01024", "BEL", "Aerospace & Defense"),
                                   ("INE040A01034", "HDFCBANK", "Banks")):
        conn.execute("insert into backfill_universe (isin, symbol, series, as_of_date, industry)"
                     " values (%s, %s, 'EQ', '2025-09-22', %s)", (isin, symbol, industry))
    conn.commit()


def _reasons(conn):
    return dict(conn.execute("select symbol, excluded_reason from backfill_universe"
                             " order by symbol").fetchall())


def test_companies_excluded_by_hand_and_by_industry(scratch_conn):
    _seed(scratch_conn)
    cfg = {"universe": {"exclude_companies": {"INE358A01014": "no NSE filings in the window"}},
           "analysis": {"exclude_industries": ["Banks"]}}
    assert universe.apply_exclusions(scratch_conn, cfg) == 2
    assert _reasons(scratch_conn) == {"ABBOTINDIA": "by hand: no NSE filings in the window",
                                      "BEL": None, "HDFCBANK": "industry: Banks"}


def test_reapplying_clears_what_config_no_longer_lists(scratch_conn):
    _seed(scratch_conn)
    universe.apply_exclusions(scratch_conn, {
        "universe": {"exclude_companies": {"INE358A01014": "x"}},
        "analysis": {"exclude_industries": ["Banks"]}})
    assert universe.apply_exclusions(scratch_conn, {"universe": {}, "analysis": {}}) == 0
    assert set(_reasons(scratch_conn).values()) == {None}
