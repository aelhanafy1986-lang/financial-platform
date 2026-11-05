# -*- coding: utf-8 -*-
"""OCR image preprocessing — المعالجة المسبقة قبل المحرك.

Contract: scanned/camera pages get their GEOMETRY repaired (global deskew
via an ink-projection search over ±6°) before the Windows-OCR engine sees
them — a 2° tilt smears each row across two engine lines and the row-band
vote then tears cost rows («تكلفة الإيراد») in half. LOCAL (Sauvola-style)
binarization joins the fixed-threshold variants as one more candidate in
the per-cell vote — shaded zebra bands keep their digits where any single
fixed threshold washes them out. Everything degrades safely: a level,
healthy page goes to the engine UNCHANGED (the deskew gate returns None),
and in the image path the preprocessed read competes under the score
referee instead of replacing the original.
"""

import io

import numpy as np
import pytest
from PIL import Image

from app.parsers.preprocess import (
    adaptive_contrast,
    binarize_local,
    deskew_page_for_ocr,
    estimate_skew,
    preprocess_for_ocr,
)

from tests.test_pdf_tb_upload import (
    _ocr_engine_available,
    _render_tb_png,
)


def _dense_page_png(path, dpi=150) -> Image.Image:
    """A statement-density page: 34 labeled/numbered rows (a real financial
    page's ink structure — sparse 4-line pages give the projection profile
    too little ink to measure tilt from)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for i in range(34):
        page.insert_text((60, y), f"بند رقم {i} 1,2{i}5,4{i}0", fontsize=11)
        page.insert_text((380, y), f"{100 + i},000.50", fontsize=11)
        y += 22
    page.get_pixmap(dpi=dpi).save(str(path))
    doc.close()
    return Image.open(str(path))


# ------------------------------------------------------- skew estimation ----

def test_estimate_skew_detects_tilt_on_dense_page(tmp_path):
    img = _dense_page_png(tmp_path / "dense.png")
    tilted = img.rotate(2.5, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    angle = estimate_skew(tilted)
    assert angle != 0.0
    assert abs(abs(angle) - 2.5) <= 0.75


def test_estimate_skew_level_page_is_zero(tmp_path):
    img = _dense_page_png(tmp_path / "dense.png")
    assert estimate_skew(img) == 0.0


def test_tiny_images_skip_skew_safely():
    assert estimate_skew(Image.new("L", (40, 30), 255)) == 0.0


# ------------------------------------------------------------ the gates ----

def test_deskew_gate_rotates_only_tilted_pages(tmp_path):
    img = _dense_page_png(tmp_path / "dense.png")
    tilted = img.rotate(2.5, resample=Image.BICUBIC, fillcolor=(255, 255, 255))

    out, meta = deskew_page_for_ocr(tilted)
    assert meta["deskewed"] is True and out is not None
    # geometry repaired: the DESKEWED page measures level again
    assert estimate_skew(out) == 0.0

    out2, meta2 = deskew_page_for_ocr(img)
    assert out2 is None and meta2["deskewed"] is False


def test_deskew_gate_degrades_on_garbage():
    out, meta = deskew_page_for_ocr(None)
    assert out is None and meta["deskewed"] is False


# ------------------------------------------------------- binarization ----

def test_binarize_local_keeps_ink_drops_shading():
    """Black glyphs on a light-gray zebra band: the band must come out
    WHITE (shading is background) while the glyphs stay BLACK — the exact
    «shaded rows vanish» failure of fixed thresholds."""
    arr = np.full((120, 300), 200, dtype=np.uint8)      # shaded band
    arr[40:70, 40:260] = 255                            # white strip inside
    arr[50:62, 60:240] = 30                             # «text» line: black
    img = Image.fromarray(arr, mode="L")

    out = np.asarray(binarize_local(img), dtype=np.uint8)
    black = (out == 0)
    assert black.sum() > 200                            # ink survived
    ink_rows = out[50:62, 60:240]
    assert (ink_rows == 0).mean() > 0.25                # glyphs kept
    band_bg = out[0:30, 0:300]                          # shaded background
    assert (band_bg == 255).mean() > 0.95               # shading dropped


def test_binarize_local_recovers_faint_digits_on_shading():
    """Faint digits (gray 150) on a shaded band (185): the fixed threshold
    128 erases them entirely (150 > 128 → white) while the LOCAL variant
    keeps them crisp — its window mean sits at the band level."""
    arr = np.full((100, 200), 185, dtype=np.uint8)
    arr[30:50, 30:170] = 150                            # faint digits
    img = Image.fromarray(arr, mode="L")

    fixed = np.asarray(img.point(lambda p: 255 if p > 128 else 0))
    assert (fixed == 0).sum() == 0                      # fixed 128: erased

    out = np.asarray(binarize_local(img), dtype=np.uint8)
    assert (out == 0).sum() > 300                       # local: recovered
    assert (out[0:20, 0:200] == 255).mean() > 0.9       # background white


# ------------------------------------------------------ adaptive contrast ----

def test_adaptive_contrast_stretches_only_faded_pages():
    arr = np.full((80, 200), 228, dtype=np.uint8)
    arr[30:44, 40:160] = 212                            # faint «text»
    faded = Image.fromarray(arr, mode="L")
    out, stretched = adaptive_contrast(faded)
    assert stretched is True
    out_arr = np.asarray(out, dtype=np.uint8)
    assert np.percentile(out_arr, 1) < 120              # ink pulled down

    healthy_arr = np.full((80, 200), 255, dtype=np.uint8)
    healthy_arr[30:44, 40:160] = 0                      # real black text
    healthy = Image.fromarray(healthy_arr, mode="L")
    out2, stretched2 = adaptive_contrast(healthy)
    assert stretched2 is False and out2 is healthy      # untouched


# ------------------------------------------------- image-path integration ----

@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_tilted_image_still_reads_with_preprocessed_candidate(tmp_path):
    """A 2° camera-tilt photo of a statement: the preprocessed (deskewed)
    attempt competes beside the original and the referee keeps whichever
    reads — the tilted scan must still yield the cost row («تكلفة
    الإيراد» → 180,000), never regress to empty."""
    from app.parsers.image_parser import parse_image

    png = tmp_path / "tb.png"
    _render_tb_png(png)
    img = Image.open(str(png))
    tilted = tmp_path / "tb_tilted.png"
    img.rotate(2.0, resample=Image.BICUBIC, fillcolor=(255, 255, 255)
               ).save(str(tilted))

    out = parse_image(tilted)
    assert out["ocr_used"] is True
    assert out.get("preprocess"), "preprocess meta missing"
    all_cells = [c for t in out["tables"] for r in t["rows"] for c in r]
    joined = " ".join(str(c) for c in all_cells)
    assert "180000" in joined.replace(",", "").replace("O", "0") or \
        "180,000" in joined, f"cost row lost: {joined[:200]}"


@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_level_image_read_unchanged(tmp_path):
    """A clean level page: preprocessing finds nothing to fix (deskew gate
    closed) and the read quality matches the proven path — no regression
    from replacement (the referee keeps the strongest candidate)."""
    from app.parsers.image_parser import parse_image
    from app.parsers.quality import STRONG_SCORE

    png = tmp_path / "tb.png"
    _render_tb_png(png)
    out = parse_image(png)
    assert out["ocr_used"] is True
    assert out["quality"]["score"] >= STRONG_SCORE
    assert out["quality"]["spine"] is True


# --------------------------------------------------- pdf-path integration ----

def _image_only_pdf(path, page_img: Image.Image) -> None:
    import pymupdf

    buf = io.BytesIO()
    page_img.save(buf, format="PNG")
    scan = pymupdf.open()
    sp = scan.new_page(width=595, height=842)
    sp.insert_image(sp.rect, stream=buf.getvalue())
    scan.save(str(path))
    scan.close()


@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_tilted_scanned_pdf_reads_cost_rows(tmp_path):
    """THE user-facing regression: a scanner PDF whose page is tilted 2°
    (deskewed by the render path) still reads the cost row 180,000 and the
    revenue 350,000 — the vote never tears the tilted rows apart."""
    from app.parsers import parse_file

    png = tmp_path / "tb.png"
    _render_tb_png(png)
    img = Image.open(str(png))
    _image_only_pdf(tmp_path / "tilted_scan.pdf",
                    img.rotate(2.0, resample=Image.BICUBIC,
                               fillcolor=(255, 255, 255)))

    out = parse_file(tmp_path / "tilted_scan.pdf")
    assert out["ocr_used"] is True
    all_cells = [c for t in out["tables"] for r in t["rows"] for c in r]
    flat = " ".join(str(c) for c in all_cells).replace(",", "").replace("O", "0")
    assert "350000" in flat, f"revenue lost: {flat[:200]}"
    assert "180000" in flat, f"cost row lost: {flat[:200]}"


@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_local_binarization_variant_joins_band_vote(tmp_path, monkeypatch):
    """The band variants now include a LOCAL binarization read beside the
    fixed thresholds — one more candidate per band in the vote."""
    import app.parsers.pdf_parser as pp

    png = tmp_path / "tb.png"
    _render_tb_png(png)
    _image_only_pdf(tmp_path / "scan.pdf", Image.open(str(png)))

    calls = {"n": 0}
    real = pp.binarize_local

    def spy(img):
        calls["n"] += 1
        return real(img)

    monkeypatch.setattr(pp, "binarize_local", spy)
    out = pp.parse_pdf(tmp_path / "scan.pdf")
    assert out["ocr_used"] is True
    assert calls["n"] >= 1, "local-binarization band variant never ran"
    all_cells = [c for t in out["tables"] for r in t["rows"] for c in r]
    flat = " ".join(str(c) for c in all_cells).replace(",", "")
    assert "350000" in flat
