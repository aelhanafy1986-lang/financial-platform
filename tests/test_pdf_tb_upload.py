# -*- coding: utf-8 -*-
"""PDF uploads carrying a trial balance MUST be read like any Excel file.

Root cause that was fixed (and must never regress): Arabic PDF writers
store Arabic as GLYPHS — presentation forms (U+FB50–U+FEFF) in visual
order — so pdfplumber extracted «الحساب» as ``'ﺏﺎﺴﺤﻟﺍ'``; every classifier
searches for logical Arabic → zero metrics → the quality gate rejected
the upload with 422. The parser now restores logical Arabic (bidi-reverse
FIRST, then NFKC — the ligature must stay one codepoint while reordering)
and statements attachment is no longer Excel-only.

Also covered:
- a BALANCED trial balance in a PDF is auto-attached (has_statements),
- an UNBALANCED one is honestly refused (no fake statements),
- a scanned (no text layer) PDF gets a clear «ممسوح ضوئيًا» hint,
- logical Arabic / English / digits pass through the restorer untouched,
- the fix is inside parse_pdf, so every consumer (analyze, comparison)
  benefits.
"""

import io
from pathlib import Path

import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient

from app.parsers.pdf_parser import (_normalize_digits,
                                    _ocr_grid_from_variants,
                                    _restore_visual_arabic, parse_pdf)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"

BALANCED_TB = [
    ["الحساب", "مدين", "دائن"],
    ["النقدية بالبنك", 685_000, 0],
    ["مدينون - العملاء", 110_000, 0],
    ["مخزون", 125_000, 0],
    ["الدائنون - الموردون", 0, 80_000],
    ["قروض طويلة الأجل", 0, 255_000],
    ["رأس المال", 0, 400_000],
    ["ايرادات المبيعات", 0, 650_000],
    ["تكلفة المبيعات", 380_000, 0],
    ["مصاريف رواتب", 85_000, 0],
]


# ------------------------------------------------------- text restorer ----

def test_restore_reversed_presentation_forms():
    import unicodedata

    assert _restore_visual_arabic("ﺏﺎﺴﺤﻟﺍ") == "الحساب"
    assert _restore_visual_arabic("ﻙﻮﻨﺒﻟﺍﻭ ﻕﻭﺪﻨﺼﻟﺎﺑ ﺔﻳﺪﻘﻨﻟﺍ") == \
        "النقدية بالصندوق والبنوك"


def test_restore_roundtrip_through_platform_renderer():
    """logical --(reshape+display)--> visual --(restore)--> logical."""
    import unicodedata

    import arabic_reshaper
    from bidi.algorithm import get_display

    for phrase in ("تكلفة المبيعات", "الإجمالي", "ايرادات المبيعات 650,000",
                   "الدائنون - الموردون"):
        visual = get_display(arabic_reshaper.reshape(phrase))
        assert _restore_visual_arabic(visual) == phrase, phrase


def test_restore_is_identity_on_logical_text():
    assert _restore_visual_arabic("ميزان المراجعة") == "ميزان المراجعة"
    assert _restore_visual_arabic("Revenue 2024") == "Revenue 2024"
    assert _restore_visual_arabic("380,000") == "380,000"
    assert _restore_visual_arabic("") == ""


def test_pdf_parser_restores_and_extracts(tmp_path):
    """End-to-end on a REAL rendered Arabic PDF (reportlab, same technique
    the platform's own reports use): the extracted rows are logical Arabic
    and the numbers survive."""
    report = pytest.importorskip("reportlab")
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    from pathlib import Path

    font_path = next(
        Path(p) for p in ("C:/Windows/Fonts/majalla.ttf",
                          "C:/Windows/Fonts/tahoma.ttf",
                          "C:/Windows/Fonts/arial.ttf")
        if Path(p).exists()
    )
    pdfmetrics.registerFont(TTFont("ArF", str(font_path)))

    def ar(t: str) -> str:
        return get_display(arabic_reshaper.reshape(t))

    rows = [[str(v) if not isinstance(v, int) else f"{v:,}"
             for v in r] for r in BALANCED_TB]
    out = tmp_path / "tb.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    st = ParagraphStyle("ar", fontName="ArF", fontSize=11, alignment=2)
    data = [[Paragraph(ar(c), st) for c in r] for r in rows]
    t = Table(data, colWidths=[8 * cm, 3 * cm, 3 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.grey)]))
    doc.build([Paragraph(ar("ميزان المراجعة"), st), Spacer(1, 0.4 * cm), t])

    parsed = parse_pdf(out)
    assert parsed["tables"], "no table extracted from the PDF"
    flat = [c for r in parsed["tables"][0]["rows"] for c in r]
    assert "الحساب" in flat and "مدين" in flat and "دائن" in flat
    assert any("685,000" in c for c in flat)
    assert not any("ﺏﺎﺴﺤﻟﺍ" in c for c in flat)


# ------------------------------------------------------------ upload ----

def _make_tb_pdf() -> bytes:
    """Balanced Arabic TB PDF via the platform's own rendering stack."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    from pathlib import Path
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    pytest.importorskip("reportlab")
    font_path = next(
        Path(p) for p in ("C:/Windows/Fonts/majalla.ttf",
                          "C:/Windows/Fonts/tahoma.ttf",
                          "C:/Windows/Fonts/arial.ttf")
        if Path(p).exists()
    )
    pdfmetrics.registerFont(TTFont("ArF", str(font_path)))

    def ar(t: str) -> str:
        return get_display(arabic_reshaper.reshape(t))

    rows = [[str(v) if not isinstance(v, int) else f"{v:,}"
             for v in r] for r in BALANCED_TB]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    st = ParagraphStyle("ar", fontName="ArF", fontSize=11, alignment=2)
    data = [[Paragraph(ar(c), st) for c in r] for r in rows]
    t = Table(data, colWidths=[8 * cm, 3 * cm, 3 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.grey)]))
    doc.build([Paragraph(ar("ميزان المراجعة"), st), Spacer(1, 0.4 * cm), t])
    return buf.getvalue()


def _make_scanned_pdf() -> bytes:
    """A PDF with NO text layer (empty pages) — the scanned-file case."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pytest.importorskip("reportlab")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.showPage()          # an image-only page: no text operators at all
    c.save()
    return buf.getvalue()


def test_pdf_trial_balance_upload_full_pipeline(client):
    """THE regression: an Arabic trial-balance PDF is read, analysed,
    AND its statements are auto-attached (has_statements=True)."""
    resp = client.post(
        "/api/upload",
        files={"files": ("ميزان.pdf", io.BytesIO(_make_tb_pdf()), PDF_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item, item
    res = item["result"]
    # the TB-driven metrics (debit-side names were classified)
    assert res["metrics"].get("revenue") == [650_000.0]
    assert res["metrics"].get("cogs") == [380_000.0]
    assert item["has_statements"] is True, "statements not attached from PDF"
    aid = item["id"]

    # the statements sheet exists in the Excel export of that PDF analysis
    export = client.get(f"/api/analyses/{aid}/export?lang=ar",
                        headers=client.auth_headers)
    assert export.status_code == 200
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(export.content))
    assert any("القوائم" in n for n in wb.sheetnames)
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_pdf_unbalanced_tb_not_attached(client):
    """An UNBALANCED trial balance: analysis may proceed, but statements
    are never attached — honesty over convenience."""
    rows = [r[:] for r in BALANCED_TB]
    rows[6][2] = 500_000        # رأس المال 400k → 500k: unbalanced
    import unicodedata
    import arabic_reshaper
    from bidi.algorithm import get_display
    from pathlib import Path
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    pytest.importorskip("reportlab")
    font_path = next(
        Path(p) for p in ("C:/Windows/Fonts/majalla.ttf",
                          "C:/Windows/Fonts/tahoma.ttf",
                          "C:/Windows/Fonts/arial.ttf")
        if Path(p).exists()
    )
    pdfmetrics.registerFont(TTFont("ArF", str(font_path)))

    def ar(t: str) -> str:
        return get_display(arabic_reshaper.reshape(t))

    text_rows = [[str(v) if not isinstance(v, int) else f"{v:,}"
                  for v in r] for r in rows]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    st = ParagraphStyle("ar", fontName="ArF", fontSize=11, alignment=2)
    data = [[Paragraph(ar(c), st) for c in r] for r in text_rows]
    t = Table(data, colWidths=[8 * cm, 3 * cm, 3 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.grey)]))
    doc.build([Paragraph(ar("ميزان المراجعة"), st), Spacer(1, 0.4 * cm), t])

    resp = client.post(
        "/api/upload",
        files={"files": ("ميزان_غير_متوازن.pdf", io.BytesIO(buf.getvalue()),
                          PDF_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    if "error" in item:
        return  # gate refused the whole upload: also honest
    assert item["has_statements"] is False
    aid = item["id"]
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


# ------------------------------------------------------------ OCR engine ----

def test_ocr_normalize_digits():
    """Arabic-Indic / Persian digits (emitted by Windows OCR ar-SA for some
    documents) become Latin digits the row parsers can read."""
    assert _normalize_digits("٤٥٠٠٠") == "45000"
    assert _normalize_digits("١٢٣/٤") == "123/4"
    assert _normalize_digits("150,000") == "150,000"
    assert _normalize_digits("الحساب ٠١٢") == "الحساب 012"


def _cell(x, txt, y=150.0, w=60.0):
    return [(x, y, w, 24.0, txt, 0)]


def test_ocr_rows_rtl_trial_balance_shape():
    """OCR word boxes of an RTL Arabic trial balance (label column on the
    right, مدين then دائن to the left) produce [label, debit, credit] rows:
    the debit amount lands in slot 1, the credit amount in slot 2 — even
    though each row carries only ONE of them (the empty slot is emitted so
    the positional reader never mistakes a credit for a debit).

    The cells come pre-split (the variant assembler's gutter rule needs a
    realistic multi-gap row); the contract under test is the slot/direction
    assembly in _ocr_grid_from_variants."""
    # physical RTL layout: الحساب x≈520, مدين x≈370, دائن x≈220
    variant_rows = [
        [_cell(520, "الحساب", 100), _cell(370, "مدين", 100), _cell(220, "دائن", 100)],
        [_cell(520, "النقدية", 150), _cell(370, "150,000", 150)],
        [_cell(520, "الموردون", 200), _cell(220, "45,000", 200)],
        [_cell(520, "الايرادات", 250), _cell(220, "350,000", 250)],
        [_cell(520, "المصاريف", 300), _cell(370, "50,000", 300)],
    ]
    rows = _ocr_grid_from_variants(variant_rows)
    by_label = {r[0]: r[1:] for r in rows}
    # empty slots read as explicit «0» (the accounting-export artefact the
    # row parsers already understand); amounts come out as healed digit runs
    assert by_label["النقدية"] == ["150000", "0"]
    assert by_label["الموردون"] == ["0", "45000"]
    assert by_label["الايرادات"] == ["0", "350000"]
    assert by_label["المصاريف"] == ["50000", "0"]


def test_ocr_rows_ltr_table_shape():
    """An LTR export (label left, amounts right) keeps [label, debit,
    credit] order — the direction comes from where the numbers sit, not
    from Arabic presence."""
    variant_rows = [
        [_cell(100, "Account", 100), _cell(300, "Debit", 100), _cell(500, "Credit", 100)],
        [_cell(100, "Cash", 150), _cell(300, "1,200", 150)],
        [_cell(100, "Payables", 200), _cell(500, "900", 200)],
    ]
    rows = _ocr_grid_from_variants(variant_rows)
    by_label = {r[0]: r[1:] for r in rows}
    assert by_label["Cash"] == ["1200", "0"]
    assert by_label["Payables"] == ["0", "900"]


def _ocr_engine_available() -> bool:
    try:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
    except Exception:
        return False
    return OcrEngine.try_create_from_language(Language("ar-SA")) is not None


def _make_image_only_tb_pdf(path) -> None:
    """Render an Arabic trial balance, then embed ONLY the page image in a
    fresh PDF — no text layer at all, exactly like a scanner output."""
    import pymupdf

    rows = [
        ["الحساب", "مدين", "دائن"],
        ["النقدية وما في حكمها", "150,000", ""],
        ["العملاء", "80,000", ""],
        ["المخزون", "40,000", ""],
        ["الأصول الثابتة", "120,000", ""],
        ["الموردون", "", "45,000"],
        ["رأس المال", "", "200,000"],
        ["الأرباح المبقاة", "", "25,000"],
        ["الايرادات", "", "350,000"],
        ["تكلفة الإيراد", "180,000", ""],
        ["المصاريف التشغيلية", "50,000", ""],
    ]
    html_rows = []
    for r in rows:
        tds = "".join(
            f"<td style='padding:6px 18px; text-align:right;'>{c}</td>"
            for c in r
        )
        html_rows.append(f"<tr>{tds}</tr>")
    html = "<table style='font-size:13px;'>" + "".join(html_rows) + "</table>"
    font_path = next(
        Path(p) for p in ("C:/Windows/Fonts/arial.ttf",
                          "C:/Windows/Fonts/tahoma.ttf")
        if Path(p).exists()
    )
    css = (f"@font-face {{font-family: ar; src: url({font_path.name});}}"
           "* {font-family: ar;}")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(pymupdf.Rect(40, 60, 555, 700), html, css=css,
                        archive=pymupdf.Archive(str(font_path.parent)))
    pix = page.get_pixmap(dpi=200)
    scan = pymupdf.open()
    sp = scan.new_page(width=595, height=842)
    sp.insert_image(sp.rect, pixmap=pix)
    scan.save(str(path))
    scan.close()
    doc.close()


@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_scanned_trial_balance_read_via_ocr(client, tmp_path):
    """THE user-facing regression: a scanner-style PDF (image only, no text
    layer) carrying a balanced Arabic trial balance is READ via OCR, passes
    the quality gate, and its statements are attached — no more «ممسوح»
    rejection."""
    pdf_path = tmp_path / "scanned_tb.pdf"
    _make_image_only_tb_pdf(pdf_path)
    data = pdf_path.read_bytes()
    # sanity: really image-only
    import pymupdf
    doc = pymupdf.open(stream=data)
    assert sum(len(pg.get_text("words")) for pg in doc) == 0
    doc.close()

    resp = client.post(
        "/api/upload",
        files={"files": ("قوائم_ممسوحة.pdf", io.BytesIO(data), PDF_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item, item
    res = item["result"]
    metrics = res.get("metrics") or {}
    assert metrics.get("revenue") == [350_000.0]
    assert item["has_statements"] is True
    client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)


def test_scanned_pdf_gets_clear_hint(client):
    """A scanned (image-only) PDF: refused, but the message says WHY and
    what to do — no more generic «لم يُستخرج أي مؤشر»."""
    resp = client.post(
        "/api/upload",
        files={"files": ("ممسوح.pdf", io.BytesIO(_make_scanned_pdf()),
                          PDF_MIME)},
        headers=client.auth_headers,
    )
    # one rejected file = whole batch fails with 400 carrying the message;
    # with siblings it comes back as a per-file error (documented shapes)
    if resp.status_code == 400:
        assert "ممسوحًا ضوئيًا" in resp.json()["detail"]
        return
    item = resp.json()["uploaded"][0]
    assert "error" in item
    assert "ممسوحًا ضوئيًا" in item["error"]


def test_excel_path_unaffected(client):
    """The Excel trial-balance flow keeps working (attach + statements)."""
    wb = Workbook()
    ws = wb.active
    for r in BALANCED_TB:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post("/api/upload",
                       files={"files": ("tb.xlsx", buf, XLSX_MIME)},
                       headers=client.auth_headers)
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item
    assert item["has_statements"] is True
    client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)


# ---------------------------------------------- OCR root-cause guards ----

def test_ocr_prose_rows_not_padded_with_fake_zeros():
    """ROOT CAUSE 1 (the المراعي-class scan failures): a date/banner line
    among money rows («31 ديسمبر 2023») used to be padded with fabricated
    «0» amount cells — the row parsers then read it as a zero-balance
    ACCOUNT, flooding the classifier with phantom rows until no numeric
    signal survived. A row that read NO amount keeps its slots EMPTY;
    only a money row pads its unread side with the explicit-zero
    accounting convention."""
    variant_rows = [
        [_cell(520, "الحساب", 100), _cell(370, "مدين", 100), _cell(220, "دائن", 100)],
        [_cell(520, "النقدية", 150), _cell(370, "150,000", 150)],
        [_cell(520, "الموردون", 200), _cell(220, "45,000", 200)],
        [_cell(520, "الايرادات", 250), _cell(220, "350,000", 250)],
        # the date line that used to become a zero-balance account:
        [_cell(520, "31", 300), _cell(430, "ديسمبر", 300), _cell(280, "2023م", 300)],
        [_cell(520, "المصاريف", 350), _cell(370, "50,000", 350)],
    ]
    rows = _ocr_grid_from_variants(variant_rows)
    date_row = next(r for r in rows if "ديسمبر" in r[0])
    assert "0" not in date_row[1:], date_row
    # money rows KEEP the explicit-zero convention the parsers expect
    by_label = {r[0]: r[1:] for r in rows}
    assert by_label["النقدية"] == ["150000", "0"]
    assert by_label["المصاريف"] == ["50000", "0"]


def _render_tb_png(path) -> None:
    """Render the balanced Arabic trial balance to a PNG — a phone
    photo/screenshot equivalent: pixels only, no text layer anywhere."""
    import pymupdf

    rows = [
        ["الحساب", "مدين", "دائن"],
        ["النقدية وما في حكمها", "150,000", ""],
        ["العملاء", "80,000", ""],
        ["المخزون", "40,000", ""],
        ["الأصول الثابتة", "120,000", ""],
        ["الموردون", "", "45,000"],
        ["رأس المال", "", "200,000"],
        ["الأرباح المبقاة", "", "25,000"],
        ["الايرادات", "", "350,000"],
        ["تكلفة الإيراد", "180,000", ""],
        ["المصاريف التشغيلية", "50,000", ""],
    ]
    html_rows = []
    for r in rows:
        tds = "".join(
            f"<td style='padding:6px 18px; text-align:right;'>{c}</td>"
            for c in r
        )
        html_rows.append(f"<tr>{tds}</tr>")
    html = "<table style='font-size:13px;'>" + "".join(html_rows) + "</table>"
    font_path = next(
        Path(p) for p in ("C:/Windows/Fonts/arial.ttf",
                          "C:/Windows/Fonts/tahoma.ttf")
        if Path(p).exists()
    )
    css = (f"@font-face {{font-family: ar; src: url({font_path.name});}}"
           "* {font-family: ar;}")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(pymupdf.Rect(40, 60, 555, 700), html, css=css,
                        archive=pymupdf.Archive(str(font_path.parent)))
    page.get_pixmap(dpi=200).save(str(path))
    doc.close()


@pytest.mark.skipif(not _ocr_engine_available(),
                    reason="Windows OCR (winsdk, ar-SA) not available")
def test_image_upload_read_via_ocr(client, tmp_path):
    """ROOT CAUSE 2 (the client flow): photos/screenshots of statements
    (.png/.jpg) were refused with «unsupported file type» — now the image
    itself is OCR'd through the same Windows pipeline as scanned PDFs and
    becomes a full analysis with attached statements."""
    png_path = tmp_path / "statement.png"
    _render_tb_png(png_path)
    resp = client.post(
        "/api/upload",
        files={"files": ("صورة_قائمة.png", png_path.read_bytes(), "image/png")},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item, item  # NOT «unsupported file type" anymore
    metrics = (item.get("result") or {}).get("metrics") or {}
    assert metrics.get("revenue") == [350_000.0]
    assert item["has_statements"] is True
    client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)
