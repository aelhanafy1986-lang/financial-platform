"""Group comparison: side-by-side revenue / gross margin / net profit across
N companies (the six 2024-report companies) via /api/compare-group."""

import pytest


def _ids(client, n: int = 6) -> list[int]:
    return [client.post("/api/demo").json()["id"] for _ in range(n)]


class TestCompareGroup:
    def test_six_companies_side_by_side(self, client):
        ids = _ids(client)
        body = client.get(f"/api/compare-group?ids={','.join(map(str, ids))}").json()
        assert [c["id"] for c in body["companies"]] == ids
        assert len(body["companies"]) == 6
        for c in body["companies"]:
            assert c["name"]
            # demo analyses carry every headline metric
            assert c["values"]["revenue"] > 0
            assert c["values"]["net_profit"] is not None
            assert c["values"]["gross_margin"] is not None
        assert [(m["key"], m["source"]) for m in body["metrics"]] == [
            ("revenue", "kpis"),
            ("net_profit", "kpis"),
            ("gross_margin", "ratios"),
        ]

    def test_missing_metric_is_none_never_guessed(self, client):
        a, b = _ids(client, 2)
        from app.main import SessionLocal
        from app.database import Analysis
        import json

        with SessionLocal() as db:
            row = db.get(Analysis, b)
            result = json.loads(row.result_json)
            del result["ratios"]["gross_margin"]
            row.result_json = json.dumps(result)
            db.commit()
        body = client.get(f"/api/compare-group?ids={a},{b}").json()
        assert body["companies"][0]["values"]["gross_margin"] is not None
        assert body["companies"][1]["values"]["gross_margin"] is None

    def test_two_minimum_and_order_preserved(self, client):
        a, b, _ = _ids(client, 3)
        body = client.get(f"/api/compare-group?ids={b},{a}").json()
        assert [c["id"] for c in body["companies"]] == [b, a]

    def test_single_id_rejected(self, client):
        (a,) = _ids(client, 1)
        assert client.get(f"/api/compare-group?ids={a}").status_code == 400

    def test_duplicate_ids_collapsed(self, client):
        a, b = _ids(client, 2)
        body = client.get(f"/api/compare-group?ids={a},{b},{a}").json()
        assert [c["id"] for c in body["companies"]] == [a, b]

    def test_unknown_id_404(self, client):
        assert client.get("/api/compare-group?ids=1,999").status_code == 404

    def test_bad_ids_400(self, client):
        assert client.get("/api/compare-group?ids=abc").status_code == 400
