from pathlib import Path

from openpyxl import load_workbook

MAX_ROWS_PER_SHEET = 500


def parse_excel(path: Path) -> dict:
    wb = load_workbook(path, data_only=True, read_only=True)
    tables = []
    try:
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                if any(c is not None and str(c).strip() for c in row):
                    rows.append(["" if c is None else c for c in row])
                if len(rows) >= MAX_ROWS_PER_SHEET:
                    break
            if rows:
                tables.append({"name": ws.title, "rows": rows})
    finally:
        wb.close()
    return {"tables": tables, "texts": []}
