"""Parsers for NSE's daily archive files (ARCHITECTURE.md §5.2, §5.9). Pure functions: no
network, no database, so every one is tested against the committed fixtures.

Two archives a day:
- the UDiFF bhavcopy (a zip holding one CSV): prices, and the only file carrying the ISIN,
  so it is the join key for everything else;
- the PR bundle (a zip of about 14 members): `pd` (Nifty 50 and each security's CORP_IND),
  `mcap` (market cap in plain rupees), `bh` (band hitters), `an` (the day's announcement
  report).

Prices and market caps are Decimal, never float (CLAUDE.md).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from tradebot.backfill.reconcile import BundleEntry, parse_bundle_line


def _dec(value: str | None) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _int(value: str | None) -> int | None:
    d = _dec(value)
    return int(d) if d is not None else None


def _rows(csv_text: str) -> list[dict]:
    """CSV rows as dicts, with header and cell whitespace stripped: the `mcap` header ends in
    runs of spaces, and `pd` pads every number."""
    reader = csv.reader(io.StringIO(csv_text))
    header = [h.strip() for h in next(reader, [])]
    out = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        out.append({h: (cells[i].strip() if i < len(cells) else "") for i, h in enumerate(header)})
    return out


# ------------------------------------------------------------------ UDiFF bhavcopy

@dataclass(frozen=True)
class PriceRow:
    trade_date: date
    isin: str
    symbol: str
    series: str
    name: str
    instrument_type: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: int | None
    traded_value: Decimal | None = None   # TtlTrfVal, rupees


def parse_udiff(csv_text: str) -> list[PriceRow]:
    """Every row with an ISIN. The series and instrument type are kept, so the universe rule
    (D9) is applied where it is decided, not here."""
    out = []
    for r in _rows(csv_text):
        isin = r.get("ISIN", "")
        if not isin:
            continue
        out.append(PriceRow(
            trade_date=date.fromisoformat(r["TradDt"]),
            isin=isin,
            symbol=r.get("TckrSymb", ""),
            series=r.get("SctySrs", ""),
            name=r.get("FinInstrmNm", ""),
            instrument_type=r.get("FinInstrmTp", ""),
            open=_dec(r.get("OpnPric")),
            high=_dec(r.get("HghPric")),
            low=_dec(r.get("LwPric")),
            close=_dec(r.get("ClsPric")),
            # NOT corporate-action adjusted (Spike B, §5.9): stored because it is in the
            # file, never used to chain returns.
            prev_close=_dec(r.get("PrvsClsgPric")),
            volume=_int(r.get("TtlTradgVol")),
            traded_value=_dec(r.get("TtlTrfVal")),
        ))
    return out


def udiff_csv_from_zip(zip_bytes: bytes) -> str:
    """The UDiFF zip holds one CSV of the same name."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in the UDiFF zip, found {names}")
        return zf.read(names[0]).decode("utf-8", errors="replace")


# ------------------------------------------------------------------ PR bundle members

def pr_members(zip_bytes: bytes, prefixes: dict[str, str]) -> dict[str, str]:
    """{kind: text} for each wanted member, e.g. {"price_data": <pd text>}.

    Matched case-insensitively on prefix + date digits, never on an exact filename: the
    2025 bundles mix capitalisation and mix DDMMYY with DDMMYYYY inside one zip (Spike B,
    §5.9). Requiring digits right after the prefix keeps "pd" from matching some other
    member whose name merely starts with those letters.
    """
    out: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            base = name.rsplit("/", 1)[-1]
            for kind, prefix in prefixes.items():
                if re.fullmatch(rf"{re.escape(prefix)}\d{{6,8}}\.(?:csv|txt)", base, re.I):
                    out[kind] = zf.read(name).decode("utf-8", errors="replace")
    return out


@dataclass(frozen=True)
class IndexClose:
    index_name: str
    close: Decimal


@dataclass(frozen=True)
class CorpAction:
    symbol: str
    series: str
    corp_ind: str


def parse_pd(csv_text: str) -> tuple[list[IndexClose], list[CorpAction]]:
    """Index closes (rows with MKT=Y, name in SECURITY) and each security's CORP_IND flag
    where one is set (§5.9: a detector of ex-dates, never an adjustment)."""
    indices, actions = [], []
    for r in _rows(csv_text):
        mkt = r.get("MKT", "")
        if mkt == "Y" and r.get("IND_SEC") == "Y":
            close = _dec(r.get("CLOSE_PRICE"))
            if close is not None and r.get("SECURITY"):
                indices.append(IndexClose(r["SECURITY"], close))
        elif mkt == "N" and r.get("CORP_IND"):
            actions.append(CorpAction(r["SYMBOL"], r["SERIES"], r["CORP_IND"]))
    return indices, actions


@dataclass(frozen=True)
class MarketCap:
    symbol: str
    series: str
    mcap_inr: Decimal


def parse_mcap(csv_text: str) -> list[MarketCap]:
    """`Market Cap(Rs.)` is plain rupees, not lakhs or crores (verified, §5.9). The file
    ends in "Permitted" and "Total" summary rows with no series; those are skipped."""
    out = []
    for r in _rows(csv_text):
        symbol, series = r.get("Symbol", ""), r.get("Series", "")
        mcap = _dec(r.get("Market Cap(Rs.)"))
        if symbol and series and mcap is not None:
            out.append(MarketCap(symbol, series, mcap))
    return out


@dataclass(frozen=True)
class BandHit:
    symbol: str
    series: str
    high_low: str   # "H" or "L"


def parse_bh(csv_text: str) -> list[BandHit]:
    """Tolerates both widths: the 2025 files carry a fifth column, INDEX FLAG, that was
    later dropped (Spike B, §5.9). Columns are read by name, so either works."""
    out = []
    for r in _rows(csv_text):
        hl = r.get("HIGH/LOW", "")
        if r.get("SYMBOL") and hl in ("H", "L"):
            out.append(BandHit(r["SYMBOL"], r.get("SERIES", ""), hl))
    return out


def parse_an(text: str) -> list[BundleEntry]:
    """The day's announcement report, one entry per filing line. The first line is a
    header ("COMPANY NAME SYMBOL : ANNOUNCEMENTS"), which is dropped."""
    out = []
    for line in text.splitlines():
        entry = parse_bundle_line(line)
        if entry is None or entry.body.upper() == "ANNOUNCEMENTS":
            continue
        out.append(entry)
    return out


def mcap_trade_date(csv_text: str) -> date | None:
    """The `Trade Date` in an mcap file ("18 SEP 2026"), to check a bundle is the day asked
    for rather than trusting the URL."""
    for r in _rows(csv_text):
        value = r.get("Trade Date", "")
        if value:
            return datetime.strptime(value.title(), "%d %b %Y").date()
    return None
