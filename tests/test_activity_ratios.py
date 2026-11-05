"""Activity ratios from built-statement balances (analysis methodology).

Receivables turnover, collection period (days) and inventory turnover are
computed ONLY from real statement balances carried into the metrics block.
Missing buckets never produce a guess. The working-capital cycle completes
the picture: payables turnover, payment period (DPO) and the composite
cash conversion cycle (CCC = DSO + DIO − DPO).
"""

from app.analyzer import compute_ratios
from app.ifrs import RATIO_STANDARDS
from app.ratio_explain import DAYS_KEYS, build_benchmark_alignment, build_ratio_insights
from app.statements import build_statements, metrics_from_statements


def _tb():
    return [
        ["النقدية بالبنك", 400_000, 0],
        ["مدينون - العملاء", 250_000, 0],
        ["مخزون", 180_000, 0],
        ["الدائنون - الموردون", 0, 150_000],
        ["رأس المال", 0, 500_000],
        ["ايرادات المبيعات", 0, 960_000],
        ["تكلفة المبيعات", 720_000, 0],
        ["مصاريف رواتب", 60_000, 0],
    ]


class TestMetricsFromStatements:
    def test_activity_balances_carried(self):
        out = build_statements(_tb())
        metrics = metrics_from_statements(out)
        assert metrics["receivables"] == [250_000]
        assert metrics["inventory"] == [180_000]
        # current pool = cash + receivables + inventory
        assert metrics["current_assets"] == [830_000]

    def test_absent_buckets_not_guessed(self):
        rows = [r for r in _tb() if "مخزون" not in str(r[0])]
        rows[1][1] += 180_000  # keep the TB balanced
        out = build_statements(rows)
        metrics = metrics_from_statements(out)
        assert "inventory" not in metrics
        assert "receivables" in metrics


class TestActivityRatios:
    def _metrics(self):
        return {
            "revenue": [1_200_000.0],
            "cogs": [720_000.0],
            "receivables": [250_000.0],
            "inventory": [180_000.0],
        }

    def test_turnover_and_days(self):
        ratios = compute_ratios(self._metrics())
        assert ratios["receivables_turnover"]["value"] == 4.8  # 1.2M / 250k
        assert ratios["receivable_days"]["value"] == 76.04  # 250k*365/1.2M
        assert ratios["inventory_turnover"]["value"] == 4.0  # 720k / 180k
        assert ratios["receivable_days"]["ar"] == "فترة التحصيل (يوم)"

    def test_skipped_without_balances(self):
        ratios = compute_ratios({"revenue": [1_000_000.0], "cogs": [400_000.0]})
        for key in ("receivables_turnover", "receivable_days", "inventory_turnover"):
            assert key not in ratios

    def test_zero_balances_skipped(self):
        ratios = compute_ratios({
            "revenue": [1_000_000.0], "cogs": [400_000.0],
            "receivables": [0], "inventory": [0],
        })
        for key in ("receivables_turnover", "receivable_days", "inventory_turnover"):
            assert key not in ratios

    def test_from_built_statements_end_to_end(self):
        out = build_statements(_tb())
        assert out["trial_balance"]["balanced"] is True
        metrics = metrics_from_statements(out)
        ratios = compute_ratios(metrics)
        assert ratios["receivables_turnover"]["value"] == 3.84  # 960k / 250k
        assert ratios["inventory_turnover"]["value"] == 4.0  # 720k / 180k
        # bonus: liquidity ratios now work on TB-built analyses too
        assert abs(ratios["current_ratio"]["value"] - 830_000 / 150_000) < 0.01
        assert ratios["quick_ratio"]["value"] > 0


class TestCardsAndReferences:
    def _result(self, key, value):
        return {"ratios": {key: {"value": value}}, "metrics": {}}

    def test_days_card_rendered_in_days(self):
        cards = build_ratio_insights(self._result("receivable_days", 76.04))
        card = cards[0]
        assert card["key"] == "receivable_days"
        assert card["is_days"] is True and card["is_percent"] is False

    def test_days_verdict_inverted(self):
        assert build_ratio_insights(self._result("receivable_days", 30))[0]["verdict"] == "good"
        assert build_ratio_insights(self._result("receivable_days", 76.04))[0]["verdict"] == "neutral"
        assert build_ratio_insights(self._result("receivable_days", 120))[0]["verdict"] == "bad"

    def test_turnover_cards(self):
        assert build_ratio_insights(self._result("receivables_turnover", 6.0))[0]["verdict"] == "neutral"
        assert build_ratio_insights(self._result("receivables_turnover", 2.0))[0]["verdict"] == "bad"
        assert build_ratio_insights(self._result("inventory_turnover", 1.0))[0]["verdict"] == "bad"

    def test_standard_references_registered(self):
        for key in ("receivables_turnover", "receivable_days", "inventory_turnover"):
            assert key in RATIO_STANDARDS
        assert "IFRS 9" in RATIO_STANDARDS["receivables_turnover"]["code"]
        assert "IAS 2" in RATIO_STANDARDS["inventory_turnover"]["code"]

    def test_bilingual_card_texts(self):
        result = self._result("receivable_days", 76.04)
        ar = build_ratio_insights(result, lang="ar")[0]
        en = build_ratio_insights(dict(result), lang="en")[0]
        assert ar["what"] and en["what"] and ar["what"] != en["what"]
        assert "IFRS 9" in ar["ifrs"]


class TestWorkingCapitalCycle:
    """دوران الدائنين، فترة السداد (DPO) ودورة التحول النقدي (CCC)."""

    def _metrics(self):
        return {
            "revenue": [960_000.0],
            "cogs": [720_000.0],
            "receivables": [250_000.0],
            "inventory": [180_000.0],
            "payables": [150_000.0],
        }

    def test_payables_carried_from_built_statements(self):
        out = build_statements(_tb())
        metrics = metrics_from_statements(out)
        assert metrics["payables"] == [150_000]

    def test_turnover_dpo_inventory_days(self):
        ratios = compute_ratios(self._metrics())
        assert ratios["payables_turnover"]["value"] == 4.8  # 720k / 150k
        assert abs(ratios["days_payable"]["value"] - 76.04) < 0.01  # 150k*365/720k
        assert abs(ratios["inventory_days"]["value"] - 91.25) < 0.01  # 180k*365/720k
        assert ratios["payables_turnover"]["ar"] == "دوران الدائنين (x)"
        assert ratios["days_payable"]["ar"] == "فترة السداد (يوم)"

    def test_ccc_composite_from_displayed_components(self):
        """CCC = collection + inventory − payment days (displayed values)."""
        ratios = compute_ratios(self._metrics())
        dso = ratios["receivable_days"]["value"]
        dio = ratios["inventory_days"]["value"]
        dpo = ratios["days_payable"]["value"]
        ccc = ratios["cash_conversion_cycle"]
        assert abs(ccc["value"] - (dso + dio - dpo)) < 0.011
        assert ccc["value"] == 110.26  # 95.05 + 91.25 − 76.04
        assert ccc["en"] == "Cash Conversion Cycle (days)"

    def test_negative_ccc_allowed(self):
        """Supplier credit longer than the operating cycle → negative CCC
        (the best case) — never suppressed."""
        ratios = compute_ratios({
            "revenue": [1_000_000.0], "cogs": [500_000.0],
            "receivables": [27_397.26],   # ≈ 10 days
            "inventory": [27_397.26],     # ≈ 20 days on cogs
            "payables": [82_191.78],      # ≈ 60 days on cogs
        })
        assert ratios["cash_conversion_cycle"]["value"] < 0

    def test_skipped_without_payables(self):
        m = self._metrics()
        del m["payables"]
        ratios = compute_ratios(m)
        for key in ("payables_turnover", "days_payable", "cash_conversion_cycle"):
            assert key not in ratios
        # inventory_days still stands on its own
        assert abs(ratios["inventory_days"]["value"] - 91.25) < 0.01

    def test_zero_and_missing_components_gate_ccc(self):
        ratios = compute_ratios({"revenue": [1_000_000.0], "cogs": [500_000.0],
                                 "payables": [0]})
        assert "payables_turnover" not in ratios
        ratios = compute_ratios({"revenue": [1_000_000.0], "cogs": [500_000.0],
                                 "payables": [100_000.0], "inventory": [50_000.0]})
        # DPO + DIO exist but no DSO → the composite must not be guessed
        assert "days_payable" in ratios and "inventory_days" in ratios
        assert "cash_conversion_cycle" not in ratios

    def test_end_to_end_from_built_statements(self):
        out = build_statements(_tb())
        ratios = compute_ratios(metrics_from_statements(out))
        assert ratios["payables_turnover"]["value"] == 4.8
        assert abs(ratios["cash_conversion_cycle"]["value"] - 110.26) < 0.011

    def test_day_units_registered(self):
        for key in ("inventory_days", "days_payable", "cash_conversion_cycle"):
            assert key in DAYS_KEYS
            assert key in RATIO_STANDARDS

    def test_verdicts(self):
        def _r(key, value):
            return {"ratios": {key: {"value": value}}, "metrics": {}}

        # DPO: longer is better (default floor branch)
        assert build_ratio_insights(_r("days_payable", 76.04))[0]["verdict"] == "good"
        assert build_ratio_insights(_r("days_payable", 10.0))[0]["verdict"] == "bad"
        assert build_ratio_insights(_r("days_payable", 20.0))[0]["verdict"] == "neutral"
        # payables turnover & days: lower is better (inverted branch)
        assert build_ratio_insights(_r("payables_turnover", 4.8))[0]["verdict"] == "good"
        assert build_ratio_insights(_r("payables_turnover", 30.0))[0]["verdict"] == "bad"
        assert build_ratio_insights(_r("inventory_days", 91.25))[0]["verdict"] == "bad"
        # CCC: negative is the best case, > 180 is off benchmark
        assert build_ratio_insights(_r("cash_conversion_cycle", -30.0))[0]["verdict"] == "good"
        assert build_ratio_insights(_r("cash_conversion_cycle", 110.26))[0]["verdict"] == "neutral"
        assert build_ratio_insights(_r("cash_conversion_cycle", 200.0))[0]["verdict"] == "bad"

    def test_days_cards_flagged(self):
        card = build_ratio_insights({"ratios": {"days_payable": {"value": 76.04}},
                                     "metrics": {}})[0]
        assert card["is_days"] is True and card["is_percent"] is False

    def test_benchmark_alignment_rows(self):
        result = {"ratios": {
            "payables_turnover": {"value": 4.8},
            "days_payable": {"value": 76.04},
            "cash_conversion_cycle": {"value": 110.26},
        }, "metrics": {}}
        for lang in ("ar", "en"):
            by_key = {r["key"]: r
                      for r in build_benchmark_alignment(result, lang)["rows"]}
            assert by_key["days_payable"]["value"].endswith("يوم" if lang == "ar" else "days")
            assert by_key["days_payable"]["verdict"] == "good"
            assert by_key["payables_turnover"]["verdict"] == "good"
            assert by_key["cash_conversion_cycle"]["verdict"] == "neutral"
