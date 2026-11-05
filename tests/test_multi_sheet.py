# -*- coding: utf-8 -*-
"""Multi-entity workbooks (one statement per sheet) + expense-sign fixes.

Regression tests for the «التقرير عام 2024» workbook: six companies, one
income statement per sheet, costs stored with the expense (negative) sign.
"""

from app.analyzer import analyze, table_has_financials
from app.main import _split_entity_sheets, _tb_acceptable


def _income_table(sales, cogs, expenses, name="شركة"):
    """A قائمة دخل sheet shaped like the real workbook (label + value cols,
    summary rows مجمل الربح/إجمالي المصروفات/الربح present)."""
    return {
        "name": name,
        "rows": [
            ["قائمة دخل شركة عام 2024", "", "", "", ""],
            ["البيان", "", "الفرعي", "", "الإجمالي"],
            ["الإيراد", "", "", "", ""],
            ["المبيعات", "", sales, "", ""],
            ["تكلفة البضاعة المباعة", "", cogs, "", ""],
            ["مجمل الربح", "", "", "", sales - abs(cogs)],
            ["المصروفات", "", "", "", ""],
            ["الرواتب", "", 50000, "", ""],
            ["إجمالي المصروفات", "", "", "", expenses],
            ["الربح", "", "", "", sales - abs(cogs) - expenses],
        ],
    }


def test_negative_cogs_normalised():
    """المطعم sheet: sales 3,153,287.03 / cogs -1,980,452.66 / expenses
    1,377,562.92 → net LOSS -204,728.55 exactly as the sheet states."""
    table = _income_table(3_153_287.03, -1_980_452.66, 1_377_562.92)
    result = analyze([table], [])
    assert result["kpis"]["revenue"]["value"] == 3_153_287.03
    net = result["kpis"]["net_profit"]["value"]
    assert abs(net - (-204_728.55)) < 0.01
    assert result["kpis"]["net_profit"]["ar"] == "صافي الخسارة"
    gm = result["ratios"]["gross_margin"]["value"]
    expected_gm = 1_172_834.37 / 3_153_287.03 * 100
    assert abs(gm - expected_gm) < 0.01
    assert result["ratios"]["net_margin"]["value"] < 0


def test_positive_cogs_unchanged():
    """Classic convention (cogs positive) keeps producing the same net."""
    table = _income_table(1_000_000, 400_000, 300_000)
    result = analyze([table], [])
    net = result["kpis"]["net_profit"]["value"]
    assert abs(net - 300_000) < 0.01
    assert result["kpis"]["net_profit"]["ar"] == "صافي الربح"


def test_table_has_financials():
    assert table_has_financials(_income_table(100, -50, 30))
    assert not table_has_financials(
        {"name": "ملاحظات", "rows": [["هذا نص تفسيري فقط"], ["لا أرقام هنا"]]}
    )


def test_split_detects_company_workbook():
    """التقرير عام 2024 shape: one P&L sheet per company → all six split."""
    names = ["المطعم", "جدة", "الدوادمي", "منصة اعتماد", "الكنافة", "شاورما لايك"]
    tables = [_income_table(1000 + i, -500, 300, name=n) for i, n in enumerate(names)]
    split = _split_entity_sheets(tables)
    assert [t["name"] for t in split] == names


def test_split_ignores_balance_sheet_sheet():
    """sample-financials.xlsx shape: IS sheet + balance-sheet sheet = one
    company split across sheets → never split."""
    is_sheet = _income_table(4_820_000, 2_834_000, 980_000, name="قائمة الدخل")
    bs_sheet = {
        "name": "الميزانية العمومية",
        "rows": [
            ["الميزانية العمومية"],
            ["البند", "2023", "2024", "2025"],
            ["إجمالي الأصول", 7200000, 8400000, 9150000],
            ["حقوق الملكية", 4100000, 4900000, 5627000],
            ["النقدية", 850000, 980000, 1120000],
        ],
    }
    assert _split_entity_sheets([is_sheet, bs_sheet]) == []


def test_split_ignores_period_named_sheets():
    """Sheet-per-year workbooks stay merged (multi-period analysis)."""
    tables = [
        _income_table(3_100_000, 1_900_000, 700_000, name="2023"),
        _income_table(4_120_000, 2_500_000, 850_000, name="2024"),
        _income_table(4_820_000, 2_834_000, 980_000, name="2025"),
    ]
    assert _split_entity_sheets(tables) == []


def test_split_includes_rollup_sheet_as_consolidated():
    """The workbook's consolidated «الإجمالي» sheet JOINS the split as the
    group's consolidated entity (the موحد analysis) instead of being
    excluded — its stacked statement blocks give the consolidation its
    periods, and the upload path aligns them to the companies' sum."""
    names = ["المطعم", "جدة", "الإجمالي"]
    tables = [_income_table(1000 + i, -500, 300, name=n) for i, n in enumerate(names)]
    split = _split_entity_sheets(tables)
    assert [t["name"] for t in split] == ["المطعم", "جدة", "الإجمالي"]


def test_note_cell_not_captured_as_value():
    """الكنافة sheet: the note «ملحوظة تم إضافة المبيعات ... عام 2024 بقيمة
    219448.98» sits next to the sales row — neither its 2024 nor 219448.98
    may be captured as revenue."""
    table = {
        "name": "الكنافة",
        "rows": [
            ["قائمة دخل الكنافة عام 2024"],
            ["المبيعات", "", 270121.17, "", "",
             "ملحوظة تم إضافة المبيعات التي تخص الكنافة الشعر لأنها لم تدرج علي نظام ساب عام 2024 بقيمة 219448.98"],
            ["تكلفة البضاعة المباعة", "", -134105.08],
            ["إجمالي المصروفات", "", "", "", 193222.31],
        ],
    }
    result = analyze([table], [])
    assert result["kpis"]["revenue"]["value"] == 270121.17
    net = result["kpis"]["net_profit"]["value"]
    assert abs(net - (-57_206.22)) < 0.01


def test_tb_gate_rejects_unbalanced():
    """Income-statement pseudo-accounts (unbalanced) must NOT attach as
    statements — the gate that used to accept them."""
    cand = {
        "trial_balance": {
            "accounts": [{"account": str(i), "debit": 1, "credit": 1} for i in range(10)],
            "total_debit": 117.5,
            "total_credit": 100.0,
            "balanced": False,
        }
    }
    assert not _tb_acceptable(cand)
    cand["trial_balance"]["balanced"] = True
    cand["trial_balance"]["total_credit"] = 117.5
    assert _tb_acceptable(cand)






class TestConsolidatedUpload:
    """التحليل الموحد للمجموعة: the «الإجمالي» sheet stops being excluded —
    it becomes the group's consolidated analysis, its stacked [current,
    prior] blocks aligned so the latest period equals the companies' sum,
    and the consolidated statements attach at upload."""

    COMPANIES = [  # (name, sales, cogs, expenses) — 2024 figures
        ("المطعم", 3_153_287.03, -1_980_452.66, 1_377_562.92),
        ("جدة", 3_402_197.35, -2_400_000.0, 1_100_000.0),
        ("الدوادمي", 5_564_619.66, -4_100_000.0, 1_450_000.0),
        ("منصة اعتماد", 213_510.0, -150_000.0, 55_000.0),
        ("الكنافة", 270_121.17, -134_105.08, 193_222.31),
        ("شاورما لايك", 876_206.95, -500_000.0, 540_000.0),
    ]

    def _workbook_bytes(self) -> bytes:
        import io

        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)
        for name, sales, cogs, exp in self.COMPANIES:
            ws = wb.create_sheet(name)
            ws.append([f"قائمة دخل {name} عام 2024"])
            ws.append(["البيان", "", "الفرعي", "", "الإجمالي"])
            ws.append(["الإيراد"])
            ws.append(["المبيعات", "", sales])
            ws.append(["تكلفة البضاعة المباعة", "", cogs])
            ws.append(["مجمل الربح", "", "", "", sales - abs(cogs)])
            ws.append(["إجمالي المصروفات", "", "", "", exp])
            ws.append(["الربح", "", "", "", sales - abs(cogs) - exp])
        # the consolidated sheet: TWO stacked blocks — [current, prior]
        cur_sales = sum(s for _, s, _, _ in self.COMPANIES)
        cur_cogs = sum(abs(c) for _, _, c, _ in self.COMPANIES)
        cur_exp = sum(e for _, _, _, e in self.COMPANIES)
        prior_sales = round(cur_sales * 0.97, 2)
        ws = wb.create_sheet("الإجمالي")
        for sales, cogs, exp in ((cur_sales, cur_cogs, cur_exp),
                                 (prior_sales, cur_cogs, cur_exp)):
            ws.append(["قائمة دخل جودة ا"])
            ws.append(["البيان", "", "الفرعي", "", "الإجمالي"])
            ws.append(["الإيراد"])
            ws.append(["المبيعات", "", sales])
            ws.append(["تكلفة البضاعة المباعة", "", -cogs])
            ws.append(["مجمل الربح", "", "", "", sales - cogs])
            ws.append(["إجمالي المصروفات", "", "", "", exp])
            ws.append(["الربح", "", "", "", sales - cogs - exp])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_upload_creates_consolidated_analysis_with_statements(self, client):
        res = client.post(
            "/api/upload",
            files={"files": ("التقرير عام 2024.xlsx", self._workbook_bytes(),
                             "application/octet-stream")},
            headers=client.auth_headers,
        )
        assert res.status_code == 200
        items = res.json()["uploaded"]
        assert len(items) == 7  # six companies + the consolidated موحد
        consolidated = next(i for i in items
                            if (i.get("display_name") or "").endswith("الإجمالي"))
        assert consolidated["has_statements"] is True  # القوائم الموحدة مرفقة

        metrics = consolidated["result"]["metrics"]
        cur_sales = sum(s for _, s, _, _ in self.COMPANIES)
        prior_sales = round(cur_sales * 0.97, 2)
        # chronology aligned: oldest → latest, latest == the companies' sum
        assert [round(v, 2) for v in metrics["revenue"]] == [prior_sales, round(cur_sales, 2)]
        net = metrics["net_profit"]
        assert len(net) == 2 and net[-1] < 0  # stated net lines reversed too
        cur_net = sum(s - abs(c) - e for _, s, c, e in self.COMPANIES)
        assert abs(net[-1] - cur_net) < 0.01

        # the six companies themselves stay single-period analyses
        companies = [i for i in items if i is not consolidated]
        assert len(companies) == 6
        assert all(len((i["result"]["metrics"].get("revenue") or [])) == 1
                   for i in companies)

    def test_align_reverses_only_when_opening_matches_sum(self):
        from app.main import _align_rollup_chronology

        companies = [{"metrics": {"revenue": [100.0]}}, {"metrics": {"revenue": [200.0]}}]
        # stacked [current, prior]: opens at the sum → reversed
        rollup = {"metrics": {"revenue": [300.0, 290.0]}}
        out = _align_rollup_chronology(rollup, [], companies)
        assert out["metrics"]["revenue"] == [290.0, 300.0]
        # already oldest → latest: untouched
        rollup = {"metrics": {"revenue": [290.0, 300.0]}}
        out = _align_rollup_chronology(rollup, [], companies)
        assert out["metrics"]["revenue"] == [290.0, 300.0]
        # neither end matches the sum (unrelated rollup): untouched
        rollup = {"metrics": {"revenue": [500.0, 400.0]}}
        out = _align_rollup_chronology(rollup, [], companies)
        assert out["metrics"]["revenue"] == [500.0, 400.0]
