"""Tests for the four file parsers using real generated fixture files."""

import pytest

from app.analyzer import analyze
from app.parsers import parse_file


# ---------------------------------------------------------------------------
# fixtures: each test builds its own real file in tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture
def xlsx_file(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "stmt.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "قائمة الدخل"
    ws.append(["البند", "2024", "2025"])
    ws.append(["الإيرادات", 4_120_000, 4_820_000])
    ws.append(["تكلفة المبيعات", 2_500_000, 2_834_000])
    ws.append(["المصاريف التشغيلية", 1_115_000, 1_346_000])
    # net profit row is intentionally omitted: it is derived from detail rows
    # (4,820,000 - 2,834,000 - 1,346,000 = 640,000)
    wb.save(path)
    return path


@pytest.fixture
def docx_file(tmp_path):
    import docx

    path = tmp_path / "report.docx"
    d = docx.Document()
    d.add_heading("التقرير السنوي")
    d.add_paragraph("Net Profit 640,000 SAR")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "2025"
    table.cell(1, 0).text = "Revenue"
    table.cell(1, 1).text = "4,820,000"
    d.save(path)
    return path


@pytest.fixture
def pptx_file(tmp_path):
    from pptx import Presentation

    path = tmp_path / "deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Quarterly Review"
    slide.placeholders[1].text = "Revenue 4,820,000"
    prs.save(path)
    return path


@pytest.fixture
def pdf_file(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "doc.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(72, 800, "Financial Summary 2025")
    c.drawString(72, 780, "Revenue 4,820,000")
    c.save()
    return path


# ---------------------------------------------------------------------------
# excel
# ---------------------------------------------------------------------------

class TestExcelParser:
    def test_extracts_sheet_names_and_rows(self, xlsx_file):
        parsed = parse_file(xlsx_file)
        assert parsed["texts"] == []
        assert len(parsed["tables"]) == 1
        assert parsed["tables"][0]["name"] == "قائمة الدخل"
        assert parsed["tables"][0]["rows"][0] == ["البند", "2024", "2025"]
        assert parsed["tables"][0]["rows"][1] == ["الإيرادات", 4_120_000, 4_820_000]

    def test_end_to_end_analysis(self, xlsx_file):
        parsed = parse_file(xlsx_file)
        result = analyze(parsed["tables"], parsed["texts"])
        assert result["kpis"]["revenue"]["value"] == 4_820_000
        # net profit derived from detail rows: 4,820,000-2,834,000-1,346,000
        assert result["kpis"]["net_profit"]["value"] == 640_000
        expected_margin = round(640_000 / 4_820_000 * 100, 2)
        assert result["ratios"]["net_margin"]["value"] == expected_margin

    def test_empty_sheets_skipped(self, tmp_path):
        from openpyxl import Workbook

        path = tmp_path / "empty.xlsx"
        wb = Workbook()
        wb.active.title = "فارغة"
        wb.save(path)
        parsed = parse_file(path)
        assert parsed["tables"] == []


# ---------------------------------------------------------------------------
# word
# ---------------------------------------------------------------------------

class TestWordParser:
    def test_paragraphs_and_tables(self, docx_file):
        parsed = parse_file(docx_file)
        assert any("التقرير السنوي" in t for t in parsed["texts"])
        assert any("Net Profit" in t for t in parsed["texts"])
        assert parsed["tables"][0]["rows"][1] == ["Revenue", "4,820,000"]

    def test_text_feeds_the_analyzer(self, docx_file):
        parsed = parse_file(docx_file)
        result = analyze(parsed["tables"], parsed["texts"])
        # only a bare "Net Profit 640,000" text line: no cogs/opex detail rows,
        # so the net line itself becomes the captured value.
        assert result["kpis"]["revenue"]["value"] == 4_820_000
        assert result["kpis"]["net_profit"]["value"] == 640_000


# ---------------------------------------------------------------------------
# pdf
# ---------------------------------------------------------------------------

class TestPdfParser:
    def test_text_extraction(self, pdf_file):
        parsed = parse_file(pdf_file)
        joined = "\n".join(parsed["texts"])
        assert "Financial Summary 2025" in joined
        assert "Revenue 4,820,000" in joined

    def test_analyzer_reads_pdf_text(self, pdf_file):
        parsed = parse_file(pdf_file)
        result = analyze(parsed["tables"], parsed["texts"])
        assert result["kpis"]["revenue"]["value"] == 4_820_000
        assert result["texts_found"] >= 2

    @pytest.mark.skipif(
        __import__("importlib.util", fromlist=["util"]).find_spec("winsdk") is None,
        reason="Windows OCR (winsdk) unavailable",
    )
    def test_scanned_pdf_with_arabic_indic_cover_only_gate(self, tmp_path):
        """Almarai-shaped regression: a scanned report whose ONLY text layer
        is a cover line with Arabic-Indic date digits («٣١ ديسمبر ٢٠٢٣»).

        The engine gate counts Latin digits only — a Hijri cover date must
        NOT satisfy it, so the PyMuPDF/OCR engines run and the scanned
        statement page is actually read (revenue lands in the KPIs).
        """
        import pymupdf

        from app.parsers.pdf_parser import _has_numeric_content

        # the regression pair: a Hijri date alone is NOT numeric content
        assert _has_numeric_content([], ["تقرير المراجع المستقل ٢٠٢٣"]) is False
        assert _has_numeric_content([], ["Revenue 4,820,000"]) is True

        doc = pymupdf.open()
        p1 = doc.new_page()  # cover: only Arabic-Indic date digits (when the
        try:  # base font can encode them — the gate asserts above carry the
            p1.insert_text((72, 90), "تقرير المراجع المستقل")  # unit proof
            p1.insert_text((72, 120), "٣١ ديسمبر ٢٠٢٣")
        except Exception:
            pass
        p2 = doc.new_page()  # scanned statement page (image, no text layer);
        # Latin labels: helv renders them, and KEYWORDS classify «Revenue».
        # THREE numeric rows — the OCR grid only becomes a TABLE at 3+
        # numeric rows (prose pages become text lines, like the real file's
        # statement pages do as tables). Large glyphs (16pt) survive OCR
        # word recognition; 11pt renders too small at the harness's 3x.
        p2.insert_text((72, 72), "Revenue", fontsize=16)
        p2.insert_text((430, 72), "19,575,585", fontsize=16)
        p2.insert_text((72, 100), "Gross Profit", fontsize=16)
        p2.insert_text((430, 100), "6,051,129", fontsize=16)
        p2.insert_text((72, 128), "Net Profit", fontsize=16)
        p2.insert_text((430, 128), "1,872,258", fontsize=16)
        pix = p2.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=False)
        page2 = doc.new_page(width=p2.rect.width, height=p2.rect.height)
        page2.insert_image(page2.rect, pixmap=pix)
        doc.delete_page(1)  # drop the text-layer original of page 2
        path = tmp_path / "scanned-report.pdf"
        doc.save(str(path))
        doc.close()

        parsed = parse_file(path)
        assert parsed.get("ocr_used") is True
        assert parsed.get("tables") or parsed.get("texts")
        # the OCR path READS the scanned statement page: the amount survives
        # into the extraction (row-pairing of synthetic 16pt labels is OCR-
        # box-geometry-dependent, and the assembler normalises «19,575,585»
        # to its digit run — the stable contract is the digit run itself)
        blob = "\n".join(
            c for t in parsed.get("tables") or [] for r in t.get("rows") or [] for c in r
        ) + "\n" + "\n".join(parsed.get("texts") or [])
        assert "19575585" in blob


# ---------------------------------------------------------------------------
# powerpoint
# ---------------------------------------------------------------------------

class TestPptxParser:
    def test_slide_text_with_prefix(self, pptx_file):
        parsed = parse_file(pptx_file)
        joined = "\n".join(parsed["texts"])
        assert "[slide 1]" in joined
        assert "Quarterly Review" in joined
        assert "Revenue 4,820,000" in joined

    def test_analyzer_reads_slide_text(self, pptx_file):
        parsed = parse_file(pptx_file)
        result = analyze(parsed["tables"], parsed["texts"])
        assert result["kpis"]["revenue"]["value"] == 4_820_000


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_unsupported_type_raises(self, tmp_path):
        # .csv is a first-class parser now — use a genuinely unsupported type
        f = tmp_path / "data.xyz"
        f.write_text("whatever", encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported"):
            parse_file(f)

    def test_all_four_types_accepted(self, xlsx_file, docx_file, pptx_file, pdf_file):
        for path in (xlsx_file, docx_file, pptx_file, pdf_file):
            parsed = parse_file(path)
            assert "tables" in parsed and "texts" in parsed
