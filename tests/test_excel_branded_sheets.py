"""Every Excel export sheet opens with the platform banner (logo + name +
tagline) — not just the summary sheet."""

import io

from openpyxl import load_workbook


def _flat(c: str) -> str:
    """Excel stores logical-order Arabic (no display shaping), so raw strings
    match after whitespace flattening."""
    return c.replace(" ", "").replace("\u00a0", "")


class TestBrandedSheets:
    def test_arabic_sheets_carry_name_and_tagline(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/export?lang=ar", headers=client.auth_headers)
        assert res.status_code == 200
        wb = load_workbook(io.BytesIO(res.content))
        name = _flat("المنصة المالية الذكية")
        tagline = _flat("محلّلك المالي المدعوم بالذكاء الاصطناعي")
        for sheet in wb.sheetnames:
            cells = [str(c.value or "") for row in wb[sheet].iter_rows(max_row=6) for c in row]
            assert any(name in _flat(c) for c in cells), \
                f"platform name missing from sheet «{sheet}»"
            assert any(tagline in _flat(c) for c in cells), \
                f"tagline missing from sheet «{sheet}»"

    def test_english_sheets_carry_name_and_tagline(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/export?lang=en", headers=client.auth_headers)
        assert res.status_code == 200
        wb = load_workbook(io.BytesIO(res.content))
        for sheet in wb.sheetnames:
            cells = [str(c.value or "") for row in wb[sheet].iter_rows(max_row=6) for c in row]
            assert any("Smart Financial Platform" in c for c in cells), \
                f"platform name missing from sheet «{sheet}»"
            assert any("Your Smart AI Financial Analyst" in c for c in cells), \
                f"tagline missing from sheet «{sheet}»"
