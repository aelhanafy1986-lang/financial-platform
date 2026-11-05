# -*- coding: utf-8 -*-
"""Multi-year English statements (>3 years) with annual growth comparison.

Contract: a statements document carrying 4+ year columns is captured with
EVERY year as its own period (oldest → newest), the comparison payload
exposes per-year values with YoY growth, and the PDF report renders an
annual growth table (value + YoY% per year) instead of collapsing to the
last two periods.
"""

import io

from fastapi.testclient import TestClient

from app.analyzer import _normalize_period_labels
from app.ratio_explain import build_yearly_comparison

DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")

INCOME_4Y = [
    ["Item", "2025", "2024", "2023", "2022"],
    ["Total revenue", "500,000", "400,000", "320,000", "250,000"],
    ["Total cost of revenue", "200,000", "160,000", "128,000", "100,000"],
    ["Sales and marketing", "80,000", "70,000", "60,000", "50,000"],
    ["Other income (expense), net", "(5,000)", "(4,000)", "(3,000)", "(2,000)"],
    ["Provision for income taxes", "30,000", "25,000", "20,000", "15,000"],
    ["Net income", "185,000", "141,000", "109,000", "83,000"],
]
BALANCE_4Y = [
    ["Item", "2025", "2024", "2023", "2022"],
    ["Total assets", "600,000", "500,000", "420,000", "350,000"],
    ["Accounts payable", "90,000", "80,000", "70,000", "60,000"],
]
CASHFLOW_4Y = [
    ["Item", "2025", "2024", "2023", "2022"],
    ["Net income", "185,000", "141,000", "109,000", "83,000"],
    ["Sales of investments", "(2,000)", "(2,000)", "(2,000)", "(2,000)"],
]


def _make_4y_docx(path) -> bytes:
    import docx

    d = docx.Document()
    d.add_heading("Financial Statements 2022-2025")
    for rows in (INCOME_4Y, BALANCE_4Y, CASHFLOW_4Y):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                t.cell(r, c).text = str(val)
    d.save(str(path))
    return path.read_bytes()


# --------------------------------------------------------------- unit ----

def test_normalize_period_labels():
    """Merged header cells repeat years; US-GAAP runs newest-first — labels
    come out deduped and ascending (oldest → latest) to match the
    year-sorted series."""
    assert _normalize_period_labels(
        ["2025", "2025", "2024", "2024", "2023", "2023"]) == \
        ["2023", "2024", "2025"]
    assert _normalize_period_labels(["2024", "2025"]) == ["2024", "2025"]
    # non-year periods keep their column order, deduped
    assert _normalize_period_labels(["Q1", "Q2", "Q3", "Q4"]) == \
        ["Q1", "Q2", "Q3", "Q4"]
    assert _normalize_period_labels(["2024"]) == ["2024"]


def test_yearly_comparison_growth_points():
    """The comparison payload carries every year with its YoY growth, and
    the year labels follow period_labels (oldest → latest)."""
    result = {
        "metrics": {
            "revenue": [250_000.0, 320_000.0, 400_000.0, 500_000.0],
            "cogs": [100_000.0, 128_000.0, 160_000.0, 200_000.0],
            "opex": [50_000.0, 60_000.0, 70_000.0, 80_000.0],
            "net_profit": [83_000.0, 109_000.0, 141_000.0, 185_000.0],
        },
        "period_labels": ["2022", "2023", "2024", "2025"],
    }
    comp = build_yearly_comparison(result, "ar")
    assert comp["years"] == ["2022", "2023", "2024", "2025"]
    assert comp["growth_title"]
    rev = next(r for r in comp["rows"] if r["key"] == "revenue")
    assert [p["label"] for p in rev["points"]] == \
        ["2022", "2023", "2024", "2025"]
    assert [p["growth"] for p in rev["points"]] == \
        [None, "+28.0%", "+25.0%", "+25.0%"]
    net = next(r for r in comp["rows"] if r["key"] == "net_profit")
    assert [p["growth"] for p in net["points"]] == \
        [None, "+31.3%", "+29.4%", "+31.2%"]


def test_yearly_comparison_two_periods_has_no_growth_table():
    """Two periods only: the growth table stays off (the curr/prev table
    already covers it)."""
    result = {
        "metrics": {"revenue": [400_000.0, 500_000.0],
                    "cogs": [160_000.0, 200_000.0]},
        "period_labels": ["2024", "2025"],
    }
    comp = build_yearly_comparison(result, "ar")
    assert comp is not None and comp.get("rows")
    assert not comp.get("years")


# ------------------------------------------------------- end-to-end ------

class TestMultiYearReportGrowth:
    def _upload(self, client, tmp_path):
        data = _make_4y_docx(tmp_path / "statements_4y.docx")
        return client.post(
            "/api/upload",
            files={"files": ("statements_4y.docx", io.BytesIO(data),
                             DOCX_MIME)},
            headers=client.auth_headers,
        )

    def test_four_years_captured(self, client, tmp_path):
        """All four years become periods of ONE analysis, oldest → newest,
        with real year labels."""
        resp = self._upload(client, tmp_path)
        assert resp.status_code == 200, resp.text
        uploaded = resp.json()["uploaded"]
        assert len(uploaded) == 1, uploaded
        item = uploaded[0]
        assert "error" not in item, item
        res = item["result"]
        assert res["period_labels"] == ["2022", "2023", "2024", "2025"]
        m = res["metrics"]
        assert m["revenue"] == [250_000.0, 320_000.0, 400_000.0, 500_000.0]
        assert m["cogs"] == [100_000.0, 128_000.0, 160_000.0, 200_000.0]
        assert m["net_profit"][-1] == 185_000.0
        assert m["assets"] == [350_000.0, 420_000.0, 500_000.0, 600_000.0]
        client.delete(f"/api/analyses/{item['id']}", headers=client.auth_headers)

    def test_report_renders_annual_growth_table(self, client, tmp_path):
        """The PDF report carries the annual growth table: every year column
        with its value and YoY change."""
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
        for needle in ("2022", "2023", "2024", "2025",
                       "+28.0%", "+25.0%", "500,000"):
            assert needle in text, needle
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
