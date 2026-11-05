# -*- coding: utf-8 -*-
"""Excel charts sheet: per-period working-capital cycle series.

The «الرسوم البيانية التحليلية» worksheet gains its own activity block: a
small table (period | فترة التحصيل | دوران المخزون | فترة السداد | دورة
التحول النقدي) plus a native line chart of the series the analysis
actually supports, computed with the same formulas compute_ratios applies
to the latest period — across EVERY captured period, so the full working-
capital heartbeat (CCC = DSO + DIO − DPO) is visible over time.
"""

import io

from openpyxl import Workbook, load_workbook

from app.analyzer import compute_activity_series

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------- unit ----

def test_activity_series_two_periods_exact():
    """United-style figures: DSO 54.75 → 61.77 days, turns 3.33 → 3.04."""
    metrics = {
        "receivables": [75000.0, 110000.0],
        "revenue": [500000.0, 650000.0],
        "inventory": [90000.0, 125000.0],
        "cogs": [300000.0, 380000.0],
    }
    act = compute_activity_series(metrics)
    assert act["receivable_days"]["values"] == [54.75, 61.77]
    assert act["receivable_days"]["ar"] == "فترة التحصيل (يوم)"
    assert act["inventory_turnover"]["values"] == [3.33, 3.04]
    assert act["inventory_turnover"]["ar"] == "دوران المخزون (x)"


def test_activity_series_missing_inputs_yield_none():
    """A period without its inputs (no revenue yet, cogs missing after p1)
    leaves a None HOLE in the series instead of a guessed value."""
    metrics = {
        "receivables": [75000.0, 110000.0, 8000.0],
        "revenue": [500000.0, 650000.0],  # third period's revenue missing
        "cogs": [300000.0],               # turns exist for period 1 only
        "inventory": [90000.0, 125000.0],
    }
    act = compute_activity_series(metrics)
    assert act["receivable_days"]["values"] == [54.75, 61.77, None]
    assert act["inventory_turnover"]["values"] == [3.33, None, None]


def test_activity_series_omitted_without_any_qualifying_period():
    """No qualifying period at all → the ratio is omitted entirely."""
    metrics = {"receivables": [75000.0], "revenue": []}
    assert compute_activity_series(metrics) == {}


def test_activity_series_single_period_available():
    metrics = {"receivables": [75000.0], "revenue": [500000.0]}
    act = compute_activity_series(metrics)
    assert act["receivable_days"]["values"] == [54.75]


def test_activity_series_abs_sign_conventions():
    """Negative-captured receivables (parentheses convention) and a
    negative revenue still produce the same positive ratio."""
    metrics = {"receivables": [-75000.0], "revenue": [-500000.0]}
    act = compute_activity_series(metrics)
    assert act["receivable_days"]["values"] == [54.75]


def test_activity_series_dpo_ccc_two_periods_exact():
    """With the payables leg present, CCC = DSO + DIO − DPO per period —
    and the latest values match compute_ratios' live United figures
    (61.77 / 120.07 / 76.84 / 105.0)."""
    metrics = {
        "receivables": [75000.0, 110000.0],
        "revenue": [500000.0, 650000.0],
        "inventory": [90000.0, 125000.0],
        "cogs": [300000.0, 380000.0],
        "payables": [65000.0, 80000.0],
    }
    act = compute_activity_series(metrics)
    assert act["days_payable"]["values"] == [79.08, 76.84]
    assert act["days_payable"]["ar"] == "فترة السداد (يوم)"
    assert act["cash_conversion_cycle"]["values"] == [85.17, 105.0]
    assert act["cash_conversion_cycle"]["ar"] == "دورة التحول النقدي (يوم)"


def test_activity_series_ccc_hole_when_leg_missing():
    """A period without its payables leaves a CCC hole there instead of a
    partial (wrong) cycle."""
    metrics = {
        "receivables": [75000.0, 110000.0],
        "revenue": [500000.0, 650000.0],
        "inventory": [90000.0, 125000.0],
        "cogs": [300000.0, 380000.0],
        "payables": [65000.0],  # second period missing
    }
    act = compute_activity_series(metrics)
    assert act["days_payable"]["values"] == [79.08, None]
    assert act["cash_conversion_cycle"]["values"] == [85.17, None]


def test_activity_series_no_payables_omits_dpo_ccc():
    """No payables captured at all → DPO and CCC are omitted entirely
    (the block shrinks to the collection/turnover columns)."""
    metrics = {"receivables": [75000.0], "revenue": [500000.0],
               "inventory": [90000.0], "cogs": [300000.0]}
    act = compute_activity_series(metrics)
    assert "days_payable" not in act
    assert "cash_conversion_cycle" not in act


def test_activity_series_empty_metrics():
    assert compute_activity_series({}) == {}


# ----------------------------------------------------------------- api ----

def _upload_two_period(client) -> int:
    """A compact comparative sheet: revenue + cogs + the two working-capital
    balances across two years (positive-cost classic convention)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "المقارنة"
    for row in [
        ["البند", "عام 2024", "عام 2025"],
        ["إجمالي المبيعات", 500000, 650000],
        ["تكلفة المبيعات", 300000, 380000],
        ["ذمم مدينة (عملاء)", 75000, 110000],
        ["المخزون السلعي", 90000, 125000],
    ]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post(
        "/api/upload",
        files={"files": ("نشاط.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["uploaded"][0]["id"]


def test_excel_charts_sheet_has_activity_block(client):
    aid = _upload_two_period(client)
    try:
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        assert resp.status_code == 200
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "التحليلية" in n)]

        texts = [str(c.value) for row in ws.iter_rows() for c in row
                 if isinstance(c.value, str)]
        joined = " ".join(texts)
        assert "تطور دورة التحول النقدي ومكوناتها" in joined
        assert "فترة التحصيل (يوم)" in joined
        assert "دوران المخزون (x)" in joined
        # no payables in this workbook → DPO/CCC columns are omitted
        assert "فترة السداد (يوم)" not in joined
        assert "دورة التحول النقدي (يوم)" not in joined

        amounts = [c.value for row in ws.iter_rows() for c in row
                   if isinstance(c.value, (int, float))
                   and not isinstance(c.value, bool)]
        for expected in (54.75, 61.77, 3.33, 3.04):
            assert expected in amounts, expected
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_excel_activity_line_chart_two_series(client):
    aid = _upload_two_period(client)
    try:
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "التحليلية" in n)]
        lines = [ch for ch in ws._charts if type(ch).__name__ == "LineChart"]
        # the combined raw-concepts line chart + the new activity chart
        assert len(lines) >= 2
        activity = next(ch for ch in lines if len(ch.series) == 2)
        assert len(activity.series) == 2
        # both series are smooth-off like the rest of the sheet's charts
        assert all(s.smooth is False or s.smooth is None for s in activity.series)
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def _upload_two_period_wc(client) -> int:
    """Comparative sheet WITH the payables leg of the cycle."""
    wb = Workbook()
    ws = wb.active
    ws.title = "المقارنة"
    for row in [
        ["البند", "عام 2024", "عام 2025"],
        ["إجمالي المبيعات", 500000, 650000],
        ["تكلفة المبيعات", 300000, 380000],
        ["ذمم مدينة (عملاء)", 75000, 110000],
        ["المخزون السلعي", 90000, 125000],
        ["ذمم دائنة (موردون)", 65000, 80000],
    ]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post(
        "/api/upload",
        files={"files": ("دورة.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["uploaded"][0]["id"]


def test_excel_full_cycle_block_and_chart(client):
    """With payables captured, the block carries ALL FOUR series (DSO,
    turnover, DPO, CCC) and the chart grows to four lines — values exact:
    DPO 79.08→76.84 days, CCC 85.17→105.0 days."""
    aid = _upload_two_period_wc(client)
    try:
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        assert resp.status_code == 200
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "التحليلية" in n)]

        texts = [str(c.value) for row in ws.iter_rows() for c in row
                 if isinstance(c.value, str)]
        joined = " ".join(texts)
        assert "تطور دورة التحول النقدي ومكوناتها" in joined
        assert "فترة السداد (يوم)" in joined
        assert "دورة التحول النقدي (يوم)" in joined

        amounts = [c.value for row in ws.iter_rows() for c in row
                   if isinstance(c.value, (int, float))
                   and not isinstance(c.value, bool)]
        for expected in (79.08, 76.84, 85.17, 105.0):
            assert expected in amounts, expected

        lines = [ch for ch in ws._charts if type(ch).__name__ == "LineChart"]
        activity = [ch for ch in lines if len(ch.series) == 4]
        assert len(activity) == 1
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_excel_activity_block_absent_without_balances(client):
    """No receivables/inventory in the file → no activity table, no stray
    zeros — the block is skipped entirely."""
    wb = Workbook()
    ws = wb.active
    ws.title = "دخل فقط"
    for row in [
        ["البند", "عام 2024", "عام 2025"],
        ["إجمالي المبيعات", 500000, 650000],
        ["تكلفة المبيعات", 300000, 380000],
    ]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post(
        "/api/upload",
        files={"files": ("دخل.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200
    aid = resp.json()["uploaded"][0]["id"]
    try:
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "التحليلية" in n)]
        texts = [str(c.value) for row in ws.iter_rows() for c in row
                 if isinstance(c.value, str)]
        joined = " ".join(texts)
        assert "تطور فترة التحصيل ودوران المخزون" not in joined
        assert "فترة التحصيل (يوم)" not in joined
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
