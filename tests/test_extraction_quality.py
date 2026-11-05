# -*- coding: utf-8 -*-
"""The PDF/image parsing METHODOLOGY: score-based best-of cascade.

The platform failed repeatedly on scanned PDFs and photos — the old
cascade escalated only on EMPTINESS, so a garbage text layer (broken
encodings, misaligned lattice) carrying digits but no priceable labels
was kept silently while the real statement sat unread. The methodology
pins: every read attempt is scored on labeled money rows + concepts
(``quality.score_extraction``), the strongest candidate WINS, scanned
PDFs get a second OCR opinion at a coarser DPI, and small images get an
upsampled read attempt.
"""

import io

import pytest

from app.parsers.quality import STRONG_SCORE, score_extraction

from tests.test_pdf_tb_upload import (
    _ocr_engine_available,
    _render_tb_png,
)

PDF_MIME = "application/pdf"


# ------------------------------------------------------------ the referee ----

def test_score_empty():
    s = score_extraction([], [])
    assert s["score"] == 0.0 and not s["spine"]


def test_score_digits_without_labels_is_weak():
    """The garbage-text-layer signature: digits everywhere, no priceable
    labeled row — exactly what the old gate mistook for success."""
    rows = [["12345", "678"], ["2023", "999"], ["411", "178"]]
    s = score_extraction([{"name": "t", "rows": rows}], [])
    assert s["numeric_rows"] == 3
    assert s["labeled_rows"] == 0
    assert s["score"] < STRONG_SCORE


def test_score_labeled_grid_is_strong():
    rows = [
        ["الحساب", "مدين", "دائن"],
        ["النقدية", "150000", "0"],
        ["الايرادات", "0", "350000"],
        ["تكلفة الإيراد", "180000", "0"],
    ]
    s = score_extraction([{"name": "t", "rows": rows}], [])
    assert s["labeled_rows"] >= 3
    assert s["spine"] is True
    assert s["score"] >= STRONG_SCORE


def test_prose_lines_carry_a_thin_signal():
    s = score_extraction([], ["شركة المراعي", "قائمة المركز المالي"])
    assert s["score"] > 0
    assert s["score"] < STRONG_SCORE


# ------------------------------------- cascade: garbage layer escalates ----

def _garbage_then_scan_pdf(path, scan_png) -> None:
    """Page 1: a text layer of digit-bearing GIBBERISH (no labels). Page 2:
    the real statement as an image only. The old cascade stopped at page
    1's digits; the methodology must escalate to OCR and read page 2."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    junk = "zz9 4102 qq 552013 ww 871240 ee 330019 rr 2024 tt 918273 yy"
    y = 60
    for _ in range(20):
        page.insert_text((60, y), junk, fontsize=10)
        y += 32
    p2 = doc.new_page(width=595, height=842)
    p2.insert_image(p2.rect, filename=str(scan_png))
    doc.save(str(path))
    doc.close()


@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_garbage_text_layer_escalates_to_ocr(tmp_path):
    import pymupdf

    from app.parsers import parse_file

    scan_png = tmp_path / "tb.png"
    _render_tb_png(scan_png)
    pdf_path = tmp_path / "junk_then_scan.pdf"
    _garbage_then_scan_pdf(pdf_path, scan_png)

    out = parse_file(pdf_path)
    # the WINNER is the OCR read of the real page — not page 1's garbage
    assert out["ocr_used"] is True
    assert out["quality"]["score"] >= STRONG_SCORE
    assert out["quality"]["spine"] is True
    all_cells = [c for t in out["tables"] for r in t["rows"] for c in r]
    assert any("350000" in str(c) for c in all_cells)


def test_parse_pdf_reports_quality_meta(tmp_path):
    """Even a healthy text-layer PDF carries the score — transparency."""
    import pymupdf

    from app.parsers import parse_file

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 80), "Revenue 1250000")
    page.insert_text((60, 110), "Cost of Sales 800000")
    doc.save(str(tmp_path / "plain.pdf"))
    doc.close()

    out = parse_file(tmp_path / "plain.pdf")
    assert "quality" in out
    assert out["quality"]["labeled_rows"] >= 1


# ----------------------------------------------- image read attempts -------

@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_small_image_uses_upscale_attempt(tmp_path):
    """A downscaled photo of a statement (< the 1800px trigger) still
    reads: the upsampled attempt recovers what native size cannot — and
    the score rides out either way."""
    from PIL import Image

    from app.parsers.image_parser import parse_image

    png = tmp_path / "tb_full.png"
    _render_tb_png(png)
    small = tmp_path / "tb_small.png"
    img = Image.open(str(png))
    img.resize((img.width // 2, img.height // 2), Image.LANCZOS).save(str(small))

    out = parse_image(small)
    assert out["ocr_used"] is True
    assert "quality" in out
    assert out["tables"], "no numeric grid survived either attempt"
    all_cells = [c for r in out["tables"][0]["rows"] for c in r]
    assert any("350000" in str(c) for c in all_cells)


def test_unreadable_image_degrades_to_prose_shape(tmp_path):
    """A blank image reads nothing — the honest empty shape with score 0."""
    from PIL import Image

    from app.parsers.image_parser import parse_image

    blank = tmp_path / "blank.png"
    Image.new("RGB", (600, 400), "white").save(str(blank))
    out = parse_image(blank)
    assert out["ocr_used"] is True
    assert "quality" in out
    assert out["tables"] == []
