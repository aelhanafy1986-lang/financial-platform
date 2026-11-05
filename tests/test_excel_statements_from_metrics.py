# -*- coding: utf-8 -*-
"""Comparison files WITHOUT a trial balance (the United-style capture: one
metric value per year column) now get a statements sheet too — the faces
(income statement / financial position / simplified cash flow) are derived
for EVERY period from the multi-period metric series, followed by one
comparative grid (rows = concepts, columns = the file's own period labels).

The trial-balance path must stay untouched: an attached TB sheet always
wins, a single-period comparison file gets NO statements sheet, and the
TB-backed sheet keeps its «مقارنة بالفترة السابقة» column behaviour.
"""

import io
import json

from openpyxl import Workbook, load_workbook

from app.statements import (
    build_statements_from_metrics,
    _derived_comparative_grid,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Two clean periods of the United-style capture (expenses are positive
# magnitudes AFTER sign normalisation, exactly as stored in result_json).
METRICS_TWO = {
    "revenue": [500_000.0, 650_000.0],
    "cogs": [300_000.0, 380_000.0],
    "opex": [70_000.0, 85_000.0],
    "cash": [120_000.0, 210_000.0],
    "inventory": [90_000.0, 125_000.0],
    "receivables": [60_000.0, 110_000.0],
    "payables": [45_000.0, 80_000.0],
    "current_assets": [270_000.0, 445_000.0],
    "current_liabilities": [45_000.0, 80_000.0],
    "assets": [500_000.0, 700_000.0],
    "liabilities": [100_000.0, 145_000.0],
    "equity": [400_000.0, 555_000.0],
}


def _upload_two_period_file(client, headers=None):
    """A comparison-style workbook: year columns + ratio labels, no TB.
    Returns the analysis id created by the upload itself."""
    wb = Workbook()
    ws = wb.active
    ws.append(["البند", "2024", "2025"])
    ws.append(["الإيرادات", 500000, 650000])
    ws.append(["تكلفة المبيعات", 300000, 380000])
    ws.append(["المصاريف التشغيلية", 70000, 85000])
    ws.append(["النقدية", 120000, 210000])
    ws.append(["المدينون", 60000, 110000])
    ws.append(["المخزون", 90000, 125000])
    ws.append(["الدائنون", 45000, 80000])
    ws.append(["إجمالي الأصول", 500000, 700000])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post("/api/upload",
                       files={"files": ("compare.xlsx", buf, XLSX_MIME)},
                       headers=headers if headers is not None else client.auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["uploaded"][0]["id"]


# ------------------------------------------------------------ builder ----

def test_builder_produces_full_faces_and_grid():
    st = build_statements_from_metrics(METRICS_TWO, ["2024", "2025"])
    assert st is not None
    assert st["derived_from_metrics"] is True
    assert st["period_labels"] == [{"ar": "2024", "en": "2024"},
                                   {"ar": "2025", "en": "2025"}]
    p0, p1 = st["periods"]

    is0 = p0["income_statement"]
    amounts = {ln["en"]: ln["amount"] for ln in is0["lines"]}
    assert amounts["Revenue"] == 500_000.0
    assert amounts["Cost of Sales"] == -300_000.0          # shown negative on the face
    assert amounts["Gross Profit"] == 200_000.0
    assert amounts["Operating Expenses"] == -70_000.0
    assert amounts["Operating Profit"] == 130_000.0
    assert amounts["Net Profit"] == 130_000.0
    assert is0["totals"]["cogs"] == 300_000.0              # positive magnitude in totals

    # second period: revenue 650k / cogs 380k / opex 85k → net 185k
    is1 = p1["income_statement"]
    assert {ln["en"]: ln["amount"] for ln in is1["lines"]}["Net Profit"] == 185_000.0
    assert is1["totals"]["cogs"] == 380_000.0

    # financial position: named balances + residual fixed assets / financing
    bs0 = p0["balance_sheet"]
    a0 = {ln["en"]: ln["amount"] for ln in bs0["assets"]["lines"]}
    l0 = {ln["en"]: ln["amount"] for ln in bs0["liabilities_equity"]["lines"]}
    assert a0["Cash & Banks"] == 120_000.0
    assert a0["Fixed Assets"] == 230_000.0                 # 500k total − named current pool
    assert l0["Payables"] == 45_000.0
    assert l0["Loans"] == 55_000.0                          # 100k liabilities − payables
    assert l0["Equity"] == 400_000.0
    assert bs0["balanced"] is True
    assert bs0["assets"]["total"] == 500_000.0

    # IFRS 18 categories ride along when captured
    st3 = build_statements_from_metrics(
        dict(METRICS_TWO, finance_cost=[10_000.0, 12_000.0],
             investment_income=[5_000.0, 7_000.0],
             tax_expense=[8_000.0, 9_000.0]),
        ["2024", "2025"],
    )
    face = {ln["en"] for ln in st3["periods"][1]["income_statement"]["lines"]}
    assert {"Investment Income", "Finance Costs",
            "Profit before Financing and Income Taxes",
            "Zakat and Income Tax"} <= face
    # net composed through the chain: 650k−380k−85k+7k−12k−9k = 171k
    amt1 = {ln["en"]: ln["amount"]
            for ln in st3["periods"][1]["income_statement"]["lines"]}
    assert amt1["Net Profit"] == 171_000.0


def test_builder_requires_two_periods():
    assert build_statements_from_metrics({"revenue": [1.0], "cogs": [1.0]}) is None
    assert build_statements_from_metrics({}) is None
    assert build_statements_from_metrics(
        {"revenue": [500_000.0, 650_000.0]}) is None        # cogs missing


def test_builder_short_series_align_and_fill():
    """The spine is the revenue series; a period missing its cogs value is
    skipped (never guessed) while the COMPLETE periods still build, and a
    concept captured for fewer periods simply has no line in later faces."""
    st = build_statements_from_metrics(
        {"revenue": [100.0, 120.0, 140.0], "cogs": [60.0, 70.0]},
        ["2023", "2024", "2025"])
    assert st is not None
    assert [p["label"]["en"] for p in st["periods"]] == ["2023", "2024"]

    st2 = build_statements_from_metrics(
        {"revenue": [100.0, 120.0, 140.0], "cogs": [60.0, 70.0, 80.0],
         "opex": [10.0]},                                   # opex only for period 1
        ["2023", "2024", "2025"])
    assert st2 is not None and len(st2["periods"]) == 3
    # period 1 has an opex line; periods 2/3 do not
    face1 = [ln["en"] for ln in st2["periods"][0]["income_statement"]["lines"]]
    face3 = [ln["en"] for ln in st2["periods"][2]["income_statement"]["lines"]]
    assert "Operating Expenses" in face1 and "Operating Expenses" not in face3


# --------------------------------------------------------------- grid ----

def test_grid_rows_labels_and_bold():
    st = build_statements_from_metrics(METRICS_TWO, ["2024", "2025"])
    headers, rows, bold = _derived_comparative_grid(st, "ar")
    assert headers == ["2024", "2025"]
    by_label = {r[0]: r[1:] for r in rows}
    assert by_label["الإيرادات"] == [500_000.0, 650_000.0]
    assert by_label["تكلفة المبيعات"] == [300_000.0, 380_000.0]   # magnitude view
    assert by_label["صافي الربح"] == [130_000.0, 185_000.0]
    assert by_label["إجمالي الأصول"] == [500_000.0, 700_000.0]
    assert by_label["حقوق الملكية"] == [400_000.0, 555_000.0]
    bold_rows = {rows[i][0] for i in bold}
    assert {"الربح الإجمالي", "صافي الربح",
            "إجمالي الأصول", "حقوق الملكية"} <= bold_rows
    # the composed operating cash flow rides below net profit: 2024 settles
    # everything in cash (net 130k); 2025 loses 50k to working capital
    # (receivables +50k, inventory +35k, payables +35k) → 135k
    assert by_label["صافي التدفق من الأنشطة التشغيلية"] == \
        [130_000.0, 135_000.0]
    # investing/financing are NOT stated by this file → never invented
    assert "صافي التدفق من الأنشطة الاستثمارية" not in by_label
    assert "صافي التدفق من الأنشطة التمويلية" not in by_label
    assert "صافي التدفق من الأنشطة التشغيلية" in bold_rows
    # concepts never captured are omitted, not zero-filled
    assert all(r[0] != "عوائد الاستثمار" for r in rows)

    headers_en, rows_en, _ = _derived_comparative_grid(st, "en")
    assert headers_en == ["2024", "2025"]
    assert rows_en[0][0] == "Revenue"


def test_grid_carries_stated_cashflow_activities():
    """When the file STATES its activity totals (cf_operating / cf_investing /
    cf_financing — the usual United-style capture), all three net-flow rows
    appear in the grid with the file's own figures, one column per period."""
    metrics = dict(METRICS_TWO,
                   cf_operating=[95_000.0, 150_000.0],
                   cf_investing=[-30_000.0, -45_000.0],
                   cf_financing=[10_000.0, -20_000.0])
    st = build_statements_from_metrics(metrics, ["2024", "2025"])
    headers, rows, bold = _derived_comparative_grid(st, "ar")
    by_label = {r[0]: r[1:] for r in rows}
    assert by_label["صافي التدفق من الأنشطة التشغيلية"] == \
        [95_000.0, 150_000.0]      # stated wins over the composed line
    assert by_label["صافي التدفق من الأنشطة الاستثمارية"] == \
        [-30_000.0, -45_000.0]     # negative flows keep their sign
    assert by_label["صافي التدفق من الأنشطة التمويلية"] == \
        [10_000.0, -20_000.0]
    bold_rows = {rows[i][0] for i in bold}
    assert {"صافي التدفق من الأنشطة التشغيلية",
            "صافي التدفق من الأنشطة الاستثمارية",
            "صافي التدفق من الأنشطة التمويلية"} <= bold_rows

    headers_en, rows_en, _ = _derived_comparative_grid(st, "en")
    by_en = {r[0]: r[1:] for r in rows_en}
    assert by_en["Net cash from operating activities"] == \
        [95_000.0, 150_000.0]
    assert by_en["Net cash from investing activities"] == \
        [-30_000.0, -45_000.0]


def test_grid_skips_concepts_absent_from_capture():
    st = build_statements_from_metrics(
        {"revenue": [100.0, 120.0], "cogs": [60.0, 70.0]}, ["2024", "2025"])
    headers, rows, bold = _derived_comparative_grid(st, "ar")
    labels = [r[0] for r in rows]
    # with no expenses captured, operating == net == gross: the subtotals
    # still show (arithmetically true), nothing else is invented. The
    # composed operating CASH flow (== net here) shows; investing/financing
    # (nothing stated) stay off the grid.
    assert labels == ["الإيرادات", "تكلفة المبيعات", "الربح الإجمالي",
                      "الربح التشغيلي", "صافي الربح",
                      "صافي التدفق من الأنشطة التشغيلية"]
    assert bold == {2, 3, 4, 5}


# ---------------------------------------------------------------- api ----

def _statements_sheet(wb):
    name = next(n for n in wb.sheetnames if "القوائم" in n)
    return wb[name]


def test_export_comparison_file_has_per_period_statements(client):
    aid = _upload_two_period_file(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)
    texts = [str(c.value) for row in ws.iter_rows() for c in row
             if isinstance(c.value, str)]
    joined = " | ".join(texts)
    # per-period section titles built from the file's own period labels
    assert "قائمة الدخل — 2024" in joined and "قائمة الدخل — 2025" in joined
    assert "قائمة المركز المالي — 2024" in joined
    assert "قائمة التدفقات النقدية — 2025" in joined
    # the comparative grid
    assert "مقارنة بالفترات" in joined
    # derived title (honest: NOT "from the trial balance")
    assert "القوائم المالية (لكل فترة)" in joined
    assert "من ميزان المراجعة" not in joined
    # single-face comparison column must NOT appear on a derived sheet
    assert "مقارنة بالفترة السابقة" not in joined
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_export_comparison_file_values_per_period(client):
    """The sheet shows the values of EACH period: 2024 revenue 500,000 /
    net 130,000; 2025 revenue 650,000 / net 185,000; the grid carries both
    periods side by side."""
    aid = _upload_two_period_file(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)

    def row_of(text):
        for row in ws.iter_rows():
            if any(c.value == text for c in row):
                return row
        return None

    # find a face row by its 2024 section, then read the value in col 2
    def value_after(section_text, label):
        in_section = False
        for row in ws.iter_rows():
            first = row[0].value
            if isinstance(first, str) and first.startswith(section_text):
                in_section = True
                continue
            if in_section and isinstance(first, str) and first == label:
                return row[1].value
        return None

    assert value_after("قائمة الدخل — 2024", "الإيرادات") == 500_000
    assert value_after("قائمة الدخل — 2024", "صافي الربح") == 130_000
    assert value_after("قائمة الدخل — 2025", "الإيرادات") == 650_000
    assert value_after("قائمة الدخل — 2025", "صافي الربح") == 185_000
    assert value_after("قائمة الدخل — 2025", "الربح الإجمالي") == 270_000

    # grid: header row [البند, 2024, 2025], revenue row [الإيرادات, 500000, 650000]
    grid_hdr = row_of("مقارنة بالفترات")
    assert grid_hdr is not None
    hdr_row = ws[grid_hdr[0].row + 1]
    assert [c.value for c in hdr_row[:3]] == ["البند", "2024", "2025"]
    rev_row = row_of("الإيرادات")  # first occurrence = inside grid? check both
    grid_rows = {}
    started = False
    for row in ws.iter_rows(min_row=grid_hdr[0].row + 1):
        first = row[0].value
        if isinstance(first, str) and first.startswith("قائمة"):
            break
        if isinstance(first, str) and first and row[2].value is not None \
                and not isinstance(row[1].value, str):
            # numeric period columns only — the «مقارنة قائمة الدخل» table
            # below the grid repeats the labels with TEXT change columns
            grid_rows[first] = [c.value for c in row[1:3]]
    assert grid_rows["الإيرادات"] == [500_000, 650_000]
    assert grid_rows["صافي الربح"] == [130_000, 185_000]
    assert grid_rows["إجمالي الأصول"] == [500_000, 700_000]
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_export_single_period_comparison_file_has_no_statements(client):
    """A one-period comparison file keeps the old behaviour: no statements
    sheet is derived (single period cannot show a financial position per
    period, and the builder refuses to invent one)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["البند", "2025"])
    ws.append(["الإيرادات", 650000])
    ws.append(["تكلفة المبيعات", 380000])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post("/api/upload",
                       files={"files": ("one.xlsx", buf, XLSX_MIME)},
                       headers=client.auth_headers)
    assert resp.status_code == 200
    aid = resp.json()["uploaded"][0]["id"]
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    assert not any("القوائم" in n for n in wb.sheetnames)
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_tb_attached_statements_still_win(client):
    """A file with BOTH metric series and an attached (balanced) trial
    balance keeps the TB-backed sheet: real statements always win."""
    from app.statements import build_statements

    TB = [
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
    wb = Workbook()
    ws = wb.active
    for row in TB:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post("/api/upload",
                       files={"files": ("tb.xlsx", buf, XLSX_MIME)},
                       headers=client.auth_headers)
    assert resp.status_code == 200
    aid = resp.json()["uploaded"][0]["id"]
    # metrics present (two periods) but statements_json attached → TB wins
    import app.database as database

    with database.SessionLocal() as db:
        row = db.get(database.Analysis, aid)
        res = json.loads(row.result_json)
        res["metrics"] = dict(METRICS_TWO)
        res["period_labels"] = ["2024", "2025"]
        row.result_json = json.dumps(res, ensure_ascii=False)
        db.commit()

    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)
    texts = [str(c.value) for row in ws.iter_rows() for c in row
             if isinstance(c.value, str)]
    joined = " | ".join(texts)
    assert "ميزان المراجعة" in joined
    assert "قائمة الدخل" in joined
    # NOT the derived per-period layout
    assert "قائمة الدخل — 2025" not in joined
    assert "مقارنة بالفترات" not in joined
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_demo_analysis_gets_derived_sheet_when_two_periods(client):
    """End-to-end: a comparison file uploaded through /api/upload gets its
    metrics-derived statements ATTACHED at upload time (has_statements),
    and the Excel export renders the derived sheet from that one source."""
    aid = _upload_two_period_file(client)
    import app.database as database

    with database.SessionLocal() as db:
        row = db.get(database.Analysis, aid)
        res = json.loads(row.result_json)
        # sanity: the upload pipeline itself captured the two-period series
        assert res.get("metrics", {}).get("revenue") == [500_000.0, 650_000.0]
        assert res.get("period_labels") == ["2024", "2025"]
        # the metrics-derived statements are attached to the row (the
        # comparison-files contract): marked, two periods, no TB claimed
        st = json.loads(row.statements_json)
        assert st["derived_from_metrics"] is True
        assert len(st["periods"]) == 2
        assert row.has_tb is False

    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    assert any("القوائم" in n for n in wb.sheetnames)
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_income_comparison_table_with_change_by_value(client):
    """The derived sheet's «مقارنة قائمة الدخل» table carries the change
    BY VALUE (SAR) column beside its percentage: revenue +150,000 / +30.0%,
    cogs +80,000 / +26.7% — 2025 vs 2024, judgement-coloured."""
    aid = _upload_two_period_file(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)

    cells = {(c.row, c.column): c for row in ws.iter_rows() for c in row
             if c.value is not None}
    hdr = next(c for c in cells.values()
               if c.value == "التغير بالقيمة")
    assert hdr.column == 4      # البند | الحالية | السابقة | بالقيمة | بالنسبة
    assert any(c.value == "مقارنة قائمة الدخل" for c in cells.values())

    def row_of(label):
        for c in cells.values():
            if c.column == 1 and c.value == label and c.row > hdr.row:
                return c.row
        return None

    rev, cogs = row_of("الإيرادات"), row_of("تكلفة الإيرادات")
    assert (cells[(rev, 4)].value, cells[(rev, 5)].value) == ("+150,000", "+30.0%")
    assert (cells[(cogs, 4)].value, cells[(cogs, 5)].value) == ("+80,000", "+26.7%")
    # judgement colours: revenue up = green, cost up = red
    assert str(cells[(rev, 4)].font.color.rgb).endswith("059669")
    assert str(cells[(cogs, 4)].font.color.rgb).endswith("DC2626")
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_mini_period_chart_beside_income_comparison_table(client):
    """The derived sheet's «مقارنة قائمة الدخل» table gains the mini
    clustered column chart: the two periods' values per concept row
    (numeric block in F..H, chart anchored beside it)."""
    aid = _upload_two_period_file(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)

    cells = {(c.row, c.column): c for row in ws.iter_rows() for c in row
             if c.value is not None}
    blk = [(rr, cc) for (rr, cc) in cells if cc in (6, 7, 8)]
    assert blk, "numeric period block missing beside the comparison table"
    hdr_row = min(rr for (rr, cc) in blk if cc == 6)
    assert cells[(hdr_row, 7)].value == "الفترة السابقة"
    assert cells[(hdr_row, 8)].value == "الفترة الحالية"
    rev_row = next(rr for (rr, cc) in blk if cc == 6 and rr > hdr_row
                   and cells[(rr, cc)].value == "الإيرادات")
    assert cells[(rev_row, 7)].value == 500_000.0
    assert cells[(rev_row, 8)].value == 650_000.0

    import zipfile
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    chart_xmls = [z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                  if n.startswith("xl/charts/chart")]
    mini = [x for x in chart_xmls
            if "<barChart>" in x and "مقارنة قائمة الدخل" in x]
    assert mini, "period-comparison chart missing on the derived sheet"
    assert mini[0].count("<ser>") == 2
    assert "0F766E" in mini[0] and "94A3B8" in mini[0]
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_export_grid_shows_cashflow_activity_rows(client):
    """The statements sheet's comparative grid carries the net cash flow of
    each activity across the periods: the composed operating row (130k →
    135k after the 50k working-capital drag) shows with its per-period
    values, while investing/financing (nothing stated in this file) are
    absent rather than invented as zeros."""
    aid = _upload_two_period_file(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)

    grid_hdr = None
    for row in ws.iter_rows():
        if any(c.value == "مقارنة بالفترات" for c in row):
            grid_hdr = row[0].row
            break
    assert grid_hdr, "comparative grid missing"

    grid_rows = {}
    for row in ws.iter_rows(min_row=grid_hdr + 1):
        first = row[0].value
        if isinstance(first, str) and first.startswith("قائمة"):
            break                      # next section — grid ended
        if isinstance(first, str) and first and row[2].value is not None \
                and not isinstance(row[1].value, str):
            grid_rows[first] = [c.value for c in row[1:3]]

    assert grid_rows["صافي التدفق من الأنشطة التشغيلية"] == \
        [130_000, 135_000]
    assert "صافي التدفق من الأنشطة الاستثمارية" not in grid_rows
    assert "صافي التدفق من الأنشطة التمويلية" not in grid_rows
    # placement: the operating-flow row sits right below net profit
    labels = list(grid_rows)
    assert labels.index("صافي التدفق من الأنشطة التشغيلية") \
        == labels.index("صافي الربح") + 1
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
