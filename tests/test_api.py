"""API tests for the FastAPI backend (client fixture lives in conftest.py)."""

from pathlib import Path


class TestHealthAndMeta:
    def test_health(self, client):
        assert client.get("/api/health").json() == {"status": "ok"}

    def test_labels_bilingual(self, client):
        labels = client.get("/api/labels").json()
        assert labels["upload"]["ar"] == "رفع ملف"
        assert labels["upload"]["en"] == "Upload File"


class TestUploadAndHistory:
    def _upload_sample(self, client):
        import subprocess
        import sys

        script = Path(__file__).resolve().parents[1] / "scripts" / "make_sample.py"
        xlsx = Path(__file__).resolve().parents[1] / "sample-financials.xlsx"
        if not xlsx.exists():
            subprocess.run([sys.executable, str(script)], check=True)
        with open(xlsx, "rb") as fh:
            response = client.post(
                "/api/upload",
                files={"files": ("sample-financials.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=client.auth_headers,
            )
        return response

    def test_upload_returns_full_analysis(self, client):
        response = self._upload_sample(client)
        assert response.status_code == 200
        body = response.json()
        uploaded = body["uploaded"][0]
        assert uploaded["filename"] == "sample-financials.xlsx"
        assert uploaded["result"]["kpis"]["revenue"]["value"] == 4_820_000
        assert uploaded["result"]["ratios"]["gross_margin"]["value"] == 41.2
        assert len(uploaded["result"]["series"]) >= 5

    def test_upload_persists_to_history(self, client):
        self._upload_sample(client)
        history = client.get("/api/analyses").json()
        assert len(history) == 1
        assert history[0]["file_type"] == ".xlsx"
        detail = client.get(f"/api/analyses/{history[0]['id']}").json()
        assert detail["result"]["kpis"]["cash"]["value"] == 1_120_000

    def test_rejects_unsupported_extension(self, client):
        response = client.post(
            "/api/upload",
            files={"files": ("notes.txt", b"hello", "text/plain")},
            headers=client.auth_headers,
        )
        assert response.status_code == 400
        assert "unsupported" in response.json()["detail"]

    def test_rejects_corrupt_office_file(self, client):
        response = client.post(
            "/api/upload",
            files={"files": ("broken.xlsx", b"not really a zip", "application/octet-stream")},
            headers=client.auth_headers,
        )
        assert response.status_code == 400
        assert "failed to process" in response.json()["detail"]

    def test_delete_removes_from_history(self, client):
        self._upload_sample(client)
        history = client.get("/api/analyses").json()
        analysis_id = history[0]["id"]
        assert client.delete(f"/api/analyses/{analysis_id}").json() == {"ok": True}

    def _sample_bytes(self):
        import subprocess
        import sys

        script = Path(__file__).resolve().parents[1] / "scripts" / "make_sample.py"
        xlsx = Path(__file__).resolve().parents[1] / "sample-financials.xlsx"
        if not xlsx.exists():
            subprocess.run([sys.executable, str(script)], check=True)
        return xlsx.read_bytes()

    def test_multi_file_upload(self, client):
        """Several files can be uploaded and analysed in one request."""
        data = self._sample_bytes()
        response = client.post(
            "/api/upload",
            files=[
                ("files", ("a.xlsx", data, "application/octet-stream")),
                ("files", ("b.xlsx", data, "application/octet-stream")),
            ],
            headers=client.auth_headers,
        )
        assert response.status_code == 200
        uploaded = response.json()["uploaded"]
        assert len(uploaded) == 2
        assert all("id" in u for u in uploaded)
        history = client.get("/api/analyses").json()
        assert len(history) == 2


class TestDemoAndReport:
    def test_demo_creates_analysis(self, client):
        body = client.post("/api/demo").json()
        assert body["result"]["kpis"]["revenue"]["value"] == 15_000_000
        assert client.get("/api/analyses").json()[0]["filename"] == "demo-quarterly-report.xlsx"

    def test_dashboard_payload_carries_health_radar(self, client):
        """مؤشر الصحة المالية rides the analytics-dashboard payload: five
        per-period dimension scores so the board can draw one polygon per
        period alongside the score gauge."""
        analysis_id = client.post("/api/demo").json()["id"]
        data = client.get(
            f"/api/analyses/{analysis_id}/dashboard?lang=ar",
            headers=client.auth_headers,
        ).json()
        health = data["health"]
        assert health is not None
        assert len(health["periods"]) >= 1
        keys = {d["key"] for d in health["radar"]}
        assert {"liquidity", "profitability", "efficiency"} <= keys
        for d in health["radar"]:
            for v in d["values"].values():
                assert v is None or 0 <= v <= 100

    def test_pdf_report_arabic(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        response = client.get(f"/api/analyses/{analysis_id}/report?lang=ar", headers=client.auth_headers)
        assert response.status_code == 200
        assert response.content[:5] == b"%PDF-"
        assert len(response.content) > 5_000

    def test_pdf_report_english(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        response = client.get(f"/api/analyses/{analysis_id}/report?lang=en", headers=client.auth_headers)
        assert response.status_code == 200
        assert response.content[:5] == b"%PDF-"

    def test_report_unknown_language_falls_back_to_arabic(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        response = client.get(f"/api/analyses/{analysis_id}/report?lang=fr", headers=client.auth_headers)
        assert response.status_code == 200

    def test_report_404_for_missing_analysis(self, client):
        assert client.get("/api/analyses/999/report", headers=client.auth_headers).status_code == 404
