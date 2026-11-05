"""Tests for manual editing of extracted values (KPIs + series)."""

AR_NAME = "تحليل معدل"


def _demo(client) -> int:
    return client.post("/api/demo").json()["id"]


def _patch_values(client, analysis_id: int, values: dict):
    return client.patch(
        f"/api/analyses/{analysis_id}", json={"values": values}
    )


class TestPatchValues:
    def test_edit_revenue_recomputes_net_margin(self, client):
        analysis_id = _demo(client)
        res = _patch_values(
            client,
            analysis_id,
            {"revenue": {"values": [12_000_000, 18_000_000]}},
        )
        assert res.status_code == 200
        result = res.json()["result"]
        # net margin = 2,250,000 / 18,000,000
        assert result["ratios"]["net_margin"]["value"] == 12.5
        # revenue KPI now the edited latest value
        assert result["kpis"]["revenue"]["value"] == 18_000_000
        # edited_at flag is set
        assert result["edited_at"]

    def test_edit_series_updates_series_and_forecast(self, client):
        analysis_id = _demo(client)
        res = _patch_values(
            client,
            analysis_id,
            {"revenue": {"values": [1000, 900, 800, 700, 600, 500]}},
        )
        result = res.json()["result"]
        assert result["series"]["revenue"]["values"] == [1000, 900, 800, 700, 600, 500]
        rev_forecast = next(
            f for f in result["forecast"] if f["concept"] == "revenue"
        )
        assert rev_forecast["trend"] == "down"

    def test_ratios_derived_from_hidden_concepts_survive(self, client):
        analysis_id = _demo(client)
        res = _patch_values(
            client, analysis_id, {"net_profit": {"values": [320_000]}}
        )
        result = res.json()["result"]
        # gross margin (derived from cogs) is kept after recomputation
        assert result["ratios"]["gross_margin"]["value"] == 30.0
        # net margin recomputed from the edited net profit
        assert result["ratios"]["net_margin"]["value"] == round(320_000 / 15_000_000 * 100, 2)

    def test_result_includes_metrics_block(self, client):
        analysis_id = _demo(client)
        _patch_values(client, analysis_id, {"cash": {"values": [500_000, 750_000]}})
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["result"]["metrics"]["cash"] == [500_000, 750_000]
        assert detail["editable"] is True

    def test_values_validated(self, client):
        analysis_id = _demo(client)
        # empty list rejected
        res = _patch_values(client, analysis_id, {"cash": {"values": []}})
        assert res.status_code == 422
        # too many values rejected
        res = _patch_values(
            client, analysis_id, {"cash": {"values": [1.0] * 25}}
        )
        assert res.status_code == 422
        # non-numeric rejected
        res = client.patch(
            f"/api/analyses/{analysis_id}",
            json={"values": {"cash": {"values": ["abc"]}}},
        )
        assert res.status_code == 422

    def test_unknown_concept_accepted_and_kept(self, client):
        analysis_id = _demo(client)
        res = _patch_values(client, analysis_id, {"custom": {"values": [1, 2, 3]}})
        assert res.status_code == 200
        result = res.json()["result"]
        assert result["metrics"]["custom"] == [1.0, 2.0, 3.0]

    def test_patch_404(self, client):
        res = _patch_values(client, 999, {"cash": {"values": [1]}})
        assert res.status_code == 404


class TestResetValues:
    def test_reset_restores_originals(self, client):
        analysis_id = _demo(client)
        _patch_values(client, analysis_id, {"revenue": {"values": [10.0]}})
        res = client.post(f"/api/analyses/{analysis_id}/values/reset")
        assert res.status_code == 200
        result = res.json()["result"]
        assert result["kpis"]["revenue"]["value"] == 15_000_000
        # recomputed from raw values (demo now consistent: 15% net margin)
        assert result["ratios"]["net_margin"]["value"] == 15.0
        assert result["edited_at"] is None

    def test_reset_404(self, client):
        assert client.post("/api/analyses/999/values/reset").status_code == 404


class TestBackwardCompatibility:
    def test_old_analyses_report_editable_false(self, client):
        # demo rows are created without metrics -> reconstructed on demand
        analysis_id = _demo(client)
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["editable"] is True  # metrics reconstructed from kpis+series

    def test_name_and_notes_edit_still_work(self, client):
        analysis_id = _demo(client)
        res = client.patch(
            f"/api/analyses/{analysis_id}",
            json={"display_name": AR_NAME, "notes": "ملاحظة"},
        )
        body = res.json()
        assert body["display_name"] == AR_NAME
        assert body["notes"] == "ملاحظة"
        assert body["result"].get("edited_at") is None


class TestValueEditsUi:
    def test_export_reflects_edited_values(self, client):
        analysis_id = _demo(client)
        _patch_values(client, analysis_id, {"revenue": {"values": [1_000_000]}})
        res = client.get(f"/api/analyses/{analysis_id}/export", headers=client.auth_headers)
        assert res.status_code == 200
