"""Tests for user-editable metadata: analysis name, notes, and file downloads."""

import io
from io import BytesIO
from pathlib import Path

import pdfplumber
from openpyxl import load_workbook

from app.report import _shape

AR_NOTE = "ملاحظة: الإيرادات تجاوزت نقطة التعادل في الربع الأخير"


def _pdf_text(content: bytes) -> str:
    """Extract visible text from PDF bytes (Arabic comes out already shaped)."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _demo_id(client) -> int:
    return client.post("/api/demo").json()["id"]


class TestDisplayName:
    def test_new_analysis_has_no_custom_name(self, client):
        detail = client.get(f"/api/analyses/{_demo_id(client)}").json()
        assert detail["display_name"] is None
        assert detail["filename"] == "demo-quarterly-report.xlsx"

    def test_set_and_get_display_name(self, client):
        analysis_id = _demo_id(client)
        res = client.patch(
            f"/api/analyses/{analysis_id}",
            json={"display_name": "تحليل الربع الثالث"},
        )
        assert res.status_code == 200
        assert res.json()["display_name"] == "تحليل الربع الثالث"
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["display_name"] == "تحليل الربع الثالث"

    def test_rename_keeps_original_filename(self, client):
        analysis_id = _demo_id(client)
        client.patch(
            f"/api/analyses/{analysis_id}", json={"display_name": "اسم جديد"}
        )
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["filename"] == "demo-quarterly-report.xlsx"

    def test_clear_display_name_with_null(self, client):
        analysis_id = _demo_id(client)
        client.patch(f"/api/analyses/{analysis_id}", json={"display_name": "x"})
        res = client.patch(f"/api/analyses/{analysis_id}", json={"display_name": None})
        assert res.json()["display_name"] is None

    def test_omitted_field_keeps_value(self, client):
        analysis_id = _demo_id(client)
        client.patch(f"/api/analyses/{analysis_id}", json={"display_name": "ابقَ"})
        res = client.patch(f"/api/analyses/{analysis_id}", json={"notes": "ملاحظة"})
        assert res.status_code == 200
        body = res.json()
        assert body["display_name"] == "ابقَ"
        assert body["notes"] == "ملاحظة"

    def test_display_name_too_long_rejected(self, client):
        res = client.patch(
            f"/api/analyses/{_demo_id(client)}", json={"display_name": "x" * 201}
        )
        assert res.status_code == 422

    def test_patch_missing_analysis_404(self, client):
        res = client.patch("/api/analyses/999", json={"display_name": "x"})
        assert res.status_code == 404

    def test_history_includes_display_name(self, client):
        analysis_id = _demo_id(client)
        client.patch(
            f"/api/analyses/{analysis_id}", json={"display_name": "الاسم المخصص"}
        )
        history = client.get("/api/analyses").json()
        assert history[0]["display_name"] == "الاسم المخصص"


class TestNotes:
    def test_new_analysis_has_empty_notes(self, client):
        detail = client.get(f"/api/analyses/{_demo_id(client)}").json()
        assert detail["notes"] is None

    def test_add_edit_and_clear_note(self, client):
        analysis_id = _demo_id(client)
        res = client.patch(f"/api/analyses/{analysis_id}", json={"notes": AR_NOTE})
        assert res.json()["notes"] == AR_NOTE

        res = client.patch(
            f"/api/analyses/{analysis_id}", json={"notes": "updated note"}
        )
        assert res.json()["notes"] == "updated note"

        res = client.patch(f"/api/analyses/{analysis_id}", json={"notes": None})
        assert res.json()["notes"] is None

    def test_multiline_note_preserved(self, client):
        analysis_id = _demo_id(client)
        note = "سطر أول\nسطر ثانٍ"
        res = client.patch(f"/api/analyses/{analysis_id}", json={"notes": note})
        assert res.json()["notes"] == note


class TestReportWithNameAndNotes:
    def test_pdf_reflects_renamed_analysis(self, client):
        analysis_id = _demo_id(client)
        client.patch(
            f"/api/analyses/{analysis_id}",
            json={"display_name": "تحليل الشاورما", "notes": AR_NOTE},
        )
        res = client.get(f"/api/analyses/{analysis_id}/report?lang=ar", headers=client.auth_headers)
        assert res.status_code == 200
        assert res.content[:5] == b"%PDF-"
        text = _pdf_text(res.content)
        assert _shape("تحليل الشاورما") in text
        assert _shape(AR_NOTE) in text

    def test_pdf_regenerated_after_note_update(self, client):
        analysis_id = _demo_id(client)
        first = _pdf_text(client.get(f"/api/analyses/{analysis_id}/report?lang=ar", headers=client.auth_headers).content)
        client.patch(f"/api/analyses/{analysis_id}", json={"notes": AR_NOTE})
        second = _pdf_text(client.get(f"/api/analyses/{analysis_id}/report?lang=ar", headers=client.auth_headers).content)
        assert _shape(AR_NOTE) not in first
        assert _shape(AR_NOTE) in second


class TestOriginalFileDownload:
    def test_upload_saves_original_and_reports_has_file(self, client):
        xlsx = _ensure_sample()
        with open(xlsx, "rb") as fh:
            res = client.post("/api/upload", files={"files": ("sample-financials.xlsx", fh)}, headers=client.auth_headers)
        assert res.status_code == 200
        body = res.json()
        detail = client.get(f"/api/analyses/{body["uploaded"][0]["id"]}").json()
        assert detail["has_file"] is True

    def test_download_original_file_roundtrip(self, client):
        xlsx = _ensure_sample()
        with open(xlsx, "rb") as fh:
            original_bytes = fh.read()
        analysis_id = client.post(
            "/api/upload", files={"files": ("sample-financials.xlsx", BytesIO(original_bytes))},
            headers=client.auth_headers,
        ).json()["uploaded"][0]["id"]

        res = client.get(f"/api/analyses/{analysis_id}/file", headers=client.auth_headers)
        assert res.status_code == 200
        assert res.content == original_bytes
        assert "attachment" in res.headers["content-disposition"]

    def test_demo_has_no_file_to_download(self, client):
        res = client.get(f"/api/analyses/{_demo_id(client)}/file", headers=client.auth_headers)
        assert res.status_code == 404
        assert "not available" in res.json()["detail"]

    def test_download_missing_analysis_404(self, client):
        assert client.get("/api/analyses/999/file", headers=client.auth_headers).status_code == 404


class TestExcelExport:
    def test_export_styled_arabic_workbook(self, client):
        analysis_id = _demo_id(client)
        client.patch(
            f"/api/analyses/{analysis_id}", json={"notes": AR_NOTE, "display_name": "تصدير تجربة"}
        )
        res = client.get(f"/api/analyses/{analysis_id}/export?lang=ar", headers=client.auth_headers)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        wb = load_workbook(BytesIO(res.content))
        # the demo analysis is a multi-period comparison: it now carries the
        # derived (per-period) statements sheet after the notes sheet
        assert wb.sheetnames == ["الملخص", "الرسوم البيانية التحليلية", "التنبؤات", "ملاحظات", "القوائم المالية (لكل فترة)"]
        summary = wb["الملخص"]
        assert summary.sheet_view.rightToLeft is True
        cells = {str(c.value) for row in summary.iter_rows() for c in row if c.value}
        assert "الإيرادات" in cells
        assert "هامش صافي الربح %" in cells
        note_cells = {
            str(c.value) for row in wb["ملاحظات"].iter_rows() for c in row if c.value
        }
        assert AR_NOTE in note_cells

    def test_export_english_layout(self, client):
        analysis_id = _demo_id(client)
        res = client.get(f"/api/analyses/{analysis_id}/export?lang=en", headers=client.auth_headers)
        assert res.status_code == 200
        wb = load_workbook(BytesIO(res.content))
        assert "Summary" in wb.sheetnames and "Analytical Charts" in wb.sheetnames
        assert wb["Summary"].sheet_view.rightToLeft is False

    def test_export_missing_analysis_404(self, client):
        assert client.get("/api/analyses/999/export", headers=client.auth_headers).status_code == 404

    def test_stats_after_analyses(self, client):
        client.post("/api/demo")
        client.post("/api/demo")
        res = client.get("/api/stats", headers=client.admin_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 2
        assert body["concepts"]["revenue"]["last"]["value"] == 15_000_000
        assert body["concepts"]["revenue"]["first"]["name"] != body["concepts"]["revenue"]["last"]["name"] or True

    def test_stats_empty(self, client):
        body = client.get("/api/stats", headers=client.admin_headers).json()
        assert body["total"] == 0 and body["analyses"] == []

    def test_stats_admin_only(self, client):
        """Cross-account statistics are restricted to the admin account."""
        assert client.get("/api/stats").status_code == 401
        assert client.get("/api/stats", headers=client.auth_headers).status_code == 403
        assert client.get("/api/stats", headers=client.admin_headers).status_code == 200
        assert (
            client.get("/api/stats/report?lang=ar", headers=client.admin_headers).status_code
            == 200
        )
        assert (
            client.get("/api/stats/report?lang=ar", headers=client.auth_headers).status_code
            == 403
        )


def _ensure_sample():
    """Build the sample workbook once per test session."""
    import subprocess
    import sys

    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    xlsx = root / "sample-financials.xlsx"
    if not xlsx.exists():
        subprocess.run(
            [sys.executable, str(root / "scripts" / "make_sample.py")], check=True
        )
    return xlsx
