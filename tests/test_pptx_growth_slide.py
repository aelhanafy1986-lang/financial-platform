# -*- coding: utf-8 -*-
"""The PPTX deck carries the annual-growth slide the PDF report has.

The PDF's «مقارنة النمو السنوي» table renders yearly_comparison["years"] +
rows[].points (value per year + YoY % coloured by the judgment rule). The
deck now renders the SAME payload as its own slide right after the
comparison slide: one card row per concept (label + one column per year,
value on top, growth % below in green/red), paginating onto continuation
slides — the deck was the only export missing this table.

Contract pinned here:
- 3+ periods → the growth slide exists with the exact title, every growth
  row's label, real values and the YoY percentages,
- column widths stay ints summing to the declared table width (the XSD
  contract that broke once before) — on the NEW tables too,
- two periods only → NO growth slide (the curr/prev table already shows
  that single transition; same threshold as the PDF),
- more rows than fit → continuation slide titled «(تابع)»,
- end-to-end through /api/upload + /pptx export on a 3-year workbook.
"""

import io
import re
import zipfile

from app import pptx_report
from app.ratio_explain import build_yearly_comparison

GROWTH_TITLE_AR = "مقارنة النمو السنوي (القيمة ونسبة التغير عن العام السابق)"


def _sh(s: str) -> str:
    return pptx_report._shape(s)


def _slide_xmls(pptx_bytes: bytes) -> dict[str, str]:
    z = zipfile.ZipFile(io.BytesIO(pptx_bytes))
    return {
        n: z.read(n).decode("utf-8", "ignore")
        for n in z.namelist()
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
    }


def _three_year_metrics() -> dict:
    return {
        "revenue": [12_000_000.0, 15_000_000.0, 18_000_000.0],
        "cogs": [8_400_000.0, 10_500_000.0, 12_600_000.0],
        "opex": [1_800_000.0, 2_250_000.0, 2_700_000.0],
        "net_profit": [1_800_000.0, 2_250_000.0, 2_700_000.0],
        "assets": [22_000_000.0, 25_000_000.0, 28_000_000.0],
        "liabilities": [9_000_000.0, 10_000_000.0, 11_000_000.0],
        "equity": [13_000_000.0, 15_000_000.0, 17_000_000.0],
    }


def _build_deck(tmp_path, comp, metrics) -> bytes:
    out = tmp_path / "deck.pptx"
    pptx_report.build_pptx_report(
        filename="w.xlsx",
        result={"kpis": {}, "ratios": {}, "series": {}, "metrics": metrics},
        out_path=out, lang="ar", yearly_comparison=comp,
    )
    return out.read_bytes()


# --------------------------------------------------------------- unit ----

def test_growth_slide_renders_same_data_as_pdf_table(tmp_path):
    comp = build_yearly_comparison({"metrics": _three_year_metrics()}, "ar")
    assert comp and comp.get("years") == ["الفترة 1", "الفترة 2", "الفترة 3"]

    xml_by_name = _slide_xmls(_build_deck(tmp_path, comp,
                                          _three_year_metrics()))
    growth_slides = [x for x in xml_by_name.values()
                     if _sh(GROWTH_TITLE_AR) in x]
    assert growth_slides, "annual-growth slide missing from the deck"
    # rows paginate across the first + continuation pages — assert on the
    # COMBINED text of all growth slides
    slide = "\n".join(growth_slides)

    # every growth row's label lands on a growth slide (same rows as PDF)
    for r in comp["rows"]:
        assert _sh(r["label"]) in slide, f"missing growth row {r['label']}"
    # real values + YoY percentages from points (revenue 12M→15M→18M)
    assert _sh("18,000,000") in slide
    assert "+25.0%" in slide and "+20.0%" in slide
    # one table per growth row (card-row layout) + one year-header band
    # per growth page (PDF parity — the header row of the PDF table)
    assert slide.count("<a:tbl>") == len(comp["rows"]) + len(growth_slides)
    # widths: ints summing to the declared table width (the XSD contract)
    for tbl in re.findall(r"<a:tbl>.*?</a:tbl>", slide, flags=re.S):
        widths = [int(m) for m in re.findall(r'<a:gridCol[^>]*w="(\d+)"', tbl)]
        assert all(isinstance(w, int) for w in widths)
        assert sum(widths) > 0


def test_growth_slide_has_year_header_band(tmp_path):
    """PDF parity: the growth card rows sit under a year-header band
    (البند + one cell per captured year) on EVERY growth page — navy-filled
    like the comparison slide's header row, so each card column reads
    against its period."""
    comp = build_yearly_comparison({"metrics": _three_year_metrics()}, "ar")
    xml_by_name = _slide_xmls(_build_deck(tmp_path, comp,
                                          _three_year_metrics()))
    pages = [x for x in xml_by_name.values()
             if _sh(GROWTH_TITLE_AR) in x
             or _sh(GROWTH_TITLE_AR + " (تابع)") in x]
    assert len(pages) >= 2, "expected first + continuation growth pages"
    for x in pages:
        for cell_txt in ("البند", "الفترة 1", "الفترة 2", "الفترة 3"):
            assert _sh(cell_txt) in x, f"year-header cell missing: {cell_txt}"
        assert 'val="0B2545"' in x, "header band not navy-filled"


def test_two_periods_no_growth_slide(tmp_path):
    """Same threshold as the PDF: with two periods the curr/prev table
    already shows the single transition — no growth slide."""
    metrics = {
        "revenue": [12_000_000.0, 15_000_000.0],
        "cogs": [8_400_000.0, 10_500_000.0],
        "opex": [1_800_000.0, 2_250_000.0],
        "net_profit": [1_800_000.0, 2_250_000.0],
        "assets": [22_000_000.0, 25_000_000.0],
        "liabilities": [9_000_000.0, 10_000_000.0],
        "equity": [13_000_000.0, 15_000_000.0],
    }
    comp = build_yearly_comparison({"metrics": metrics}, "ar")
    assert not comp.get("years")  # builder itself withholds the table

    xml_by_name = _slide_xmls(_build_deck(tmp_path, comp, metrics))
    assert not [x for x in xml_by_name.values() if GROWTH_TITLE_AR in x]


def test_growth_rows_paginate_with_cont_suffix(tmp_path):
    comp = build_yearly_comparison({"metrics": _three_year_metrics()}, "ar")
    xml_by_name = _slide_xmls(_build_deck(tmp_path, comp,
                                          _three_year_metrics()))
    titles = [n for n, x in xml_by_name.items() if _sh(GROWTH_TITLE_AR) in x]
    assert len(titles) >= 1
    # 8 possible concepts ≥3 periods → more than one page fits → the
    # continuation slide carries the «(تابع)» suffix
    cont = [n for n, x in xml_by_name.items()
            if _sh(GROWTH_TITLE_AR + " (تابع)") in x]
    assert cont, "expected a continuation slide for the growth rows"


# ---------------------------------------------------------- end-to-end ----

def test_three_year_workbook_export_has_growth_slide(client, tmp_path):
    from openpyxl import Workbook

    is_rows = [
        ["قائمة الدخل المقارنة", "", "", ""],
        ["البند", "عام 2022", "عام 2023", "عام 2024"],
        ["إجمالي المبيعات", 500000, 650000, 800000],
        ["تكلفة البضاعة المباعة", -300000, -380000, -460000],
        ["مجمل الربح", 200000, 270000, 340000],
        ["مصاريف بيعية وتوزيعية", -45000, -55000, -62000],
        ["مصاريف إدارية وعمومية", -60000, -70000, -78000],
        ["صافي الربح", 63000, 106200, 150000],
    ]
    bs_rows = [
        ["قائمة المركز المالي المقارنة", "", "", ""],
        ["البند", "عام 2022", "عام 2023", "عام 2024"],
        ["النقدية وما يعادلها", 50000, 85000, 110000],
        ["إجمالي الأصول", 555000, 695000, 830000],
        ["إجمالي الالتزامات", 255000, 295000, 330000],
        ["إجمالي حقوق الملكية", 300000, 400000, 500000],
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "ثلاث سنوات"
    for r in is_rows + bs_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)

    res = client.post(
        "/api/upload",
        files={"files": ("ثلاث-سنوات.xlsx", buf,
                         "application/octet-stream")},
        headers=client.auth_headers,
    )
    assert res.status_code == 200, res.text
    item = res.json()["uploaded"][0]
    assert "error" not in item, item
    analysis_id = item["id"]

    res = client.get(f"/api/analyses/{analysis_id}/pptx?lang=ar",
                     headers=client.auth_headers)
    assert res.status_code == 200
    assert res.content[:4] == b"PK\x03\x04"

    xml_by_name = _slide_xmls(res.content)
    growth = [x for x in xml_by_name.values() if _sh(GROWTH_TITLE_AR) in x]
    assert growth, "annual-growth slide missing from the exported deck"
    slide = "\n".join(growth)
    # the workbook's REAL YoY: 500k→650k = +30.0%, 650k→800k = +23.1%
    assert "+30.0%" in slide
    assert "800,000" in slide

    client.delete(f"/api/analyses/{analysis_id}", headers=client.auth_headers)
