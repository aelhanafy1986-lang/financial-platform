# -*- coding: utf-8 -*-
"""Financial statements must be part of the ANALYSIS REPORTS whenever their
data exists — PDF, PowerPoint and Excel alike, never a separate file.

For comparison files (United-style, no trial balance) the reports used to
read ``row.statements_json`` directly and silently SKIP the statements
section. The endpoints now derive the statements from the metric series
and surface them with the REAL-statements face (latest period as the face,
previous period riding along as «prev» evidence), so:

- a comparison analysis' PDF report CONTAINS the statements section
  (income statement face + balance sheet), and
- its PowerPoint deck contains a statements slide, and
- the PPTX amount column follows the SAME alignment rule as everywhere
  (RTL: value column flush against the item column — one visual rule,
  not amount right / compare left as two versions of the same code).
"""

import io
import json

import pytest
from openpyxl import Workbook, load_workbook

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

METRICS_TWO = {
    "revenue": [500_000.0, 650_000.0],
    "cogs": [300_000.0, 380_000.0],
    "opex": [70_000.0, 85_000.0],
    "cash": [120_000.0, 210_000.0],
    "inventory": [90_000.0, 125_000.0],
    "receivables": [60_000.0, 110_000.0],
    "payables": [45_000.0, 80_000.0],
    "current_assets": [270_000.0, 445_000.0],
    "current_liabilities": [45_000.0, 80_000.0],
    "assets": [500_000.0, 700_000.0],
    "liabilities": [100_000.0, 145_000.0],
    "equity": [400_000.0, 555_000.0],
}


def _upload_comparison(client):
    wb = Workbook()
    ws = wb.active
    ws.append(["البند", "2024", "2025"])
    ws.append(["الإيرادات", 500000, 650000])
    ws.append(["تكلفة المبيعات", 300000, 380000])
    ws.append(["المصاريف التشغيلية", 70000, 85000])
    ws.append(["النقدية", 120000, 210000])
    ws.append(["المدينون", 60000, 110000])
    ws.append(["المخزون", 90000, 125000])
    ws.append(["الدائنون", 45000, 80000])
    ws.append(["إجمالي الأصول", 500000, 700000])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post("/api/upload",
                       files={"files": ("compare.xlsx", buf, XLSX_MIME)},
                       headers=client.auth_headers)
    assert resp.status_code == 200, resp.text
    aid = resp.json()["uploaded"][0]["id"]
    import app.database as database

    with database.SessionLocal() as db:
        row = db.get(database.Analysis, aid)
        res = json.loads(row.result_json)
        res["metrics"] = dict(METRICS_TWO)
        res["period_labels"] = ["2024", "2025"]
        row.result_json = json.dumps(res, ensure_ascii=False)
        db.commit()
    return aid


def _pdf_text(content: bytes) -> str:
    """Extract + restore: the platform RENDERS Arabic reshaped/visual, so
    pdfplumber reads presentation forms — exactly the input our parser fix
    reverses (the restorer is identity on the Latin parts)."""
    pdfplumber = pytest.importorskip("pdfplumber")
    from app.parsers.pdf_parser import _restore_visual_arabic

    out = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            out.append("\n".join(_restore_visual_arabic(line)
                                 for line in text.splitlines()))
    return "\n".join(out)


# ------------------------------------------------------------- helper ----

def test_extend_derived_statements_has_face_and_prev():
    from app.statements import (build_statements_from_metrics,
                                extend_derived_statements_for_export)

    st = build_statements_from_metrics(METRICS_TWO, ["2024", "2025"])
    out = extend_derived_statements_for_export(st)
    assert out["income_statement"]["lines"]
    by_en = {ln["en"]: ln for ln in out["income_statement"]["lines"]}
    assert by_en["Revenue"]["amount"] == 650_000.0      # latest = face
    assert by_en["Revenue"]["prev"] == 500_000.0         # honest evidence
    assert by_en["Gross Profit"]["prev"] == 200_000.0
    assert by_en["Net Profit"]["prev"] == 130_000.0
    bs = out["balance_sheet"]
    assert bs["liabilities_equity"]["total"] == 700_000.0
    tb = out["trial_balance"]
    assert tb["balanced"] is True and tb["accounts"] == []
    assert out["equity_statement"]["total"] == 555_000.0


# ------------------------------------------------------- pdf / pptx ----

def test_comparison_pdf_report_contains_statements(client):
    aid = _upload_comparison(client)
    resp = client.get(f"/api/analyses/{aid}/report?lang=ar",
                      headers=client.auth_headers)
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "قائمة الدخل" in text
    assert "قائمة المركز المالي" in text
    # the derived face (latest period) values are IN the report
    assert "650,000" in text.replace("\u066c", ",")
    assert "700,000" in text
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_comparison_pptx_report_contains_statements(client):
    pptx = pytest.importorskip("pptx")
    aid = _upload_comparison(client)
    resp = client.get(f"/api/analyses/{aid}/pptx?lang=ar",
                      headers=client.auth_headers)
    assert resp.status_code == 200
    from app.parsers.pdf_parser import _restore_visual_arabic

    prs = pptx.Presentation(io.BytesIO(resp.content))
    texts = " | ".join(
        _restore_visual_arabic(shape.text_frame.text)
        for slide in prs.slides for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "القوائم المالية" in texts
    assert "قائمة الدخل" in texts
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_tb_pdf_report_keeps_statements(client):
    """Regression guard: the trial-balance route still renders statements
    in the PDF (unchanged path)."""
    from app.statements import build_statements  # noqa: F401 (clarity)

    TB = [
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
    wb = Workbook()
    ws = wb.active
    for r in TB:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    demo = client.post("/api/demo").json()
    resp = client.post(
        f"/api/analyses/{demo['id']}/trial-balance",
        files={"file": ("tb.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200
    aid = demo["id"]
    resp = client.get(f"/api/analyses/{aid}/report?lang=ar",
                      headers=client.auth_headers)
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "قائمة الدخل" in text
    assert "650,000" in text
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


# ------------------------------------------------------------ pptx ----

def test_pptx_amount_column_alignment_rule():
    """In an RTL deck the amount column must hug the ITEM column (left
    edge) with the comparison at the far side — one rule for both columns'
    placement, mirroring the UI/Excel value-column unification."""
    src = open("app/pptx_report.py", encoding="utf-8").read()
    assert src.count("PP_ALIGN.LEFT if lang == \"ar\"") >= 2
    # the amounts column anchor can no longer be the slide's far right
    amounts_far_right = "\"4.3\", _fmt("   # the old far-right amount anchor
    assert amounts_far_right not in src


def test_excel_export_still_carries_statements(client):
    """The workbook's statements sheet (the Excel side of «within the
    analysis») keeps working for comparison files — not a separate file."""
    aid = _upload_comparison(client)
    export = client.get(f"/api/analyses/{aid}/export?lang=ar",
                        headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(export.content))
    assert any("القوائم" in n for n in wb.sheetnames)
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
