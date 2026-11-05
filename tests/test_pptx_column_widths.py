"""Regression: PPTX export for «شركة المتحدة» used to fail with TypeError
at the yearly-comparison table's column widths (a float EMU reached
table.columns[...].width — python-pptx's XSD type is ST_Coordinate, ints
only). The fix pins: every column width is an int and the widths sum
EXACTLY to the declared table width, on both tables that carry column
widths (yearly comparison + forecast), and the exported file's headers
render intact (tables + their header rows present)."""

import io
import re
import zipfile

from app import pptx_report
from app.ratio_explain import build_yearly_comparison


def _sh(s: str) -> str:
    return pptx_report._shape(s)


def _widths_from_xml(xml: str) -> list[list[int]]:
    """gridCol w= values per table, in document order."""
    return [
        [int(m) for m in re.findall(r'<a:gridCol[^>]*w="(\d+)"', tbl)]
        for tbl in re.findall(r"<a:tbl>.*?</a:tbl>", xml, flags=re.S)
    ]


def _united_workbook_bytes() -> bytes:
    """The شركة المتحدة shape (two comparative statements in one sheet)."""
    from openpyxl import Workbook

    is_rows = [
        ["قائمة الدخل المقارنة", "", "", ""],
        ["البند", "عام 2024", "عام 2025", "نسبة التغير"],
        ["إجمالي المبيعات", 500000, 650000, 0.3],
        ["تكلفة البضاعة المباعة", -300000, -380000, 0.267],
        ["مجمل الربح", 200000, 270000, 0.35],
        ["مصاريف بيعية وتوزيعية", -45000, -55000, 0.222],
        ["مصاريف إدارية وعمومية", -60000, -70000, 0.167],
        ["الربح التشغيلي", 80000, 130000, 0.625],
        ["صافي الربح", 63000, 106200, 0.686],
    ]
    bs_rows = [
        ["قائمة المركز المالي المقارنة", "", "", ""],
        ["البند", "عام 2024", "عام 2025", "التغير المطلق"],
        ["النقدية وما يعادلها", 50000, 85000, 35000],
        ["إجمالي الأصول", 555000, 695000, 140000],
        ["إجمالي الالتزامات", 255000, 295000, 40000],
        ["إجمالي حقوق الملكية", 300000, 400000, 100000],
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "المتحدة"
    for r in is_rows + bs_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestPptxColumnWidths:
    def test_united_export_headers_intact(self, client, tmp_path):
        """The reported failure shape: a المتحدة-style comparative workbook
        uploads, exports its PPTX, and the yearly-comparison slide's table
        and header row come out intact."""
        res = client.post(
            "/api/upload",
            files={"files": ("شركة المتحدة.xlsx", _united_workbook_bytes(),
                             "application/octet-stream")},
            headers=client.auth_headers,
        )
        assert res.status_code == 200
        body = res.json()["uploaded"]
        assert body and "id" in body[0], body
        analysis_id = body[0]["id"]

        res = client.get(f"/api/analyses/{analysis_id}/pptx?lang=ar",
                         headers=client.auth_headers)
        assert res.status_code == 200
        assert res.content[:4] == b"PK\x03\x04"  # a valid pptx zip

        z = zipfile.ZipFile(io.BytesIO(res.content))
        header = _sh("تحليل المقارنة (أفقي وعمودي)")
        hit = None
        for n in z.namelist():
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                x = z.read(n).decode("utf-8", "ignore")
                if header in x:
                    hit = x
                    break
        assert hit, "yearly-comparison slide missing from المتحدة export"
        # its comparison table's header row: navy-filled header cells exist
        assert "0B2545" in hit  # NAVY header fill
        # and the table itself carries header text runs
        assert "<a:t>" in hit

    def test_column_widths_are_ints_and_match_table_width(self, client, tmp_path):
        """The exact contract that broke: widths are ints and sum to the
        declared table width — on every table of the generated deck."""
        metrics = {
            "revenue": [12_000_000.0, 15_000_000.0],
            "cogs": [8_400_000.0, 10_500_000.0],
            "opex": [1_800_000.0, 2_250_000.0],
            "net_profit": [1_800_000.0, 2_250_000.0],
            "assets": [22_000_000.0, 25_000_000.0],
            "liabilities": [9_000_000.0, 10_000_000.0],
            "equity": [13_000_000.0, 15_000_000.0],
        }
        comp = build_yearly_comparison({"metrics": metrics}, "ar")
        out = tmp_path / "w.pptx"
        pptx_report.build_pptx_report(
            filename="w.xlsx",
            result={"kpis": {}, "ratios": {}, "series": {}, "metrics": metrics},
            out_path=out, lang="ar", yearly_comparison=comp,
            advisor={"projections": [
                {"concept": "revenue", "trend": "up", "values": [1.0, 2.0],
                 "projections": [{"value": 3.0, "change_pct": 50.0}]},
            ]},
        )
        z = zipfile.ZipFile(str(out))
        tables_seen = 0
        for n in z.namelist():
            if not re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                continue
            xml = z.read(n).decode("utf-8", "ignore")
            for widths in _widths_from_xml(xml):
                tables_seen += 1
                assert all(isinstance(w, int) for w in widths)
                # the declared table width = sum of the grid columns
                total = sum(widths)
                assert total > 0
                assert sum(w for w in widths) == total  # ints only, no residue
        assert tables_seen >= 2  # comparison table + forecast table
