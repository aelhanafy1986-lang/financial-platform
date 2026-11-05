"""Tests for the comparison engine and its API + PDF endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.compare import compare_results


def _result(revenue, net, series_rev):
    margin = round(net / revenue * 100, 2) if revenue else 0.0
    return {
        "kpis": {
            "revenue": {"value": revenue, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": net, "en": "Net Profit", "ar": "صافي الربح"},
        },
        "ratios": {
            "net_margin": {"value": margin, "en": "Net Margin %", "ar": "هامش صافي الربح %"},
        },
        "series": {
            "revenue": {"values": series_rev, "en": "Revenue", "ar": "الإيرادات"},
        },
        "forecast": [],
        "tables_found": 1,
        "texts_found": 0,
        "analysed_at": "2025-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------

class TestCompareEngine:
    def test_kpi_delta(self):
        base = _result(4_120_000, 505_000, [3_100_000, 4_120_000])
        target = _result(4_820_000, 640_000, [4_120_000, 4_820_000])
        out = compare_results(base, target)
        row = out["kpis"]["revenue"]
        assert row["base"] == 4_120_000
        assert row["target"] == 4_820_000
        assert row["change_pct"] == 17.0
        assert row["ar"] == "الإيرادات"
        assert row["en"] == "Revenue"

    def test_ratio_delta_uses_points(self):
        base = _result(1_000_000, 100_000, [1_000_000])
        target = _result(1_000_000, 150_000, [1_000_000])
        out = compare_results(base, target)
        assert out["ratios"]["net_margin"]["base"] == 10.0
        assert out["ratios"]["net_margin"]["target"] == 15.0

    def test_series_delta_with_values(self):
        base = _result(1, 1, [100.0, 200.0])
        target = _result(1, 1, [200.0, 300.0])
        out = compare_results(base, target)
        s = out["series"]["revenue"]
        assert s["base_values"] == [100.0, 200.0]
        assert s["target_values"] == [200.0, 300.0]
        assert s["change_pct"] == 50.0

    def test_missing_on_one_side_is_skipped(self):
        base = _result(1_000_000, 100_000, [1_000_000])
        target = _result(1_000_000, 100_000, [1_000_000])
        del target["kpis"]["net_profit"]
        out = compare_results(base, target)
        assert "net_profit" not in out["kpis"]
        assert "revenue" in out["kpis"]

    def test_zero_base_never_divides(self):
        base = _result(0, 0, [0.0])
        target = _result(5, 5, [5.0])
        out = compare_results(base, target)
        assert out["kpis"] == {}
        assert out["series"] == {}

    def test_empty_results(self):
        out = compare_results({}, {})
        assert out == {"kpis": {}, "ratios": {}, "series": {}}


# ---------------------------------------------------------------------------
# API + PDF
# ---------------------------------------------------------------------------

@pytest.fixture
def two_ids(client):
    id1 = client.post("/api/demo").json()["id"]
    id2 = client.post("/api/demo").json()["id"]
    return id1, id2


class TestCompareAPI:
    def test_compare_endpoint(self, client, two_ids):
        a, b = two_ids
        body = client.get(f"/api/compare/{a}/{b}").json()
        assert body["base"]["id"] == a
        assert body["target"]["id"] == b
        assert body["kpis"]["revenue"]["base"] == 15_000_000
        assert body["kpis"]["revenue"]["change_pct"] == 0.0

    def test_compare_with_self_rejected(self, client, two_ids):
        a, _ = two_ids
        assert client.get(f"/api/compare/{a}/{a}").status_code == 400

    def test_compare_missing_analysis_404(self, client, two_ids):
        a, b = two_ids
        assert client.get(f"/api/compare/{a}/999").status_code == 404

    def test_comparison_pdf_arabic(self, client, two_ids):
        a, b = two_ids
        response = client.get(f"/api/compare/{a}/{b}/report?lang=ar", headers=client.auth_headers)
        assert response.status_code == 200
        assert response.content[:5] == b"%PDF-"
        assert len(response.content) > 5_000

    def test_comparison_pdf_english(self, client, two_ids):
        a, b = two_ids
        response = client.get(f"/api/compare/{a}/{b}/report?lang=en", headers=client.auth_headers)
        assert response.status_code == 200
        assert response.content[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# upload two different files and compare end-to-end
# ---------------------------------------------------------------------------

class TestEndToEndCompare:
    def test_upload_two_files_then_compare(self, client):
        from openpyxl import Workbook
        import io

        def build(revenue_2025: int) -> bytes:
            wb = Workbook()
            ws = wb.active
            ws.append(["البند", "2024", "2025"])
            ws.append(["الإيرادات", revenue_2025 - 500_000, revenue_2025])
            ws.append(["صافي الربح", 400_000, 500_000])
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        for rev in (4_000_000, 4_820_000):
            response = client.post(
                "/api/upload",
                files={"files": (f"y-{rev}.xlsx", build(rev), "application/octet-stream")},
                headers=client.auth_headers,
            )
            assert response.status_code == 200

        history = client.get("/api/analyses").json()
        ids = sorted((h["id"] for h in history), reverse=True)
        body = client.get(f"/api/compare/{ids[1]}/{ids[0]}").json()
        assert body["kpis"]["revenue"]["base"] == 4_000_000
        assert body["kpis"]["revenue"]["target"] == 4_820_000
        assert body["kpis"]["revenue"]["change_pct"] == pytest.approx(20.5, abs=0.1)


# ---------------------------------------------------------------------------
# judgment-based verdicts (heatmap layer)

def _full_result(revenue, cogs, liabilities, margin):
    return {
        "kpis": {
            "revenue": {"value": revenue, "en": "Revenue", "ar": "الإيرادات"},
            "cogs": {"value": cogs, "en": "Cost of Sales", "ar": "تكلفة المبيعات"},
        },
        "ratios": {
            "net_margin": {"value": margin, "en": "Net Margin %", "ar": "هامش صافي الربح %"},
            "debt_ratio": {"value": 40.0, "en": "Debt Ratio %", "ar": "نسبة الالتزامات %"},
        },
        "series": {},
    }


class TestVerdicts:
    def test_revenue_up_good_cost_up_bad(self):
        base = _full_result(1_000_000, 600_000, 0, 10.0)
        target = _full_result(1_200_000, 800_000, 0, 12.0)
        out = compare_results(base, target)
        assert out["kpis"]["revenue"]["verdict"] == "good"      # +20%
        assert out["kpis"]["cogs"]["verdict"] == "bad"          # +33% cost
        assert out["ratios"]["net_margin"]["verdict"] == "good"  # +2pt

    def test_liabilities_down_is_good(self):
        base = _full_result(1_000_000, 600_000, 0, 10.0)
        target = _full_result(1_000_000, 600_000, 0, 10.0)
        target["ratios"]["debt_ratio"]["value"] = 30.0
        out = compare_results(base, target)
        assert out["ratios"]["debt_ratio"]["verdict"] == "good"  # debt fell

    def test_flat_change_has_no_verdict(self):
        base = _full_result(1_000_000, 600_000, 0, 10.0)
        target = _full_result(1_000_001, 600_000, 0, 10.0)
        out = compare_results(base, target)
        row = out["kpis"]["revenue"]  # +0.0001% → rounded 0.0
        assert row["verdict"] is None


class TestRowHistory:
    def test_kpi_history_from_series(self):
        base = {
            "kpis": {"revenue": {"value": 4_120_000.0, "en": "Revenue", "ar": "الإيرادات"}},
            "ratios": {},
            "series": {"revenue": {"values": [3_100_000.0, 3_600_000.0, 4_120_000.0]}},
        }
        target = {
            "kpis": {"revenue": {"value": 4_820_000.0, "en": "Revenue", "ar": "الإيرادات"}},
            "ratios": {},
            "series": {"revenue": {"values": [4_820_000.0]}},
        }
        out = compare_results(base, target)
        hist = out["kpis"]["revenue"]["history"]
        assert hist == [3_100_000.0, 3_600_000.0, 4_120_000.0, 4_820_000.0]

    def test_history_empty_without_series(self):
        base = _full_result(1_000_000, 600_000, 0, 10.0)
        target = _full_result(1_200_000, 700_000, 0, 12.0)
        out = compare_results(base, target)
        assert out["kpis"]["revenue"]["history"] == []
