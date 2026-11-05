# -*- coding: utf-8 -*-
"""A Word document with several financial statements is ONE company.

Regression: a Microsoft-style statements document (income statement +
balance sheet + cash flows as separate TABLES of the same docx) was split
into three «entities» because each table carried a revenue-classified row
(«Total revenue», «Short-term unearned revenue», «Sales of investments»).
Three wrong analyses came back and none carried statements.

Contract now: ONLY spreadsheet files split per sheet; a Word/PDF/PPTX
document is one entity by construction. The English keyword fixes (cost of
revenue → cogs, sales and marketing → opex, unearned revenue excluded,
pre-tax lines excluded, income-tax balance lines excluded) keep the merged
analysis honest, and its report carries the derived القوائم المالية.
"""

import io

from fastapi.testclient import TestClient

from app.analyzer import _to_number
from app.main import _split_entity_sheets

DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")

INCOME = [
    ["Item", "2025", "2024"],
    ["Total revenue", "500,000", "400,000"],
    ["Total cost of revenue", "200,000", "160,000"],
    ["Sales and marketing", "80,000", "70,000"],
    ["Other income (expense), net", "(5,000)", "(4,000)"],
    ["Provision for income taxes", "30,000", "25,000"],
    ["Net income", "185,000", "141,000"],
]
BALANCE = [
    ["Item", "2025", "2024"],
    ["Total assets", "600,000", "500,000"],
    ["Short-term income taxes", "5,000", "4,000"],
    ["Accounts payable", "90,000", "80,000"],
]
CASHFLOW = [
    ["Item", "2025", "2024"],
    ["Net income", "185,000", "141,000"],
    ["Sales of investments", "(2,000)", "(1,000)"],
]


def _make_statements_docx(path) -> bytes:
    """A Word file whose TABLES are complementary statements of ONE company
    (the Microsoft annual-report shape)."""
    import docx

    d = docx.Document()
    d.add_heading("القوائم المالية — شركة واحدة")
    for rows in (INCOME, BALANCE, CASHFLOW):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                t.cell(r, c).text = str(val)
    d.save(str(path))
    return path.read_bytes()


# --------------------------------------------------------------- unit ----

def test_split_entity_sheets_only_for_spreadsheets():
    """Two revenue-carrying tables split ONLY when the file is a
    spreadsheet — a Word document is one entity even when several of its
    tables carry revenue-classified rows."""
    tables = [
        {"name": "table_1", "rows": [["Item", "2025"], ["Revenue", "500,000"]]},
        {"name": "table_2", "rows": [["Item", "2025"], ["الإيراد", "300,000"]]},
    ]
    assert _split_entity_sheets(tables, ".docx") == []
    assert _split_entity_sheets(tables, ".pdf") == []
    assert _split_entity_sheets(tables, ".pptx") == []
    assert len(_split_entity_sheets(tables, ".xlsx")) == 2
    assert len(_split_entity_sheets(tables, ".xlsm")) == 2


def test_paren_fragment_is_negative():
    """Word tables split accounting parens across cells: «(4,901» in one
    cell and «)» in the next — the fragment still reads negative."""
    assert _to_number("(4,901") == -4901.0
    assert _to_number("(5,000)") == -5000.0
    assert _to_number("788") == 788.0


# ------------------------------------------------------- end-to-end ------

class TestWordStatementsOneEntity:
    def _upload(self, client, tmp_path):
        data = _make_statements_docx(tmp_path / "microsoft.docx")
        return client.post(
            "/api/upload",
            files={"files": ("microsoft.docx", io.BytesIO(data), DOCX_MIME)},
            headers=client.auth_headers,
        )

    def test_one_analysis_not_three(self, client, tmp_path):
        """THE regression: one docx → ONE analysis, never three."""
        resp = self._upload(client, tmp_path)
        assert resp.status_code == 200, resp.text
        uploaded = resp.json()["uploaded"]
        assert len(uploaded) == 1, uploaded
        item = uploaded[0]
        assert "error" not in item, item
        client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)

    def test_merged_metrics_are_true(self, client, tmp_path):
        """The merged analysis reads the real figures: revenue/cogs/opex/
        net from the income statement, assets from the balance sheet —
        oldest→newest, with the noise rows excluded."""
        resp = self._upload(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        metrics = item["result"]["metrics"]
        # ascending years: latest last
        assert metrics["revenue"] == [400_000.0, 500_000.0]
        assert metrics["cogs"] == [160_000.0, 200_000.0]
        assert metrics["opex"] == [70_000.0, 80_000.0]
        assert metrics["investment_income"] == [-4_000.0, -5_000.0]
        assert metrics["tax_expense"] == [25_000.0, 30_000.0]
        assert metrics["assets"] == [500_000.0, 600_000.0]
        assert metrics["net_profit"][-1] == 185_000.0
        client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)

    def test_report_carries_statements(self, client, tmp_path):
        """القوائم المالية تظهر في تقرير PDF المشتق من مقاييس التحليل."""
        resp = self._upload(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        aid = item["id"]
        report = client.get(f"/api/analyses/{aid}/report?lang=ar",
                            headers=client.auth_headers)
        assert report.status_code == 200, report.text
        import pymupdf

        doc = pymupdf.open(stream=report.content)
        text = "".join(pg.get_text() for pg in doc)
        doc.close()
        # the derived statements face carries the analysis figures
        assert "500,000.00" in text
        assert "185,000.00" in text
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
