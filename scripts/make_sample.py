"""Generate a sample Arabic financial Excel file for testing the platform.

Run after installing requirements:
    python scripts/make_sample.py
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

OUT = Path(__file__).resolve().parent.parent / "sample-financials.xlsx"

HEAD_FILL = PatternFill("solid", fgColor="0F766E")
HEAD_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)

YEARS = ["2023", "2024", "2025"]

INCOME_ROWS = [
    ("الإيرادات", 3_100_000, 4_120_000, 4_820_000),
    ("تكلفة المبيعات", 1_900_000, 2_500_000, 2_834_000),
    ("الربح الإجمالي", 1_200_000, 1_620_000, 1_986_000),
    ("المصاريف التشغيلية", 700_000, 850_000, 980_000),
    ("صافي الربح", 310_000, 505_000, 640_000),
]

BALANCE_ROWS = [
    ("إجمالي الأصول", 7_200_000, 8_400_000, 9_150_000),
    ("إجمالي الالتزامات", 3_100_000, 3_500_000, 3_523_000),
    ("حقوق الملكية", 4_100_000, 4_900_000, 5_627_000),
    ("النقدية", 850_000, 980_000, 1_120_000),
]


def write_sheet(ws, title: str, rows) -> None:
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    ws.append([])
    ws.append(["البند", *YEARS])
    for cell in ws[3]:
        if cell.value:
            cell.fill = HEAD_FILL
            cell.font = HEAD_FONT
    for name, y1, y2, y3 in rows:
        ws.append([name, y1, y2, y3])
    for col, width in zip("ABCD", (28, 16, 16, 16)):
        ws.column_dimensions[col].width = width


def main() -> None:
    wb = Workbook()
    write_sheet(wb.active, "قائمة الدخل", INCOME_ROWS)
    wb.active.title = "قائمة الدخل"
    balance = wb.create_sheet("الميزانية العمومية")
    write_sheet(balance, "الميزانية العمومية", BALANCE_ROWS)
    wb.save(OUT)
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
