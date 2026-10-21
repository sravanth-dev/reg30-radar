"""The three NSE clients go through the shared guard (common/nse_guard.py): warm-ups are
paced and checked, a clean archive 404 is an answer, five failures in a row stop the run,
the gap holds across clients, and an unrecognised answer stops at once. No network: fake
sessions, and the per-test guard from conftest.py (no sleeping, a temporary lock)."""

from pathlib import Path

import pytest

from reg30_radar.collector import nse
from reg30_radar.common import nse_guard
from reg30_radar.common.nse_guard import NseHardStop, NseStructureChanged
from reg30_radar.documents.fetch import PdfFetcher
from reg30_radar.market.fetch import ArchiveFetcher

ROW = {"symbol": "BEL", "an_dt": "18-Sep-2026 10:17:50", "desc": "Press Release",
       "seq_id": "1", "sm_isin": "INE263A01024", "attchmntFile": "https://x/a.pdf",
       "exchdisstime": "18-Sep-2026 10:17:52"}


class Response:
    def __init__(self, status=200, body=None, content=b"", bad_json=False):
        self.status_code = status
        self._body = body
        self._content = content
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("Expecting value")
        return self._body

    def iter_content(self, chunk_size):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Session:
    """Answers each GET with the next scripted response, and records the URLs."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, params=None, timeout=None, stream=False):
        self.urls.append(url)
        nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def close(self):
        pass


def api_client(*responses):
    c = nse.NseClient()
    c.session = Session(*responses)
    return c


def test_an_object_without_data_stops_at_once(nse_guard_for_tests):
    c = api_client(Response(200, body={}), Response(200, body={"message": "moved"}))
    with pytest.raises(NseStructureChanged, match="unexpected response shape"):
        c.poll_announcements()


def test_a_renamed_announcement_field_stops_at_once():
    renamed = {k: v for k, v in ROW.items() if k != "attchmntFile"} | {"attachment": "x"}
    c = api_client(Response(200, body={}), Response(200, body=[renamed, renamed]))
    with pytest.raises(NseStructureChanged, match="attchmntFile"):
        c.poll_announcements()


def test_a_row_without_its_timestamp_stops_at_once():
    c = api_client(Response(200, body={}), Response(200, body=[{"symbol": "BEL", "desc": "x"}]))
    with pytest.raises(NseStructureChanged, match="an_dt"):
        c.poll_announcements()


def test_good_rows_and_both_known_shapes_pass():
    c = api_client(Response(200, body={}), Response(200, body=[ROW]))
    assert c.poll_announcements().rows == [ROW]
    c = api_client(Response(200, body={}), Response(200, body={"data": [], "totalCount": 0}))
    got = c.fetch_integrated_results("BEL")
    assert got.ok and got.rows == [] and got.total == 0


def test_a_failed_warm_up_is_reported_not_raised(nse_guard_for_tests):
    c = api_client(Response(503))
    got = c.poll_announcements()
    assert not got.ok and "warm-up HTTP 503" in got.error
    assert nse_guard_for_tests.consecutive_failures == 1
    assert len(c.session.urls) == 1                 # the API itself was never called


def test_a_block_page_counts_as_a_failure(nse_guard_for_tests):
    c = api_client(Response(200, body={}), Response(200, bad_json=True))
    assert not c.poll_announcements().ok
    assert nse_guard_for_tests.consecutive_failures == 1


def test_five_failed_polls_in_a_row_stop_the_run():
    c = api_client(Response(200, body={}), Response(503))
    for _ in range(4):
        assert not c.poll_announcements().ok
    with pytest.raises(NseHardStop, match="5 consecutive"):
        c.poll_announcements()


def test_a_clean_404_from_the_archive_never_counts(nse_guard_for_tests):
    f = ArchiveFetcher()
    f.session = Session(Response(200), Response(404))
    for _ in range(8):                              # weekends and holidays, back to back
        assert f.get("https://x/BhavCopy_20261004.zip").status == 404
    assert nse_guard_for_tests.consecutive_failures == 0


def test_five_archive_errors_in_a_row_stop_the_run():
    f = ArchiveFetcher()
    f.session = Session(Response(200), ConnectionResetError(10054, "reset"))
    for _ in range(4):
        assert not f.get("https://x/PR011026.zip").ok
    with pytest.raises(NseHardStop):
        f.get("https://x/PR011026.zip")


def test_the_gap_holds_across_clients(nse_guard_for_tests, monkeypatch):
    waits = []
    monkeypatch.setattr(nse_guard_for_tests, "sleep", waits.append)
    monkeypatch.setattr(nse_guard.random, "uniform", lambda a, b: 0.0)
    api = api_client(Response(200, body={}), Response(200, body=[ROW]))
    api.min_gap = 3.0
    api.poll_announcements()                        # warm-up, then the poll: one gap
    archive = ArchiveFetcher()
    archive.session = Session(Response(200), Response(404))
    archive.get("https://x/a.zip")                  # its own warm-up, then the file: two more
    assert len(waits) == 3 and all(w == pytest.approx(3.0, abs=0.01) for w in waits)


def test_the_pdf_client_warms_up_again_after_a_403(tmp_path: Path):
    f = PdfFetcher()
    f.session = Session(Response(200), Response(403), Response(200),
                        Response(200, content=b"%PDF-1.4 x"))
    assert f.fetch("https://x/a.pdf", tmp_path).http_status == 403
    assert f.fetch("https://x/a.pdf", tmp_path).ok
    warmups = [u for u in f.session.urls if "corporate-filings-announcements" in u]
    assert len(warmups) == 2
