"""Tests for public site statistics: visits tracking, counters, and the
removal of the budget-notes (إيضاحات الميزانية) section from reports."""

import io

from openpyxl import load_workbook


class TestPublicStats:
    def test_stats_start_at_zero(self, client):
        body = client.get("/api/public/stats").json()
        assert body["analyses_count"] == 0
        assert body["statements_count"] == 0
        assert body["visits"] == 0
        assert body["recent"] == []
        assert body["since"]

    def test_visit_is_counted(self, client):
        client.post("/api/visit")
        client.post("/api/visit")
        body = client.get("/api/public/stats").json()
        assert body["visits"] == 2
        assert body["last_visit"]

    def test_analysis_upload_bumps_counter(self, client):
        client.post("/api/demo")
        client.post("/api/demo")
        body = client.get("/api/public/stats").json()
        assert body["analyses_count"] == 2
        assert len(body["recent"]) == 2
        assert body["recent"][0]["name"] == "demo-quarterly-report.xlsx"

    def test_trial_balance_bumps_statements_counter(self, client):
        import io as _io

        from openpyxl import Workbook

        analysis_id = client.post("/api/demo").json()["id"]
        wb = Workbook()
        ws = wb.active
        for row in [
            ["الحساب", "مدين", "دائن"],
            ["النقدية بالبنك", 100_000, 0],
            ["رأس المال", 0, 100_000],
        ]:
            ws.append(row)
        buf = _io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        res = client.post(
            f"/api/analyses/{analysis_id}/trial-balance",
            files={"file": ("tb.xlsx", buf)},
        )
        assert res.status_code == 200
        body = client.get("/api/public/stats").json()
        assert body["statements_count"] == 1

    def test_delete_does_not_decrement_counters(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        client.delete(f"/api/analyses/{analysis_id}")
        body = client.get("/api/public/stats").json()
        assert body["analyses_count"] == 1


class TestNotesSectionRemoved:
    """إيضاحات الميزانية must not appear on the face of the statements view
    or in the PDF report."""

    def test_statements_payload_still_has_detail_notes_internally(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        st = client.get(f"/api/analyses/{analysis_id}/statements").json()
        assert st["has_statements"] is False

    def test_pdf_has_no_budget_notes_heading(self, client):
        import pdfplumber

        from app.report import _shape

        analysis_id = client.post("/api/demo").json()["id"]
        res = client.get(f"/api/analyses/{analysis_id}/report?lang=ar", headers=client.auth_headers)
        assert res.status_code == 200 and res.content[:5] == b"%PDF-"
        with pdfplumber.open(io.BytesIO(res.content)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        assert _shape("إيضاحات الميزانية") not in text
        assert _shape("التقرير المالي") in text


class TestExcelExportA4:
    def test_export_has_a4_print_setup(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        res = client.get(f"/api/analyses/{analysis_id}/export?lang=ar", headers=client.auth_headers)
        assert res.status_code == 200
        wb = load_workbook(io.BytesIO(res.content))
        ws = wb["الملخص"]
        assert ws.page_setup.paperSize == 9  # A4
        assert ws.page_setup.fitToWidth == 1
        assert ws.sheet_properties.pageSetUpPr.fitToPage is True
        assert ws.oddFooter.right.text  # branded footer present
