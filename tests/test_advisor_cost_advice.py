# -*- coding: utf-8 -*-
"""Quantified cost-reduction advice for weak/loss net margins.

The «المطعم» regression: a loss-making single-period entity used to get
generic «review expenses» lines (with an English word leaking into the
Arabic text). The advice now carries an explicit recovery plan computed
from the entity's own figures — break-even cost cut, break-even revenue
alternative, the per-1%-of-COGS margin effect and the opex-cut coverage.
"""

from app.advisor import build_advisor


def _loss_result() -> dict:
    """The المطعم shape: sales 3,153,287.03 / cogs 1,980,579.58 /
    opex 1,377,436.00 → net -204,728.55 (single period, no series)."""
    return {
        "kpis": {
            "revenue": {"value": 3_153_287.03, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": -204_728.55, "en": "Net Loss", "ar": "صافي الخسارة"},
        },
        "ratios": {
            "net_margin": {"value": -6.49},
            "gross_margin": {"value": 37.19},
        },
        "metrics": {
            "revenue": [3_153_287.03],
            "cogs": [1_980_579.58],
            "opex": [1_377_436.00],
        },
        "series": {},
    }


def _net_entry(adv: dict) -> dict:
    return next(a for a in adv["advice"] if a["key"] == "net_margin")


class TestQuantifiedCostAdvice:
    def test_loss_recovery_plan_quantified(self):
        adv = build_advisor(_loss_result(), "ar")
        entry = _net_entry(adv)
        assert "خسارة صافية" in entry["ar"]
        sols = entry["solutions_ar"]
        # dynamic lines come first
        assert "نقطة التعادل" in sols[0]
        assert any("204,729" in s for s in sols)   # break-even cost cut
        assert any("6.5% من الإيراد" in s for s in sols)
        assert any("19,806" in s for s in sols)    # 1% of cogs
        assert any("137,744" in s for s in sols)   # 10% opex cut
        assert any("0.63 نقطة" in s for s in sols)  # margin points per 1% cogs
        # the revenue-growth alternative: opex / gm - revenue ≈ +17.5%
        assert any("+17.5%" in s for s in sols)
        # generic advice still present after the dynamic lines
        assert any("بنداً بنداً" in s for s in sols)

    def test_solutions_payload_carries_the_plan(self):
        adv = build_advisor(_loss_result(), "ar")
        assert adv["solutions"][0].startswith("نقطة التعادل")
        assert any("204,729" in s for s in adv["solutions"])

    def test_no_language_leak_in_arabic(self):
        adv = build_advisor(_loss_result(), "ar")
        flat = " ".join(adv["solutions"])
        assert "quarterly" not in flat
        assert "ربع سنوي" in flat

    def test_en_mirror(self):
        adv = build_advisor(_loss_result(), "en")
        entry = _net_entry(adv)
        assert "Net loss" in entry["en"]
        sols = entry["solutions_en"]
        assert "Break-even" in sols[0]
        assert any("204,729" in s for s in sols)
        assert all("خسارة" not in s for s in sols)
        flat = " ".join(adv["solutions"])
        assert "ربع سنوي" not in flat and "quarterly goal" in flat

    def test_weak_positive_margin_gets_milder_plan(self):
        r = _loss_result()
        r["kpis"]["net_profit"] = {"value": 50_000.0, "en": "Net Profit", "ar": "صافي الربح"}
        r["ratios"]["net_margin"] = {"value": 1.5}  # below critical 3.0, positive
        adv = build_advisor(r, "ar")
        entry = _net_entry(adv)
        assert "خسارة" not in entry["ar"]
        sols = entry["solutions_ar"]
        assert any("19,806" in s for s in sols)
        assert not any("نقطة التعادل" in s for s in sols)

    def test_healthy_margin_untouched(self):
        r = _loss_result()
        r["kpis"]["net_profit"] = {"value": 300_000.0, "en": "Net Profit", "ar": "صافي الربح"}
        r["ratios"]["net_margin"] = {"value": 15.0}
        adv = build_advisor(r, "ar")
        assert all(a["key"] != "net_margin" for a in adv["advice"])
        assert all("نقطة التعادل" not in s for s in adv["solutions"])

    def test_without_cogs_opex_still_quantifies_break_even(self):
        """P&L file that only carries revenue + net: the total cost-cut line
        still appears; per-component lines are skipped, never guessed."""
        r = _loss_result()
        r["metrics"] = {"revenue": [3_153_287.03]}
        adv = build_advisor(r, "ar")
        sols = _net_entry(adv)["solutions_ar"]
        assert any("204,729" in s for s in sols)
        assert not any("19,806" in s for s in sols)
        assert not any("137,744" in s for s in sols)
