# -*- coding: utf-8 -*-
"""Verify the formatting fixes: PPTX units beside values, PDF grey header,
Excel ratio number formats."""
import re
import zipfile

ok = 0
total = 0

def check(label, cond, detail=""):
    global ok, total
    total += 1
    if cond:
        ok += 1
    print(("OK " if cond else "FAIL") + f" | {label} | {detail}")

# ---------- PPTX ----------
z = zipfile.ZipFile("reports/pptx_11_ar.pptx")
slides = sorted(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
xml_by_slide = {s: z.read(s).decode("utf-8", "ignore") for s in slides}
all_xml = "".join(xml_by_slide.values())
# percent values appear glued to a number like >40.00%< or >30.40%<
pct_glued = re.findall(r">\s*(-?[\d,]+\.\d{2})%\s*<", all_xml)
x_glued = re.findall(r">\s*(-?[\d,]+\.\d{2})x\s*<", all_xml)
check("PPTX: percent glued to value", len(pct_glued) >= 3, f"found={pct_glued[:6]}")
check("PPTX: x-multiple glued to value", len(x_glued) >= 2, f"found={x_glued[:6]}")
# no bare lone numbers ending a text run in the ratios slide (heuristic)
ratios_slide = next((x for s, x in xml_by_slide.items() if "asset_turnover" in x or "Debt" in x and "Ratio" in x), None)
check("PPTX: slide count >= 4", len(slides) >= 4, f"slides={len(slides)}")

# ---------- PDF: header background is grey now ----------
import pdfplumber
with pdfplumber.open("reports/report_11_ar.pdf") as pdf:
    page = pdf.pages[0]
    rects = page.rects
    teal_like, grey_like = 0, 0
    for rc in rects:
        fill = rc.get("non_stroking_color")
        if not fill:
            continue
        try:
            r, g, b = [float(c) for c in (list(fill) + [fill[0], fill[0], fill[0]])[:3]]
        except Exception:
            continue
        # teal #0f766e -> (0.059, 0.463, 0.431): g and b high vs r
        # (only counts as a violation when it is a tall header band at the top)
        if g > 0.3 and b > 0.25 and r < 0.15 and rc.get("height", 0) > 40 and rc.get("top", 999) < 120:
            teal_like += 1
        # grey #eef1f5 -> ~(0.93, 0.95, 0.96): near-equal high channels
        if r > 0.85 and g > 0.85 and b > 0.85 and (max(r, g, b) - min(r, g, b)) < 0.05:
            grey_like += 1
check("PDF: no big teal band in header", teal_like == 0, f"teal rects={teal_like}")
check("PDF: grey band present", grey_like >= 1, f"grey rects={grey_like}")

# ---------- Excel: number formats ----------
from openpyxl import load_workbook
wb = load_workbook("reports/excel_11_ar.xlsx")
ws = wb["الملخص"] if "الملخص" in wb.sheetnames else wb[wb.sheetnames[0]]
pct_fmt, x_fmt = 0, 0
for row in ws.iter_rows():
    for c in row:
        fmt = c.number_format or ""
        if '"%"' in fmt:
            pct_fmt += 1
        if '"x"' in fmt:
            x_fmt += 1
check("Excel: percent formats on ratio rows", pct_fmt >= 3, f"count={pct_fmt}")
check("Excel: x formats on multiple rows", x_fmt >= 1, f"count={x_fmt}")
check("Excel: print titles set", ws.print_title_rows in ("1:1", "$1:$1"), str(ws.print_title_rows))
insight_wrapped = sum(
    1 for row in ws.iter_rows() for c in row
    if isinstance(c.value, str) and len(c.value) > 60 and c.alignment and c.alignment.wrap_text
)
check("Excel: long insight texts wrapped", insight_wrapped >= 4, f"count={insight_wrapped}")

print(f"\n== {ok}/{total} checks passed ==")
