"""Benchmark-alignment summary (مواءمة معيارية) tests.

Each computed ratio is compared against its reference anchor (the ideal
current ratio of 2, interest coverage of 3x, collection within 90 days...)
with a colour-coded verdict, and the section renders into the PDF report.
"""

import io

from app.analyzer import compute_ratios
from app.ratio_explain import build_benchmark_alignment
from app.report import build_report


def _rich_metrics():
    return {
        "revenue": [1_200_000.0],
        "cogs": [720_000.0],
        "opex": [60_000.0],
        "gross_profit": [480_000.0],
        "net_profit": [180_000.0],
        "assets": [830_000.0],
        "liabilities": [150_000.0],
        "equity": [680_000.0],
        "cash": [400_000.0],
        "receivables": [250_000.0],
        "inventory": [180_000.0],
        "current_assets": [830_000.0],
        "finance_cost": [40_000.0],
    }


def _alignment(ratios=None):
    result = {"ratios": ratios if ratios is not None else compute_ratios(_rich_metrics())}
    return build_benchmark_alignment(result)


class TestAlignmentData:
    def test_none_without_ratios(self):
        assert build_benchmark_alignment({"ratios": {}}) is None
        assert build_benchmark_alignment({}) is None

    def test_covers_key_anchors(self):
        alignment = _alignment()
        by_key = {r["key"]: r for r in alignment["rows"]}
        for key in ("current_ratio", "interest_coverage", "receivable_days",
                    "debt_ratio", "inventory_turnover"):
            assert key in by_key

    def test_benchmark_texts(self):
        by_key = {r["key"]: r for r in _alignment()["rows"]}
        assert "2.0" in by_key["current_ratio"]["benchmark"]
        assert "3.0" in by_key["interest_coverage"]["benchmark"]
        assert "90" in by_key["receivable_days"]["benchmark"]

    def test_value_units(self):
        by_key = {r["key"]: r for r in _alignment()["rows"]}
        assert by_key["current_ratio"]["value"].endswith("x")
        assert by_key["gross_margin"]["value"].endswith("%")
        assert by_key["receivable_days"]["value"].endswith("يوم")

    def test_verdicts_match_thresholds(self):
        by_key = {r["key"]: r for r in _alignment()["rows"]}
        # 830k current assets vs 150k liabilities → current ratio 5.53 ≥ 2
        assert by_key["current_ratio"]["verdict"] == "good"
        assert by_key["current_ratio"]["symbol"] == "✓"
        # receivable days = 250k*365/1.2M ≈ 76 → near the ≤45/≤90 band
        assert by_key["receivable_days"]["verdict"] == "neutral"
        assert by_key["receivable_days"]["symbol"] == "≈"

    def test_off_benchmark_case(self):
        ratios = compute_ratios({
            "revenue": [1_000_000.0], "cogs": [400_000.0],
            "receivables": [300_000.0],  # 109.5 days → off benchmark
        })
        rows = {r["key"]: r for r in build_benchmark_alignment({"ratios": ratios})["rows"]}
        assert rows["receivable_days"]["verdict"] == "bad"
        assert rows["receivable_days"]["symbol"] == "✗"

    def test_bilingual_rows(self):
        ar = _alignment()
        en = build_benchmark_alignment(
            {"ratios": compute_ratios(_rich_metrics())}, lang="en")
        ar_by = {r["key"]: r for r in ar["rows"]}
        en_by = {r["key"]: r for r in en["rows"]}
        assert ar_by["current_ratio"]["status"] == "مستوفٍ"
        assert en_by["current_ratio"]["status"] == "Aligned"
        assert ar_by["current_ratio"]["benchmark"] != en_by["current_ratio"]["benchmark"]


class TestPdfIntegration:
    def test_pdf_renders_with_alignment_section(self, tmp_path):
        result = {
            "kpis": {
                "revenue": {"value": 1_200_000.0, "en": "Revenue", "ar": "الإيرادات"},
                "net_profit": {"value": 180_000.0, "en": "Net Profit", "ar": "صافي الربح"},
            },
            "ratios": compute_ratios(_rich_metrics()),
            "metrics": _rich_metrics(),
            "series": {},
            "forecast": [],
            "tables_found": 1,
            "texts_found": 0,
            "analysed_at": None,
        }
        out = tmp_path / "bench.pdf"
        build_report(
            filename="bench.xlsx",
            result=result,
            out_path=out,
            lang="ar",
            ratio_insights=None,
        )
        assert out.exists() and out.stat().st_size > 10_000

        import pdfplumber
        with pdfplumber.open(str(out)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        from bidi.algorithm import get_display
        import arabic_reshaper

        def _shape(s):
            return get_display(arabic_reshaper.reshape(s))

        flat = "".join(text.split())
        assert _shape("المعايير المرجعية") in flat or "2.0" in flat
        # the anchor texts made it to the page
        assert "3.0" in flat and "90" in flat
