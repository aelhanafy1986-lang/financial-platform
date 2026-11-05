# -*- coding: utf-8 -*-
"""BI-tool integration layer (Excel · Power BI · Tableau · Google Looker ·
SQL · Python): turns one analysis into tidy, connector-ready datasets.

Three tidy (long-format) tables — the shape BI tools ingest best:
- facts:   one row per (concept × period) with bilingual concept labels
- growth:  per-year values + YoY % + the next-year forecast row (mean
           historical growth — the SAME rule the PDF/PPTX growth tables
           render), flagged ``is_forecast = 1``
- ratios:  every computed ratio with its value

Formats: CSV (UTF-8 BOM so Excel/Power BI/Looker read Arabic correctly),
plain XLSX (header on row 1, frozen — Power Query/Tableau/Looker ingest it
without any cleaning), portable SQL (CREATE TABLE IF NOT EXISTS + DELETE by
analysis_id + INSERTs), and a ZIP bundle with a README connection guide.
"""

from __future__ import annotations

import csv
import io
import zipfile

from .ratio_explain import build_yearly_comparison

# (key, ar, en) — the same labels the comparative analysis table uses
_CONCEPTS = [
    ("revenue", "الإيرادات", "Revenue"),
    ("cogs", "تكلفة الإيرادات", "Cost of Sales"),
    ("gross_profit", "مجمل الربح", "Gross Profit"),
    ("opex", "مصاريف التشغيل", "Operating Expenses"),
    ("net_profit", "صافي الربح", "Net Profit"),
    ("assets", "إجمالي الأصول", "Total Assets"),
    ("liabilities", "إجمالي الالتزامات", "Total Liabilities"),
    ("equity", "حقوق الملكية", "Equity"),
]


def _labels(key: str) -> tuple[str, str]:
    for k, ar, en in _CONCEPTS:
        if k == key:
            return ar, en
    return key, key


FACT_COLUMNS = ["concept", "concept_ar", "concept_en", "period_label",
                "period_index", "value", "is_forecast"]
GROWTH_COLUMNS = ["concept", "concept_ar", "concept_en", "period_label",
                  "value", "yoy_pct", "is_forecast"]
RATIO_COLUMNS = ["ratio", "ratio_ar", "ratio_en", "value"]

BI_TABLES = ("facts", "growth", "ratios")


def forecast_rows(result: dict, lang: str = "ar") -> list[dict]:
    """Next-year forecast rows (mean historical growth) from the shared
    yearly-comparison builder — the single source of truth the reports
    already read. Empty when the growth table doesn't exist (< 3 periods)."""
    comp = build_yearly_comparison(result, lang)
    if not comp or not comp.get("forecast_label"):
        return []
    rows = []
    for r in comp.get("rows") or []:
        fc = r.get("forecast")
        if not fc:
            continue
        ar, en = _labels(r["key"])
        rows.append({
            "concept": r["key"], "concept_ar": ar, "concept_en": en,
            "period_label": comp["forecast_label"],
            "period_index": len(r.get("points") or []) + 1,
            "value": fc["raw"], "is_forecast": 1,
        })
    return rows


def facts_rows(result: dict, lang: str = "ar",
               include_forecast: bool = True) -> list[dict]:
    """Every stored concept series in long format (oldest → latest per
    concept); forecast periods appended when available (``is_forecast=1``)."""
    metrics = result.get("metrics") or {}
    plabels = [str(x).strip() for x in (result.get("period_labels") or [])]
    rows: list[dict] = []
    for key, vals in metrics.items():
        nums = [float(v) for v in (vals or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not nums:
            continue
        ar, en = _labels(key)
        for i, v in enumerate(nums):
            rows.append({
                "concept": key, "concept_ar": ar, "concept_en": en,
                "period_label": plabels[i] if i < len(plabels)
                else f"period_{i + 1}",
                "period_index": i + 1,
                "value": round(v, 2), "is_forecast": 0,
            })
    if include_forecast:
        rows.extend(forecast_rows(result, lang))
    return rows


def growth_rows(result: dict, lang: str = "ar") -> list[dict]:
    """Annual growth table in long format: value + YoY % per year, then the
    next-year forecast row per concept (mean historical growth)."""
    comp = build_yearly_comparison(result, lang)
    if not comp or not comp.get("years"):
        return []
    rows: list[dict] = []
    for r in comp.get("rows") or []:
        pts = r.get("points") or []
        ar, en = _labels(r["key"])
        for k, p in enumerate(pts):
            yoy = None
            if k and pts[k - 1].get("raw"):
                yoy = round((p["raw"] - pts[k - 1]["raw"])
                            / abs(pts[k - 1]["raw"]) * 100, 2)
            rows.append({
                "concept": r["key"], "concept_ar": ar, "concept_en": en,
                "period_label": p["label"], "value": p["raw"],
                "yoy_pct": yoy, "is_forecast": 0,
            })
        fc = r.get("forecast")
        if fc:
            # the mean rate the forecast actually applied (full precision,
            # not the 1-dp display string «+26.5%»)
            rates = [(pts[k]["raw"] - pts[k - 1]["raw"])
                     / abs(pts[k - 1]["raw"])
                     for k in range(1, len(pts)) if pts[k - 1]["raw"]]
            yoy = (sum(rates) / len(rates) * 100) if rates else 0.0
            rows.append({
                "concept": r["key"], "concept_ar": ar, "concept_en": en,
                "period_label": comp["forecast_label"],
                "value": fc["raw"], "yoy_pct": round(yoy, 2),
                "is_forecast": 1,
            })
    return rows


def ratios_rows(result: dict) -> list[dict]:
    """Every computed ratio with its value (snapshot — ratios are scalar)."""
    ratios = result.get("ratios") or {}
    rows = []
    for key, entry in ratios.items():
        if not isinstance(entry, dict):
            continue
        v = entry.get("value")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        rows.append({
            "ratio": key,
            "ratio_ar": entry.get("ar") or key,
            "ratio_en": entry.get("en") or key,
            "value": v,
        })
    return rows


def build_table_rows(result: dict, table: str,
                     lang: str = "ar") -> tuple[list[dict], list[str]]:
    """Dispatch for the live connector endpoints. Returns (rows, columns)."""
    if table == "facts":
        return facts_rows(result, lang), FACT_COLUMNS
    if table == "growth":
        return growth_rows(result, lang), GROWTH_COLUMNS
    if table == "ratios":
        return ratios_rows(result), RATIO_COLUMNS
    raise ValueError(f"unknown BI table: {table}")


def build_sales_table_rows(sales: dict, lang: str = "ar") -> list:
    """Sections for the SALES-kind Excel export: (title, headers, rows)
    triples mirroring the sales dashboard — KPI summary, monthly trend,
    regions and salespersons ranking. Numeric cells stay numbers so Excel
    sums/charts them; text stays text."""
    if lang == "ar":
        t_summary = "ملخص المبيعات"
        t_monthly = "الاتجاه الشهري"
        t_regions = "تحليل المناطق"
        t_products = "الأصناف الأكثر مبيعًا"
        t_reps = "ترتيب المندوبين"
        h = {
            "metric": ("المؤشر", "القيمة"),
            "month": ("الشهر", "المبيعات", "العمليات", "النمو %", "عملاء جدد"),
            "region": ("المنطقة", "المبيعات", "النصيب %", "العمليات",
                       "متوسط العملية", "النمو %", "أفضل مندوب"),
            "product": ("#", "الصنف", "المبيعات", "النصيب %", "الكمّية",
                        "متوسط قيمة العملية", "عدد الفواتير", "أفضل شهر"),
            "rep": ("#", "المندوب", "المنطقة", "المبيعات", "العمليات", "النمو %", "عملاء جدد"),
        }
    else:
        t_summary, t_monthly, t_regions, t_products, t_reps = (
            "Sales Summary", "Monthly Trend", "Regions",
            "Top-selling Products", "Sales Representatives")
        h = {
            "metric": ("Metric", "Value"),
            "month": ("Month", "Sales", "Txns", "Growth %", "New customers"),
            "region": ("Region", "Sales", "Share %", "Txns", "Avg ticket", "Growth %", "Best rep"),
            "product": ("#", "Item", "Sales", "Share %", "Qty",
                        "Avg ticket", "Invoice lines", "Top month"),
            "rep": ("#", "Rep", "Region", "Sales", "Txns", "Growth %", "New customers"),
        }

    # summary
    summary_rows = [
        (("إجمالي المبيعات" if lang == "ar" else "Total sales"),
         sales.get("total_sales") or 0),
        ("عدد العمليات" if lang == "ar" else "Transactions",
         sales.get("total_transactions") or 0),
        ("متوسط العملية" if lang == "ar" else "Avg ticket",
         sales.get("avg_ticket_overall") or 0),
        ("عملاء جدد" if lang == "ar" else "New customers",
         sales.get("new_customers") or 0),
    ]
    fc = sales.get("forecast_next_month") or {}
    if fc.get("sales"):
        summary_rows.append(
            ("توقع الشهر القادم" if lang == "ar" else "Next-month forecast",
             fc["sales"]))

    monthly_rows = []
    for m in (sales.get("monthly") or []):
        monthly_rows.append([
            str(m.get("month") or ""),
            m.get("sales"), m.get("transactions"),
            m.get("growth"), m.get("new_customers"),
        ])

    region_rows = []
    for r in (sales.get("regions") or []):
        region_rows.append([
            str(r.get("region") or ""), r.get("sales"), r.get("share_pct"),
            r.get("transactions"), r.get("avg_ticket"), r.get("growth"),
            str(r.get("best_rep") or "-"),
        ])

    rep_rows = []
    for i, r in enumerate(sales.get("reps") or [], 1):
        rep_rows.append([
            i, str(r.get("rep") or ""), str(r.get("region") or "-"),
            r.get("sales"), r.get("transactions"), r.get("growth"),
            r.get("new_customers"),
        ])

    product_rows = []
    for i, p in enumerate((sales.get("products") or []), 1):
        product_rows.append([
            i, str(p.get("product") or ""), p.get("sales"), p.get("share_pct"),
            p.get("transactions"), p.get("avg_ticket"), p.get("units"),
            str(p.get("top_month") or "-"),
        ])

    sections = [
        (t_summary, h["metric"], summary_rows),
        (t_monthly, h["month"], monthly_rows),
        (t_regions, h["region"], region_rows),
    ]
    if product_rows:
        sections.append((t_products, h["product"], product_rows))
    sections.append((t_reps, h["rep"], rep_rows))
    return sections


def to_csv(rows: list[dict], columns: list[str]) -> str:
    """RFC-4180 CSV text. Callers encode as UTF-8 WITH BOM so Excel, Power
    BI and Looker Studio detect Arabic correctly."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def build_xlsx(tables: dict[str, tuple[list[str], list[dict]]]) -> bytes:
    """Plain workbook, one sheet per table, header on ROW 1 and frozen —
    deliberately banner-free so Power Query / Tableau / Looker ingest the
    range without any cleaning."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    for name, (cols, rows) in tables.items():
        ws = wb.create_sheet(name[:31])
        ws.append(list(cols))
        for r in rows:
            ws.append([r.get(c) for c in cols])
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0F766E")
        for col in ws.columns:
            letter = col[0].column_letter
            width = max((len(str(c.value or "")) for c in col), default=0)
            ws.column_dimensions[letter].width = min(34, max(12, width + 4))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_SQL_TYPES = {"period_index": "INTEGER", "is_forecast": "INTEGER",
              "value": "REAL", "yoy_pct": "REAL"}


def _sql_quote(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(float(v)) if isinstance(v, float) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def build_sql(analysis_id: int, tables: dict[str, tuple[list[str], list[dict]]]) -> str:
    """Portable SQL (SQLite / PostgreSQL / SQL Server, no dialect tricks):
    CREATE TABLE IF NOT EXISTS, DELETE for this analysis (idempotent
    re-runs), then INSERTs. ``analysis_id`` is the first column so several
    analyses can coexist in one warehouse."""
    out = [
        f"-- BI dataset for analysis {analysis_id}",
        "-- Portable SQL: sqlite3 my.db < schema.sql  |  psql -f schema.sql",
    ]
    for name, (cols, rows) in tables.items():
        table = f"bi_{name}"
        out.append(f"CREATE TABLE IF NOT EXISTS {table} (")
        out.append("  analysis_id INTEGER,")
        out.append(",\n".join(f"  {c} {_SQL_TYPES.get(c, 'TEXT')}"
                              for c in cols))
        out.append(");")
        out.append(f"DELETE FROM {table} WHERE analysis_id = {int(analysis_id)};")
        full_cols = ["analysis_id"] + list(cols)
        for r in rows:
            vals = [analysis_id] + [r.get(c) for c in cols]
            out.append(f"INSERT INTO {table} ({', '.join(full_cols)}) "
                       f"VALUES ({', '.join(_sql_quote(v) for v in vals)});")
    return "\n".join(out) + "\n"


def build_readme(analysis_id: int, entity: str, lang: str = "ar") -> str:
    """Connection guide for the six analysis tools (Arabic-first)."""
    ar = lang == "ar"
    idc = str(analysis_id)
    if ar:
        return f"""# حزمة BI — التحليل {idc} ({entity})

بيانات التحليل بصيغة نظيفة (tidy/long) جاهزة للاستيراد في أدوات التحليل الست.

## الملفات
| الملف | المحتوى |
|---|---|
| `facts.csv` / `facts.xlsx` | كل بند × كل فترة (القيم) + صفوف التوقع `is_forecast=1` |
| `growth_forecast.csv` | القيمة والنسبة السنوية لكل بند + صف التوقع (متوسط النمو التاريخي) |
| `ratios.csv` | النسب المالية المحسوبة وقيمها |
| `schema.sql` | إنشاء جداول `bi_facts` / `bi_growth_forecast` / `bi_ratios` وإدراج البيانات |
| `README.md` | هذا الدليل |

> الترميز UTF-8 مع BOM — يفتح العربي صحيحًا في Excel وPower BI مباشرة.
> رأس الجدول في الصف 1 دائمًا (بدون شعارات) ليقرأه الموصلات دون تنظيف.

## خطوات الربط

### Excel
افتح `facts.xlsx` مباشرة، أو من مصنف جديد: بيانات ← من نص/CSV ← `facts.csv`.

### Power BI
- ملف: Get Data ← Text/CSV (أو Excel workbook) ← اختر `facts.csv`.
- رابط حي (يتحدّث مع إعادة التحليل): Get Data ← Web ←
  `/api/analyses/{idc}/bi/facts?fmt=csv` (على عنوان خادم المنصة).

### Tableau
Connect ← To a File ← Text file ← `facts.csv` (UTF-8). لدمج أكثر من جدول:
استخدم علاقة على عمود `concept`.

### Google Looker Studio
Create ← Report ← Add data ← «Upload a file from a device» ← `facts.csv`،
أو ارفع `facts.xlsx` إلى Google Sheets ثم اربطه.

### SQL
```
sqlite3 financial.db < schema.sql
SELECT period_label, SUM(value) FROM bi_facts WHERE concept='revenue' GROUP BY period_label;
```

### Python
```python
import pandas as pd
facts = pd.read_csv("facts.csv")          # أو قراءة JSON من الموصل الحي
fc = facts[facts.is_forecast == 1]        # صفوف التوقع (متوسط النمو التاريخي)
```

## نقاط الموصل الحي
| الجدول | JSON | CSV |
|---|---|---|
| القيم | `/api/analyses/{idc}/bi/facts` | `…?fmt=csv` |
| النمو والتوقع | `/api/analyses/{idc}/bi/growth` | `…?fmt=csv` |
| النسب | `/api/analyses/{idc}/bi/ratios` | `…?fmt=csv` |

> التوقع رقم تقديري بمنهجية «آخر قيمة × (1 + متوسط النمو السنوي التاريخي)»
> — وليس وعدًا. التسميات عربية افتراضيًا؛ أضف `&lang=en` للإنجليزية.
"""
    return f"""# BI pack — analysis {idc} ({entity})

Tidy (long-format) datasets ready for the six analysis tools.

## Files
| File | Content |
|---|---|
| `facts.csv` / `facts.xlsx` | every concept × period + forecast rows (`is_forecast=1`) |
| `growth_forecast.csv` | yearly value & YoY % per concept + forecast row (mean historical growth) |
| `ratios.csv` | computed financial ratios |
| `schema.sql` | CREATE + INSERT for `bi_facts` / `bi_growth_forecast` / `bi_ratios` |

> UTF-8 with BOM — Arabic renders correctly in Excel/Power BI out of the box.
> Headers always sit on row 1 (no banners) so connectors ingest cleanly.

## Connect
- **Excel**: open `facts.xlsx` directly, or Data ← From Text/CSV.
- **Power BI**: Get Data ← Text/CSV; or live: Get Data ← Web ←
  `/api/analyses/{idc}/bi/facts?fmt=csv`.
- **Tableau**: Connect ← To a File ← Text file ← `facts.csv`.
- **Looker Studio**: Create ← Report ← Add data ← Upload a file.
- **SQL**: `sqlite3 my.db < schema.sql`.
- **Python**: `pandas.read_csv("facts.csv")`.

## Live endpoints
`/api/analyses/{idc}/bi/facts` · `/bi/growth` · `/bi/ratios` — add `?fmt=csv`.
Labels are Arabic by default; add `&lang=en` for English. The forecast is a
linear estimate (latest value × (1 + mean historical YoY growth)).
"""


def build_bi_pack(analysis_id: int, entity: str, result: dict,
                  lang: str = "ar") -> bytes:
    """One ZIP with every BI deliverable for an analysis."""
    facts = facts_rows(result, lang)
    growth = growth_rows(result, lang)
    ratios = ratios_rows(result)
    tables = {
        "facts": (FACT_COLUMNS, facts),
        "growth_forecast": (GROWTH_COLUMNS, growth),
        "ratios": (RATIO_COLUMNS, ratios),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("facts.csv", to_csv(facts, FACT_COLUMNS).encode("utf-8-sig"))
        z.writestr("growth_forecast.csv",
                   to_csv(growth, GROWTH_COLUMNS).encode("utf-8-sig"))
        z.writestr("ratios.csv", to_csv(ratios, RATIO_COLUMNS).encode("utf-8-sig"))
        z.writestr("facts.xlsx", build_xlsx(tables))
        z.writestr("schema.sql", build_sql(analysis_id, tables))
        z.writestr("README.md", build_readme(analysis_id, entity, lang))
    return buf.getvalue()
