# -*- coding: utf-8 -*-
"""Analytical dashboard charts (gauge / donut / bullets / stack / trend).

Adds depth to the client-facing PDF and PPTX in the style of the reference
dashboards: a score gauge with coloured bands, an expense-mix donut, ratio
bullet bars against benchmark anchors, a revenue-composition bar and
value-labelled trend lines. Each builder returns PNG bytes; the section is
wired into both reports and degrades gracefully on partial data.
"""

import re
import zipfile

from app.analyzer import compute_ratios
from app.dashboard_charts import (activity_lines, cost_composition, cost_stack,
                                  dashboard_payload, expense_components,
                                  expense_donut, ratio_bullet_rows,
                                  ratio_bullets, score_gauge, trend_line)


def _metrics() -> dict:
    return {
        "revenue": [3_153_287.03],
        "cogs": [1_980_579.58],
        "opex": [1_377_436.00],
        "finance_cost": [60_000.0],
        "tax_expense": [25_000.0],
        "net_profit": [-204_728.55],
        "current_assets": [1_456_800.0],
        "liabilities": [1_214_000.0],
        "assets": [3_150_000.0],
        "equity": [1_936_000.0],
    }


def _result() -> dict:
    return {
        "kpis": {
            "revenue": {"value": 3_153_287.03, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": -204_728.55, "en": "Net Loss", "ar": "صافي الخسارة"},
        },
        "ratios": compute_ratios(_metrics()),
        "metrics": _metrics(),
        "series": {
            "revenue": {"values": [2_800_000.0, 2_950_000.0, 3_100_000.0, 3_153_287.03],
                        "en": "Revenue", "ar": "الإيرادات"},
        },
        "period_labels": ["2021", "2022", "2023", "2024"],
    }


SCORE = {"score": 58.0, "grade": {"ar": "مقبول", "en": "Fair"}, "dimensions": []}


def _is_png(data) -> bool:
    return isinstance(data, bytes) and data.startswith(b"\x89PNG") and len(data) > 3_000


class TestBuilders:
    def test_gauge_png(self):
        assert _is_png(score_gauge(58.0, "مقبول"))
        assert _is_png(score_gauge(0.0))
        assert _is_png(score_gauge(120.0))  # clamped, never crashes

    def test_donut_png_and_minimum_parts(self):
        comps = [("تكلفة المبيعات", 1_980_579.58), ("المصاريف التشغيلية", 1_377_436.0)]
        assert _is_png(expense_donut(comps, center_label="المصروفات", title="التوزيع"))
        # a single slice carries no composition story → no chart
        assert expense_donut([("واحد فقط", 5.0)]) is None

    def test_bullets_png(self):
        rows = ratio_bullet_rows(_result(), "ar")
        assert len(rows) >= 4
        assert _is_png(ratio_bullets(rows, "النسب مقابل المعايير"))
        assert ratio_bullets(rows[:1]) is None  # needs ≥ 2 rows

    def test_trend_and_stack_png(self):
        assert _is_png(trend_line([2_800_000.0, 2_950_000.0, 3_100_000.0, 3_153_287.03],
                                  labels=["2021", "2022", "2023", "2024"],
                                  title="الإيرادات"))
        assert trend_line([1.0]) is None  # single point → no trend
        parts = [("تكلفة المبيعات", 1_980_579.58), ("المصاريف التشغيلية", 1_172_707.45)]
        assert _is_png(cost_stack(parts, "بنية الإيراد"))
        assert cost_stack([("واحد", 5.0)]) is None


class TestDataExtraction:
    def test_expense_components_positive_only(self):
        comps = dict(expense_components(_result(), "ar"))
        assert comps["تكلفة المبيعات"] == 1_980_579.58
        assert comps["مصاريف التمويل"] == 60_000.0
        assert "صافي الربح" not in comps  # net is NOT an expense slice

    def test_bullet_rows_normalise_against_anchors(self):
        rows = {r["key"]: r for r in ratio_bullet_rows(_result(), "ar")}
        # debt_ratio 38.5 vs anchor 70 (ceiling) → 70/38.5 = 1.82
        assert abs(rows["debt_ratio"]["norm"] - 1.82) < 0.01
        assert rows["debt_ratio"]["verdict"] == "good"
        # current_ratio 1.2 vs anchor 2.0 (floor) → 0.6
        assert abs(rows["current_ratio"]["norm"] - 0.6) < 0.01
        # negatives never enter the chart
        assert all(r["norm"] >= 0 for r in rows.values())

    def test_cost_composition_splits_revenue(self):
        # loss-making file: costs exceed revenue → no composition bar
        assert cost_composition(_result(), "ar") == []
        # profitable file: cogs + opex + net tile the revenue exactly
        r = _result()
        r["metrics"] = {
            "revenue": [4_820_000.0], "cogs": [2_834_000.0],
            "opex": [980_000.0], "net_profit": [1_006_000.0],
        }
        parts = cost_composition(r, "ar")
        total = sum(v for _, v in parts)
        assert abs(total - 4_820_000.0) < 1.0
        labels = [lbl for lbl, _ in parts]
        assert "تكلفة المبيعات" in labels and "صافي الربح" in labels

    def test_payload_shape(self):
        data = dashboard_payload(_result(), "ar", SCORE)
        assert data["score"] == 58.0
        assert data["grade_label"] == "مقبول"
        assert data["trends"][0]["concept"] == "revenue"
        assert data["period_labels"] == ["2021", "2022", "2023", "2024"]


class TestReportIntegration:
    def test_pdf_carries_the_dashboard_section(self, tmp_path):
        from app.report import build_report

        out = tmp_path / "dash.pdf"
        build_report(filename="dash.xlsx", result=_result(), out_path=out,
                     lang="ar", score=SCORE)
        assert out.exists() and out.stat().st_size > 60_000  # charts embedded

        import pdfplumber
        with pdfplumber.open(str(out)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            images = sum(len(p.images) for p in pdf.pages)
        from bidi.algorithm import get_display
        import arabic_reshaper

        def _shape(s):
            return get_display(arabic_reshaper.reshape(s))

        assert _shape("لوحة المؤشرات التحليلية").replace(" ", "") \
            in text.replace(" ", "")
        assert images >= 3  # gauge + donut + bullets/stack/trend

    def test_pptx_gains_a_dashboard_slide_with_pictures(self, tmp_path):
        from app.pptx_report import build_pptx_report

        out = tmp_path / "dash.pptx"
        build_pptx_report(filename="dash.xlsx", result=_result(), out_path=out,
                          lang="ar", score=SCORE)
        z = zipfile.ZipFile(str(out))
        pics = 0
        for n in z.namelist():
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                pics += z.read(n).decode("utf-8", "ignore").count("<p:pic>")
        assert pics >= 3  # gauge + donut + composition bar


class TestActivityLines:
    """Working-capital heartbeat chart (DSO & inventory turnover) — the same
    compute_activity_series values the Excel activity chart draws, now in the
    reports' charts slide/section."""

    ACT = {
        "receivable_days": {"ar": "فترة التحصيل (يوم)", "en": "Collection Period (days)",
                            "values": [54.8, 60.8, 52.1]},
        "inventory_turnover": {"ar": "دوران المخزون (x)", "en": "Inventory Turnover (x)",
                               "values": [2.2, 2.5, 2.9]},
        "days_payable": {"ar": "فترة السداد (يوم)", "en": "Payment Period (days)",
                         "values": [50.5, 57.6, None]},
        "cash_conversion_cycle": {"ar": "دورة التحول النقدي (يوم)",
                                  "en": "Cash Conversion Cycle (days)",
                                  "values": [56.5, 65.9, None]},
    }

    def test_png_from_activity_series(self):
        assert _is_png(activity_lines(self.ACT, title="دورة التحول النقدي"))

    def test_degrades_on_partial_data(self):
        # single period = a dot, not a trend → no chart
        one = {k: {**s, "values": s["values"][:1]} for k, s in self.ACT.items()}
        assert activity_lines(one) is None
        assert activity_lines({}) is None
        assert activity_lines(None) is None
        # None holes are skipped, never plotted as zero — still renders
        assert _is_png(activity_lines(
            {"receivable_days": {"ar": "فترة التحصيل", "en": "DSO",
                                 "values": [10.0, None, 20.0]}}))

    def test_wired_from_compute_activity_series(self):
        from app.analyzer import compute_activity_series

        act = compute_activity_series({
            "revenue": [1_000_000.0, 1_200_000.0],
            "receivables": [150_000.0, 200_000.0],
            "inventory": [300_000.0, 330_000.0],
            "cogs": [650_000.0, 760_000.0],
            "payables": [90_000.0, 120_000.0],
        })
        assert "receivable_days" in act and "inventory_turnover" in act
        assert _is_png(activity_lines(act, title="دورة التحول النقدي"))

    def test_pdf_carries_the_activity_chart(self, tmp_path):
        import pdfplumber

        from app.report import build_report

        r = _result()
        r["metrics"] = {
            "revenue": [1_000_000.0, 1_200_000.0],
            "receivables": [150_000.0, 200_000.0],
            "inventory": [300_000.0, 330_000.0],
            "cogs": [650_000.0, 760_000.0],
            "payables": [90_000.0, 120_000.0],
        }
        out = tmp_path / "act.pdf"
        build_report(filename="act.xlsx", result=r, out_path=out, lang="ar")
        assert out.exists()
        with pdfplumber.open(str(out)) as pdf:
            images = sum(len(p.images) for p in pdf.pages)
        assert images >= 4  # gauge + donut + bullets/stack + the activity lines

    def test_pptx_carries_the_activity_chart(self, tmp_path):
        from app.pptx_report import build_pptx_report

        r = _result()
        r["metrics"] = {
            "revenue": [1_000_000.0, 1_200_000.0],
            "receivables": [150_000.0, 200_000.0],
            "inventory": [300_000.0, 330_000.0],
            "cogs": [650_000.0, 760_000.0],
            "payables": [90_000.0, 120_000.0],
        }
        out = tmp_path / "act.pptx"
        build_pptx_report(filename="act.xlsx", result=r, out_path=out, lang="ar")
        z = zipfile.ZipFile(str(out))
        pics = 0
        for n in z.namelist():
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                pics += z.read(n).decode("utf-8", "ignore").count("<p:pic>")
        assert pics >= 4  # gauge + donut + composition + the activity lines


class TestRevenueTrend:
    """The web analytics dashboard's revenue trend + forecast — the deck's
    trend_line slide, served by /dashboard as revenue_trend."""

    def test_payload_includes_revenue_trend_matching_deck(self):
        from app.advisor import _forecast_horizon

        res = _result()
        payload = dashboard_payload(res, "ar", SCORE)
        rt = payload["revenue_trend"]
        assert rt is not None
        assert rt["values"] == [2_800_000.0, 2_950_000.0, 3_100_000.0, 3_153_287.03]
        assert rt["label"] == "الإيرادات"
        assert rt["period_labels"] == ["2021", "2022", "2023", "2024"]
        # SAME forecast methodology as the deck's evolution slide: the
        # advisor's linear-regression projections
        deck = next(p for p in _forecast_horizon(res) if p["concept"] == "revenue")
        assert rt["projections"] == [{"value": p["value"]} for p in deck["projections"]]

    def test_projection_values_follow_linear_regression(self):
        payload = dashboard_payload(_result(), "en", SCORE)
        rt = payload["revenue_trend"]
        assert rt["label"] == "Revenue"
        vals = rt["values"]
        n = len(vals)
        xs = list(range(n))
        mx = sum(xs) / n
        my = sum(vals) / n
        denom = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / denom
        assert rt["projections"][0]["value"] == round(vals[-1] + slope, 2)
        assert rt["projections"][1]["value"] == round(vals[-1] + 2 * slope, 2)

    def test_no_trend_for_single_period(self):
        res = _result()
        res["series"]["revenue"]["values"] = [100.0]
        assert dashboard_payload(res, "ar", SCORE)["revenue_trend"] is None

    def test_dashboard_endpoint_serves_revenue_trend(self, client):
        aid = client.post("/api/demo").json()["id"]
        body = client.get(f"/api/analyses/{aid}/dashboard?lang=ar").json()
        rt = body["revenue_trend"]
        assert rt["values"] == [12_000_000.0, 15_000_000.0]
        # demo revenue [12M, 15M]: slope = 3M → projections 18M, 21M
        assert [p["value"] for p in rt["projections"]] == [18_000_000.0, 21_000_000.0]
