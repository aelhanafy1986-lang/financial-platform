# -*- coding: utf-8 -*-
"""Trial-balance uploads MUST take their figures from the built statements.

The generic extractor reads a TB's debit/credit columns as concept series
and used to return systematically wrong KPIs (a NEGATIVE revenue, a
fabricated net profit that contradicted the statements' own net). The
auto-attach path only replaced the KPIs when the extractor had found
NOTHING — a plausible-but-wrong capture survived and showed the dashboard
a profit that disagreed with the statements. Contract now: a REAL trial
balance is the ground truth — metrics (and therefore KPIs, ratios, series
and the «مقارنة بالفترة السابقة» column) are always rebuilt from the
attached statements, every series is single-period, and a negative net is
labelled «صافي الخسارة» both on the KPI card and on the statement face.
"""

import io

from openpyxl import Workbook

from app.main import _income_comparison

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# A balanced LOSS-making trial balance (debits 1,330,000 = credits):
# revenue 650,000 − cogs 900,000 − opex 150,000 → net = −400,000.
# Face ties: assets 280,000 = payables 40,000 + loans 10,000
#            + capital 630,000 + net (−400,000).
LOSS_TB = [
    ["الحساب", "مدين", "دائن"],
    ["النقدية بالبنك", 200_000, 0],
    ["مدينون - العملاء", 80_000, 0],
    ["الدائنون - الموردون", 0, 40_000],
    ["قروض قصيرة الأجل", 0, 10_000],
    ["رأس المال", 0, 630_000],
    ["ايرادات المبيعات", 0, 650_000],
    ["تكلفة المبيعات", 900_000, 0],
    ["مصاريف رواتب", 90_000, 0],
    ["مصاريف ايجار", 60_000, 0],
]


def _upload_tb(client, rows, name="ميزان مراجعة.xlsx"):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return client.post(
        "/api/upload",
        files={"files": (name, buf, XLSX_MIME)},
        headers=client.auth_headers,
    )


def _detail(client, aid):
    return client.get(f"/api/analyses/{aid}").json()


def _statements(client, aid):
    return client.get(f"/api/analyses/{aid}/statements").json()


class TestTrialBalanceGroundTruth:
    def test_loss_tb_kpis_come_from_the_statements(self, client):
        """The whole regression in one upload: a loss-making TB shows its
        TRUE net — the statements' own figure — never the extractor's
        fabricated capture."""
        resp = _upload_tb(client, LOSS_TB)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        aid = item["id"]
        assert item["has_statements"] is True

        detail = _detail(client, aid)
        assert detail["has_tb"] is True
        res = detail["result"]

        st = _statements(client, aid)["statements"]
        face_net = st["income_statement"]["totals"]["net_profit"]
        assert face_net < 0  # the built statements say LOSS

        # KPI = the statements' net, same sign, honestly labelled
        kpi = res["kpis"]["net_profit"]
        assert kpi["value"] == face_net
        assert kpi["ar"] == "صافي الخسارة"
        assert kpi["en"] == "Net Loss"

        # revenue is POSITIVE on the KPI (the extractor used to return it
        # negative from the TB's debit/credit columns)
        rev = res["kpis"]["revenue"]
        assert rev["value"] == st["income_statement"]["totals"]["revenue"]
        assert rev["value"] > 0

        # the statement FACE says «صافي الخسارة», not «صافي الربح»
        net_line = next(
            ln for ln in st["income_statement"]["lines"]
            if ln["amount"] == face_net and ln["ar"].startswith("صافي")
        )
        assert net_line["ar"] == "صافي الخسارة"

        # single-period everywhere: no fabricated second period
        for concept, series in res["metrics"].items():
            assert len(series) == 1, (concept, series)

        # and therefore NO «مقارنة بالفترة السابقة» column at all
        assert _income_comparison(res, st) == {}

        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_profit_tb_kpis_still_come_from_the_statements(self, client):
        """The profit case keeps the same single-source contract: KPI net ==
        statements net (the reversed anchoring of the loss test)."""
        profit_tb = [
            ["الحساب", "مدين", "دائن"],
            ["النقدية بالبنك", 685_000, 0],
            ["مدينون - العملاء", 110_000, 0],
            ["مخزون", 125_000, 0],
            ["الدائنون - الموردون", 0, 80_000],
            ["قروض طويلة الأجل", 0, 255_000],
            ["رأس المال", 0, 400_000],
            ["ايرادات المبيعات", 0, 650_000],
            ["تكلفة المبيعات", 380_000, 0],
            ["مصاريف رواتب", 85_000, 0],
        ]
        resp = _upload_tb(client, profit_tb, name="ميزان.xlsx")
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        aid = item["id"]
        assert item["has_statements"] is True

        res = _detail(client, aid)["result"]
        st = _statements(client, aid)["statements"]
        face_net = st["income_statement"]["totals"]["net_profit"]
        assert face_net > 0
        kpi = res["kpis"]["net_profit"]
        assert kpi["value"] == face_net
        assert kpi["ar"] == "صافي الربح"
        assert all(len(s) == 1 for s in res["metrics"].values())
        assert _income_comparison(res, st) == {}

        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_ratios_follow_the_statements_net(self, client):
        """Net margin is negative for the loss TB — not a fabricated
        positive margin from the wrong capture."""
        resp = _upload_tb(client, LOSS_TB, name="ميزان 2.xlsx")
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        aid = item["id"]
        res = _detail(client, aid)["result"]
        nm = res["ratios"]["net_margin"]
        assert nm["value"] < 0
        face_net = _statements(client, aid)["statements"][
            "income_statement"]["totals"]["net_profit"]
        face_rev = res["kpis"]["revenue"]["value"]
        assert nm["value"] == round(face_net / face_rev * 100, 2)
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
