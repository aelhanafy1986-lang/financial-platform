"""Tests for advisor (recommendations/projections) and statements engine."""

from openpyxl import Workbook

from app.advisor import build_advisor
from app.statements import build_statements


def _demo_result(net=640_000.0, revenue=4_820_000.0):
    return {
        "kpis": {
            "revenue": {"value": revenue, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": net, "en": "Net Profit", "ar": "صافي الربح"},
            "assets": {"value": 9_150_000, "en": "Total Assets", "ar": "إجمالي الأصول"},
            "cash": {"value": 1_120_000, "en": "Cash", "ar": "النقدية"},
        },
        "ratios": {
            "gross_margin": {"value": 41.2, "en": "Gross Margin %", "ar": "هامش الربح الإجمالي %"},
            "net_margin": {"value": round(net / revenue * 100, 2), "en": "Net Margin %", "ar": "هامش صافي الربح %"},
            "debt_ratio": {"value": 38.5, "en": "Debt Ratio %", "ar": "نسبة الالتزامات %"},
        },
        "series": {
            "revenue": {
                "values": [3_100_000, 3_450_000, 3_800_000, 4_120_000, 4_450_000, revenue],
                "en": "Revenue", "ar": "الإيرادات",
            },
        },
        "forecast": [],
        "tables_found": 1,
        "texts_found": 0,
        "analysed_at": None,
    }


class TestAdvisor:
    def test_healthy_result_gives_positive_headline(self):
        out = build_advisor(_demo_result(), "ar")
        assert out["summary"]["critical"] == 0
        assert "سليم" in out["headline"]
        assert any(a["severity"] == "info" for a in out["advice"])

    def test_loss_makes_critical_with_solutions(self):
        result = _demo_result(net=-500_000.0)
        out = build_advisor(result, "ar")
        assert out["summary"]["critical"] >= 1
        assert out["solutions"], "loss must produce solutions"
        assert any(a["key"] == "net_margin" for a in out["advice"])

    def test_low_cash_flags_liquidity(self):
        result = _demo_result()
        result["kpis"]["cash"]["value"] = 50_000  # ~1% of revenue
        out = build_advisor(result, "ar")
        assert any(a["key"] == "cash" and a["severity"] in {"critical", "warning"}
                   for a in out["advice"])

    def test_projections_numeric_and_trended(self):
        out = build_advisor(_demo_result(), "en")
        rev = next(p for p in out["projections"] if p["concept"] == "revenue")
        assert rev["trend"] == "up"
        assert len(rev["projections"]) == 2
        # revenue series is increasing -> projection above last value
        assert rev["projections"][0]["value"] > rev["values"][-1]

    def test_bilingual_outputs(self):
        ar = build_advisor(_demo_result(net=-1_000.0), "ar")
        en = build_advisor(_demo_result(net=-1_000.0), "en")
        assert ar["headline"] != en["headline"]
        assert all(isinstance(s, str) and s for s in en["solutions"])


class TestStatements:
    def _tb_rows(self):
        return [
            ["النقدية بالبنك", 500_000, 0],
            ["المدينون - العملاء", 300_000, 0],
            ["المخزون", 200_000, 0],
            ["أصول ثابتة - سيارات", 400_000, 0],
            ["الدائنون - الموردون", 0, 250_000],
            ["قرض بنكي", 0, 350_000],
            ["رأس المال", 0, 500_000],
            ["ايرادات المبيعات", 0, 1_000_000],
            ["تكلفة المبيعات", 600_000, 0],
            ["مصاريف رواتب", 80_000, 0],
            ["مصاريف ايجار", 20_000, 0],
        ]

    def test_income_statement_totals(self):
        out = build_statements(self._tb_rows())
        isx = out["income_statement"]["totals"]
        assert isx["revenue"] == 1_000_000
        assert isx["gross_profit"] == 400_000
        assert isx["net_profit"] == 300_000

    def test_balance_sheet_balances_with_net_profit(self):
        out = build_statements(self._tb_rows())
        bs = out["balance_sheet"]
        # assets = 500+300+200+400 = 1,400,000
        assert bs["assets"]["total"] == 1_400_000
        # liab = 600,000 + equity 500,000 + net 300,000 = 1,400,000
        assert bs["liabilities_equity"]["total"] == 1_400_000
        assert bs["balanced"] is True

    def test_trial_balance_check(self):
        out = build_statements(self._tb_rows())
        tb = out["trial_balance"]
        assert tb["total_debit"] == tb["total_credit"] == 2_100_000
        assert tb["balanced"] is True

    def test_unbalanced_tb_detected(self):
        rows = self._tb_rows() + [["حساب مزيف", 999, 0]]
        out = build_statements(rows)
        assert out["trial_balance"]["balanced"] is False

    def test_cash_flow_three_activities(self):
        out = build_statements(self._tb_rows())
        cf = out["cash_flow"]
        # operating: 300k profit + 0 depr - 300k AR - 200k inv + 250k AP = 50k
        assert cf["operating"]["total"] == 50_000
        # investing: -400k fixed assets
        assert cf["investing"]["total"] == -400_000
        # financing: 350k loans + 500k equity = 850k
        assert cf["financing"]["total"] == 850_000
        # net change = 50k - 400k + 850k = 500k = cash balance
        assert cf["net_change"] == 500_000
        assert cf["reconciles"] is True

    def test_equity_statement_components(self):
        out = build_statements(self._tb_rows())
        eq = out["equity_statement"]
        amounts = {ln["en"]: ln["amount"] for ln in eq["lines"]}
        assert amounts["Paid-in capital"] == 500_000
        assert amounts["Net profit for the period"] == 300_000
        assert eq["total"] == 800_000

    def test_notes_generated_with_details(self):
        out = build_statements(self._tb_rows())
        notes = out["notes"]
        # basis note first, balance-check note last, details in between
        assert notes[0]["en"] == "Basis of preparation"
        assert "balanced" in notes[-1]["text_en"]
        detail_notes = [n for n in notes if n.get("lines")]
        assert len(detail_notes) >= 8
        cash_note = next(n for n in detail_notes if n["en"] == "Cash & banks")
        assert cash_note["lines"][0]["account"] == "النقدية بالبنك"

    def test_depreciation_flagged_in_opex(self):
        rows = self._tb_rows() + [["مصاريف استهلاك", 30_000, 0]]
        out = build_statements(rows)
        opex_lines = out["income_statement"]["detail"]["opex"]
        depr = [ln for ln in opex_lines if ln.get("depreciation")]
        assert len(depr) == 1 and depr[0]["amount"] == 30_000
        # depr is added back in operating cash flow
        assert out["cash_flow"]["operating"]["lines"][1]["amount"] == 30_000


class TestEndpoints:
    def _upload_tb(self, client, analysis_id, rows):
        wb = Workbook()
        ws = wb.active
        for r in rows:
            ws.append(r)
        import io

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return client.post(
            f"/api/analyses/{analysis_id}/trial-balance",
            files={"file": ("tb.xlsx", buf)},
            headers=client.auth_headers,
        )

    def test_trial_balance_end_to_end(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        rows = [
            ["الحساب", "مدين", "دائن"],
            ["النقدية بالبنك", 100_000, 0],
            ["رأس المال", 0, 100_000],
        ]
        res = self._upload_tb(client, analysis_id, rows)
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["statements"]["balance_sheet"]["balanced"] is True

        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["has_tb"] is True

        st = client.get(f"/api/analyses/{analysis_id}/statements").json()
        assert st["has_statements"] is True

        # advice endpoint includes statements
        advice = client.get(f"/api/analyses/{analysis_id}/advice?lang=ar").json()
        assert advice["statements"] is not None

        # PDF regenerates with statements section
        res = client.get(f"/api/analyses/{analysis_id}/report?lang=ar", headers=client.auth_headers)
        assert res.status_code == 200 and res.content[:5] == b"%PDF-"

    def test_trial_balance_rejects_non_excel(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        res = client.post(
            f"/api/analyses/{analysis_id}/trial-balance",
            files={"file": ("tb.txt", b"not excel")},
            headers=client.auth_headers,
        )
        assert res.status_code == 400

    def test_trial_balance_404(self, client):
        import io

        wb = Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        res = client.post(
            "/api/analyses/999/trial-balance",
            files={"file": ("tb.xlsx", buf)},
            headers=client.auth_headers,
        )
        assert res.status_code == 404

    def test_stats_pdf_generated(self, client):
        client.post("/api/demo")
        res = client.get("/api/stats/report?lang=ar", headers=client.admin_headers)
        assert res.status_code == 200
        assert res.content[:5] == b"%PDF-"

    def test_advice_endpoint_shape(self, client):
        analysis_id = client.post("/api/demo").json()["id"]
        advice = client.get(f"/api/analyses/{analysis_id}/advice?lang=ar").json()
        assert {"headline", "advice", "projections", "summary", "solutions"} <= set(advice)


class TestHierarchicalTB:
    """Trial balances are hierarchical: main / sub / aggregate rows repeat
    their children's totals. Only detail (leaf) rows may be summed."""

    def _hier_rows(self):
        # No 'إجمالي' markers on the two aggregate rows: detection must be
        # structural (parent code + amounts match), not label-based.
        return [
            ["الحساب", "كود", "مدين", "دائن"],
            ["صندوق أ", "AT120101", 300_000, ""],
            ["صندوق ب", "AT120102", 200_000, ""],
            ["النقدية", "AT1201", 500_000, ""],          # aggregate
            ["عميل ١", "AT120301", 200_000, ""],
            ["عميل ٢", "AT120302", 100_000, ""],
            ["العملاء", "AT1203", 300_000, ""],           # aggregate
            ["المخزون", "AT1204", 200_000, ""],
            ["مورد", "LT2201", "", 200_000],
            ["رأس المال", "LT3101", "", 400_000],
            ["مبيعات", "RT4101", "", 1_000_000],
            ["تكلفة المبيعات", "MT5101", 575_000, ""],
            ["مصروف نقل", "XT6201160001", 20_000, ""],
            # leaf whose code is a prefix-sibling of the one above — must
            # NOT be dropped despite the code-prefix relation (amounts differ)
            ["مصروف نقل آخر", "XT62011600010", 5_000, ""],
        ]

    def test_aggregates_dropped_leaves_kept(self):
        out = build_statements(self._hier_rows())
        labels = [a["account"] for a in out["trial_balance"]["accounts"]]
        assert "النقدية" not in labels      # aggregate dropped
        assert "العملاء" not in labels      # aggregate dropped
        assert "مصروف نقل" in labels        # leaf kept
        assert "مصروف نقل آخر" in labels    # leaf with prefix-like code kept
        h = out["trial_balance"]["hierarchy"]
        assert h["detail_rows"] == 11
        assert h["aggregate_rows"] >= 2

    def test_no_double_counting_and_identity(self):
        out = build_statements(self._hier_rows())
        tb = out["trial_balance"]
        # detail debit rows: 300+200+200+100+200+575+20+5 = 1600k
        assert tb["total_debit"] == 1_600_000
        assert tb["total_credit"] == 1_600_000
        assert tb["balanced"]
        bs = out["balance_sheet"]
        assert bs["balanced"]
        assert bs["difference"] == 0.0
        # net profit 400k and cash flow ties to cash
        assert out["income_statement"]["totals"]["net_profit"] == 400_000
        assert out["cash_flow"]["reconciles"]

    def test_grouped_totals_without_sum_match(self):
        # aggregate equals a SINGLE child (grouped total), not the sum —
        # e.g. a sub-group with one active leaf.
        rows = [
            ["الحساب", "كود", "مدين", "دائن"],
            ["بنك الرئيسي", "AT120201", 250_000, ""],
            ["البنوك", "AT1202", 250_000, ""],   # equals the child, no sum
            ["مورد", "LT2201", "", 100_000],
            ["رأس المال", "LT3101", "", 150_000],
        ]
        out = build_statements(rows)
        labels = [a["account"] for a in out["trial_balance"]["accounts"]]
        assert "البنوك" not in labels
        assert "بنك الرئيسي" in labels
        # detail-only TB: Dr 250k = Cr 250k
        assert out["trial_balance"]["balanced"]
        assert out["balance_sheet"]["balanced"]
