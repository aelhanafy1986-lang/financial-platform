"""Print-ready financial statements sheet in the Excel export.

Adds a dedicated worksheet with the trial balance, income statement,
statement of financial position and cash flow from the built statements,
plus a native profit waterfall chart (revenue → net profit).
"""

import io

from openpyxl import Workbook, load_workbook


def _upload_tb(client, rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    demo = client.post("/api/demo").json()
    resp = client.post(
        f"/api/analyses/{demo['id']}/trial-balance",
        files={"file": ("tb.xlsx", buf,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200
    return demo["id"]


TB_ROWS = [
    ["الحساب", "مدين", "دائن"],
    ["النقدية بالبنك", 600_000, 0],
    ["مدينون - العملاء", 250_000, 0],
    ["مخزون", 180_000, 0],
    ["الدائنون - الموردون", 0, 200_000],
    ["رأس المال", 0, 500_000],
    ["ايرادات المبيعات", 0, 1_200_000],
    ["تكلفة المبيعات", 700_000, 0],
    ["مصاريف رواتب", 60_000, 0],
    ["فوائد قروض", 30_000, 0],
]


class TestStatementsWorksheet:
    def test_sheet_created_with_sections(self, client):
        aid = _upload_tb(client, TB_ROWS)
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        assert resp.status_code == 200
        wb = load_workbook(io.BytesIO(resp.content))
        names = wb.sheetnames
        assert any("القوائم" in n for n in names)
        ws = wb[next(n for n in names if "القوائم" in n)]
        texts = [str(c.value) for row in ws.iter_rows() for c in row
                 if isinstance(c.value, str)]
        joined = " ".join(texts)
        assert "قائمة الدخل" in joined
        assert "قائمة المركز المالي" in joined
        assert "قائمة التدفقات النقدية" in joined
        assert "ميزان المراجعة" in joined
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_income_statement_table_values(self, client):
        aid = _upload_tb(client, TB_ROWS)
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]
        amounts = [c.value for row in ws.iter_rows() for c in row
                   if isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
        # revenue, gross, operating and net figures from the statements face
        for expected in (1_200_000, 500_000, 410_000, 440_000 - 30_000 + 420_000 - 420_000):
            pass  # values depend on the face; assert the key ones explicitly
        assert 1_200_000 in amounts          # revenue
        assert 500_000 in amounts            # gross profit (1.2M - 700k)
        assert 440_000 in amounts            # operating profit (gross - 60k)
        assert 410_000 in amounts            # net profit (op - 30k finance)
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_waterfall_chart_present(self, client):
        aid = _upload_tb(client, TB_ROWS)
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]
        kinds = [type(ch).__name__ for ch in ws._charts]
        assert "BarChart" in kinds  # the stacked waterfall
        waterfall = next(ch for ch in ws._charts if type(ch).__name__ == "BarChart")
        assert waterfall.grouping == "stacked"
        assert waterfall.overlap == 100
        # 3 series: ghost base + rises + falls
        assert len(waterfall.series) == 3
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_cash_flow_waterfall_chart(self, client):
        """A SECOND native waterfall: cash flow cycle operating → investing
        → financing → cash balance, same stacked-column technique."""
        aid = _upload_tb(client, TB_ROWS)
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]
        bars = [ch for ch in ws._charts if type(ch).__name__ == "BarChart"]
        assert len(bars) == 2  # profit waterfall + cash-flow waterfall
        cf_wf = bars[1]
        assert cf_wf.grouping == "stacked"
        assert cf_wf.overlap == 100
        assert len(cf_wf.series) == 3  # ghost base + rises + falls
        texts = [str(c.value) for row in ws.iter_rows() for c in row
                 if isinstance(c.value, str)]
        joined = " ".join(texts)
        assert "شلال التدفق النقدي" in joined
        # the cycle's four columns appear in BOTH the cf table and the
        # waterfall helper block
        assert joined.count("الأنشطة التشغيلية") >= 2
        assert joined.count("رصيد النقدية") >= 2
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_print_setup_print_ready(self, client):
        aid = _upload_tb(client, TB_ROWS)
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb[next(n for n in wb.sheetnames if "القوائم" in n)]
        assert ws.page_setup.paperSize in (9, ws.PAPERSIZE_A4)
        assert ws.page_setup.fitToWidth == 1
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
