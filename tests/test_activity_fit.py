# -*- coding: utf-8 -*-
"""«ملاءمة الأنشطة» — activity-fit section of the company cards.

The detected activity type (food/trade/industrial/... as shown on the
dashboard's about-card) is judged against its sector's rule-of-thumb
inventory-turnover band; 'unknown' when the turnover is not measurable
(services activity / no inventory balance). The section rides inside the
executive brief's company card, so PDF/PPTX/Excel/UI all inherit it.
"""

from app.brief import build_activity_fit, build_executive_brief


def _result(turnover=None, assets=None, cogs=700_000.0, filename=None) -> dict:
    ratios = {}
    if turnover is not None:
        ratios["inventory_turnover"] = {
            "value": turnover, "en": "Inventory Turnover (x)", "ar": "دوران المخزون (x)"}
    kpis = {
        "revenue": {"value": 1_200_000.0, "en": "Revenue", "ar": "الإيرادات"},
        "net_profit": {"value": 300_000.0, "en": "Net Profit", "ar": "صافي الربح"},
        "cogs": {"value": cogs, "en": "Cost of Sales", "ar": "تكلفة المبيعات"},
    }
    if assets is not None:
        kpis["assets"] = {"value": assets, "en": "Total Assets", "ar": "إجمالي الأصول"}
    return {
        "kpis": kpis, "ratios": ratios, "metrics": {}, "series": {},
        "_filename": filename or "",
    }


class TestActivityFit:
    def test_industrial_within_band(self):
        fit = build_activity_fit(_result(turnover=6.0, assets=2_000_000.0))
        assert fit["key"] == "industrial"
        assert fit["verdict"] == "fit"
        assert "4" in fit["range_txt"] and "8" in fit["range_txt"]
        assert fit["turnover_txt"] == "6.0x"

    def test_food_filename_sets_band(self):
        fit = build_activity_fit(
            _result(turnover=20.0, assets=2_000_000.0, filename="food.xlsx"))
        assert fit["key"] == "food"
        assert fit["verdict"] == "fit"
        # 5 turns is far below the food band (12–24) → slow
        slow = build_activity_fit(
            _result(turnover=5.0, assets=2_000_000.0, filename="مطعم.xlsx"))
        assert slow["verdict"] == "slow"
        assert "أبطأ من القطاع" in slow["verdict_label"]

    def test_trade_band_boundaries(self):
        fit = build_activity_fit(
            _result(turnover=9.0, assets=2_000_000.0, filename="trading co.xlsx"))
        assert fit["key"] == "trade"
        assert fit["verdict"] == "fit"
        edge_low = build_activity_fit(
            _result(turnover=5.9, assets=2_000_000.0, filename="trading co.xlsx"))
        assert edge_low["verdict"] == "slow"
        edge_high = build_activity_fit(
            _result(turnover=12.1, assets=2_000_000.0, filename="trading co.xlsx"))
        assert edge_high["verdict"] == "fast"

    def test_fast_flags_high_velocity(self):
        fit = build_activity_fit(_result(turnover=15.0, assets=2_000_000.0))
        assert fit["verdict"] == "fast"  # industrial band is 4–8
        assert "أسرع من القطاع" in fit["verdict_label"]

    def test_unknown_without_inventory_balance(self):
        """P&L-only file: no balance sheet → the check never guesses."""
        fit = build_activity_fit(_result())
        assert fit["key"] == "pnl_only"
        assert fit["verdict"] == "unknown"
        assert fit["turnover_txt"] == "—"
        assert fit["range_txt"] == "—"
        assert "غير قابل للقياس" in fit["verdict_label"]

    def test_unknown_for_industrial_without_stock(self):
        """Full statements but no inventory row (service-like) → unknown."""
        fit = build_activity_fit(_result(assets=2_000_000.0))
        assert fit["key"] == "industrial"
        assert fit["verdict"] == "unknown"

    def test_bilingual_outputs(self):
        r = _result(turnover=6.0, assets=2_000_000.0)
        ar = build_activity_fit(r, lang="ar")
        en = build_activity_fit(r, lang="en")
        assert ar["title"] != en["title"]
        assert ar["title"] == "ملاءمة النشاط القطاعية"
        assert en["title"] == "Activity fit (sector)"
        assert "النطاق القطاعي" in ar["range_txt"]
        assert "Sector range" in en["range_txt"]
        assert ar["activity"] != en["activity"]

    def test_brief_company_card_carries_the_section(self):
        brief = build_executive_brief(_result(turnover=6.0, assets=2_000_000.0))
        fit = brief["company"]["activity_fit"]
        assert fit["verdict"] == "fit"
        assert fit["key"] == "industrial"
        # and a services (P&L-only) brief still carries an unknown fit
        brief2 = build_executive_brief(_result())
        assert brief2["company"]["activity_fit"]["verdict"] == "unknown"
