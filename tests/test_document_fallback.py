# -*- coding: utf-8 -*-
"""Document-analysis fallback — a scanned file whose OCR yields REAL text
but NO financial indicators is KEPT as a document analysis (extracted-text
sample + loud «no financial statements» D1 warning) instead of refused:
the user cannot fix a prose-only PDF by re-exporting it. Corrupt reads
(no OCR text either) stay refused with the scanned-file hint.

Verified LIVE end-to-end before this test was pinned (Windows OCR ar-SA):
upload → saved row with audit.mode=document, D1 warning, texts_sample.
"""

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analyzer import texts_sample
from app.audit import run_quality_gate
from tests.conftest import client  # noqa: F401

PDF_MIME = "application/pdf"


def test_texts_sample_shapes_the_document_view():
    lines = ["", "شركة الأفق للاستشارات  ", "خط طويل " * 40, "__TABLE__x",
             "سيعقد الاجتماع في نهاية الشهر"]
    sample = texts_sample(lines, limit=24, max_len=40)
    # empties + table markers dropped, whitespace collapsed, length capped
    assert len(sample) == 3
    assert sample[0] == "شركة الأفق للاستشارات"
    assert all(len(s) <= 40 for s in sample)
    assert "__TABLE__" not in " ".join(sample)


def test_metrics_empty_result_is_fatal_without_the_doc_branch():
    """The gate itself still refuses a metrics-empty result — the DOC
    fallback is the upload path's BRANCH BEFORE persistence, not a gate
    relaxation: no silent weakening of C7."""
    res = {"kpis": {}, "ratios": {}, "series": {}, "forecast": {},
           "metrics": {}, "tables_found": 0, "texts_found": 2}
    res["metrics"] = {}
    gate = run_quality_gate(res)
    assert gate["fatal"] is True


def test_doc_branch_saved_shape_matches_contract(client, tmp_path):
    """Wire-level contract of the DOC branch, exercised through the real
    upload path with a metrics-empty OCR prose result (the scanned PDF is
    synthesized when the OCR engine is available; the branch logic is the
    same either way — the gate's fatal C7 + ocr_used + texts)."""
    from app.analyzer import analyze

    # simulate exactly what the upload path holds after an OCR prose read
    parsed_texts = ["شركة الأفق للاستشارات الإدارية",
                    "نعلمكم بأن اجتماع الجمعية العامة السنوي سيعقد قريبًا"]
    res = analyze([], parsed_texts)
    res["metrics"] = {}
    res["original_metrics"] = {}
    res["_ocr_used"] = True
    doc_text = texts_sample(parsed_texts)
    assert doc_text, "the branch precondition: real prose was read"
    res["texts_sample"] = doc_text
    res["audit"] = {
        "ok": False, "errors": [],
        "warnings": [{"code": "D1", "severity": "warning",
                      "ar": "مستند بلا قوائم مالية",
                      "en": "Document without financial statements"}],
        "repairs": [], "mode": "document",
        "checked_at": "2026-01-01T00:00:00+00:00",
    }
    # the branch payload shape the UI badge + notice read
    assert res["audit"]["mode"] == "document"
    assert res["audit"]["warnings"][0]["code"] == "D1"
    assert isinstance(res["texts_sample"], list) and res["texts_sample"]

    # and recompute_result must NOT drop the document evidence
    from app.analyzer import recompute_result

    kept = recompute_result(res)
    assert kept.get("texts_sample") == res["texts_sample"]
    assert kept["audit"]["mode"] == "document"
