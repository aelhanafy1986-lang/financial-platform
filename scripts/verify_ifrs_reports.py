# -*- coding: utf-8 -*-
"""Verify IFRS content inside generated PDF / PPTX / Excel for analysis 11."""
import re
import zipfile

PASS = []

def check(label, cond, detail=""):
    PASS.append((label, bool(cond), detail))
    print(("OK " if cond else "FAIL") + f" | {label} | {detail}")

# ---------- PDF (ar) ----------
import pdfplumber
with pdfplumber.open("reports/report_11_ar.pdf") as pdf:
    ar_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    ar_pages = len(pdf.pages)
with pdfplumber.open("reports/report_11_en.pdf") as pdf:
    en_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

for t, name in ((ar_text, "PDF-ar"), (en_text, "PDF-en")):
    check(f"{name}: IAS 1 present", "IAS 1" in t, f"pages={ar_pages if name=='PDF-ar' else ''}")
    check(f"{name}: IFRS 18 present", "IFRS 18" in t)
    check(f"{name}: basis (standard reference)", ("basis of preparation" in t.lower()) or ("IAS" in t and "IFRS" in t))

# Arabic in PDFs is stored reshaped (presentation forms) in visual order —
# apply the same transform used at generation time before searching.
from bidi.algorithm import get_display
import arabic_reshaper

def _shape(s):
    return get_display(arabic_reshaper.reshape(s))

ifrs_kw_ar = ["المعايير الدولية", "المرجع المعياري"]
import sys
sys.path.insert(0, ".")
from app.ifrs import basis_of_preparation
# Whitespace-insensitive comparison: the paragraph wraps across lines in the PDF.
import re as _re


def _squash(s):
    return _re.sub(r"[\s\u00a0]+", "", s)


flat_pdf = _squash(ar_text)
# Take the test chunk from the SHAPED full basis paragraph so contextual
# letter forms match exactly what was rendered; do not re-shape it after.
_basis_shaped = _squash(_shape(basis_of_preparation("ar")))
_basis_chunk = _basis_shaped[15:55]
print(f"   (basis chunk tested: {_basis_chunk[:30]!r}...)")
for kw in ifrs_kw_ar:
    shaped = _shape(kw)
    found = (_squash(shaped) in flat_pdf) or (kw in ar_text)
    check(f"PDF-ar: ar keyword {kw[:25]!r}", found)
found_basis = _basis_chunk in flat_pdf
check("PDF-ar: basis paragraph chunk (shaped, squashed)", found_basis)

check("PDF-ar: ratio card ref line", ("IAS 2" in ar_text) or ("IAS 16" in ar_text) or ("IFRS" in ar_text and "المرجع" in ar_text.replace("\u200f", "")))

# ---------- PPTX (ar) ----------
z = zipfile.ZipFile("reports/pptx_11_ar.pptx")
slides = sorted(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
all_xml = "".join(z.read(s).decode("utf-8", "ignore") for s in slides)
check("PPTX: slide count >= 4", len(slides) >= 4, f"slides={len(slides)}")
check("PPTX: IFRS 18 latin", "IFRS 18" in all_xml)
check("PPTX: IAS 1 latin", "IAS 1" in all_xml)
check("PPTX: >=2 standards mentioned", len(set(re.findall(r"(?:IFRS|IAS)\s?\d+", all_xml))) >= 2,
      "found=" + ",".join(sorted(set(re.findall(r"(?:IFRS|IAS)\s?\d+", all_xml)))))

# ---------- Excel ----------
from openpyxl import load_workbook
wb = load_workbook("reports/excel_11_ar.xlsx")
ws = wb["الملخص"] if "الملخص" in wb.sheetnames else wb[wb.sheetnames[0]]
cells = []
for row in ws.iter_rows():
    for c in row:
        if isinstance(c.value, str) and c.value.strip():
            cells.append(c.value)
joined = "\n".join(cells)
has_title = any("IFRS" in v or "IAS" in v for v in cells)
check("Excel: ifrs title row", has_title)
check("Excel: basis paragraph", any(("الاستحقاق" in v) or ("accrual" in v.lower()) or ("IFRS" in v and len(v) > 120) for v in cells))
stds_xl = set(re.findall(r"(?:IFRS|IAS)\s?\d+", joined))
check("Excel: >=2 standards", len(stds_xl) >= 2, "found=" + ",".join(sorted(stds_xl)))

fails = [p for p in PASS if not p[1]]
print(f"\n== {len(PASS) - len(fails)}/{len(PASS)} checks passed ==")
