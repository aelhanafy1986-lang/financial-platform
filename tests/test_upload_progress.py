# -*- coding: utf-8 -*-
"""Live upload progress: the sidebar must never look frozen during OCR.

/api/upload responds only AFTER every file is analysed (~20s per scanned
file), so the frontend polls GET /api/upload/progress/{job_id} while the
request runs. Covered here:

- the upload path ticks the shared progress slot («pdf» stage, then
  «ocr» page N of total) via the parser's progress dict — with a REAL
  image-only scanned PDF on machines with the Windows OCR engine,
- parse runs OFF the event loop: a concurrent progress read DURING a
  (patched-slow) upload returns stage «ocr», not 404,
- «done» is terminal and reports the per-file counters,
- unknown/never-polled jobs answer 404,
- parse_file passes the progress dict ONLY to the pdf parser.
"""

import io
import threading
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.parsers import parse_file

from tests.test_pdf_tb_upload import _make_image_only_tb_pdf, _ocr_engine_available

PDF_MIME = "application/pdf"


# ------------------------------------------------------------ parser wiring ----

def test_parse_file_passes_progress_to_pdf_parser(tmp_path):
    seen = {}

    # PARSERS binds parse_pdf at import time — patch the DICT entry, not
    # the module attribute, or the spy never runs.
    import app.parsers as parsers_pkg

    original = parsers_pkg.PARSERS[".pdf"]

    def spy(path, progress=None):
        seen.update(progress or {})
        seen["called"] = True
        return {"tables": [], "texts": [], "ocr_used": False}

    parsers_pkg.PARSERS[".pdf"] = spy
    try:
        parse_file(tmp_path / "whatever.pdf", progress={"probe": 1})
    finally:
        parsers_pkg.PARSERS[".pdf"] = original
    assert seen.get("called") is True
    assert seen.get("probe") == 1


def test_parse_file_progress_ignored_for_non_pdf(tmp_path, monkeypatch):
    """The xlsx parser keeps its exact signature — a progress dict arg must
    never reach it (the upload path passes one unconditionally)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["البيان", "قيمة"])
    ws.append(["الإيرادات", 1000])
    path = tmp_path / "t.xlsx"
    wb.save(path)

    # no crash, and parsing still works with a progress dict attached
    parsed = parse_file(path, progress={"stage": "pdf"})
    assert parsed["tables"]


# ------------------------------------------------------ progress endpoint ----

def test_progress_unknown_job_is_404(client: TestClient):
    assert client.get("/api/upload/progress/deadbeef").status_code == 404


def test_progress_done_after_upload(client: TestClient):
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "make_sample.py"
    xlsx = Path(__file__).resolve().parents[1] / "sample-financials.xlsx"
    if not xlsx.exists():
        import subprocess
        import sys
        subprocess.run([sys.executable, str(script)], check=True)
    with open(xlsx, "rb") as fh:
        resp = client.post(
            "/api/upload",
            files={"files": ("sample-financials.xlsx", fh)},
            headers={**client.auth_headers, "X-Upload-Job-Id": "job-done-1"},
        )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-done-1"

    body = client.get("/api/upload/progress/job-done-1").json()
    assert body["done"] is True
    assert body["stage"] == "done"
    assert body["files_done"] == 1
    assert body["files_total"] == 1


def test_progress_live_during_slow_parse(client: TestClient, monkeypatch, tmp_path):
    """THE behavioural regression: while a (patched-slow) upload is still
    running, a concurrent GET of the progress endpoint answers with the
    live stage — possible only because parse runs OFF the event loop."""
    import app.parsers.pdf_parser as pp
    import app.parsers as parsers_pkg

    real_parse_pdf = parsers_pkg.PARSERS[".pdf"]

    def slow_parse_pdf(path, progress=None):
        # emulate a slow OCR: tick the slot like the real parser, then hold
        pp._progress_set(progress, "ocr", 2, 7)
        time.sleep(1.2)
        return real_parse_pdf(path, progress=progress)

    monkeypatch.setitem(parsers_pkg.PARSERS, ".pdf", slow_parse_pdf)

    body = io.BytesIO(b"%PDF-1.4 fake scanned pdf bytes")
    results: list = []
    thread_error: list = []

    def do_upload():
        try:
            results.append(client.post(
                "/api/upload",
                files={"files": ("scan.pdf", body, PDF_MIME)},
                headers={**client.auth_headers, "X-Upload-Job-Id": "job-live-1"},
            ))
        except Exception as exc:  # surfaced below — never swallow silently
            thread_error.append(repr(exc))

    th = threading.Thread(target=do_upload, daemon=True)
    th.start()
    time.sleep(0.4)  # the upload is now parked inside the slow parse
    assert not thread_error, thread_error

    live = client.get("/api/upload/progress/job-live-1")
    th.join(timeout=30)
    assert not thread_error, thread_error

    assert live.status_code == 200, (
        "progress endpoint was NOT live during upload; "
        f"upload result: {results}" 
    )
    assert live.json()["stage"] == "ocr"
    assert live.json()["page"] == 2
    assert live.json()["total"] == 7
    # whatever happened to the fake pdf itself, the upload request finished
    assert results and results[0].status_code in (200, 400)


# ------------------------------------------------- real OCR ticks the slot ----

@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_scanned_upload_ticks_ocr_pages(client: TestClient, monkeypatch, tmp_path):
    """With a REAL image-only scanned PDF, the upload's progress slot walks
    the «ocr» stage page by page while parse_file runs."""
    pdf_path = tmp_path / "scan.pdf"
    _make_image_only_tb_pdf(pdf_path)
    job_id = "job-ocr-ticks"

    captured = [None]
    original_parse_file = main_module.parse_file

    def spying_parse_file(path, progress=None):
        # snapshot AFTER the parse: this IS the shared slot (same dict
        # identity), so its live stage at return time is the OCR ticks
        out = original_parse_file(path, progress=progress)
        captured[0] = dict(progress or {})
        return out

    monkeypatch.setattr(main_module, "parse_file", spying_parse_file)

    with open(pdf_path, "rb") as fh:
        resp = client.post(
            "/api/upload",
            files={"files": ("scan.pdf", fh, PDF_MIME)},
            headers={**client.auth_headers, "X-Upload-Job-Id": job_id},
        )

    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item, item
    client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)

    progress = captured[0]
    assert progress is not None
    assert progress.get("stage") == "ocr"
    assert 1 <= progress.get("page", 0) <= progress.get("total", 0) <= 20
    # and the endpoint reflects the terminal state afterwards
    done = client.get(f"/api/upload/progress/{job_id}").json()
    assert done["done"] is True
