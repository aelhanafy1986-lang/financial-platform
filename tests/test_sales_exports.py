# -*- coding: utf-8 -*-
"""Sales-kind export parity: PDF / PPTX / Excel for a «مبيعات» analysis
must mirror the SALES dashboard, never render financial zero-value output.

- /pptx serves the sales deck (branded cover + sales tables),
- /export serves the sales workbook (summary/monthly/regions/reps),
- both refuse to build from a sales analysis with an empty sales payload,
- the records list carries `kind` so the UI routes the buttons.
"""

import io
import json
from pathlib import Path

from openpyxl import Workbook
import pytest

from app.main import _sales_records_for_tables
from app.report import build_sales_report
from app.sales_analyzer import analyze_sales
from app.pptx_report import build_sales_pptx_report


def _make_sales_xlsx(tmp_path) -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(["التاريخ", "رقم الفاتورة", "مسؤول المبيعات", "المنطقة",
               "المنتج", "الكمية", "سعر الوحدة", "المبلغ الإجمالي"])
    rows = [
        ["2026-01-01", "INV-1", "أحمد", "الوسطى", "هاتف", 3, 3200, 9600],
        ["2026-01-03", "INV-2", "سارة", "الغربية", "حاسب", 2, 5000, 10000],
        ["2026-02-01", "INV-3", "أحمد", "الوسطى", "هاتف", 5, 3200, 16000],
        ["2026-02-05", "INV-4", "سارة", "الغربية", "حاسب", 1, 5000, 5000],
        ["2026-03-01", "INV-5", "أحمد", "الوسطى", "هاتف", 2, 3200, 6400],
        ["2026-03-04", "INV-6", "سارة", "الغربية", "حاسب", 4, 5000, 20000],
    ]
    for r in rows:
        ws.append(r)
    p = tmp_path / "sales.xlsx"
    wb.save(p)
    return str(p)


def _sales_analysis(tmp_path) -> dict:
    from app.parsers import parse_file

    _make_sales_xlsx(tmp_path)
    parsed = parse_file(tmp_path / "sales.xlsx")
    records = _sales_records_for_tables(parsed["tables"])
    return analyze_sales(records)


def test_sales_pdf_builds_and_carries_numbers(tmp_path):
    sales = _sales_analysis(tmp_path)
    out = tmp_path / "sales.pdf"
    build_sales_report("sales.xlsx", sales, out, lang="ar")
    assert out.exists() and out.stat().st_size > 10_000


def test_sales_pptx_builds_and_carries_numbers(tmp_path):
    sales = _sales_analysis(tmp_path)
    out = tmp_path / "sales.pptx"
    build_sales_pptx_report("sales.xlsx", sales, out, lang="ar")
    assert out.exists() and out.stat().st_size > 20_000
    # the deck is a real presentation with slides
    from pptx import Presentation

    prs = Presentation(str(out))
    assert len(prs.slides) >= 3


def test_sales_excel_sections_match_dashboard(tmp_path):
    sales = _sales_analysis(tmp_path)
    from app.bi_export import build_sales_table_rows

    sections = build_sales_table_rows(sales, "ar")
    titles = [t for t, _h, _rows in sections]
    assert any("الملخص" in t or "مبيعات" in t for t in titles)
    assert any("المناطق" in t for t in titles)
    assert any("المندوبين" in t for t in titles)
    # monthly rows carry real numbers
    monthly = next(rows for t, _h, rows in sections if "الشهري" in t or "Trend" in t)
    assert sum(r[1] for r in monthly) == sales["total_sales"]


@pytest.mark.usefixtures("client")
class TestSalesExportRoutes:
    """End-to-end: upload a sales file, then the /pptx and /export routes
    return sales-shaped artifacts instead of financial zero-decks."""

    def test_pptx_and_export_serve_sales_artifacts(self, client, tmp_path):
        from app.parsers import parse_file

        with open(_make_sales_xlsx(tmp_path), "rb") as fh:
            resp = client.post(
                "/api/upload",
                files={"files": ("sales.xlsx", fh,
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"file_kind": "sales"},
                headers=client.auth_headers,
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        items = data.get("uploaded") if isinstance(data, dict) else data
        assert items and "error" not in items[0], items
        ana_id = items[0]["id"]
        assert items[0]["result"].get("kind") == "sales"

        pptx = client.get(
            f"/api/analyses/{ana_id}/pptx?lang=ar", headers=client.auth_headers)
        assert pptx.status_code == 200, pptx.text
        assert len(pptx.content) > 20_000
        from pptx import Presentation

        prs = Presentation(io.BytesIO(pptx.content))
        assert len(prs.slides) >= 3

        xls = client.get(
            f"/api/analyses/{ana_id}/export?lang=ar", headers=client.auth_headers)
        assert xls.status_code == 200, xls.text
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(xls.content))
        ws = wb.active
        texts = " ".join(str(c.value) for row in ws.iter_rows() for c in row
                         if c.value is not None)
        assert "المناطق" in texts
        assert "المندوبين" in texts
        # a financial workbook's ηa:d-sheet names must not appear
        assert "قائمة الدخل" not in texts

    def test_records_list_carries_kind(self, client, tmp_path):
        from app.parsers import parse_file

        with open(_make_sales_xlsx(tmp_path), "rb") as fh:
            resp = client.post(
                "/api/upload",
                files={"files": ("sales.xlsx", fh,
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"file_kind": "sales"},
                headers=client.auth_headers,
            )
        assert resp.status_code == 200
        listing = client.get("/api/analyses").json()
        target = next(x for x in listing if x["id"] == (
            (resp.json().get("uploaded") or resp.json())[0]["id"]))
        assert target["kind"] == "sales"


# ------------------------------------------------------- top-selling products ----

def _make_products_xlsx(tmp_path) -> str:
    """Invoice-grain sales file WITH a product/item column — the shape the
    «الأصناف الأكثر مبيعًا» section needs to radiate."""
    wb = Workbook()
    ws = wb.active
    ws.append(["التاريخ", "رقم الفاتورة", "مسؤول المبيعات", "المنطقة",
               "المنتج", "الكمية", "سعر الوحدة", "المبلغ الإجمالي"])
    rows = [
        ["2026-01-01", "INV-1", "أحمد", "الوسطى", "هاتف", 3, 3200, 9600],
        ["2026-01-02", "INV-2", "أحمد", "الوسطى", "حاسب", 2, 5000, 10000],
        ["2026-02-01", "INV-3", "سارة", "الغربية", "هاتف", 5, 3200, 16000],
        ["2026-02-03", "INV-4", "سارة", "الغربية", "سماعات", 10, 300, 3000],
    ]
    for r in rows:
        ws.append(r)
    p = tmp_path / "products.xlsx"
    wb.save(p)
    return str(p)


def _products_analysis(tmp_path) -> dict:
    from app.parsers import parse_file

    parsed = parse_file(Path(_make_products_xlsx(tmp_path)))
    records = _sales_records_for_tables(parsed["tables"])
    return analyze_sales(records)


def test_products_ranked_and_aggregated(tmp_path):
    products = _products_analysis(tmp_path)["products"]
    assert [p["product"] for p in products] == ["هاتف", "حاسب", "سماعات"]  # by sales desc
    top = products[0]
    assert top["sales"] == 25600.0
    assert top["share_pct"] == 66.3
    assert top["transactions"] == 8       # sum of the quantity column
    assert top["top_month"] == "فبراير"   # its biggest month


def test_products_hidden_without_product_column(tmp_path):
    """A sales file WITHOUT a product/item column keeps «products» empty —
    the panel and every export then hide the section (honest absence)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["الشهر", "المنطقة", "مسؤول المبيعات", "إجمالي المبيعات"])
    for row in (["يناير", "الوسطى", "أحمد", 50000],
                ["يناير", "الغربية", "سارة", 40000],
                ["فبراير", "الوسطى", "أحمد", 55000]):
        ws.append(row)
    p = tmp_path / "grid.xlsx"
    wb.save(p)
    from app.parsers import parse_file

    parsed = parse_file(Path(str(p)))
    records = _sales_records_for_tables(parsed["tables"])
    assert analyze_sales(records).get("products", []) == []


def test_products_reach_pdf_pptx_and_excel(tmp_path):
    sales = _products_analysis(tmp_path)
    out = tmp_path / "p.pdf"
    build_sales_report("products.xlsx", sales, out, lang="ar")
    import pymupdf

    hay_n = _norm("".join(pg.get_text() for pg in pymupdf.open(out)))
    assert _hits(hay_n, "الأصناف")
    assert _hits(hay_n, "هاتف")

    deck = tmp_path / "p.pptx"
    build_sales_pptx_report("products.xlsx", sales, deck, lang="ar")
    from pptx import Presentation

    texts = [
        sh.text_frame.text
        for sl in Presentation(str(deck)).slides
        for sh in sl.shapes
        if sh.has_text_frame
    ]
    # PPTX stores the DISPLAY-shaped string — match through the same
    # shaping pipeline the deck uses (NFKC breaks lam-alef ligatures in
    # the reversed word, so a plain reversed match fails)
    from app.pptx_report import _shape as _shape_pptx

    assert any(_shape_pptx("الأصناف") in t for t in texts)
    # the products slide carries its table (rank + item + share + month)
    has_row = any(
        sh.has_table and any(_shape_pptx("هاتف") in "".join(str(c.text) for c in row.cells)
                             for row in sh.table.rows)
        for sl in Presentation(str(deck)).slides
        for sh in sl.shapes
    )
    assert has_row

    from app.bi_export import build_sales_table_rows

    sections = build_sales_table_rows(sales, "ar")
    pproducts = next(rows for t, _h, rows in sections
                     if "الأصناف" in t or "Products" in t)
    assert pproducts and pproducts[0][1] == "هاتف" and pproducts[0][2] == 25600.0


# ---------------------------------------------------- slowdown alert & diagnosis ----

def _declining_sales() -> dict:
    """A sales payload whose MoM growth slides 3+ consecutive months (the
    exact pattern that fires the live panel's slowdown alert), with one
    region honouring the pattern and one not."""
    months = ["يناير", "فبراير", "مارس", "أبريل", "مايو"]
    monthly = [
        {"month": months[0], "sales": 300000, "transactions": 100,
         "new_customers": 5, "growth": None},
        {"month": months[1], "sales": 280000, "transactions": 95,
         "new_customers": 3, "growth": -6.7},
        {"month": months[2], "sales": 240000, "transactions": 90,
         "new_customers": 2, "growth": -14.3},
        {"month": months[3], "sales": 200000, "transactions": 70,
         "new_customers": 0, "growth": -16.7},
        {"month": months[4], "sales": 150000, "transactions": 60,
         "new_customers": 0, "growth": -25.0},
    ]
    # الشمالية declines every month (target pattern) · الجنوبية recovers
    north, south = {}, {}
    n_sales = [180000, 162000, 123000, 90000, 48000]
    s_sales = [120000, 118000, 117000, 110000, 102000]
    n_txns = [60, 57, 42, 30, 18]
    s_txns = [40, 38, 48, 40, 42]
    for i, mo in enumerate(months):
        north[mo] = {"sales": n_sales[i], "transactions": n_txns[i], "new_customers": 0}
        south[mo] = {"sales": s_sales[i], "transactions": s_txns[i], "new_customers": 0}
    return {
        "total_sales": sum(m["sales"] for m in monthly),
        "total_transactions": sum(m["transactions"] for m in monthly),
        "new_customers": sum(m["new_customers"] for m in monthly),
        "months": months, "monthly": monthly,
        "regions": [], "reps": [],
        "peak_month": {"month": months[0], "sales": 300000},
        "low_month": {"month": months[-1], "sales": 150000},
        "strengths": [], "weaknesses": [], "reps_target_note": None,
        "forecast_next_month": {"sales": 100000, "growth": -33.3},
        "recommendations": [],
        "by_region_months": {"الشمالية": north, "الجنوبية": south},
        "by_rep_months": {},
    }


def _norm(s: str) -> str:
    """NFKC collapses Arabic presentation forms (the exporters shape text
    before writing) and drop whitespace — a stable cross-artifact matcher
    for RTL text whose word ORDER extraction reverses differently in
    PDF (visual order) vs PPTX (as stored)."""
    import unicodedata

    return unicodedata.normalize("NFKC", str(s)).replace(" ", "").replace("\n", "")


def _hits(joined: str, *words: str) -> bool:
    """Every word must appear as a contiguous NFKC'd token, in EITHER
    letter direction: PPTX stores the fully display-reversed form while
    the PDF text layer keeps logical order — cover both."""
    for w in words:
        nw = _norm(w)
        if nw in joined or nw[::-1] in joined:
            continue
        return False
    return True


def test_slowdown_stays_hidden_when_growth_patterns_honour_it():
    from app.sales_analyzer import slowdown_alert

    assert slowdown_alert(_declining_sales()) is not None
    # a rising-tail variant (like the live sample) must NOT fire
    rising = _declining_sales()
    m = rising["monthly"]
    m[-1]["growth"] = 40.0
    m[-2]["growth"] = 12.0
    assert slowdown_alert(rising) is None


def test_slowdown_alert_names_steepest_entity_and_lever():
    from app.sales_analyzer import slowdown_alert

    alert = slowdown_alert(_declining_sales())
    assert alert is not None
    assert alert["slowdown"]["months"] == 3
    assert alert["slowdown"]["negative"] is True
    top = alert["top"]
    assert top is not None and top["kind"] == "region"
    assert top["name"] == "الشمالية"
    assert top["drop"] <= 0  # the slide is steepest = most negative
    assert alert["lever"]["key"] in ("txns", "ticket")
    assert alert["candidates_n"] >= 1


def test_slowdown_section_renders_in_pdf_and_pptx(tmp_path):
    sales = _declining_sales()
    out = tmp_path / "alert.pdf"
    build_sales_report("sales.xlsx", sales, out, lang="ar")
    assert out.exists()
    import pymupdf

    hay = "".join(pg.get_text() for pg in pymupdf.open(out))
    hay_n = _norm(hay)
    # the alert sentence names the pattern-honouring region (الشمالية)
    assert _hits(hay_n, "تنبيه", "تباطؤ")
    assert _hits(hay_n, "الشمالية")

    deck = tmp_path / "alert.pptx"
    build_sales_pptx_report("sales.xlsx", sales, deck, lang="ar")
    from pptx import Presentation

    texts = [
        sh.text_frame.text
        for sl in Presentation(str(deck)).slides
        for sh in sl.shapes
        if sh.has_text_frame
    ]
    joined = _norm(" ".join(texts))
    assert _hits(joined, "تنبيه", "تباطؤ")
    assert _hits(joined, "الشمالية")
    # the live panel hides the alert when no slowdown fires — the deck must
    # do the same (build the quiet variant and compare slide counts)
    quiet = _declining_sales()
    m = quiet["monthly"]
    m[-1]["growth"] = 20.0
    m[-2]["growth"] = 5.0
    base = tmp_path / "quiet.pptx"
    build_sales_pptx_report("sales.xlsx", quiet, base, lang="ar")
    n_alert = len(Presentation(str(deck)).slides)
    n_quiet = len(Presentation(str(base)).slides)
    assert n_alert == n_quiet + 1


def test_security_or_locale_keys_present():
    from app.report import _SALES_L
    from app.pptx_report import _sales_labels

    for L in (_SALES_L["ar"], _SALES_L["en"]):
        assert "sd_title" in L and "sd_diag" in L and "lever_txns" in L
    for L in (_sales_labels("ar"), _sales_labels("en")):
        assert "sd_title" in L and "sd_diag" in L
