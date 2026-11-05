# -*- coding: utf-8 -*-
"""Invoice-grain sales uploads: multi-sheet workbooks and CSV files.

The sales route must read every parsed table (one branch/month per sheet),
and a declared-sales CSV must parse through the same record extraction as
Excel — with BOM-utf-8 and Windows-Arabic (cp1256) encodings both working.
"""

import csv as csv_mod
import io
from pathlib import Path

from openpyxl import Workbook

from app.main import _sales_records_for_tables
from app.parsers import parse_file
from app.sales_analyzer import detect_sales_table


# ------------------------------------------------------------- unit pieces ----

INVOICE_SHEET_ROWS = [
    ["التاريخ", "رقم الفاتورة", "مسؤول المبيعات", "المنطقة", "المنتج",
     "الكمية", "سعر الوحدة", "المبلغ الإجمالي", "طريقة الدفع"],
    ["2026-01-01", "INV-1000", "خالد المطيري", "المنطقة الوسطى", "هاتف", 3, 3200, 9600, "نقداً"],
    ["2026-01-05", "INV-1001", "سارة الشمري", "المنطقة الغربية", "حاسب", 2, 5000, 10000, "شبكة"],
]


def _sales_workbook(path: Path) -> Path:
    """Two invoice sheets (فروع مبيعات) — each one a complete invoice grid."""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "يناير"
    for row in INVOICE_SHEET_ROWS:
        ws1.append(row)
    ws2 = wb.create_sheet("فبراير")
    for i, row in enumerate(INVOICE_SHEET_ROWS):
        vals = list(row)
        if i > 0:
            vals[0] = "2026-02-0" + str(i)
        ws2.append(vals)
    wb.save(path)
    return path


def test_multi_sheet_invoice_workbook_all_sheets_read(tmp_path):
    """Every sheet of a multi-sheet invoice workbook contributes its rows —
    not just the first sheet (the old first-sheet-only behaviour lost the
    sibling branch/month sheets)."""
    parsed = parse_file(_sales_workbook(tmp_path / "sales.xlsx"))
    assert len(parsed["tables"]) == 2

    records = _sales_records_for_tables(parsed["tables"])
    # every sheet contributes its 2 invoice rows
    assert len(records) == 4, f"expected 4 records, got {len(records)}"
    # months from BOTH sheets aggregated (تاريخ → شهر)
    months = {r["month"] for r in records}
    assert months == {"2026-01-01", "2026-01-05", "2026-02-01", "2026-02-02"}
    # reps mapped from «مسؤول المبيعات», NOT from invoice numbers
    reps = {r["rep"] for r in records}
    assert reps == {"خالد المطيري", "سارة الشمري"}
    # regions from «المنطقة»
    regions = {r["region"] for r in records}
    assert "خالد المطيري" not in regions  # rep never leaks into region


def test_header_detector_still_maps_invoice_columns():
    records = detect_sales_table(INVOICE_SHEET_ROWS)
    assert len(records) == 2
    assert records[0]["sales"] == 9600.0
    assert records[0]["txns"] == 3  # الكمية → عمليات
    assert records[0]["rep"] == "خالد المطيري"
    assert records[0]["region"] == "المنطقة الوسطى"


# ------------------------------------------------------------------- CSV ----

def _csv_bytes(rows, encoding="utf-8-sig", delimiter=",") -> bytes:
    buf = io.StringIO()
    writer = csv_mod.writer(buf, delimiter=delimiter)
    for row in rows:
        writer.writerow([c.encode(encoding) if isinstance(c, bytes) else c
                         for c in row])
    return buf.getvalue().encode(encoding)


def test_csv_sales_upload_end_to_end(client):
    """A declared-sales CSV flows through /api/upload into a sales analysis
    with the correct totals (the CSV parser feeds the same sales route)."""
    rows = INVOICE_SHEET_ROWS + [
        ["2026-03-02", "INV-2000", "خالد المطيري", "المنطقة الوسطى", "هاتف", 5, 3200, 16000, "نقداً"],
    ]
    payload = _csv_bytes(rows)
    resp = client.post(
        "/api/upload",
        files={"files": ("sales.csv", payload, "text/csv")},
        data={"file_kind": "sales"},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    items = data.get("uploaded") if isinstance(data, dict) else data
    assert items and "error" not in items[0], items
    result = items[0]["result"]
    assert result.get("kind") == "sales"
    sa = result["sales_analysis"]
    # 9600 + 10000 + 16000
    assert sa["total_sales"] == 35600.0
    assert sa["total_transactions"] == 10
    reps = {r["rep"] for r in sa["reps"]}
    assert reps == {"خالد المطيري", "سارة الشمري"}


def test_parse_csv_encodings_and_delimiters(tmp_path):
    """BOM-utf-8 and Windows-Arabic (cp1256) CSVs both parse; `;` delimiter
    is sniffed too."""
    header = ["التاريخ", "مسؤول المبيعات", "المنطقة", "المبلغ الإجمالي"]
    rows = [
        ["2026-01-01", "خالد المطيري", "الوسطى", 9600],
        ["2026-02-01", "سارة الشمري", "الغربية", 10000],
    ]

    for encoding in ("utf-8-sig", "cp1256"):
        buf = io.StringIO()
        w = csv_mod.writer(buf)
        for r in rows:
            w.writerow(r)
        text = (",".join(header) + "\n" + buf.getvalue())
        raw = text.encode("cp1256") if encoding == "cp1256" else text.encode("utf-8-sig")
        p = tmp_path / f"sales_{encoding}.csv"
        p.write_bytes(raw)
        parsed = parse_file(p)
        assert len(parsed["tables"]) == 1
        table = parsed["tables"][0]["rows"]
        assert table[0] == header
        assert table[1][1] == "خالد المطيري"

    # semicolon delimiter
    buf = io.StringIO()
    w = csv_mod.writer(buf, delimiter=";")
    for r in rows:
        w.writerow(r)
    p = tmp_path / "sales_semi.csv"
    p.write_bytes((";".join(header) + "\n" + buf.getvalue()).encode("utf-8-sig"))
    parsed = parse_file(p)
    assert parsed["tables"][0]["rows"][1][0] == "2026-01-01"


def test_invalid_sales_csv_refused_with_message(client):
    """A csv with NO usable sales rows is refused with the existing helpful
    error — not a zero-report analysis."""
    payload = "التاريخ,ملاحظة\n2026-01-01,بلا أعمدة مبيعات\n".encode("utf-8-sig")
    resp = client.post(
        "/api/upload",
        files={"files": ("empty.csv", payload, "text/csv")},
        data={"file_kind": "sales"},
        headers=client.auth_headers,
    )
    data = resp.json()
    if resp.status_code == 400:
        # a top-level refusal (HTTPException with the sales-row hint)
        assert "صالح" in data["detail"] or "شكل" in data["detail"]
        return
    # or a per-file error item inside «uploaded»
    items = data.get("uploaded") if isinstance(data, dict) else data
    assert items and "error" in items[0]
    assert "صالح" in items[0]["error"] or "شكل" in items[0]["error"]
