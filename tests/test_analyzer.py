"""Tests for the financial analysis engine (app/analyzer.py).

Uses Arabic and English multi-year statements, mirroring real files, plus a
single-column P&L (like the Shawarma report) where profit lines must be
derived from detail rows and losses keep their negative sign.
"""

from app.analyzer import (
    _extract_metrics,
    _to_number,
    analyze,
    compute_kpis,
    compute_ratios,
    compute_series,
    forecast,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class TestToNumberRatioArtifacts:
    """Cached-formula RATIO cells (openpyxl data_only floats, or their
    pasted-as-text twins) must never be read as financial amounts: the
    «الراشد January-2026» workbook carries «=C6/C5» → -0.6413145167662294
    inside the «الإيراد» row, which leaked a phantom value into the
    revenue series next to 762,284.99."""

    def test_cached_formula_float_ratio_rejected(self):
        assert _to_number(-0.6413145167662294) is None
        assert _to_number(0.6491467824748406) is None

    def test_pasted_text_ratio_rejected(self):
        assert _to_number("0.6413145167662294") is None
        assert _to_number("-0.6413145167662294") is None
        assert _to_number("-.641") is None

    def test_real_amounts_and_short_decimals_kept(self):
        assert _to_number(762_284.99) == 762_284.99
        assert _to_number("-0.02") == -0.02
        assert _to_number(0.5) == 0.5
        assert _to_number("1,250,000") == 1_250_000.0

AR_ROWS = [
    ["البند", "2023", "2024", "2025"],
    ["الإيرادات", 3_100_000, 4_120_000, 4_820_000],
    ["تكلفة المبيعات", 1_900_000, 2_500_000, 2_834_000],
    ["الربح الإجمالي", 1_200_000, 1_620_000, 1_986_000],
    ["صافي الربح", 310_000, 505_000, 640_000],
    ["إجمالي الأصول", 7_200_000, 8_400_000, 9_150_000],
    ["إجمالي الالتزامات", 3_100_000, 3_500_000, 3_523_000],
    ["حقوق الملكية", 4_100_000, 4_900_000, 5_627_000],
    ["النقدية", 850_000, 980_000, 1_120_000],
]

EN_ROWS = [
    ["Item", "FY2023", "FY2024"],
    ["Revenue", "1,250,000", "1,480,000"],
    ["Cost of Sales", "710,000", "820,000"],
    ["Net Profit", "155,000", "198,000"],
    ["Total Assets", "2,300,000", "2,650,000"],
]

# Single-column P&L: computed lines present (margins, totals) — like the
# Shawarma profit-and-loss report the user uploaded.
PL_ROWS = [
    ["", "كشف أرباح وخسائر", "", "", ""],
    ["", "", "المبيعات", "", 4_663_364.45],
    ["", "", "تكلفة البضاعة المباعة", "", 2_851_080.18],
    ["", "", "مجمل الربح", "", 1_812_284.27],
    ["", "", "هامش الربح الإجمالي", "", 0.3886216248871563],
    ["", "", "إجمالي المصروفات", "", 2_595_270.28],
    ["", "", "الخسارة", "", -782_986.01],
    ["", "", "هامش صافي الربح", "", -0.16790152654699758],
    ["", "", "جاري الشركاء", "", 790_190],
]


def _ar_tables():
    return [{"name": "income", "rows": AR_ROWS}]


def _pl_tables():
    return [{"name": "pl", "rows": PL_ROWS}]


# ---------------------------------------------------------------------------
# number parsing
# ---------------------------------------------------------------------------

class TestToNumber:
    def test_plain_int(self):
        assert _to_number(4200) == 4200.0

    def test_float(self):
        assert _to_number(3.5) == 3.5

    def test_comma_string(self):
        assert _to_number("1,250,000") == 1250000.0

    def test_currency_string(self):
        assert _to_number("SAR 980,000") == 980000.0

    def test_arabic_context_string(self):
        assert _to_number("الإيرادات: 4,820,000 ريال") == 4820000.0

    def test_negative(self):
        assert _to_number("-12,500") == -12500.0

    def test_bool_rejected(self):
        assert _to_number(True) is None

    def test_empty_and_garbage(self):
        assert _to_number("") is None
        assert _to_number("لا يوجد") is None
        assert _to_number(None) is None


# ---------------------------------------------------------------------------
# metric extraction
# ---------------------------------------------------------------------------

class TestExtractMetrics:
    def test_arabic_multi_year_series(self):
        metrics = _extract_metrics(_ar_tables(), [])
        assert metrics["revenue"] == [3_100_000, 4_120_000, 4_820_000]
        assert metrics["cogs"] == [1_900_000, 2_500_000, 2_834_000]
        # derived/aggregate rows (مجمل الربح) are NOT captured raw — but the
        # STATED bottom line (صافي الربح) IS: post-profit allocation rows
        # (tax/manager %) make the derived chain diverge from the face's own
        # bottom line, so the stated series is the ground truth
        assert "net_profit" not in metrics or metrics["net_profit"] == [310_000, 505_000, 640_000]
        assert "gross_profit" not in metrics
        assert metrics["assets"] == [7_200_000, 8_400_000, 9_150_000]

    def test_cost_of_sales_not_confused_with_revenue(self):
        """Regression: 'تكلفة المبيعات' contains the generic word 'المبيعات'."""
        metrics = _extract_metrics(_ar_tables(), [])
        # three revenue values come only from the revenue row, not from cogs
        assert len(metrics["revenue"]) == 3
        assert 1_900_000 not in metrics["revenue"]

    def test_english_rows(self):
        metrics = _extract_metrics([{"name": "t", "rows": EN_ROWS}], [])
        assert metrics["revenue"] == [1_250_000, 1_480_000]
        assert metrics["cogs"] == [710_000, 820_000]
        # a bare "Net Profit" table row IS the stated figure — captured
        assert metrics["net_profit"] == [155_000, 198_000]

    def test_percentage_cells_skipped(self):
        rows = [["البند", "2025"], ["الإيرادات", "4,820,000", "13.3%"]]
        metrics = _extract_metrics([{"name": "t", "rows": rows}], [])
        assert metrics["revenue"] == [4_820_000]

    def test_text_lines_fallback(self):
        texts = ["Revenue: 5,000,000\nNet Profit 750,000"]
        metrics = _extract_metrics([], texts)
        assert metrics["revenue"][0] == 5_000_000
        # in free text a bare net-profit line IS the stated value
        assert metrics["net_profit"][0] == 750_000

    def test_single_column_pl_captures_details(self):
        """Shawarma-style sheet: sales, cost, expenses and partners captured;
        margins/totals/gross/loss lines excluded."""
        metrics = _extract_metrics(_pl_tables(), [])
        assert metrics["revenue"] == [4_663_364.45]
        assert metrics["cogs"] == [2_851_080.18]
        assert metrics["opex"] == [2_595_270.28]
        assert metrics["equity"] == [790_190]
        assert "net_profit" not in metrics
        assert "gross_profit" not in metrics
        # margins must never leak into revenue
        assert 0.3886216248871563 not in metrics["revenue"]


# ---------------------------------------------------------------------------
# kpis, ratios, series, forecast
# ---------------------------------------------------------------------------

class TestComputeKpis:
    def test_latest_values_with_bilingual_labels(self):
        metrics = _extract_metrics(_ar_tables(), [])
        kpis = compute_kpis(metrics)
        assert kpis["revenue"]["value"] == 4_820_000
        assert kpis["revenue"]["ar"] == "الإيرادات"
        assert kpis["revenue"]["en"] == "Revenue"
        assert kpis["cash"]["value"] == 1_120_000
        # the STATED bottom line (صافي الربح 640,000) outranks the derived
        # chain: the face's own net series is the ground truth — a chain
        # (gross − opex − tax) can never reproduce rows like manager % that
        # some statements carry below the tax line
        assert kpis["net_profit"]["value"] == 640_000

    def test_net_profit_from_detail_rows(self):
        metrics = _extract_metrics(_pl_tables(), [])
        kpis = compute_kpis(metrics)
        # 4,663,364.45 - 2,851,080.18 - 2,595,270.28 = -782,986.01 (a LOSS)
        assert round(kpis["net_profit"]["value"], 2) == -782_986.01
        assert kpis["net_profit"]["ar"] == "صافي الخسارة"
        assert kpis["net_profit"]["en"] == "Net Loss"
        assert kpis["revenue"]["value"] == 4_663_364.45

    def test_profit_keeps_positive_label(self):
        metrics = {"revenue": [1_000_000.0], "cogs": [400_000.0], "opex": [200_000.0]}
        kpis = compute_kpis(metrics)
        assert kpis["net_profit"]["value"] == 400_000
        assert kpis["net_profit"]["ar"] == "صافي الربح"
        assert kpis["net_profit"]["en"] == "Net Profit"


class TestComputeRatios:
    def test_full_arabic_statement(self):
        metrics = _extract_metrics(_ar_tables(), [])
        ratios = compute_ratios(metrics)
        assert ratios["gross_margin"]["value"] == 41.2
        # net margin from the STATED صافي الربح (640,000 / 4,820,000)
        assert ratios["net_margin"]["value"] == 13.28
        assert ratios["debt_ratio"]["value"] == 38.5
        assert ratios["debt_to_equity"]["value"] == 0.63

    def test_shawarma_net_margin_negative(self):
        metrics = _extract_metrics(_pl_tables(), [])
        ratios = compute_ratios(metrics)
        assert ratios["gross_margin"]["value"] == 38.86
        assert ratios["net_margin"]["value"] == -16.79

    def test_gross_derived_from_cogs_when_missing(self):
        metrics = {"revenue": [1000.0], "cogs": [600.0]}
        ratios = compute_ratios(metrics)
        assert ratios["gross_margin"]["value"] == 40.0

    def test_empty_metrics_give_no_ratios(self):
        assert compute_ratios({}) == {}


class TestSeriesAndForecast:
    def test_series_requires_two_or_more(self):
        metrics = _extract_metrics(_ar_tables(), [])
        series = compute_series(metrics)
        assert "revenue" in series and "assets" in series and "cogs" in series
        assert series["revenue"]["values"] == [3_100_000, 4_120_000, 4_820_000]

    def test_single_value_not_a_series(self):
        assert compute_series({"revenue": [100.0]}) == {}

    def test_forecast_direction_and_value(self):
        metrics = _extract_metrics(_ar_tables(), [])
        series = compute_series(metrics)
        fc = {item["concept"]: item for item in forecast(series)}
        assert fc["revenue"]["trend"] == "up"
        assert 15 < fc["revenue"]["change_pct"] < 30

    def test_downward_trend_detected(self):
        series = {"revenue": {"values": [1000.0, 800.0, 500.0], "en": "Revenue", "ar": "الإيرادات"}}
        fc = forecast(series)
        assert fc[0]["trend"] == "down"
        assert fc[0]["change_pct"] < -20


# ---------------------------------------------------------------------------
# end-to-end analyze()
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_cash_flow_ratios_from_cf_totals(self):
        """The cash-flow reference ratios (81/82/83/87) compute ONLY from a
        real captured OCF total, and stay absent without one — no guess."""
        from app.analyzer import compute_ratios

        base = {
            "revenue": [1_000_000.0], "net_profit": [280_000.0],
            "liabilities": [800_000.0], "current_liabilities": [250_000.0],
        }
        with_cf = dict(base, cf_operating=[350_000.0])
        r = compute_ratios(with_cf)
        assert r["ocf_margin"]["value"] == 35.0       # 350k / 1M
        assert r["ocf_to_debt"]["value"] == 0.44      # 350k / 800k
        assert r["ocf_liquidity"]["value"] == 1.4     # 350k / 250k
        assert r["earnings_quality"]["value"] == 1.25  # 350k / 280k

        r2 = compute_ratios(base)
        assert not any(k in r2 for k in
                       ("ocf_margin", "ocf_to_debt", "ocf_liquidity",
                        "earnings_quality"))

    def test_full_pipeline_arabic(self):
        result = analyze(_ar_tables(), [])
        assert result["tables_found"] == 1
        assert result["texts_found"] == 0
        assert len(result["kpis"]) == 4
        # the widened ratio set: the classic seven PLUS the extended
        # reference-guide additions computable from these buckets
        rr = result["ratios"]
        for k in ("gross_margin", "net_margin", "operating_margin",
                  "debt_ratio", "debt_to_equity",
                  "equity_ratio", "roa", "roe"):   # payload-dependent set
            assert k in rr, f"missing {k}"
        assert len(rr) >= 7
        assert len(result["series"]) >= 4
        assert result["forecast"]
        assert result["analysed_at"]

    def test_shawarma_pl_pipeline(self):
        """End-to-end on the single-column loss-making P&L."""
        result = analyze(_pl_tables(), [])
        kpis = result["kpis"]
        assert kpis["revenue"]["value"] == 4_663_364.45
        assert round(kpis["net_profit"]["value"], 2) == -782_986.01
        assert kpis["net_profit"]["ar"] == "صافي الخسارة"
        assert result["ratios"]["net_margin"]["value"] == -16.79

    def test_no_financial_data_is_handled(self):
        result = analyze([{"name": "t", "rows": [["اسم", "عمر"], ["أحمد", "30"]]}], ["نص عادي بلا أرقام"])
        assert result["kpis"] == {}
        assert result["ratios"] == {}
        assert result["series"] == {}
        assert result["forecast"] == []


class TestOcrNumberAccuracy:
    """Scanned-balance accuracy: glued digit fragments and the suspect-OCR
    pipeline (mirrors the al-Marāʾī OCR patterns «1872 2 2 58»/«19 575585»)."""

    def test_ocr_glued_digit_groups_healed(self):
        # ragged OCR fragments are one amount — rejoined before NUM_RE
        assert _to_number("1872 2 2 58") == 18_722_258.0
        assert _to_number("19 575585") == 19_575_585.0
        # proper thousand-grouping split by stray spaces
        assert _to_number("19 575 585") == 19_575_585.0
        # an Arabic letter riding along blocks healing ON PURPOSE (dates):
        # the cell reads its first fragment like any text cell
        assert _to_number("19 575585 ا") == 19.0
        assert _to_number("31 ديسمبر 2023") == 31.0
        assert _to_number("2023 م") == 2023.0
        # below the 6-digit amount range nothing is merged
        assert _to_number("1 2") == 1.0
        assert _to_number("1 500") == 1.0

    def test_ocr_suspect_series_reach_the_kpis_clean(self):
        rows = [
            ["Revenue", "", "19,575,585"],
            ["Net Profit", "", "1,872,258"],
            ["Tax expense", "", "249,659"],
        ]
        result = analyze([{"name": "p1_ocr", "rows": rows}], [])
        assert result["kpis"]["revenue"]["value"] == 19_575_585.0
        assert result["kpis"]["net_profit"]["value"] == 1_872_258.0
        # tax is captured as its own concept, never folded into profit
        assert result["metrics"]["tax_expense"] == [249_659.0]
