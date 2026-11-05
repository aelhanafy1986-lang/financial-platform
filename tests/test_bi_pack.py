# -*- coding: utf-8 -*-
"""BI-tool integration (Excel · Power BI · Tableau · Looker · SQL · Python).

Contract: every analysis is exposed as tidy (long-format) tables through
- live endpoints  GET /api/analyses/{id}/bi/{facts|growth|ratios}[?fmt=csv]
- a ZIP bundle    GET /api/analyses/{id}/bi-pack  (CSV + XLSX + SQL + README)

The growth table carries the next-year forecast rows (mean historical
growth, ``is_forecast=1``) — the SAME rule the PDF/PPTX growth tables use.
CSVs are UTF-8 **with BOM** so Excel/Power BI/Looker read Arabic directly,
and the plain XLSX keeps headers on row 1 for connector ingestion. The
styled Excel export gains a «النمو السنوي والتوقع» sheet with the forecast
column.
"""

import csv
import io
import sqlite3
import zipfile

from openpyxl import Workbook, load_workbook

IS_ROWS = [
    ["قائمة الدخل المقارنة", "", "", ""],
    ["البند", "عام 2022", "عام 2023", "عام 2024"],
    ["إجمالي المبيعات", 500000, 650000, 800000],
    ["تكلفة البضاعة المباعة", -300000, -380000, -460000],
    ["مجمل الربح", 200000, 270000, 340000],
    ["صافي الربح", 63000, 106200, 150000],
]
BS_ROWS = [
    ["البند", "عام 2022", "عام 2023", "عام 2024"],
    ["إجمالي الأصول", 555000, 695000, 830000],
    ["إجمالي الالتزامات", 255000, 295000, 330000],
    ["إجمالي حقوق الملكية", 300000, 400000, 500000],
]


def _upload_three_years(client):
    """Upload a 3-year workbook → (analysis_id, parsed result)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "ثلاث سنوات"
    for r in IS_ROWS + BS_ROWS:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    res = client.post(
        "/api/upload",
        files={"files": ("three-years.xlsx", buf,
                         "application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")},
        headers=client.auth_headers,
    )
    assert res.status_code == 200, res.text
    item = res.json()["uploaded"][0]
    assert "error" not in item, item
    return item["id"], item["result"]


def _expected_forecast(series: list[float]) -> tuple[float, float]:
    """(value, mean YoY %) — re-derived independently from the raw series."""
    rates = [(series[k] - series[k - 1]) / abs(series[k - 1])
             for k in range(1, len(series)) if series[k - 1]]
    avg = sum(rates) / len(rates)
    return series[-1] * (1 + avg), avg * 100


# ------------------------------------------------------- live endpoints ----

class TestBiTables:
    def test_facts_json_shape(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/bi/facts",
                         headers=client.auth_headers)
        assert res.status_code == 200
        rows = res.json()
        assert rows, "facts table must not be empty"
        assert {"concept", "concept_ar", "concept_en", "period_label",
                "period_index", "value", "is_forecast"} == set(rows[0])
        assert all(r["is_forecast"] == 0 for r in rows)  # demo: 2 periods
        assert all(r["period_index"] >= 1 for r in rows)

    def test_facts_csv_has_utf8_bom_and_header(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/bi/facts?fmt=csv",
                         headers=client.auth_headers)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        assert res.content[:3] == b"\xef\xbb\xbf", "Excel/Power BI need BOM"
        text = res.content.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)))
        assert header[0] == "concept" and "value" in header

    def test_ratios_table_bilingual(self, client):
        client.post("/api/demo")
        rows = client.get("/api/analyses/1/bi/ratios",
                          headers=client.auth_headers).json()
        assert rows and {"ratio", "ratio_ar", "ratio_en", "value"} == set(rows[0])
        assert all(isinstance(r["value"], (int, float)) for r in rows)
        assert any(r["ratio"] == "gross_margin" for r in rows)

    def test_growth_carries_forecast_rows(self, client):
        aid, result = _upload_three_years(client)
        rows = client.get(f"/api/analyses/{aid}/bi/growth",
                          headers=client.auth_headers).json()
        assert rows, "3-year upload must yield growth rows"
        hist = [r for r in rows if r["is_forecast"] == 0]
        fc = [r for r in rows if r["is_forecast"] == 1]
        assert hist and fc
        assert {r["concept"] for r in fc} <= {r["concept"] for r in hist}
        # every historical row after the first has a YoY %, first is None
        # (rows arrive oldest → latest; the parser normalizes labels to years)
        rev_hist = [r for r in hist if r["concept"] == "revenue"]
        assert [r["period_label"] for r in rev_hist] == \
            ["2022", "2023", "2024"]
        assert rev_hist[0]["yoy_pct"] is None
        assert rev_hist[1]["yoy_pct"] == 30.0 and rev_hist[2]["yoy_pct"] == 23.08
        # the revenue forecast row matches the mean-growth rule, independently
        exp_val, exp_pct = _expected_forecast(result["metrics"]["revenue"])
        rev_fc = next(r for r in fc if r["concept"] == "revenue")
        assert rev_fc["value"] == round(exp_val, 2)
        assert rev_fc["yoy_pct"] == round(exp_pct, 2) == 26.54
        # forecast period label bumps the last year: 2024 → 2025
        assert rev_fc["period_label"] == "2025"

    def test_facts_include_forecast_rows_when_growth_table_exists(self, client):
        aid, result = _upload_three_years(client)
        rows = client.get(f"/api/analyses/{aid}/bi/facts",
                          headers=client.auth_headers).json()
        fc = [r for r in rows if r["is_forecast"] == 1]
        assert fc, "forecast rows must appear in facts for a 3-year analysis"
        rev_fc = next(r for r in fc if r["concept"] == "revenue")
        exp_val, _ = _expected_forecast(result["metrics"]["revenue"])
        assert rev_fc["value"] == round(exp_val, 2)
        assert rev_fc["period_index"] == 4  # after the three historical years

    def test_unknown_table_404(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/bi/nonsense",
                         headers=client.auth_headers)
        assert res.status_code == 404

    def test_download_requires_login(self, client):
        client.post("/api/demo")
        for url in ("/api/analyses/1/bi/facts", "/api/analyses/1/bi-pack"):
            assert client.get(url).status_code == 401


# ------------------------------------------------------------ the pack ----

class TestBiPack:
    def test_pack_contents(self, client):
        aid, _ = _upload_three_years(client)
        res = client.get(f"/api/analyses/{aid}/bi-pack",
                         headers=client.auth_headers)
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"
        assert res.content[:2] == b"PK"
        z = zipfile.ZipFile(io.BytesIO(res.content))
        assert set(z.namelist()) == {
            "facts.csv", "facts.xlsx", "growth_forecast.csv", "ratios.csv",
            "schema.sql", "README.md"}
        for csv_name in ("facts.csv", "growth_forecast.csv", "ratios.csv"):
            assert z.read(csv_name)[:3] == b"\xef\xbb\xbf", csv_name
        readme = z.read("README.md").decode("utf-8")
        for tool in ("Power BI", "Tableau", "Looker", "Excel", "SQL",
                     "Python"):
            assert tool in readme, tool
        wb = load_workbook(io.BytesIO(z.read("facts.xlsx")))
        assert wb.sheetnames == ["facts", "growth_forecast", "ratios"]
        assert wb["facts"]["A1"].value == "concept"
        assert wb["facts"].freeze_panes == "A2"

    def test_schema_sql_runs_on_sqlite_and_carries_forecast(self, client):
        aid, result = _upload_three_years(client)
        z = zipfile.ZipFile(io.BytesIO(client.get(
            f"/api/analyses/{aid}/bi-pack",
            headers=client.auth_headers).content))
        sql = z.read("schema.sql").decode("utf-8")
        assert "CREATE TABLE IF NOT EXISTS bi_facts" in sql
        assert "INSERT INTO bi_facts" in sql
        # idempotent re-runs: DELETE for this analysis before the INSERTs
        assert f"DELETE FROM bi_facts WHERE analysis_id = {aid}" in sql
        conn = sqlite3.connect(":memory:")
        conn.executescript(sql)  # must run unchanged on SQLite
        n, n_fc = conn.execute(
            "SELECT COUNT(*), SUM(is_forecast) FROM bi_facts").fetchone()
        assert n > 0 and n_fc > 0
        exp_val, _ = _expected_forecast(result["metrics"]["revenue"])
        got = conn.execute(
            "SELECT value FROM bi_facts WHERE concept='revenue' "
            "AND is_forecast=1").fetchone()[0]
        assert got == round(exp_val, 2)


# --------------------------------------------- styled Excel export sheet ----

class TestExcelGrowthSheet:
    def test_growth_and_forecast_sheet(self, client):
        aid, _ = _upload_three_years(client)
        res = client.get(f"/api/analyses/{aid}/export?lang=ar",
                         headers=client.auth_headers)
        assert res.status_code == 200
        wb = load_workbook(io.BytesIO(res.content))
        assert "النمو السنوي والتوقع" in wb.sheetnames
        ws = wb["النمو السنوي والتوقع"]
        cells = [(c, str(c.value or "")) for row in ws.iter_rows() for c in row]
        texts = [t for _, t in cells]
        # the forecast column header (bumped last year) + both sections + note
        assert "2025" in texts
        assert "القيم عبر السنوات + التوقع" in texts
        assert "نسبة التغير السنوي + متوسط النمو (التوقع)" in texts
        assert any("متوسط النمو التاريخي" in t for t in texts)
        # the forecast cell is amber-bold like the PDF/PPTX column — a real
        # NUMBER (Excel formats it), matching the mean-growth arithmetic
        fc_cell = next(c for c, t in cells
                       if isinstance(c.value, float)
                       and abs(c.value - 1012307.69) < 0.01)
        assert fc_cell.font.bold
        assert str(fc_cell.font.color.rgb).endswith("B45309")

    def test_two_period_analysis_has_no_growth_sheet(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/export?lang=ar",
                         headers=client.auth_headers)
        assert res.status_code == 200
        wb = load_workbook(io.BytesIO(res.content))
        assert "النمو السنوي والتوقع" not in wb.sheetnames
