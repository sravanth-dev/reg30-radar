"""market/parse.py against the committed archive fixtures. Each expected number was
recorded independently by a spike (WORKLOG 21-22 Sep, ARCHITECTURE §5.2-§5.9) before this
parser existed, so these check the parser against known answers, not against itself."""

import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from reg30_radar.market.parse import (
    mcap_trade_date, parse_an, parse_bh, parse_mcap, parse_pd, parse_udiff, pr_members,
    udiff_csv_from_zip,
)

F = Path(__file__).resolve().parents[1] / "fixtures"


def _read(name: str) -> str:
    return (F / name).read_text(encoding="utf-8", errors="replace")


def test_udiff_rows_carry_isin_and_decimal_prices():
    # The BSE UDiFF fixture has the identical column set NSE uses (Spike B).
    rows = parse_udiff(_read("BhavCopy_BSE_CM_0_0_0_20260918_F_0000.CSV"))
    abb = rows[0]
    assert (abb.isin, abb.symbol, abb.trade_date) == ("INE117A01022", "ABB", date(2026, 9, 18))
    assert abb.close == Decimal("7235.20") and abb.prev_close == Decimal("7129.00")
    assert abb.volume == 18369
    assert abb.traded_value == Decimal("132648938.00")


def test_udiff_reads_the_nse_column_subset_too():
    rows = parse_udiff(_read("corpaction_20250805_20250806.csv"))
    assert rows[0].symbol == "BLUEDART" and rows[0].close == Decimal("5794.00")


def test_pd_gives_nifty_close_and_corporate_action_flags():
    indices, actions = parse_pd(_read("pd18092026.csv"))
    assert indices[0].index_name == "Nifty 50"
    assert indices[0].close == Decimal("23346.40")
    counts = {}
    for a in actions:
        counts[a.corp_ind] = counts.get(a.corp_ind, 0) + 1
    assert counts == {"XD": 70, "XI": 2, "XO": 1}     # §5.9, 18 Sep 2026


def test_mcap_is_plain_rupees_and_skips_summary_rows():
    caps = parse_mcap(_read("mcap18092026.csv"))
    bel = [c for c in caps if c.symbol == "BEL"]
    assert bel[0].mcap_inr == Decimal("2874936013445.70")   # 7,309,778,829 x 393.30
    assert not any(c.symbol in ("Total", "Permitted") for c in caps)
    assert mcap_trade_date(_read("mcap18092026.csv")) == date(2026, 9, 18)


def test_band_hitters_match_the_spike_count():
    hits = parse_bh(_read("bh18092026.csv"))
    assert len(hits) == 298
    assert sum(h.high_low == "H" for h in hits) == 181


def test_band_hitter_file_with_the_2025_index_flag_column():
    text = "SYMBOL,SERIES,SECURITY,HIGH/LOW,INDEX FLAG\nABC,EQ,ABC LTD,H,N\n"
    assert [(h.symbol, h.high_low) for h in parse_bh(text)] == [("ABC", "H")]


def test_announcement_report_parses_every_body():
    entries = parse_an(_read("an18092026.txt"))
    assert len(entries) == 1229                       # §5.4
    assert entries[0].symbol == "CPL"
    assert sum(e.is_order for e in entries) == 23     # 22 order_win + 1 order_candidate


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text)
    return buf.getvalue()


PREFIXES = {"announcements": "an", "price_data": "pd", "market_cap": "mcap",
            "band_hitters": "bh"}


def test_pr_members_match_2025_mixed_case_and_mixed_date_widths():
    # The 2025-08-06 bundle's real member names (Spike B).
    z = _zip({"An060825.txt": "an", "Pd060825.csv": "pd", "bh060825.csv": "bh",
              "MCAP06082025.csv": "mcap", "pr060825.csv": "other", "pdfx.csv": "no"})
    got = pr_members(z, PREFIXES)
    assert got == {"announcements": "an", "price_data": "pd", "band_hitters": "bh",
                   "market_cap": "mcap"}


def test_pr_members_match_2026_lowercase_names():
    z = _zip({"an18092026.txt": "an", "pd18092026.csv": "pd", "bh18092026.csv": "bh",
              "mcap18092026.csv": "mcap"})
    assert set(pr_members(z, PREFIXES)) == set(PREFIXES)


def test_udiff_zip_holds_one_csv():
    z = _zip({"BhavCopy_NSE_CM_0_0_0_20260918_F_0000.csv": "TradDt,ISIN\n"})
    assert udiff_csv_from_zip(z) == "TradDt,ISIN\n"


def test_a_flag_on_a_be_row_under_mkt_g_is_read():
    # BE and ST series can sit under MKT=G (20 BE rows on 18 Sep 2026); a bonus there must
    # still exclude the event (audit, 20 Oct 2026). Index rows (MKT=Y) are never actions.
    text = ("MKT,SERIES,SYMBOL,SECURITY,PREV_CL_PR,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,"
            "NET_TRDVAL,NET_TRDQTY,IND_SEC,CORP_IND,TRADES,HI_52_WK,LO_52_WK\n"
            "G,BE,KHADIM,KHADIM INDIA LIMITED,200,200,201,199,200,1,1,N,XB,1,1,1\n"
            "Y, ,NIFTY,Nifty 50,1,1,1,1,1,1,1,Y,XD,1,1,1\n")
    _, actions = parse_pd(text)
    assert [(a.symbol, a.series, a.corp_ind) for a in actions] == [("KHADIM", "BE", "XB")]
