"""Tests for the Financial Score (0-100), scenarios and subscription plans."""

from app.scoring import compute_scenarios, compute_score, health_radar


def _rich_result() -> dict:
    return {
        "kpis": {
            "revenue": {"value": 1_000_000, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": 150_000, "en": "Net Profit", "ar": "صافي الربح"},
            "cash": {"value": 120_000, "en": "Cash", "ar": "النقدية"},
            "assets": {"value": 900_000, "en": "Total Assets", "ar": "إجمالي الأصول"},
            "opex": {"value": 200_000, "en": "Opex", "ar": "المصاريف"},
        },
        "ratios": {
            "gross_margin": {"value": 42.0},
            "net_margin": {"value": 15.0},
            "debt_ratio": {"value": 30.0},
            "debt_to_equity": {"value": 0.43},
        },
        "series": {
            "revenue": {"values": [800_000, 900_000, 1_000_000], "en": "Revenue", "ar": "الإيرادات"}
        },
    }


class TestScore:
    def test_healthy_company_scores_high(self):
        s = compute_score(_rich_result())
        assert s["score"] is not None
        assert s["score"] >= 80
        keys = {d["key"] for d in s["dimensions"]}
        assert {"profitability", "liquidity", "leverage", "efficiency"} <= keys

    def test_loss_making_scores_low(self):
        result = _rich_result()
        result["ratios"]["net_margin"]["value"] = -16.8
        result["ratios"]["gross_margin"]["value"] = 38.9
        s = compute_score(result)
        assert s["score"] < 50
        assert s["grade"]["en"] in {"Weak", "Critical", "Fair"}

    def test_pl_only_file_still_scores(self):
        """P&L-only data (no cash/assets) renormalises weights instead of failing."""
        result = {
            "kpis": {"revenue": {"value": 100_000}},
            "ratios": {"net_margin": {"value": 12.0}, "gross_margin": {"value": 35.0}},
        }
        s = compute_score(result)
        assert s["score"] is not None
        dims = {d["key"] for d in s["dimensions"]}
        assert dims == {"profitability"}

    def test_empty_result_returns_none_score(self):
        s = compute_score({})
        assert s["score"] is None


class TestHealthRadar:
    """مؤشر الصحة المالية — per-period 0-100 dimension scores for the radar."""

    def _two_period_result(self) -> dict:
        return {
            "metrics": {
                "revenue": [1_000_000, 1_200_000],
                "net_profit": [150_000, 120_000],
                "gross_profit": [420_000, 500_000],
                "cash": [120_000, 200_000],
                "assets": [900_000, 1_100_000],
                "liabilities": [300_000, 440_000],
                "equity": [600_000, 660_000],
                "opex": [200_000, 260_000],
            },
            "period_labels": ["2024", "2025"],
        }

    def test_five_dims_two_periods(self):
        h = health_radar(self._two_period_result())
        assert h is not None
        assert h["periods"] == ["2024", "2025"]
        keys = {d["key"] for d in h["radar"]}
        assert keys == {"profitability", "liquidity", "leverage", "efficiency", "growth"}
        for d in h["radar"]:
            assert set(d["values"]) == {"2024", "2025"}
            for v in d["values"].values():
                assert v is None or 0 <= v <= 100

    def test_growth_needs_a_prior_period(self):
        h = health_radar(self._two_period_result())
        growth = next(d for d in h["radar"] if d["key"] == "growth")
        assert growth["values"]["2024"] is None   # no prior period to compare
        assert growth["values"]["2025"] == 100.0  # +20% revenue → full marks

    def test_single_period_drops_growth(self):
        result = self._two_period_result()
        result["metrics"] = {k: [v[0]] for k, v in result["metrics"].items()}
        h = health_radar(result)
        assert h is not None
        assert h["periods"] == ["2024"]
        keys = {d["key"] for d in h["radar"]}
        assert "growth" not in keys
        assert {"profitability", "liquidity", "leverage", "efficiency"} <= keys

    def test_dims_without_data_are_dropped(self):
        result = self._two_period_result()
        result["metrics"] = {"revenue": [100.0, 120.0]}
        h = health_radar(result)
        assert h is not None
        keys = {d["key"] for d in h["radar"]}
        assert keys == {"growth"}

    def test_no_data_returns_none(self):
        assert health_radar({}) is None
        assert health_radar({"metrics": {"cash": [5.0]}}) is None  # no revenue anchor


class TestScenarios:
    def test_three_scenarios_ordered(self):
        out = compute_scenarios(_rich_result())
        assert out is not None
        keys = [s["key"] for s in out["scenarios"]]
        assert keys == ["optimistic", "realistic", "conservative"]
        revs = [s["revenue"] for s in out["scenarios"]]
        assert revs[0] >= revs[1] >= revs[2]

    def test_no_data_returns_none(self):
        assert compute_scenarios({}) is None

    def test_flat_series_never_collapses_to_identical(self):
        """Bug fix: with a flat revenue series the optimistic scenario must
        not equal the realistic one (0% growth everywhere)."""
        result = {
            "kpis": {
                "revenue": {"value": 4_663_364.45},
                "net_profit": {"value": -782_986.01},
            },
            "ratios": {"net_margin": {"value": -16.79}, "gross_margin": {"value": 38.86}},
            "series": {
                "revenue": {
                    "values": [1_165_841.11, 1_165_841.11, 1_165_841.11, 1_165_841.12],
                }
            },
        }
        out = compute_scenarios(result)
        assert out is not None
        opt, real, cons = out["scenarios"]
        assert opt["growth_pct"] > real["growth_pct"] >= cons["growth_pct"]
        assert opt["revenue"] > real["revenue"] > cons["revenue"]
        assert real["growth_pct"] == 0.0  # flat series -> realistic holds flat

    def test_single_point_uses_fallback_signals(self):
        """No series at all: substitute signals keep the scenarios spread."""
        result = {
            "kpis": {"revenue": {"value": 500_000}, "net_profit": {"value": 60_000}},
            "ratios": {"net_margin": {"value": 12.0}},
        }
        out = compute_scenarios(result)
        assert out is not None
        opt, real, cons = out["scenarios"]
        assert opt["revenue"] > real["revenue"] > cons["revenue"]
        assert opt["growth_pct"] != real["growth_pct"]

    def test_loss_maker_does_not_assume_growth(self):
        result = {
            "kpis": {"revenue": {"value": 500_000}, "net_profit": {"value": -80_000}},
            "ratios": {"net_margin": {"value": -16.0}},
        }
        out = compute_scenarios(result)
        real = out["scenarios"][1]
        assert real["growth_pct"] <= 2.0

    def test_noisy_series_never_produces_absurd_growth(self):
        """Regression: a noisy series (tiny bases, sign errors) must not yield
        +15,000% growth or a >100% margin. Falls back to margin-based signals."""
        result = {
            "kpis": {"revenue": {"value": 5_021_467}, "net_profit": {"value": 1_919_550}},
            "ratios": {"gross_margin": {"value": 41.2}, "net_margin": {"value": 13.3}},
            "series": {
                "revenue": {"values": [5_891, 5_029_289, -5_023_398, 6_003, 4_072,
                                        1_931, 11_894, 5_033_361]}
            },
        }
        out = compute_scenarios(result)
        for s in out["scenarios"]:
            assert abs(s["growth_pct"]) <= 60.0
            assert s["margin_pct"] <= 100.0
            assert s["net"] <= s["revenue"] * 1.0  # net can never exceed revenue

    def test_margin_never_exceeds_100_percent(self):
        """A garbage extracted net margin (e.g. 77,000%) is clamped."""
        result = {
            "kpis": {"revenue": {"value": 1_000_000}, "net_profit": {"value": 900_000}},
            "ratios": {"net_margin": {"value": 77_604.0}},
            "series": {"revenue": {"values": [900_000.0, 1_000_000.0]}},
        }
        out = compute_scenarios(result)
        for s in out["scenarios"]:
            assert s["margin_pct"] <= 95.0
            assert s["net"] <= s["revenue"]


class TestPlansAPI:
    def test_plans_listed(self, client):
        res = client.get("/api/subscription/plans")
        assert res.status_code == 200
        plans = res.json()["plans"]
        keys = {p["key"] for p in plans}
        assert {"pro", "business"} <= keys
        by_key = {p["key"]: p for p in plans}
        assert by_key["pro"]["price"] == 50.0
        assert by_key["business"]["price"] == 100.0
        # CMRRS ladder: free 1 one-time (demo gate), pro 5/mo, business 20/mo
        assert by_key["pro"]["uploads"] == 5
        assert by_key["business"]["uploads"] == 20

    def test_activate_with_plan(self, client):
        session = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "secret123", "lang": "ar"},
        ).json()
        res = client.post(
            "/api/subscription/activate",
            json={
                "card_number": "4242424242424242", "holder": "T",
                "expiry": "12/28", "cvv": "123", "plan": "business", "lang": "ar",
            },
            headers=client.auth_headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["plan"] == "business"
        assert body["plan_expires"]
