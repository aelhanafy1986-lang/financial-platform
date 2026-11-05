"""IFRS 18 income-statement classification tests (effective 1 Jan 2027).

The built statements classify income-statement items into the IFRS 18
categories (operating / investing / financing / taxes) and present the
defined subtotals: Operating Profit and Profit before Financing and
Income Taxes. Without such items the face reduces to the classic
five-line statement, so legacy behaviour is unchanged.
"""

from app.audit import run_quality_gate, validate_statements
from app.statements import build_statements, metrics_from_statements


def _tb_with_categories():
    return [
        ["النقدية بالبنك", 700_000, 0],
        ["مدينون - العملاء", 85_000, 0],
        ["رأس المال", 0, 500_000],
        ["ايرادات المبيعات", 0, 1_000_000],
        ["تكلفة المبيعات", 600_000, 0],
        ["مصاريف رواتب", 80_000, 0],
        ["فوائد قروض", 40_000, 0],        # financing (was swallowed by loans rule)
        ["عوائد ودائع بنكية", 0, 15_000],  # investing income (credit side)
        ["زكاة الدخل", 10_000, 0],         # taxes
    ]


class TestClassification:
    def test_category_buckets(self):
        out = build_statements(_tb_with_categories())
        totals = out["income_statement"]["totals"]
        assert totals["revenue"] == 1_000_000
        assert totals["gross_profit"] == 400_000
        assert totals["operating_profit"] == 320_000
        assert totals["investment_income"] == 15_000
        assert totals["finance_cost"] == 40_000
        assert totals["tax_expense"] == 10_000
        assert totals["profit_before_financing_taxes"] == 295_000
        assert totals["net_profit"] == 285_000

    def test_face_order_and_categories(self):
        out = build_statements(_tb_with_categories())
        lines = out["income_statement"]["lines"]
        names = [ln["en"] for ln in lines]
        assert names == [
            "Revenue", "Cost of Sales", "Gross Profit", "Operating Expenses",
            "Operating Profit", "Investment Income", "Finance Costs",
            "Profit before Financing and Income Taxes",
            "Zakat and Income Tax", "Net Profit",
        ]
        cats = {ln["en"]: ln.get("category") for ln in lines}
        assert cats["Revenue"] == "operating"
        assert cats["Investment Income"] == "investing"
        assert cats["Finance Costs"] == "financing"
        assert cats["Zakat and Income Tax"] == "taxes"
        # subtotals are bold
        for name in ("Operating Profit", "Gross Profit",
                     "Profit before Financing and Income Taxes", "Net Profit"):
            assert next(ln for ln in lines if ln["en"] == name)["bold"]

    def test_ifrs18_metadata(self):
        out = build_statements(_tb_with_categories())
        meta = out["income_statement"]["ifrs18"]
        assert meta["applied"] is True
        assert "2027" in meta["note"]["en"] and "2027" in meta["note"]["ar"]

    def test_balance_sheet_identity_holds(self):
        out = build_statements(_tb_with_categories())
        bs = out["balance_sheet"]
        assert bs["balanced"] is True
        assert bs["assets"]["total"] == 785_000
        # liabilities only from equity + net profit (no misclassified loans)
        assert bs["liabilities_equity"]["total"] == 785_000
        # trial balance balanced
        assert out["trial_balance"]["balanced"] is True

    def test_interest_on_loans_pulled_from_loans_bucket(self):
        """«فوائد قروض» is interest expense, not the loan principal."""
        out = build_statements(_tb_with_categories())
        # no loans balance on the BS (the loan itself is not in this TB)
        assert all(not ln.get("bold") or True for ln in [])
        loans_line = next(
            (ln for ln in out["balance_sheet"]["liabilities_equity"]["lines"]
             if ln["en"] == "Loans"), None)
        assert loans_line is None
        # and the detail carries the finance-cost account
        detail = out["income_statement"]["detail"]["finance_cost"]
        assert detail[0]["account"] == "فوائد قروض"
        assert detail[0]["amount"] == 40_000

    def test_vat_never_income_tax(self):
        rows = _tb_with_categories() + [["ضريبة القيمة المضافة", 0, 5_000]]
        rows[0][1] += 5_000  # keep the TB balanced (cash absorbs the credit)
        out = build_statements(rows)
        detail = out["income_statement"]["detail"].get("tax_expense", [])
        accounts = [ln["account"] for ln in detail]
        assert "ضريبة القيمة المضافة" not in accounts
        assert "زكاة الدخل" in accounts  # the genuine zakat stays classified

    def test_legacy_face_without_category_items(self):
        rows = [
            ["النقدية بالبنك", 500_000, 0],
            ["مدينون - العملاء", 220_000, 0],
            ["رأس المال", 0, 400_000],
            ["ايرادات المبيعات", 0, 1_000_000],
            ["تكلفة المبيعات", 600_000, 0],
            ["مصاريف رواتب", 80_000, 0],
        ]
        out = build_statements(rows)
        isx = out["income_statement"]
        # face gains only the Operating Profit subtotal; no category rows
        names = [ln["en"] for ln in isx["lines"]]
        assert names == [
            "Revenue", "Cost of Sales", "Gross Profit", "Operating Expenses",
            "Operating Profit", "Net Profit",
        ]
        totals = isx["totals"]
        assert totals["operating_profit"] == totals["net_profit"] == 320_000
        assert "finance_cost" not in totals and "tax_expense" not in totals
        assert isx["ifrs18"]["applied"] is False
        # new note present (basis first, balance-checks last preserved)
        notes = out["notes"]
        assert notes[0]["en"] == "Basis of preparation"
        assert notes[1]["en"] == "Income statement classification per IFRS 18"
        assert "balanced" in notes[-1]["text_en"]


class TestValidationAndMetrics:
    def test_validate_statements_pass_with_categories(self):
        out = build_statements(_tb_with_categories())
        assert validate_statements(out) == []

    def test_validate_statements_catches_broken_chain(self):
        out = build_statements(_tb_with_categories())
        out["income_statement"]["totals"]["net_profit"] = 999_999.0
        assert any("قائمة الدخل" in p for p in validate_statements(out))

    def test_validate_statements_catches_operating_subtotal(self):
        out = build_statements(_tb_with_categories())
        out["income_statement"]["totals"]["operating_profit"] = 1.0
        assert any("الربح التشغيلي" in p for p in validate_statements(out))

    def test_metrics_carry_category_concepts(self):
        out = build_statements(_tb_with_categories())
        metrics = metrics_from_statements(out)
        assert metrics["net_profit"] == [285_000]
        assert metrics["finance_cost"] == [40_000]
        assert metrics["tax_expense"] == [10_000]
        assert metrics["investment_income"] == [15_000]


class TestGateIntegration:
    def test_gate_passes_chain_without_repairs(self):
        """The quality gate must use the IFRS 18 chain, not force
        net = gross − opex (which would corrupt the tax/finance items)."""
        out = build_statements(_tb_with_categories())
        metrics = metrics_from_statements(out)
        result = {"metrics": metrics}
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert report["repairs"] == 0
        assert result["kpis"]["net_profit"]["value"] == 285_000
        assert result["metrics"]["net_profit"] == [285_000]

    def test_gate_repairs_broken_chain(self):
        out = build_statements(_tb_with_categories())
        metrics = metrics_from_statements(out)
        metrics["net_profit"] = [250_000]  # inconsistent with the chain
        result = {"metrics": metrics}
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert result["metrics"]["net_profit"] == [285_000]

    def test_check_only_flags_broken_chain_without_mutation(self):
        out = build_statements(_tb_with_categories())
        metrics = metrics_from_statements(out)
        metrics["net_profit"] = [250_000]
        result = {"metrics": metrics}
        run_quality_gate(result, apply_repairs=False)
        assert result["metrics"]["net_profit"] == [250_000]
        assert any(i["code"] == "R3" for i in result["audit"]["warnings"])
