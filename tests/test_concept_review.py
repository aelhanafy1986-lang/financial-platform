"""Manual concept corrections: fix OCR-confused financial concepts from the
UI BEFORE accepting the analysis — reclassify/rename captured concepts and
assign unclassified review rows — with the ratios recomputing immediately."""

import io

from openpyxl import Workbook, load_workbook

from app.analyzer import analyze, build_concept_review


def _demo_id(client) -> int:
    return client.post("/api/demo").json()["id"]


def _detail(client, aid: int) -> dict:
    return client.get(f"/api/analyses/{aid}").json()


def _mangled_xlsx() -> bytes:
    """A statement whose cost row label is OCR-mangled («تكلفة البيعات»):
    unclassifiable exactly, fuzzy-close to cogs."""
    wb = Workbook()
    ws = wb.active
    ws.title = "قائمة الدخل"
    ws.append(["البيان", "2023", "2024"])
    ws.append(["الإيرادات", 1000000, 1500000])
    ws.append(["تكلفة البيعات", 400000, 600000])
    ws.append(["صافي الربح", 600000, 900000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_mangled(client) -> int:
    res = client.post(
        "/api/upload",
        files={"files": ("mangled.xlsx", io.BytesIO(_mangled_xlsx()))},
        headers=client.auth_headers,
    )
    assert res.status_code == 200, res.text
    uploaded = res.json()["uploaded"]
    assert uploaded and uploaded[0].get("id"), res.json()
    return uploaded[0]["id"]


class TestBuildConceptReview:
    def test_mangled_arabic_label_detected_with_cogs_candidate(self):
        tables = [{"name": "قائمة الدخل", "rows": [
            ["البيان", "2023", "2024"],
            ["الإيرادات", 1000000, 1500000],
            ["تكلفة البيعات", 400000, 600000],
        ]}]
        items = build_concept_review(tables, [])
        assert items, "the mangled row must be offered for review"
        assert items[0]["label"] == "تكلفة البيعات"
        assert "cogs" in items[0]["candidates"]
        assert items[0]["values"] == [400000.0, 600000.0]
        assert items[0]["rid"] == "r0"

    def test_mangled_english_label_detected(self):
        items = build_concept_review(
            [{"name": "s", "rows": [["Revemue", 500, 700]]}], []
        )
        assert items and "revenue" in items[0]["candidates"]

    def test_clean_labels_produce_no_review(self):
        tables = [{"name": "s", "rows": [
            ["الإيرادات", 100], ["المصاريف التشغيلية", 40],
        ]}]
        assert build_concept_review(tables, []) == []

    def test_analyze_attaches_review_block(self):
        tables = [{"name": "s", "rows": [
            ["البيان", "2023", "2024"],
            ["الإيرادات", 100, 150],
            ["تكلفة البيعات", 40, 60],
        ]}]
        result = analyze(tables, [])
        assert result["concept_review"]["items"]


class TestReclassifyEndpoint:
    def test_reclassify_moves_series_and_recomputes(self, client):
        aid = _demo_id(client)
        before = _detail(client, aid)
        assert "opex" in before["result"]["metrics"]
        opex_vals = before["result"]["metrics"]["opex"]

        res = client.patch(
            f"/api/analyses/{aid}",
            json={"concepts": {"opex": {"to": "finance_cost"}}},
        )
        assert res.status_code == 200
        body = res.json()
        # the response IS the fresh analysis (immediate recompute contract)
        assert body["result"]["metrics"]["finance_cost"] == opex_vals
        assert "opex" not in body["result"]["metrics"]
        # series rebuilt under the new key
        assert body["result"]["series"]["finance_cost"]["values"] == opex_vals
        # audit trail + manual-edit marker
        fixes = body["result"]["concept_fixes"]
        assert fixes and fixes[-1]["concept"] == "opex"
        assert fixes[-1]["to"] == "finance_cost"
        assert body["result"]["edited_at"]
        # the stored detail agrees
        detail = _detail(client, aid)
        assert detail["result"]["metrics"]["finance_cost"] == opex_vals

    def test_occupied_target_409_then_explicit_swap(self, client):
        aid = _demo_id(client)
        before = _detail(client, aid)["result"]["metrics"]
        res = client.patch(
            f"/api/analyses/{aid}", json={"concepts": {"opex": {"to": "cogs"}}}
        )
        assert res.status_code == 409

        res = client.patch(
            f"/api/analyses/{aid}",
            json={"concepts": {"opex": {"to": "cogs", "swap": True}}},
        )
        assert res.status_code == 200
        metrics = res.json()["result"]["metrics"]
        assert metrics["opex"] == before["cogs"]
        assert metrics["cogs"] == before["opex"]
        # gross margin recomputed on the swapped series: 15M revenue vs
        # 2.25M cogs → 85%
        assert res.json()["result"]["ratios"]["gross_margin"]["value"] == 85.0

    def test_custom_label_override_survives_values_edit(self, client):
        aid = _demo_id(client)
        res = client.patch(
            f"/api/analyses/{aid}",
            json={"concepts": {"opex": {"label": "مصاريف إدارية"}}},
        )
        assert res.status_code == 200
        assert res.json()["result"]["series"]["opex"]["ar"] == "مصاريف إدارية"

        # a later values edit must NOT wipe the corrected name
        res = client.patch(
            f"/api/analyses/{aid}",
            json={"values": {"opex": {"values": [2000000, 2500000]}}},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["result"]["series"]["opex"]["ar"] == "مصاريف إدارية"
        assert body["result"]["metrics"]["opex"] == [2000000, 2500000]

    def test_unknown_target_422(self, client):
        res = client.patch(
            f"/api/analyses/{_demo_id(client)}",
            json={"concepts": {"opex": {"to": "not_a_concept"}}},
        )
        assert res.status_code == 422

    def test_missing_source_404(self, client):
        res = client.patch(
            f"/api/analyses/{_demo_id(client)}",
            json={"concepts": {"payables": {"to": "cash"}}},
        )
        assert res.status_code == 404

    def test_patch_missing_analysis_404(self, client):
        res = client.patch(
            "/api/analyses/999", json={"concepts": {"opex": {"to": "cogs"}}}
        )
        assert res.status_code == 404


class TestReviewRowAssignment:
    def test_upload_surfaces_review_rows(self, client):
        aid = _upload_mangled(client)
        detail = _detail(client, aid)
        items = detail["result"]["concept_review"]["items"]
        assert items and items[0]["rid"] == "r0"
        assert items[0]["label"] == "تكلفة البيعات"
        assert "cogs" in items[0]["candidates"]

    def test_assign_review_row_recomputes_ratios(self, client):
        aid = _upload_mangled(client)
        before = _detail(client, aid)
        assert "cogs" not in before["result"]["metrics"]

        res = client.patch(
            f"/api/analyses/{aid}", json={"review_rows": {"r0": {"to": "cogs"}}}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["result"]["metrics"]["cogs"] == [400000.0, 600000.0]
        # immediate recompute: gross margin = (1.5M − 0.6M) / 1.5M = 60%
        assert body["result"]["ratios"]["gross_margin"]["value"] == 60.0
        # the row is marked applied so it leaves the pending list
        items = body["result"]["concept_review"]["items"]
        assert items[0]["applied"] == "cogs"
        assert body["result"]["concept_fixes"][-1]["review_row"] == "r0"

    def test_assign_to_occupied_target_409(self, client):
        aid = _upload_mangled(client)
        client.patch(
            f"/api/analyses/{aid}", json={"review_rows": {"r0": {"to": "cogs"}}}
        )
        res = client.patch(
            f"/api/analyses/{aid}", json={"review_rows": {"r0": {"to": "cogs"}}}
        )
        assert res.status_code == 409

    def test_assign_unknown_rid_404(self, client):
        res = client.patch(
            f"/api/analyses/{_demo_id(client)}",
            json={"review_rows": {"nope": {"to": "cogs"}}},
        )
        assert res.status_code == 404


class TestResetSemantics:
    def test_reset_restores_classification_and_drops_fixes(self, client):
        aid = _demo_id(client)
        client.patch(
            f"/api/analyses/{aid}",
            json={"concepts": {
                "opex": {"to": "finance_cost", "label": "فوائد"},
            }},
        )
        res = client.post(f"/api/analyses/{aid}/values/reset")
        assert res.status_code == 200
        body = res.json()
        assert body["result"]["metrics"]["opex"] == [1800000, 2250000]
        assert "finance_cost" not in body["result"]["metrics"]
        assert "concept_fixes" not in body["result"]
        assert "concept_labels" not in body["result"]
        assert body["result"]["edited_at"] is None


class TestPreservationAndCaches:
    def test_review_block_survives_values_edit(self, client):
        aid = _upload_mangled(client)
        res = client.patch(
            f"/api/analyses/{aid}",
            json={"values": {"revenue": {"values": [1100000, 1600000]}}},
        )
        assert res.status_code == 200
        items = res.json()["result"]["concept_review"]["items"]
        assert items and items[0]["rid"] == "r0"

    def test_export_cache_invalidated_by_concept_fix(self, client):
        # REPORTS is redirected per-test by the conftest fixture — resolve
        # it lazily from the app module, never at import time.
        from app import main as app_main

        aid = _demo_id(client)
        first = client.get(
            f"/api/analyses/{aid}/export?lang=ar", headers=client.auth_headers
        )
        assert first.status_code == 200
        cache = app_main.REPORTS / f"export_{aid}.xlsx"
        assert cache.exists(), "the export endpoint must cache its workbook"

        res = client.patch(
            f"/api/analyses/{aid}",
            json={"concepts": {"opex": {"to": "finance_cost"}}},
        )
        assert res.status_code == 200
        assert not cache.exists(), "stale export must not survive the fix"

        second = client.get(
            f"/api/analyses/{aid}/export?lang=ar", headers=client.auth_headers
        )
        assert second.status_code == 200
        wb = load_workbook(io.BytesIO(second.content))
        summary_cells = {
            str(c.value) for row in wb["الملخص"].iter_rows() for c in row
            if c.value
        }
        assert "مصاريف التشغيلية" not in summary_cells
