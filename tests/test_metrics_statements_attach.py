# -*- coding: utf-8 -*-
"""Statement attachment for COMPARISON files (no trial balance).

The TB auto-attach only ever fired for a real, balanced trial balance —
comparison documents (multi-year income statements, English annual-report
faces) stayed ``has_statements=False`` even though the reports derived
their statements from the metrics anyway. Contract now: when the TB path
cannot attach, the statements are composed from the captured multi-period
metric series (``build_statements_from_metrics`` + the export extension)
and attached, so upload response, the statements endpoint, the reports and
the Excel export all read ONE source. Single-period analyses cannot
support the derivation and stay honestly unattached; a real trial balance
still attaches through the original path with ``has_tb=True``.
"""

import io

from fastapi.testclient import TestClient

DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# A Microsoft-style annual report: complementary statement TABLES of ONE
# company, THREE year columns, no trial balance anywhere.
INCOME_3Y = [
    ["Item", "2025", "2024", "2023"],
    ["Total revenue", "600,000", "500,000", "400,000"],
    ["Total cost of revenue", "240,000", "200,000", "160,000"],
    ["Sales and marketing", "90,000", "80,000", "70,000"],
    ["Other income (expense), net", "(6,000)", "(5,000)", "(4,000)"],
    ["Provision for income taxes", "36,000", "30,000", "25,000"],
    ["Net income", "228,000", "185,000", "141,000"],
]
BALANCE_3Y = [
    ["Item", "2025", "2024", "2023"],
    ["Total assets", "700,000", "600,000", "500,000"],
    ["Short-term income taxes", "6,000", "5,000", "4,000"],
    ["Accounts payable", "100,000", "90,000", "80,000"],
]
CASHFLOW_3Y = [
    ["Item", "2025", "2024", "2023"],
    ["Net income", "228,000", "185,000", "141,000"],
    ["Sales of investments", "(3,000)", "(2,000)", "(1,000)"],
]

TB_ROWS = [
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


def _make_docx(path, years=3) -> bytes:
    """Word file whose tables are one company's statements (1 or 3 years)."""
    import docx

    def keep(cols):
        return [row[:1 + years] for row in cols]

    d = docx.Document()
    d.add_heading("القوائم المالية — شركة واحدة")
    for rows in (keep(INCOME_3Y), keep(BALANCE_3Y), keep(CASHFLOW_3Y)):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                t.cell(r, c).text = str(val)
    d.save(str(path))
    return path.read_bytes()


def _upload_docx(client, tmp_path, name="comparison.docx", years=3):
    data = _make_docx(tmp_path / name, years)
    return client.post(
        "/api/upload",
        files={"files": (name, io.BytesIO(data), DOCX_MIME)},
        headers=client.auth_headers,
    )


def _delete(client, aid):
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


class TestComparisonStatementsAttached:
    def test_upload_response_says_has_statements(self, client, tmp_path):
        """3-year comparison docx → has_statements=True in the upload
        response itself (previously False — statements were report-only)."""
        resp = _upload_docx(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        assert item["has_statements"] is True
        _delete(client, item["id"])

    def test_statements_endpoint_carries_derived_faces(self, client, tmp_path):
        """The statements endpoint returns the attached metrics-derived
        statements (marked ``derived_from_metrics``, one period per year,
        latest period as the face) and the row keeps ``has_tb=False``."""
        resp = _upload_docx(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        aid = item["id"]

        st = client.get(f"/api/analyses/{aid}/statements").json()
        assert st["has_statements"] is True
        statements = st["statements"]
        assert statements["derived_from_metrics"] is True
        assert len(statements["periods"]) == 3
        # latest period is the face: 2025 revenue
        rev = next(ln for ln in statements["income_statement"]["lines"]
                   if ln.get("en") == "Revenue")
        assert rev["amount"] == 600_000.0

        detail = client.get(f"/api/analyses/{aid}").json()
        assert detail["has_tb"] is False  # honest: there is no trial balance
        _delete(client, aid)

    def test_reports_read_the_attached_source(self, client, tmp_path):
        """PDF report, PPTX and the Excel export all work off the attached
        statements (200 + the statements sheet / figures present)."""
        resp = _upload_docx(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        aid = item["id"]

        report = client.get(f"/api/analyses/{aid}/report?lang=ar",
                            headers=client.auth_headers)
        assert report.status_code == 200, report.text
        import pymupdf

        doc = pymupdf.open(stream=report.content)
        text = "".join(pg.get_text() for pg in doc)
        doc.close()
        assert "600,000.00" in text  # 2025 revenue from the attached face
        assert "228,000.00" in text  # 2025 net (IFRS chain over metrics)

        export = client.get(f"/api/analyses/{aid}/export?lang=ar",
                            headers=client.auth_headers)
        assert export.status_code == 200
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(export.content))
        assert any("القوائم" in n for n in wb.sheetnames)

        pptx = client.get(f"/api/analyses/{aid}/pptx?lang=ar",
                          headers=client.auth_headers)
        assert pptx.status_code == 200, pptx.text
        _delete(client, aid)


class TestHonestEdges:
    def test_single_period_stays_unattached(self, client, tmp_path):
        """One year only → no metrics-derived statements possible →
        has_statements stays False everywhere (nothing is invented)."""
        resp = _upload_docx(client, tmp_path, name="single.docx", years=1)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        assert item["has_statements"] is False
        aid = item["id"]
        st = client.get(f"/api/analyses/{aid}/statements").json()
        assert st["has_statements"] is False
        assert st["statements"] is None
        _delete(client, aid)

    def test_balanced_tb_still_uses_the_tb_path(self, client):
        """A real balanced trial balance keeps the original attach path:
        has_tb=True and the statements are NOT the metrics-derived kind."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for r in TB_ROWS:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = client.post(
            "/api/upload",
            files={"files": ("tb.xlsx", buf, XLSX_MIME)},
            headers=client.auth_headers,
        )
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        assert item["has_statements"] is True
        aid = item["id"]

        detail = client.get(f"/api/analyses/{aid}").json()
        assert detail["has_tb"] is True
        st = client.get(f"/api/analyses/{aid}/statements").json()
        assert st["has_statements"] is True
        assert st["statements"].get("derived_from_metrics") is not True
        assert (st["statements"]["trial_balance"]["accounts"] or [])
        _delete(client, aid)
