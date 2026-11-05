# -*- coding: utf-8 -*-
"""End-to-end API test: uploading a multi-COMPANY workbook.

POSTs a single workbook whose sheets each carry a self-contained income
statement for a different company (the «التقرير عام 2024» shape) and
verifies the response contains one analysis PER SHEET, each carrying that
company's true figures — never the others'. Also pins the persistence
contract: every split sheet becomes its own history row, retrievable by
id with the same numbers, while a sheet-per-YEAR workbook stays merged
into one analysis.
"""

from pathlib import Path

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Three companies with deliberately different shapes: one on the
# expense-sign convention (loss), one classic with a strong margin, one
# thin-margin — so a mixed-up sheet cannot pass by accident.
COMPANIES = {
    "المطعم": (3_153_287.03, -1_980_452.66, 1_377_562.92),
    "جدة": (4_820_000.0, 2_834_000.0, 980_000.0),
    "الدوادمي": (1_000_000.0, 400_000.0, 300_000.0),
}


def _expected(sales, cogs, expenses) -> dict:
    """Ground truth derived independently of the analyzer."""
    return {
        "revenue": sales,
        "net": sales - abs(cogs) - expenses,
        "gross_margin": (sales - abs(cogs)) / sales * 100,
        "net_margin": (sales - abs(cogs) - expenses) / sales * 100,
    }


def _income_rows(sales, cogs, expenses, name) -> list:
    """One P&L sheet shaped like the real workbook (label + value cols,
    الفرعي/الإجمالي columns, summary rows present)."""
    return [
        [f"قائمة دخل {name} عام 2024", "", "", "", ""],
        ["البيان", "", "الفرعي", "", "الإجمالي"],
        ["الإيراد", "", "", "", ""],
        ["المبيعات", "", sales, "", ""],
        ["تكلفة البضاعة المباعة", "", cogs, "", ""],
        ["مجمل الربح", "", "", "", sales - abs(cogs)],
        ["المصروفات", "", "", "", ""],
        ["الرواتب", "", 50000, "", ""],
        ["إجمالي المصروفات", "", "", "", expenses],
        ["الربح", "", "", "", sales - abs(cogs) - expenses],
    ]


def _make_workbook(path: Path, sheets: dict) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for sheet_name, (sales, cogs, expenses) in sheets.items():
        ws = wb.create_sheet(title=sheet_name)
        for row in _income_rows(sales, cogs, expenses, sheet_name):
            ws.append(row)
    wb.save(path)
    return path


def _upload(client, path: Path):
    with open(path, "rb") as fh:
        return client.post(
            "/api/upload",
            files={"files": (path.name, fh, XLSX_MIME)},
            headers=client.auth_headers,
        )


class TestMultiCompanyWorkbookUpload:
    def _split_upload(self, client, tmp_path):
        wb = _make_workbook(tmp_path / "دفتر الشركات.xlsx", COMPANIES)
        response = _upload(client, wb)
        assert response.status_code == 200, response.text
        return response.json()["uploaded"]

    def test_upload_splits_per_sheet_with_true_numbers(self, client, tmp_path):
        """One analysis per company sheet, each with ITS OWN figures."""
        uploaded = self._split_upload(client, tmp_path)

        assert len(uploaded) == len(COMPANIES)
        assert len({u["id"] for u in uploaded}) == len(COMPANIES)
        assert {u["filename"] for u in uploaded} == {"دفتر الشركات.xlsx"}

        by_sheet = {}
        for item in uploaded:
            # display_name carries the sheet it was built from
            assert " — " in (item["display_name"] or "")
            sheet = item["display_name"].split(" — ", 1)[1]
            by_sheet[sheet] = item

        assert set(by_sheet) == set(COMPANIES)
        for sheet, (sales, cogs, expenses) in COMPANIES.items():
            exp = _expected(sales, cogs, expenses)
            res = by_sheet[sheet]["result"]
            assert res["kpis"]["revenue"]["value"] == exp["revenue"]
            assert abs(res["kpis"]["net_profit"]["value"] - exp["net"]) < 0.01
            assert abs(res["ratios"]["gross_margin"]["value"] - exp["gross_margin"]) < 0.01
            assert abs(res["ratios"]["net_margin"]["value"] - exp["net_margin"]) < 0.01

        # the loss-making sheet keeps its loss identity, the healthy one
        # keeps its profit
        assert by_sheet["المطعم"]["result"]["kpis"]["net_profit"]["ar"] == "صافي الخسارة"
        assert by_sheet["جدة"]["result"]["kpis"]["net_profit"]["ar"] == "صافي الربح"
        assert by_sheet["المطعم"]["result"]["ratios"]["net_margin"]["value"] < 0
        assert by_sheet["جدة"]["result"]["ratios"]["net_margin"]["value"] > 0

    def test_each_analysis_persisted_and_fetchable_by_id(self, client, tmp_path):
        """Every split sheet is its own history row with the same numbers."""
        uploaded = self._split_upload(client, tmp_path)

        history = client.get("/api/analyses").json()
        assert len(history) == len(COMPANIES)
        assert {h["display_name"] for h in history} == {
            u["display_name"] for u in uploaded
        }

        for item in uploaded:
            detail = client.get(f"/api/analyses/{item['id']}").json()
            res = detail["result"]
            sheet = item["display_name"].split(" — ", 1)[1]
            sales = COMPANIES[sheet][0]
            assert res["kpis"]["revenue"]["value"] == sales
            exp = _expected(*COMPANIES[sheet])
            assert abs(res["kpis"]["net_profit"]["value"] - exp["net"]) < 0.01

    def test_sheet_per_year_workbook_stays_single_analysis(self, client, tmp_path):
        """The split is per COMPANY, not per sheet: one P&L per YEAR stays
        one merged (multi-period) analysis at the API level too."""
        wb = _make_workbook(
            tmp_path / "سنوات.xlsx",
            {"2023": (3_100_000.0, 1_900_000.0, 700_000.0),
             "2024": (4_120_000.0, 2_500_000.0, 850_000.0)},
        )
        response = _upload(client, wb)
        assert response.status_code == 200, response.text
        uploaded = response.json()["uploaded"]
        assert len(uploaded) == 1
        assert "display_name" not in uploaded[0]  # never treated as a company
