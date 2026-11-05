# -*- coding: utf-8 -*-
"""«مقارنة بالفترة السابقة» column on the balance-sheet table of the
statements worksheet — the balance-sheet twin of the income comparison.

Same honesty contract (_balance_comparison): two+ periods AND the latest
captured values tie the attached face (1% tolerance). Judgement colouring:
assets/equity up = green (good_up), liabilities up = red (financing
strain). The assets/liabilities/equity totals render as extra comparison
rows — ONLY when the column exists (never breaking table alignment) — and
only when the face totals tie the captured series.
"""

import io
import json

from openpyxl import Workbook, load_workbook

from app.main import _balance_comparison
from app.statements import build_statements

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Balanced TB (Dr 1,770,000 = Cr 1,770,000): assets 1,280,000
# liabilities+equity 1,500,000 (payables 200k, capital 500k, net 800k):
# face → revenue 1,200,000 / cogs 700,000 / opex 60,000 / finance 30,000
# / net 410,000 → equity 500k + 410k = 910,000 … wait: credits 200k + 500k
# + 1,200k = 1,900k vs debits 1,770k — NOT balanced; fixed below.
TB_ROWS = [
    ["الحساب", "مدين", "دائن"],
    ["النقدية بالبنك", 600_000, 0],
    ["مدينون - العملاء", 250_000, 0],
    ["مخزون", 180_000, 0],
    ["الدائنون - الموردون", 0, 200_000],
    ["رأس المال", 0, 1_020_000],
    ["ايرادات المبيعات", 0, 1_200_000],
    ["تكلفة المبيعات", 700_000, 0],
    ["مصاريف رواتب", 60_000, 0],
    ["فوائد قروض", 30_000, 0],
]

# Latest-period balance series ties the TB face EXACTLY:
#   assets 1,030,000 = cash 600k + receivables 250k + inventory 180k (no FA → no FA face line)
#   liabilities 1,120,000 = payables 200,000 (face) + loans 920,000 (non-face rest)
#   equity 1,430,000 = capital 1,020,000 + net 410,000 (ties the Equity face line)
METRICS_TWO = {
    "revenue": [1_000_000.0, 1_200_000.0],
    "cogs": [560_000.0, 700_000.0],
    "opex": [50_000.0, 60_000.0],
    "finance_cost": [25_000.0, 30_000.0],
    "assets": [900_000.0, 1_030_000.0],
    "liabilities": [810_000.0, 1_630_000.0],   # ties the face total (payables + equity)
    "equity": [790_000.0, 1_430_000.0],
    "cash": [500_000.0, 600_000.0],
    "receivables": [200_000.0, 250_000.0],
    "inventory": [150_000.0, 180_000.0],
    "payables": [150_000.0, 200_000.0],
}


def _attach_tb(client, rows=None):
    wb = Workbook()
    ws = wb.active
    for r in (rows or TB_ROWS):
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    demo = client.post("/api/demo").json()
    resp = client.post(
        f"/api/analyses/{demo['id']}/trial-balance",
        files={"file": ("tb.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return demo["id"]


def _inject_metrics(aid, metrics):
    import app.database as database

    with database.SessionLocal() as db:
        row = db.get(database.Analysis, aid)
        res = json.loads(row.result_json)
        res["metrics"] = dict(metrics)
        res["period_labels"] = ["2024", "2025"]
        row.result_json = json.dumps(res, ensure_ascii=False)
        db.commit()


def _bs_cells(ws):
    """(row_index, row_cells) of the BS table rows, keyed by col-2 text."""
    rows = {}
    for row in ws.iter_rows():
        if len(row) >= 2 and isinstance(row[1].value, str) and row[1].value:
            rows[row[1].value] = row
    return rows


# ------------------------------------------------------------ builder ----

def test_function_full_column_on_tying_face():
    st = build_statements(TB_ROWS)
    comp = _balance_comparison({"metrics": METRICS_TWO}, st)
    lines = (st["balance_sheet"]["assets"]["lines"]
             + st["balance_sheet"]["liabilities_equity"]["lines"])
    by_en = {ln["en"]: comp.get(i) for i, ln in enumerate(lines)}
    # direct concepts tie → compared
    assert by_en["Cash & Banks"] == {"pct": 20.0, "kind": "good_up"}
    assert by_en["Receivables"] == {"pct": 25.0, "kind": "good_up"}
    assert by_en["Inventory"] == {"pct": 20.0, "kind": "good_up"}
    assert by_en["Payables"] == {"pct": 33.3, "kind": "liability"}
    # 790k → 1,430k = +81.0%
    assert by_en["Equity"] == {"pct": 81.0, "kind": "good_up"}


def test_function_empty_when_assets_do_not_tie():
    """Per-line honesty: with assets NOT tying, the direct concepts that
    still tie keep their comparison — only pool/total-composed views lose
    theirs (and a TB face has no total-assets LINE to compare anyway)."""
    st = build_statements(TB_ROWS)
    metrics = dict(METRICS_TWO, assets=[900_000.0, 1_500_000.0])
    comp = _balance_comparison({"metrics": metrics}, st)
    lines = (st["balance_sheet"]["assets"]["lines"]
             + st["balance_sheet"]["liabilities_equity"]["lines"])
    by_en = {ln["en"]: comp.get(i) for i, ln in enumerate(lines)}
    assert by_en["Cash & Banks"]["pct"] == 20.0      # direct lines still tie
    assert by_en["Equity"]["pct"] == 81.0
    # and indeed no total-assets face line exists to compare
    assert "Total Assets" not in by_en


def test_function_partial_tie_skips_only_broken_lines():
    st = build_statements(TB_ROWS)
    metrics = dict(METRICS_TWO, payables=[150_000.0, 400_000.0])  # ≠ face 200k
    comp = _balance_comparison({"metrics": metrics}, st)
    lines = (st["balance_sheet"]["assets"]["lines"]
             + st["balance_sheet"]["liabilities_equity"]["lines"])
    by_en = {ln["en"]: comp.get(i) for i, ln in enumerate(lines)}
    assert by_en["Payables"] is None          # non-tying → «—»
    assert by_en["Cash & Banks"]["pct"] == 20.0
    assert by_en["Equity"]["pct"] == 81.0


def test_fixed_assets_derived_pool_composes():
    """A TB WITH fixed assets: the FA line composes from the shared pool
    (assets − cash − receivables − inventory) exactly as the builder does,
    per period."""
    tb2 = [row[:] for row in TB_ROWS]
    tb2[1][1] = 300_000                     # cash 600k → 300k
    tb2.insert(2, ["أثاث ومعدات", 300_000, 0])
    st = build_statements(tb2)
    # pool curr: 1,330,000 captured − 600k − 250k − 180k = 300,000 (ties the
    # FA face line); prev pool: 950k − 500k − 200k − 150k = 100,000 → +200%
    metrics = dict(METRICS_TWO, assets=[950_000.0, 1_330_000.0])
    comp = _balance_comparison({"metrics": metrics}, st)
    lines = (st["balance_sheet"]["assets"]["lines"]
             + st["balance_sheet"]["liabilities_equity"]["lines"])
    by_en = {ln["en"]: comp.get(i) for i, ln in enumerate(lines)}
    assert by_en["Fixed Assets"] == {"pct": 200.0, "kind": "good_up"}


def test_single_period_no_column():
    st = build_statements(TB_ROWS)
    single = {k: [v[-1]] for k, v in METRICS_TWO.items()}
    assert _balance_comparison({"metrics": single}, st) == {}
    assert _balance_comparison({}, st) == {}


# ----------------------------------------------------------------- api ----

def _statements_sheet(wb):
    return wb[next(n for n in wb.sheetnames if "القوائم" in n)]


def test_bs_comparison_column_rendered_with_colors(client):
    aid = _attach_tb(client)
    # payables' previous period EQUALS its current (a re-stated duplicate,
    # not a period) → that line renders «—» while the others compare
    _inject_metrics(aid, dict(METRICS_TWO, payables=[200_000.0, 200_000.0]))
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)

    hdrs = [c for row in ws.iter_rows() for c in row
            if c.value == "مقارنة بالفترة السابقة"]
    assert hdrs, "balance comparison column header missing"
    # col 3 = income statement's column, col 4 = the balance sheet's new one
    assert all(h.column in (3, 4) for h in hdrs)
    assert any(h.column == 4 for h in hdrs)

    rows = _bs_cells(ws)

    def comp_row(ar_label):
        for row in ws.iter_rows():
            if row[0].value == ar_label:
                return row
        return None

    ta = comp_row("إجمالي الأصول (مقارنة)")
    assert ta is not None and ta[2].value == 1_030_000 and ta[3].value == "+14.4% ▲"
    tl = comp_row("إجمالي الالتزامات (مقارنة)")
    assert tl is not None and tl[2].value == 1_630_000 and tl[3].value == "+101.2% ▲"
    eq = comp_row("حقوق الملكية (مقارنة)")
    assert eq is not None and eq[2].value == 1_430_000 and eq[3].value == "+81.0% ▲"
    # the face equity line remains in the table (before the totals rows)
    assert rows["Equity"][2].value == 1_430_000
    # the duplicate-payables line: dash in the comparison column, muted
    pay_dash = rows["Payables"][3]
    assert pay_dash.value == "—"
    assert str(pay_dash.font.color.rgb).endswith("64748B")   # MUTED

    pct_cells = [c for row in ws.iter_rows() for c in row
                 if isinstance(c.value, str) and c.value.endswith(("▲", "▼", "◄►"))
                 and "%" in c.value]
    by_pct = {c.value: c.font.color.rgb for c in pct_cells}
    assert str(by_pct["+14.4% ▲"]).endswith("059669")    # GREEN assets up
    assert str(by_pct["+101.2% ▲"]).endswith("DC2626")   # RED liabilities up
    assert str(by_pct["+81.0% ▲"]).endswith("059669")    # GREEN equity up
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_bs_totals_only_added_when_column_exists(client):
    """Two-period P&L WITHOUT balance concepts: the income column renders,
    the BS table gains NEITHER the comparison column NOR the (مقارنة)
    totals rows — alignment is never broken."""
    aid = _attach_tb(client)
    _inject_metrics(aid, {"revenue": [1_000_000.0, 1_200_000.0],
                          "cogs": [560_000.0, 700_000.0],
                          "opex": [50_000.0, 60_000.0]})
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)
    texts = [str(c.value) for row in ws.iter_rows() for c in row
             if isinstance(c.value, str)]
    joined = " | ".join(texts)
    assert "مقارنة بالفترة السابقة" in joined          # income side has it
    assert "(مقارنة)" not in joined                    # BS totals not added
    # BS face values are intact (single-face, 3 columns)
    rows = _bs_cells(ws)
    assert rows["Cash & Banks"][2].value == 600_000
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_tb_without_metrics_has_no_bs_column(client):
    aid = _attach_tb(client)
    resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                      headers=client.auth_headers)
    wb = load_workbook(io.BytesIO(resp.content))
    ws = _statements_sheet(wb)
    texts = [str(c.value) for row in ws.iter_rows() for c in row
             if isinstance(c.value, str)]
    joined = " | ".join(texts)
    assert "مقارنة بالفترة السابقة" not in joined
    assert "(مقارنة)" not in joined
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
