"""One-off: re-download the HMT filing that exposed the garbled-OCR gap (WORKLOG, 24 Sep
2026 evening entry), so it can be committed as a permanent regression fixture.

One polite NSE request, through the same PdfFetcher the pipeline uses (warm-up, headers,
pacing from config/sources.yaml - D25). Throwaway probe, per ARCHITECTURE.md Sect.10: lives
in spikes/, not src/.
"""

from __future__ import annotations

from pathlib import Path

from reg30_radar.documents.fetch import PdfFetcher

URL = "https://nsearchives.nseindia.com/corporate/HMT_22092026135910_TWC.pdf"
DEST_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "scans"
FINAL = DEST_DIR / "hmt_glyphless.pdf"

if __name__ == "__main__":
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    fetcher = PdfFetcher()
    got = fetcher.fetch(URL, DEST_DIR)
    if not got.ok:
        print("FAILED:", got.error)
        raise SystemExit(1)
    got.path.rename(FINAL)
    print("saved", FINAL, got.size_bytes, "bytes, sha256", got.sha256)
