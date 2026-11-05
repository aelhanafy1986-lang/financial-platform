"""Conditional benchmark colouring for ratio rows in the Excel export.

Green fill/text when a ratio meets its reference benchmark, red when it
does not — verdicts come from the same _judge thresholds as the cards and
the PDF alignment section, plus a static ✓/✗ chip column that renders
everywhere.
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

GOOD_FILL = "00E5F3EA"  # ARGB with alpha prefix as openpyxl stores it
BAD_FILL = "00FBE5E5"


class TestRatioRowColouring:
    def _load(self, client, aid):
        resp = client.get(f"/api/analyses/{aid}/export?lang=ar",
                          headers=client.auth_headers)
        assert resp.status_code == 200
        return load_workbook(io.BytesIO(resp.content))

    def _summary(self, wb):
        return wb[next(n for n in wb.sheetnames if "الملخص" in n or n == "Summary")]

    def test_chip_column_verdicts(self, client):
        aid = _upload_tb(client, TB_ROWS)
        wb = self._load(client, aid)
        ws = self._summary(wb)
        # collect ratio rows: label (A) + value (B) + chip (D)
        chips = {}
        for row in ws.iter_rows():
            if (len(row) > 3
                    and isinstance(row[1].value, (int, float))
                    and not isinstance(row[1].value, bool)
                    and row[0].value and isinstance(row[0].value, str)
                    and isinstance(row[3].value, str)
                    and row[3].value in ("✓", "✗", "≈")
                    and row[3].font and row[3].font.bold):
                chips[row[0].value] = (row[3].value, str(row[3].font.color.rgb))
        assert chips, "no verdict chips found next to ratio values"
        # gross margin 41.2% ≥ 20 → green ✓
        gm = next((v for k, v in chips.items() if "الإجمالي" in k), None)
        assert gm and gm[0] == "✓" and "157A2E" in gm[1]
        # debt ratio 0.0% ≤ 70 → green ✓  (assets financed by debt = 0 here)
        dr = next((v for k, v in chips.items() if "الالتزامات" in k), None)
        assert dr and dr[0] == "✓"
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_bad_verdict_red_chip(self, client):
        # receivables of 900k vs revenue 1.2M → collection ≈ 274 days → bad
        rows = [list(r) for r in TB_ROWS]
        rows[2][1] = 900_000  # مدينون
        rows[3][1] += 0  # keep the rest
        aid = _upload_tb(client, rows)
        wb = self._load(client, aid)
        ws = self._summary(wb)
        found_bad = False
        for row in ws.iter_rows():
            if (len(row) > 3 and row[0].value and isinstance(row[0].value, str)
                    and "فترة التحصيل" in str(row[0].value)
                    and isinstance(row[3].value, str) and row[3].value == "✗"):
                assert "DC2626" in str(row[3].font.color.rgb)
                found_bad = True
        assert found_bad, "collection-period row was not flagged red"
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_conditional_formatting_rules_registered(self, client):
        aid = _upload_tb(client, TB_ROWS)
        wb = self._load(client, aid)
        ws = self._summary(wb)
        cf_ranges = list(ws.conditional_formatting)
        assert cf_ranges, "no conditional formatting registered on the summary"
        # every rule is one of ours: fill green/red + bold font
        rules = [r for cf in cf_ranges for r in cf.rules]
        assert rules, "conditional formatting present but empty"
        fills = {str(r.dxf.fill.bgColor.rgb) for r in rules
                 if r.dxf and r.dxf.fill and r.dxf.fill.bgColor}
        assert any("E5F3EA" in f for f in fills), fills
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_openpyxl_roundtrip_preserves_rules(self, client):
        """The openpyxl roundtrip keeps the rules — Excel will apply them."""
        aid = _upload_tb(client, TB_ROWS)
        wb = self._load(client, aid)
        ws = self._summary(wb)
        total_rules = sum(len(cf.rules) for cf in ws.conditional_formatting)
        assert total_rules >= 1
        # and a save/load cycle keeps them
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        wb2 = load_workbook(buf)
        ws2 = wb2[wb.sheetnames[0] if "الملخص" not in wb.sheetnames
                  else next(n for n in wb2.sheetnames if "الملخص" in n)]
        assert sum(len(cf.rules) for cf in ws2.conditional_formatting) >= 1
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
