"""Reanalyze routing LOCK — the upload-screen declaration (file_kind /
analysis_mode) is stamped at upload and re-run verbatim on reanalyze;
re-analysis never re-classifies the file or switches the reading mode."""

import json

import pytest


@pytest.fixture
def authed_client(client):
    return client


class TestReanalyzeLock:
    def _upload(
        self,
        client,
        file_kind="statements",
        analysis_mode="auto",
        filename="sample-financials.xlsx",
        monkeypatch=None,
    ):
        """Upload the standard sample with an EXPLICIT declared routing."""
        from pathlib import Path

        import sys
        script = Path(__file__).resolve().parents[1] / "scripts" / "make_sample.py"
        xlsx = Path(__file__).resolve().parents[1] / "sample-financials.xlsx"
        if not xlsx.exists():
            import subprocess
            subprocess.run([sys.executable, str(script)], check=True)
        data = xlsx.read_bytes()
        response = client.post(
            "/api/upload",
            files={"files": (filename, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"file_kind": file_kind, "analysis_mode": analysis_mode},
            headers=client.auth_headers,
        )
        assert response.status_code == 200, response.text
        uploaded = response.json()["uploaded"][0]
        return uploaded["id"], uploaded

    def _reanalyze(self, client, aid):
        response = client.post(f"/api/analyses/{aid}/reanalyze", headers=client.auth_headers)
        assert response.status_code == 200, response.text
        return response.json()

    def test_stamp_is_frozen_at_upload(self, client):
        aid, uploaded = self._upload(client, file_kind="statements")
        assert uploaded["result"]["_file_kind"] == "statements"
        assert uploaded["result"]["_analysis_mode"] == "auto"
        # the LIST/detail payloads surface the badge fields
        listing = client.get("/api/analyses").json()
        row = next(r for r in listing if r["id"] == aid)
        assert row["file_kind"] == "statements"
        detail = client.get(f"/api/analyses/{aid}").json()
        assert detail["file_kind"] == "statements"
        assert detail["analysis_mode"] == "auto"

    def test_reanalyze_keeps_declared_route(self, client):
        aid, _ = self._upload(client, file_kind="trial_balance",
                              analysis_mode="force_trial_balance")
        detail = self._reanalyze(client, aid)
        assert detail["result"]["_file_kind"] == "trial_balance"
        assert detail["result"]["_analysis_mode"] == "force_trial_balance"
        # the financial route can never silently become a sales grid
        assert detail["result"].get("kind") != "sales"

    def test_reanalyze_restamp_survives_recompute(self, client):
        aid, _ = self._upload(client, file_kind="trial_balance",
                              analysis_mode="auto")
        body = self._reanalyze(client, aid)
        assert body["result"]["_analysis_mode"] == "auto"
        # a manual value edit (PATCH → recompute_result) must preserve the stamp
        metrics = body["result"]["metrics"]
        concept = next(k for k, v in metrics.items() if v)
        vals = metrics[concept]
        response = client.patch(
            f"/api/analyses/{aid}",
            json={"values": {concept: {"values": vals}}},
            headers=client.auth_headers,
        )
        assert response.status_code == 200, response.text
        after = response.json()
        assert after["result"]["_file_kind"] == "trial_balance"

    def test_legacy_row_without_stamp_falls_back(self, client):
        aid, uploaded = self._upload(client)
        # simulate a legacy row created before the stamp existed
        import app.database as database
        from app.main import Analysis
        with database.SessionLocal() as db:
            row = db.get(Analysis, aid)
            res = json.loads(row.result_json)
            res.pop("_file_kind", None)
            res.pop("_analysis_mode", None)
            row.result_json = json.dumps(res, ensure_ascii=False)
            db.commit()
        detail = self._reanalyze(client, aid)
        # legacy behaviour preserved: financial rows re-analyse financially
        # and FIRST reanalyze acquires the stamp for the future
        assert detail["result"].get("_file_kind") in ("statements", "trial_balance", "sales")
        assert detail["result"].get("_analysis_mode") == "auto"
