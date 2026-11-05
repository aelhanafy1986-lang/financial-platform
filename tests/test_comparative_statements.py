# -*- coding: utf-8 -*-
"""Comparative (two-period) statements — the شركة المتحدة regression.

A clean comparative workbook (income statement + balance sheet, columns
«عام 2024 | عام 2025 | نسبة التغير») used to be mis-read: the trailing
«التغير» column was captured as a THIRD period (assets ended at its change
value), decimal change ratios leaked into series (cogs ended at 0.267 →
inventory_days of 47.8 MILLION), «إجمالي المبيعات» / «صافي الربح» were
rejected as summary lines (no revenue at all), supplier/customer balances
were never classified (3 ratios only) and per-period expense detail rows
interleaved. Every fix is pinned here against the exact workbook shape.
"""

from app.analyzer import _extract_metrics, analyze
from app.ratio_explain import build_yearly_comparison


def _comparative_tables() -> list:
    """The المتحدة shape: one sheet, two comparative statements, each row =
    label | عام 2024 | عام 2025 | التغير (absolute or percentage)."""
    is_rows = [
        ["1️⃣ قائمة الدخل المقارنة (Comparative Income Statement)", "", "", ""],
        ["البند (Income Statement Items)", "عام 2024 (ريال)", "عام 2025 (ريال)", "نسبة التغير (%)"],
        ["إجمالي المبيعات (الإيرادات)", 500000, 650000, 0.3],
        ["تكلفة البضاعة المباعة", -300000, -380000, 0.267],
        ["مجمل الربح (Gross Profit)", 200000, 270000, 0.35],
        ["مصاريف بيعية وتوزيعية", -45000, -55000, 0.222],
        ["مصاريف إدارية وعمومية", -60000, -70000, 0.167],
        ["مصاريف الاستهلاك", -15000, -15000, 0],
        ["الربح التشغيلي (EBIT)", 80000, 130000, 0.625],
        ["مصاريف الفوائد البنكية", -10000, -12000, 0.2],
        ["الربح قبل الزكاة والضريبة", 70000, 118000, 0.686],
        ["الزكاة المقدرة", -7000, -11800, 0.686],
        ["صافي الربح (Net Income)", 63000, 106200, 0.686],
    ]
    bs_rows = [
        ["2️⃣ قائمة المركز المالي المقارنة (Comparative Balance Sheet)", "", "", ""],
        ["البند (Balance Sheet Items)", "عام 2024 (ريال)", "عام 2025 (ريال)", "التغير المطلق (ريال)"],
        ["الأصول المتداولة:", "", "", ""],
        ["النقدية وما يعادلها", 50000, 85000, 35000],
        ["ذمم مدينة (عملاء)", 75000, 110000, 35000],
        ["المخزون السلعي", 90000, 125000, 35000],
        ["إجمالي الأصول المتداولة", 215000, 320000, 105000],
        ["الأصول غير المتداولة (الثابتة):", "", "", ""],
        ["العقارات والآلات والمعدات", 400000, 450000, 50000],
        ["(ناقص) مجمع الاستهلاك", -60000, -75000, "(+15,000)"],
        ["صافي الأصول غير المتداولة", 340000, 375000, 35000],
        ["إجمالي الأصول (Total Assets)", 555000, 695000, 140000],
        ["الالتزامات المتداولة:", "", "", ""],
        ["ذمم دائنة (موردون)", 65000, 80000, 15000],
        ["قروض قصيرة الأجل", 40000, 30000, -10000],
        ["إجمالي الالتزامات المتداولة", 105000, 110000, 5000],
        ["الالتزامات غير المتداولة:", "", "", ""],
        ["قروض طويلة الأجل", 150000, 185000, 35000],
        ["إجمالي الالتزامات", 255000, 295000, 40000],
        ["حقوق الملكية:", "", "", ""],
        ["رأس المال المدفوع", 250000, 250000, 0],
        ["الأرباح المبقاة", 50000, 150000, 100000],
        ["إجمالي حقوق الملكية", 300000, 400000, 100000],
        ["إجمالي الالتزامات وحقوق الملكية", 555000, 695000, 140000],
    ]
    return [{"name": "Sheet1", "rows": is_rows}, {"name": "bs", "rows": bs_rows}]


def _analysis() -> dict:
    result = analyze(_comparative_tables(), [])
    # the API layer attaches the (sign-normalised) metrics block after
    # analyze — mirror it so consumers see the same shape
    from app.analyzer import _extract_metrics, _normalise_expense_signs

    m = _extract_metrics(_comparative_tables(), [])
    _normalise_expense_signs(m)
    result["metrics"] = m
    return result


class TestComparativeCapture:
    def _metrics(self) -> dict:
        return _extract_metrics(_comparative_tables(), [])

    def test_periods_only_no_change_column(self):
        m = self._metrics()
        # the trailing «التغير» column never becomes a third period and the
        # decimal change ratios (0.267 …) never leak into a series
        assert m["assets"] == [555000.0, 695000.0]
        assert m["cash"] == [50000.0, 85000.0]
        assert m["cogs"] == [-300000.0, -380000.0]
        assert 0.267 not in m["cogs"] and 140000.0 not in m["assets"]

    def test_natural_titles_accepted(self):
        m = self._metrics()
        assert m["revenue"] == [500000.0, 650000.0]      # «إجمالي المبيعات»
        assert m["current_assets"] == [215000.0, 320000.0]

    def test_working_capital_balances_from_file_bs(self):
        m = self._metrics()
        assert m["receivables"] == [75000.0, 110000.0]   # «ذمم مدينة (عملاء)»
        assert m["payables"] == [65000.0, 80000.0]       # «ذمم دائنة (موردون)»
        assert m["inventory"] == [90000.0, 125000.0]


        m = self._metrics()
        assert m["finance_cost"] == [-10000.0, -12000.0]  # not sunk into opex
        assert m["tax_expense"] == [-7000.0, -11800.0]

    def test_expense_rows_sum_per_period(self):
        m = self._metrics()
        # بيعية + إدارية + استهلاك per YEAR, not interleaved
        assert m["opex"] == [-120000.0, -140000.0]

    def test_section_subtotals_never_pollute_totals(self):
        m = self._metrics()
        assert m["liabilities"] == [255000.0, 295000.0]   # not the current part
        assert 555000.0 not in m["equity"]                # combined closing line
        assert m["equity"] == [300000.0, 400000.0]


class TestComparativeAnalysis:
    def test_full_ratio_set(self):
        r = _analysis()
        expected = {
            "gross_margin": 41.54, "net_margin": 16.34,
            "debt_ratio": 42.45, "debt_to_equity": 0.74,
            "current_ratio": 2.91, "quick_ratio": 1.77,  # ÷ CURRENT liabilities
            "roa": 15.28, "roe": 26.55, "asset_turnover": 0.94,
            "interest_coverage": 9.85,
            "receivables_turnover": 5.91, "receivable_days": 61.77,
            "inventory_turnover": 3.04, "inventory_days": 120.07,
            "payables_turnover": 4.75, "days_payable": 76.84,
            "cash_conversion_cycle": 105.0,
        }
        for key, value in expected.items():
            assert r["ratios"][key]["value"] == value, key

    def test_net_profit_exact(self):
        r = _analysis()
        assert r["kpis"]["net_profit"]["value"] == 106200.0
        assert r["kpis"]["revenue"]["value"] == 650000.0

    def test_period_labels_from_comparative_headers(self):
        assert _analysis()["period_labels"] == ["2024", "2025"]

    def test_yearly_comparison_is_full(self):
        """The horizontal/vertical analysis covers every face of both
        statements (this file's comparison used to be thin)."""
        comp = build_yearly_comparison(_analysis(), "ar")
        keys = {row["key"] for row in comp["rows"]}
        assert {"revenue", "cogs", "opex", "net_profit", "assets",
                "liabilities", "equity"} <= keys
        by_key = {row["key"]: row for row in comp["rows"]}
        assert by_key["revenue"]["curr"] == "650,000"
        assert by_key["revenue"]["prev"] == "500,000"
        assert by_key["opex"]["curr"] == "140,000"   # summed, not interleaved
        # the derived bottom line tracks the statement exactly
        assert by_key["net_profit"]["curr"] == "106,200"
        assert by_key["net_profit"]["prev"] == "63,000"


class TestTbAndParens:
    def test_tb_tables_skip_customer_supplier_buckets(self):
        """A trial balance keeps owning its buckets via the statements
        builder — the generic capture must not read debit/credit as periods
        (the second column would zero the balances)."""
        tb = [
            ["الحساب", "مدين", "دائن"],
            ["مدينون - العملاء", 250000, 0],
            ["الدائنون - الموردون", 0, 150000],
            ["النقدية بالبنك", 400000, 0],
        ]
        m = _extract_metrics([{"name": "tb", "rows": tb}], [])
        assert "receivables" not in m
        assert "payables" not in m
        assert m["cash"] == [400000.0]  # trailing credit ZERO dropped

    def test_accounting_parentheses_are_negative(self):
        m = _extract_metrics(
            [{"name": "t", "rows": [["مصاريف الاستهلاك", -15000, "(15,000)"]]}], [])
        assert m["opex"] == [-15000.0, -15000.0]


class TestScannedFaceScoping:
    """المراعي regression: a scanned report's faces are SEPARATE OCR tables
    (one per page). Cross-face pollution used to corrupt the statements —
    the BS page's expense-labelled ASSETS fed opex, the P&L page's finance
    cost fed liabilities, and OCR's dropped parentheses mixed signs into
    the per-column expense sums. Also pinned: the glued date «312023» is a
    date, not a year-column header."""

    @staticmethod
    def _scanned_tables() -> list:
        is_rows = [
            ["شركة المراعي", "", "", "", ""],
            ["قائمة الربح أو الخسارة الموحدة", "", "", "", ""],
            ["للسنة المنتهية في", "312023", "", "", ""],
            ["إيرادات 33", "0", "19575585", "0", "18722258"],
            ["تكلفة الإيرادات 27", "0", "13524295", "0", "13098035"],
            ["مصاريف بيع وبورنيج 28", "0", "(2789745)", "0", "(2709538)"],
            ["مصاريف عمومية وإدارية 29", "0", "469022", "0", "458694"],
            ["زكاة 25", "0", "0", "0", "114276"],
            ["ربح السنة", "0", "2051529", "0", "1778138"],
        ]
        bs_rows = [
            ["شركة المراعي", "", "", "", ""],
            ["قائمة المركز المالي الموحدة", "", "", "", ""],
            ["31 ديسمبر 31 ديسمبر", "", "", "", ""],
            ["مخزون 3", "0", "6148189", "0", "5237136"],
            ["ذمم مدينة تجارية ومصاريف مدف", "0", "2564646", "0", "2156142"],
            ["مصاريف مدفوعة مقدما طويلة ال", "0", "525153", "0", "552415"],
            ["نقد وما في حكمه 6", "0", "666336", "0", "546916"],
            ["إجمالي الموجودات", "0", "36194015", "0", "19730739"],
            ["ذمم دائنة تجارية وذمم دائنة", "0", "4245868", "0", "3655553"],
            ["إجمالي حقوق الملكية", "0", "17808885", "0", "16982865"],
        ]
        return [{"name": "p3_ocr", "rows": is_rows},
                {"name": "p2_ocr", "rows": bs_rows}]

    def _metrics(self) -> dict:
        return _extract_metrics(self._scanned_tables(), [])

    def test_bs_expense_labelled_assets_never_feed_opex(self):
        m = self._metrics()
        # «مصاريف مدفوعة مقدما طويلة الأجل» is a prepaid ASSET on the BS
        # face — it must not sink into opex (the derived income statement
        # showed 552,415 as operating expenses)
        assert 525153.0 not in m.get("opex", [])
        assert 552415.0 not in m.get("opex", [])

    def test_bs_receivables_survive_expense_words_in_label(self):
        m = self._metrics()
        # «ذمم مدينة تجارية ومصاريف مدفوعة…» hits the opex keyword first;
        # on the BS face opex is scoped out and receivables wins
        assert m["receivables"] == [2156142.0, 2564646.0]
        assert m["inventory"] == [5237136.0, 6148189.0]
        # «نقد وما في حكمه» from the BS face (not the CF deltas)
        assert m["cash"] == [546916.0, 666336.0]

    def test_pl_finance_cost_never_feeds_liabilities(self):
        m = self._metrics()
        # «تكلفة تمويل، صافي» (a P&L line matching the «تمويل» keyword)
        # used to become the liabilities series
        assert "liabilities" not in m

    def test_bs_totals_captured(self):
        m = self._metrics()
        # «إجمالي الموجودات» — the Saudi BS wording — is total assets
        assert m["assets"] == [19730739.0, 36194015.0]
        assert m["equity"] == [16982865.0, 17808885.0]

    def test_ocr_expense_columns_sum_magnitude_when_signs_mix(self):
        m = self._metrics()
        # بيع reads (2,789,745) parenthesised, عمومية reads 469,022 bare —
        # the OCR dropped the parens on some rows, so the per-column sums
        # are magnitude sums: 2,789,745+469,022 = 3,258,767 (current)
        assert m["opex"] == [3168232.0, 3258767.0]

    def test_glued_date_is_not_a_year_header(self):
        from app.analyzer import _year_columns
        rows = self._scanned_tables()[0]["rows"]
        # «312023» (31/12/2023 glued) must not plant a year column
        assert _year_columns(rows) == {}

    def test_mixed_sheet_stays_unrestricted(self):
        # one sheet carrying BOTH faces' titles (stacked mid-table) keeps
        # the UNRESTRICTED classifier — scoping it by its first title would
        # blind the second face's rows. The trade-off is documented: the
        # BS prepaid row still reaches opex there (status quo ante), while
        # the scanned separate-page faces (the common client case) are
        # scoped cleanly above.
        rows = self._scanned_tables()[0]["rows"] + self._scanned_tables()[1]["rows"]
        m = _extract_metrics([{"name": "one_sheet", "rows": rows}], [])
        assert 525153.0 in m.get("opex", [])
