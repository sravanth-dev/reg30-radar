"""§5.5 Part C: a value read from this pipeline's own vision OCR needs a second read that
agrees before it counts (extractor/part_c.py, backfill/vision_check.py).

The unit tests need no database. The stage tests run on real SQL in a scratch schema
(conftest.py), with a real labelled PDF standing in for the re-download and a fake
transcriber standing in for the model, so no request leaves the machine."""

import hashlib
import shutil
from decimal import Decimal
from pathlib import Path

from tradebot.backfill import vision_check
from tradebot.documents.fetch import Fetched
from tradebot.extractor import part_c
from tradebot.llm.client import LlmRefused

CR = Decimal(10) ** 7
PAGE1 = "Letter to the exchange about an order received."
PAGE2 = "Broad consideration: Rs. 283 Crore for the corridor works."
TEXT = PAGE1 + "\n\n" + PAGE2


def report(source1, source2, chars2=len(PAGE2)):
    return [{"page": 1, "verdict": "ok", "source": source1, "chars": len(PAGE1)},
            {"page": 2, "verdict": "ok", "source": source2, "chars": chars2}]


# --- which values are vision-sourced ------------------------------------------------------

def test_a_value_on_a_text_layer_page_needs_no_second_read():
    assert not part_c.vision_sourced(TEXT, report("vision", "text_layer"),
                                     "Rs. 283 Crore", 283 * CR)


def test_a_value_on_a_vision_page_does():
    assert part_c.vision_sourced(TEXT, report("text_layer", "vision"),
                                 "Rs. 283 Crore", 283 * CR)


def test_when_pages_cannot_be_told_apart_the_value_counts_as_vision_sourced():
    # 12 of the 94 OCR'd backfill documents: the recorded counts do not add up.
    assert part_c.vision_sourced(TEXT, report("text_layer", "vision", chars2=5),
                                 "Rs. 283 Crore", 283 * CR)


def test_a_document_with_no_vision_page_is_never_affected():
    assert not part_c.vision_sourced(TEXT, report("text_layer", "ocr_overlay"),
                                     "Rs. 283 Crore", 283 * CR)


def test_the_gate():
    g = part_c.gate
    assert g("verified", vision=False, second_read=None, second_read_inr=None,
             value_inr=1) == ("verified", None)
    assert g("verified", vision=True, second_read=None, second_read_inr=None,
             value_inr=1) == ("needs_review", "pending")
    assert g("verified", vision=True, second_read="agrees", second_read_inr=1,
             value_inr=1) == ("verified", "agrees")
    # an agreement about a different value is not an agreement about this one
    assert g("verified", vision=True, second_read="agrees", second_read_inr=2,
             value_inr=1) == ("needs_review", "pending")
    assert g("verified", vision=True, second_read="disagrees", second_read_inr=1,
             value_inr=1) == ("needs_review", "disagrees")
    assert g("needs_review", vision=True, second_read=None, second_read_inr=None,
             value_inr=1) == ("needs_review", None)


# --- the stage, on real SQL ---------------------------------------------------------------

PDF = Path(__file__).resolve().parents[1] / "labelled" / "HEG_20260918_1.pdf"
SHA = hashlib.sha256(PDF.read_bytes()).hexdigest()


class Fetcher:
    """Hands back a copy of a real PDF, as a re-download would."""

    def __init__(self, sha_ok=True):
        self.calls = 0
        self.sha_ok = sha_ok

    def fetch(self, url, dest_dir):
        self.calls += 1
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "copy.pdf"
        shutil.copyfile(PDF, path)
        return Fetched(True, path=path, sha256=SHA if self.sha_ok else "0" * 64, http_status=200)


class Transcriber:
    def __init__(self, transcript=None, refuse=False):
        self.transcript = transcript
        self.refuse = refuse
        self.calls = []

    def transcribe_image(self, png, *, prompt_version, purpose):
        if self.refuse:
            raise LlmRefused("backfill cap reached")
        self.calls.append(purpose)
        return self.transcript


def _seed(conn, *, value=283 * CR, span="Rs. 283 Crore"):
    conn.execute("insert into raw_announcements (id, source, source_id, payload_sha256,"
                 " first_seen_at, attachment_url, payload) overriding system value values"
                 " (1, 'nse', 's1', 'h', now(), 'https://x/heg.pdf', '{}')")
    conn.execute("insert into documents (id, url, sha256, text, method, extracted_at,"
                 " page_report) overriding system value values (1, 'u', %s, %s, 'vision', now(),"
                 " %s)", (SHA, TEXT, __import__("json").dumps(report("text_layer", "vision"))))
    conn.execute("insert into order_extractions (raw_announcement_id, document_id, bucket,"
                 " order_related, relevance_reason, path, review_status, value_inr, value_span,"
                 " processed_at) values (1, 1, 'order_win', true, 'x', 'llm', 'verified', %s, %s,"
                 " now())", (value, span))
    conn.commit()


def _row(conn):
    return conn.execute("select review_status, second_read, second_read_inr"
                        " from order_extractions").fetchone()


def test_a_second_read_that_agrees_keeps_the_value(scratch_conn, tmp_path):
    _seed(scratch_conn)
    ocr = Transcriber("Broad consideration: Rs. 283 Crore for the corridor works.")
    out = vision_check.run(scratch_conn, client=ocr, fetcher=Fetcher(), work_dir=tmp_path)
    assert out["agrees"] == 1 and ocr.calls == ["ocr_second_read"]   # only page 2 re-read
    assert _row(scratch_conn) == ("verified", "agrees", 283 * CR)
    assert list(tmp_path.iterdir()) == []                            # D8: the PDF is gone


def test_a_second_read_that_disagrees_sends_it_to_review(scratch_conn, tmp_path):
    _seed(scratch_conn)
    ocr = Transcriber("Broad consideration: Rs. 28.3 Crore for the corridor works.")
    vision_check.run(scratch_conn, client=ocr, fetcher=Fetcher(), work_dir=tmp_path)
    assert _row(scratch_conn) == ("needs_review", "disagrees", 283 * CR)
    # and a later run does not ask again about the same value
    again = Fetcher()
    vision_check.run(scratch_conn, client=ocr, fetcher=again, work_dir=tmp_path)
    assert again.calls == 0


def test_a_different_file_is_never_re_read(scratch_conn, tmp_path):
    _seed(scratch_conn)
    ocr = Transcriber("Rs. 283 Crore")
    vision_check.run(scratch_conn, client=ocr, fetcher=Fetcher(sha_ok=False), work_dir=tmp_path)
    assert _row(scratch_conn) == ("needs_review", "unavailable", 283 * CR)
    assert ocr.calls == [] and list(tmp_path.iterdir()) == []


def test_at_the_spend_cap_the_value_waits(scratch_conn, tmp_path):
    _seed(scratch_conn)
    vision_check.run(scratch_conn, client=Transcriber(refuse=True), fetcher=Fetcher(),
                     work_dir=tmp_path)
    assert _row(scratch_conn)[:2] == ("needs_review", "pending")


# --- what "agrees" means ------------------------------------------------------------------

def test_the_same_amount_printed_differently_agrees():
    # An independent read is not obliged to reproduce the first read's wording.
    assert vision_check.agrees("Order value:\nRs.283 Cr. (excluding taxes)", "Rs. 283 Crore",
                               283 * CR)
    assert vision_check.agrees("Rs.\n283 Crores", "Rs. 283 Crore", 283 * CR)   # split lines


def test_a_different_amount_or_a_quantity_does_not_agree():
    assert not vision_check.agrees("Order value: Rs. 28.3 Crore", "Rs. 283 Crore", 283 * CR)
    assert not vision_check.agrees("Supply of 283 MW", "Rs. 283 Crore", 283 * CR)
    assert not vision_check.agrees("", "Rs. 283 Crore", 283 * CR)


def test_the_second_transcript_is_kept_beside_the_first(scratch_conn, tmp_path):
    _seed(scratch_conn)
    ocr = Transcriber("Broad consideration: Rs.283 Cr. for the corridor works.")
    vision_check.run(scratch_conn, client=ocr, fetcher=Fetcher(), work_dir=tmp_path)
    status, kept = scratch_conn.execute(
        "select review_status, second_read_text from order_extractions").fetchone()
    assert status == "verified" and "Rs.283 Cr." in kept


def test_an_empty_second_transcript_is_no_read_not_a_disagreement(scratch_conn, tmp_path):
    _seed(scratch_conn)
    vision_check.run(scratch_conn, client=Transcriber(""), fetcher=Fetcher(), work_dir=tmp_path)
    assert _row(scratch_conn)[:2] == ("needs_review", "unavailable")
