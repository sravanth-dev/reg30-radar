"""The §5.5 document pipeline, offline.

No network: a fake fetcher copies a real filing from `tests/labelled/` into the pipeline's
work directory, which is exactly what a download produces. That keeps `pytest` free of live
requests (CLAUDE.md) while still exercising the real extractor on a real PDF.

The test that matters most is the one asserting the pipeline refuses to delete outside its
work directory. `tests/labelled/` holds the only hand-labelled data in the project, D8 makes
it the standing exception to delete-after-extraction, and a pipeline bug that reached it
would be unrecoverable.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from tradebot.documents.fetch import Fetched, sha256_of
from tradebot.documents.pipeline import UnsafeDeletePath, _delete_downloaded, process_url
from tradebot.documents.text import extract

LABELLED = Path(__file__).resolve().parents[1] / "labelled"
SAMPLE = LABELLED / "RAILTEL_20260917_1.pdf"      # 2 pages, real text layer


class FakeFetcher:
    """Stands in for a download: copies a local PDF into the work directory, hashing it.

    Deliberately produces the same shape a real fetch does, including naming the file by
    its hash, so the pipeline under test is the real one.
    """

    def __init__(self, source: Path, *, fail: str | None = None) -> None:
        self.source = Path(source)
        self.fail = fail
        self.calls = 0

    def fetch(self, url: str, dest_dir: Path) -> Fetched:
        self.calls += 1
        if self.fail:
            return Fetched(False, error=self.fail)
        dest_dir.mkdir(parents=True, exist_ok=True)
        data = self.source.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        path = Path(dest_dir) / f"{sha}.pdf"
        path.write_bytes(data)
        return Fetched(True, path=path, sha256=sha, size_bytes=len(data), http_status=200)


def test_sample_exists():
    assert SAMPLE.exists(), "the labelled set is the fixture source for this suite"


# --------------------------------------------------------------------- extraction

def test_extract_reads_a_real_filing():
    got = extract(SAMPLE)
    assert got.pages == 2
    assert got.method == "pdfplumber"
    assert not got.is_scanned
    assert len(got.text.strip()) > 500


def test_extract_on_a_missing_file_fails_without_raising():
    got = extract(LABELLED / "does_not_exist.pdf")
    assert got.text == ""
    assert got.method.startswith("failed:")
    # An unreadable file counts as scanned so it lands in the manual-review queue rather
    # than silently becoming an empty document.
    assert got.is_scanned


def test_sha256_of_matches_hashlib(tmp_path):
    copy = tmp_path / "x.pdf"
    shutil.copy(SAMPLE, copy)
    assert sha256_of(copy) == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()


# --------------------------------------------------------------------- the D8 guard

def test_delete_refuses_a_path_outside_the_work_directory(tmp_path):
    """The guard that protects tests/labelled/ from a pipeline bug."""
    with pytest.raises(UnsafeDeletePath):
        _delete_downloaded(SAMPLE, tmp_path)
    assert SAMPLE.exists(), "the labelled PDF must still be there"


def test_delete_refuses_a_traversal_out_of_the_work_directory(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    escape = work / ".." / "elsewhere.pdf"
    (tmp_path / "elsewhere.pdf").write_bytes(b"%PDF-1.4\n")
    with pytest.raises(UnsafeDeletePath):
        _delete_downloaded(escape, work)
    assert (tmp_path / "elsewhere.pdf").exists()


def test_delete_removes_a_file_it_did_download(tmp_path):
    f = tmp_path / "downloaded.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    assert _delete_downloaded(f, tmp_path) is True
    assert not f.exists()


# --------------------------------------------------------------------- the pipeline

def test_pipeline_extracts_then_deletes_the_pdf(tmp_path):
    fetcher = FakeFetcher(SAMPLE)
    out = process_url("https://example.invalid/a.pdf", work_dir=tmp_path, fetcher=fetcher)

    assert out.ok
    assert out.sha256 == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    assert out.pages == 2
    assert out.chars > 500
    assert out.method == "pdfplumber"

    # D8: the file is gone, and the work directory holds no PDF at all.
    assert out.pdf_deleted is True
    assert list(tmp_path.glob("*.pdf")) == []


def test_pipeline_leaves_the_source_labelled_pdf_untouched(tmp_path):
    before = SAMPLE.read_bytes()
    process_url("https://example.invalid/a.pdf", work_dir=tmp_path,
                fetcher=FakeFetcher(SAMPLE))
    assert SAMPLE.read_bytes() == before


def test_pipeline_reports_a_failed_download_without_raising(tmp_path):
    out = process_url("https://example.invalid/a.pdf", work_dir=tmp_path,
                      fetcher=FakeFetcher(SAMPLE, fail="HTTP 404"))
    assert out.ok is False
    assert out.error == "HTTP 404"
    assert out.pdf_deleted is False


def test_pipeline_flags_a_scan_for_review(tmp_path, monkeypatch):
    """A filing with no text layer must reach the §5.5 review queue, not pass silently."""
    from tradebot.documents import pipeline as mod

    def fake_extract(path):
        from tradebot.documents.text import Extracted
        return Extracted(text="", pages=3, method="pdfplumber", is_scanned=True)

    monkeypatch.setattr(mod, "extract", fake_extract)
    out = process_url("https://example.invalid/scan.pdf", work_dir=tmp_path,
                      fetcher=FakeFetcher(SAMPLE))
    assert out.is_scanned
    assert out.needs_review
    # Still deleted: a scan's bytes are no more worth keeping than any other (D8).
    assert out.pdf_deleted is True


def test_pipeline_runs_without_a_database(tmp_path):
    # §9: most tests need no database, and the eval harness runs the extraction path with
    # conn=None. This asserts that stays true.
    out = process_url("https://example.invalid/a.pdf", work_dir=tmp_path,
                      fetcher=FakeFetcher(SAMPLE), conn=None)
    assert out.ok
    assert out.document_id is None
