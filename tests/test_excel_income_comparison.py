# -*- coding: utf-8 -*-
"""Statements worksheet: «مقارنة بالفترة السابقة» column on the income
statement — rendered ONLY when the analysis carries two periods whose
latest captured values tie to the attached statements' face.

Judgment colouring mirrors build_yearly_comparison: revenue/profit up =
green, costs up = red. Lines whose concept has no honest previous period
(single-period capture, restated duplicates, non-tying face) render «—»,
and with no comparable line at all the column is dropped entirely.
"""

import io
import json
import zipfile

from openpyxl import Workbook, load_workbook

from app.main import _income_comparison
from app.statements import build_statements

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# A balanced trial balance OF THE LATEST PERIOD (debits 1,385,000 = credits):
# face → revenue 650,000 / cogs 380,000 / opex 85,000 / net 185,000.
TB_LATEST = [
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

METRICS_TWO = {
    "revenue": [500_000.0, 650_000.0],
    "cogs": [300_000.0, 380_000.0],
    "opex": [70_000.0, 85_000.0],
}


# ---------------------------------------------------------------- unit ----

def _comp_by_label(comp, st):
    lines = st["income_statement"]["lines"]
    return {ln["en"]: comp.get(i) for i, ln in enumerate(lines)}


def test_two_clean_periods_full_column():
    st = build_statements(TB_LATEST)
    comp = _income_comparison({"metrics": METRICS_TWO}, st)
    by = _comp_by_label(comp, st)
    assert by["Revenue"] == {"pct": 30.0, "change": 150_000.0,
                             "curr": 650_000.0, "prev": 500_000.0,
                             "is_cost": False}
    assert by["Cost of Sales"] == {"pct": 26.7, "change": 80_000.0,
                                   "curr": 380_000.0, "prev": 300_000.0,
                                   "is_cost": True}
    assert by["Gross Profit"] == {"pct": 35.0, "change": 70_000.0,
                                  "curr": 270_000.0, "prev": 200_000.0,
                                  "is_cost": False}
    assert by["Operating Expenses"] == {"pct": 21.4, "change": 15_000.0,
                                        "curr": 85_000.0, "prev": 70_000.0,
                                        "is_cost": True}
    assert by["Operating Profit"] == {"pct": 42.3, "change": 55_000.0,
                                      "curr": 185_000.0, "prev": 130_000.0,
                                      "is_cost": False}
    assert by["Net Profit"] == {"pct": 42.3, "change": 55_000.0,
                                "curr": 185_000.0, "prev": 130_000.0,
                                "is_cost": False}


def test_single_period_no_comparison():
    st = build_statements(TB_LATEST)
    single = {k: [v[-1]] for k, v in METRICS_TWO.items()}
    assert _income_comparison({"metrics": single}, st) == {}
    assert _income_comparison({}, st) == {}


def test_non_tying_face_lines_skipped():
    """A latest capture that does NOT tie the face (the statements are of a
    different period) gets «—» on the affected lines — only honest lines
    keep their comparison."""
    st = build_statements(TB_LATEST)
    metrics = {
        "revenue": [500_000.0, 700_000.0],   # latest ≠ face 650,000
        "cogs": [300_000.0, 380_000.0],      # ties
        "opex": [70_000.0, 85_000.0],        # ties
    }
    comp = _income_comparison({"metrics": metrics}, st)
    by = _comp_by_label(comp, st)
    assert by["Revenue"] is None            # non-tying → «—»
    assert by["Gross Profit"] is None       # composition no longer ties
    assert by["Net Profit"] is None
    assert by["Cost of Sales"]["pct"] == 26.7
    assert by["Operating Expenses"]["pct"] == 21.4


def test_fully_unrelated_metrics_no_column():
    st = build_statements(TB_LATEST)
    metrics = {"revenue": [900_000.0, 999_000.0],
               "cogs": [111.0, 222.0], "opex": [1.0, 2.0]}
    assert _income_comparison({"metrics": metrics}, st) == {}


def test_tb_restatement_duplicates_skipped():
    """A trial-balance sheet sharing the workbook re-states the latest
    values (and its debit-side zero): those are NOT previous periods —
    the previous distinct non-zero value wins."""
    st = build_statements(TB_LATEST)
    metrics = {
        "revenue": [500_000.0, 650_000.0, 0.0, 650_000.0],
        "cogs": [300_000.0, 380_000.0, 380_000.0],
        "opex": [85_000.0, 70_000.0, 85_000.0],
    }
    comp = _income_comparison({"metrics": metrics}, st)
    by = _comp_by_label(comp, st)
    assert by["Revenue"]["pct"] == 30.0
    assert by["Cost of Sales"]["pct"] == 26.7
    assert by["Operating Expenses"]["pct"] == 21.4
    assert by["Net Profit"]["pct"] == 42.3


def test_present_single_period_component_blocks_net():
    """A face WITH a finance-cost line whose capture is single-period (even
    when it TIES the face) blocks the derived before-financing and net
    lines — no honest previous for a component, no honest previous for the
    composition. The finance line itself also renders «—»."""
    tb = [row[:] for row in TB_LATEST]
    tb.append(["فوائد قروض", 12_000, 0])
    tb[5][2] = 267_000  # قروض طويلة الأجل → rebalance credits
    st = build_statements(tb)
    metrics = dict(METRICS_TWO, finance_cost=[12_000.0])  # single period!
    comp = _income_comparison({"metrics": metrics}, st)
    by = _comp_by_label(comp, st)
    assert by["Finance Costs"] is None                    # single period
    assert by["Profit before Financing and Income Taxes"] is None
    assert by["Net Profit"] is None
    # the two-period concepts still compare
    assert by["Revenue"]["pct"] == 30.0


def test_two_period_finance_component_composes_net():
    """With TWO finance-cost periods tying the face, the finance line
    compares (+20%) and the derived before-financing/net lines compose
    over every component's previous period."""
    tb = [row[:] for row in TB_LATEST]
    tb.append(["فوائد قروض", 12_000, 0])
    tb[5][2] = 267_000
    st = build_statements(tb)
    metrics = dict(METRICS_TWO, finance_cost=[10_000.0, 12_000.0])
    comp = _income_comparison({"metrics": metrics}, st)
    by = _comp_by_label(comp, st)
    assert by["Finance Costs"] == {"pct": 20.0, "change": 2_000.0,
                                   "curr": 12_000.0, "prev": 10_000.0,
                                   "is_cost": True}
    assert by["Profit before Financing and Income Taxes"]["pct"] == 44.2
    assert by["Net Profit"]["pct"] == 44.2


def test_absent_categories_do_not_block_net():
    """No finance/tax lines on the face and no such concepts captured →
    they contribute zero and do NOT block the net comparison."""
    st = build_statements(TB_LATEST)
    comp = _income_comparison({"metrics": METRICS_TWO}, st)
    by = _comp_by_label(comp, st)
    assert by["Net Profit"]["pct"] == 42.3  # already proven; net not blocked


# ----------------------------------------------------------------- api ----

def _attach_tb(client):
    demo = client.post("/api/demo").json()
    wb = Workbook()
    ws = wb.active
    for row in TB_LATEST:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post(
        f"/api/analyses/{demo['id']}/trial-balance",
        files={"file": ("tb.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return demo["id"]


def test_pure_tb_single_period_has_no_column(client):
    aid = _attach_tb(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]
    texts = [str(c.value) for row in ws.iter_rows() for c in row
             if isinstance(c.value, str)]
    assert "قائمة الدخل" in " ".join(texts)
    assert "مقارنة بالفترة السابقة" not in texts
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_comparison_column_rendered_when_two_periods(client):
    aid = _attach_tb(client)
    # simulate the honest multi-period case: the attached statements ARE the
    # latest period of a two-period analysis
    import app.database as database

    with database.SessionLocal() as db:
        row = db.get(database.Analysis, aid)
        res = json.loads(row.result_json)
        res["metrics"] = METRICS_TWO
        row.result_json = json.dumps(res, ensure_ascii=False)
        db.commit()

    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]

    cells = {}
    for row_cells in ws.iter_rows():
        for c in row_cells:
            if c.value is not None:
                cells[(c.row, c.column)] = c
    header_cells = [c for c in cells.values()
                    if c.value == "مقارنة بالفترة السابقة"]
    assert header_cells, "comparison column header missing"
    hdr = header_cells[0]
    assert hdr.column == 4   # value | change AMOUNT | change %
    assert any(c.value == "التغير بالقيمة (ريال)" and c.column == 3
               for c in cells.values()), "change-amount column header missing"

    pct_cells = [c for c in cells.values()
                 if isinstance(c.value, str) and c.value.endswith(("▲", "▼", "◄►"))
                 and "%" in c.value]
    joined = " ".join(c.value for c in pct_cells)
    for expected in ("+30.0% ▲", "+26.7% ▲", "+35.0% ▲",
                     "+21.4% ▲", "+42.3% ▲"):
        assert expected in joined, expected

    # judgment colours: revenue up = green, costs up = red
    by_pct = {c.value: c.font.color.rgb for c in pct_cells}
    assert str(by_pct["+30.0% ▲"]).endswith("059669")   # GREEN
    assert str(by_pct["+26.7% ▲"]).endswith("DC2626")   # RED
    assert str(by_pct["+21.4% ▲"]).endswith("DC2626")   # RED
    assert str(by_pct["+42.3% ▲"]).endswith("059669")   # GREEN

    # the new SAR-amount column sits BEFORE the % column, same judgement
    # colours, signed amounts with thousands separators + shared arrow
    amt_cells = [c for c in cells.values()
                 if isinstance(c.value, str) and c.value.endswith(("▲", "▼", "◄►"))
                 and "%" not in c.value and (c.value.startswith("+") or c.value.startswith("-"))]
    amts = {c.value: c for c in amt_cells}
    for expected in ("+150,000 ▲",   # revenue 650k − 500k
                     "+80,000 ▲",    # cogs 380k − 300k
                     "+15,000 ▲"):   # opex 85k − 70k
        assert expected in amts, expected
    assert str(amts["+150,000 ▲"].font.color.rgb).endswith("059669")  # GREEN
    assert str(amts["+80,000 ▲"].font.color.rgb).endswith("DC2626")   # RED
    assert str(amts["+15,000 ▲"].font.color.rgb).endswith("DC2626")   # RED
    # the amount column is text-formatted (keeps «+» and separators)
    assert amts["+150,000 ▲"].number_format == "@"
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_mini_period_columns_chart_beside_income_table(client):
    """A small clustered column chart beside the income statement face
    compares the two periods' values for every line carrying the new change
    columns — fed by a visible prev/curr block in the sheet."""
    aid = _attach_tb(client)
    import app.database as database

    with database.SessionLocal() as db:
        row = db.get(database.Analysis, aid)
        res = json.loads(row.result_json)
        res["metrics"] = METRICS_TWO
        row.result_json = json.dumps(res, ensure_ascii=False)
        db.commit()

    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]

    # the visible data block beside the face (columns F..H): header +
    # one row per comparable line with prev/curr magnitudes
    cells = {(c.row, c.column): c for row_ in ws.iter_rows() for c in row_
             if c.value is not None}
    blk = [(rr, cc) for (rr, cc) in cells if cc in (6, 7, 8)]
    assert blk, "comparison data block missing beside the income table"
    hdr_row = min(rr for (rr, cc) in blk if cc == 6)
    assert cells[(hdr_row, 6)].value == "البند"
    assert cells[(hdr_row, 7)].value == "الفترة السابقة"
    assert cells[(hdr_row, 8)].value == "الفترة الحالية"
    labels = [cells[(rr, 6)].value for (rr, cc) in blk
              if cc == 6 and rr > hdr_row]
    assert set(labels) >= {"الإيرادات", "تكلفة المبيعات", "صافي الربح"}
    rev_row = next(rr for (rr, cc) in blk if cc == 6 and rr > hdr_row
                   and cells[(rr, cc)].value == "الإيرادات")
    assert cells[(rev_row, 7)].value == 500_000.0   # previous
    assert cells[(rev_row, 8)].value == 650_000.0   # current

    # the chart itself: a clustered column chart with the two period series
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    chart_xmls = [z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                  if n.startswith("xl/charts/chart")]
    # openpyxl serialises charts with the default namespace (no c: prefix)
    mini = [x for x in chart_xmls
            if "<barChart>" in x and "مقارنة قائمة الدخل" in x]
    assert mini, "period-comparison column chart missing"
    assert mini[0].count("<ser>") == 2              # previous + current
    assert 'val="col"' in mini[0]
    # brand colours: current teal, previous muted slate
    assert "0F766E" in mini[0] and "94A3B8" in mini[0]
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_no_chart_without_comparison(client):
    """Single-period export: no comparison columns → no period chart."""
    aid = _attach_tb(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    chart_xmls = [z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                  if n.startswith("xl/charts/chart")]
    assert not [x for x in chart_xmls
                if "مقارنة قائمة الدخل" in x], \
        "period chart must not render without comparable lines"
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
