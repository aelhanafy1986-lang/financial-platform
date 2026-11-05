"""Professional PowerPoint report generation with Arabic support.

The deck follows the user's reference template (تحليل مالي لأداء كنافة العاصمة
للحلويات 2025): navy 0B2545 cover with decorative accent bars, Sakkal Majalla
typography (latin + complex-script), content slides with a right-aligned navy
title over a gold underline bar and a muted footer line, rounded KPI cards,
scenario cards, native forecast tables and matplotlib trend charts.

Arabic text needs reshaping + bidi, mirroring app/report.py.
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from matplotlib import font_manager, use as mpl_use
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from pptx.util import Emu

from .ifrs import basis_of_preparation, detect_applicable as detect_ifrs
from .ratio_explain import DAYS_KEYS

_RAW_ARABIC = re.compile(r"[\u0621-\u064A]")

mpl_use("Agg")

# ---- template palette ------------------------------------------------------
NAVY = RGBColor(0x0B, 0x25, 0x45)        # cover background / dark bands
TITLE = RGBColor(0x05, 0x2F, 0x61)       # slide titles
ACCENT = RGBColor(0x00, 0x70, 0xC0)      # blue accents
GOLD = RGBColor(0xFF, 0xC0, 0x00)        # underline bar / highlights
ORANGE = RGBColor(0xEE, 0x6C, 0x4D)      # secondary accent
GREEN = RGBColor(0x6A, 0x9E, 0x1F)       # positive
RED = RGBColor(0xC0, 0x00, 0x00)         # negative
INK = RGBColor(0x26, 0x26, 0x26)
MUTED = RGBColor(0x5E, 0x6B, 0x7A)
PANEL = RGBColor(0xF2, 0xF6, 0xFA)       # light card background
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xD7, 0xDF, 0xE8)
OPT_BG = RGBColor(0xEC, 0xFD, 0xF5)
REAL_BG = RGBColor(0xEF, 0xF6, 0xFF)
CONS_BG = RGBColor(0xFF, 0xF7, 0xED)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

FONT_AR = "Sakkal Majalla"
FONT_FALLBACK = "Tahoma"

_SHAPE4 = {"rect": 1, "round": 5, "oval": 9, "tri": 7}

_FONT_PATH: str | None = None


def _find_arabic_font() -> str | None:
    global _FONT_PATH
    if _FONT_PATH is not None:
        return _FONT_PATH or None
    for c in (
        Path("C:/Windows/Fonts/majalla.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if c.exists():
            _FONT_PATH = str(c)
            return _FONT_PATH
    try:
        for f in font_manager.findSystemFonts():
            name = Path(f).name.lower()
            if "amiri" in name or "notonaskh" in name:
                _FONT_PATH = f
                return _FONT_PATH
    except Exception:
        pass
    _FONT_PATH = ""
    return None


# Symbols the Arabic TTFs (Sakkal Majalla…) do NOT carry — PowerPoint
# renders them as hollow boxes. Same mapping report.py applies so BOTH
# report engines emit only glyphs the declared font actually has
# (pinned by tests/test_font_coverage.py).
_GLYPH_SUBS = {
    "\u2713": "\u2022",  # ✓ → •
    "\u2717": "\u00d7",  # ✗ → ×
    "\u2192": "\u2013",  # → → –
    "\u25cf": "\u2022",  # ● → •
    "\u2588": "\u2022",  # █ → •
    "\u2591": "\u00b7",  # ░ → ·
    # direction markers + trend chips (yearly comparison, labels.py): majalla
    # has no geometric shapes, so the platform's ▲/▼/◄/► affordance degrades
    # to covered ASCII glyphs — the verdict colour (green/red) carries the
    # judgment, the marker the direction
    "\u25b2": "^",       # ▲ → ^ (up)
    "\u25bc": "v",       # ▼ → v (down)
    "\u25c4": "<",       # ◄ → < (flat)
    "\u25ba": ">",       # ► → >
    "\u26a0": "!",       # ⚠ → ! (majalla has no warning sign)
}


def _shape(text: str) -> str:
    if not text:
        return text
    text = str(text)
    if any(bad in text for bad in _GLYPH_SUBS):
        for bad, good in _GLYPH_SUBS.items():
            if bad in text:
                text = text.replace(bad, good)
    # Idempotent: text that is already shaped (contains Arabic presentation
    # forms) passes through untouched — re-running the reshaper + bidi on
    # visual-order text would scramble it (double-shaping bug).
    if any(0xFB50 <= ord(ch) <= 0xFEFF for ch in text):
        return text
    return get_display(arabic_reshaper.reshape(text))


def _fmt(n, decimals: int = 0) -> str:
    try:
        return f"{float(n):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(n)


def _apply_font(run, name: str | None = None) -> None:
    """Set both latin and complex-script typefaces so Arabic uses the font."""
    name = name or (FONT_AR if _find_arabic_font() else FONT_FALLBACK)
    run.font.name = name
    _font_face(run.font, name)


def _font_face(font, name: str) -> None:
    """python-pptx ``Font.name`` sets only the LATIN typeface — Arabic text
    (chart axis labels, legends) is picked via the complex-script face, so
    both must point at the Arabic font or PowerPoint falls back."""
    font.name = name
    rPr = font._rPr
    for tag in ("a:cs", "a:ea"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def _labels(lang: str) -> dict:
    if lang == "ar":
        return {
            "deck_title": "العرض التقديمي المالي",
            "platform": "المنصة المالية الذكية",
            "tagline": "محلّلك المالي المدعوم بالذكاء الاصطناعي",
            "issued": "تم إنشاؤه: {d}",
            "entity": "المنشأة: {name}",
            "period": "فترة التحليل: {p}",
            "source": "إعداد وتحليل: {name}",
            "exec_brief": "الملخص التنفيذي",
            "about_company": "نبذة عن الشركة ونشاطها",
            "activity": "نوع النشاط",
            "size": "حجم الشركة",
            "pattern": "نمط التشغيل",
            "results_summary": "ملخص النتائج",
            "strengths": "نقاط القوة",
            "weaknesses": "نقاط الضعف",
            "kpis": "المؤشرات الرئيسية",
            "ratios": "النسب المالية",
            "ratio_insights": "تحليل النسب المالية",
            "comparison": "تحليل المقارنة (أفقي وعمودي)",
            "yc_legend": "▲ تحسّن · ▼ تراجع · ◄ مستقر · شدة اللون = حجم التغير",
            "yc_growth": "مقارنة النمو السنوي (القيمة ونسبة التغير عن العام السابق)",
            "evo_title": "تطور الإيرادات وصافي الربح عبر السنوات",
            "evo_revenue": "الإيرادات",
            "evo_net": "صافي الربح",
            "what_q": "ما هي؟", "why_q": "ما فائدتها؟", "opinion_q": "الرأي:",
            "trends": "الرسوم البيانية التحليلية",
            "score_title": "التقييم المالي",
            "scenarios": "السيناريوهات المستقبلية",
            "growth": "النمو",
            "next_rev": "الإيراد المتوقع",
            "next_net": "صافي الربح المتوقع",
            "forecast": "التنبؤات المستقبلية",
            "advice": "التوصيات",
            "no_issues": "لا توجد مؤشرات سلبية — استمر في المتابعة الدورية",
            "solutions": "حلول مقترحة",
            "statements": "القوائم المالية",
            "is_title": "قائمة الدخل",
            "bs_title": "قائمة المركز المالي",
            "cf_title": "قائمة التدفقات النقدية",
            "eq_title": "قائمة التغير في حقوق الملكية",
            "item_col": "البند",
            "value_col": "القيمة",
            "current_col": "الحالي",
            "projected_col": "المتوقع",
            "delta_col": "التغير %",
            "notes": "ملاحظات",
            "critical": "حرج", "warning": "تنبيه", "info": "إيجابي",
            "ifrs_title": "الإطار المعياري (IFRS)",
            "dash_title": "لوحة المؤشرات التحليلية",
            "activity_title": "تطور دورة التحول النقدي ومكوناتها عبر الفترات",
        "dash_expenses": "توزيع المصروفات",
        "dash_expenses_center": "المصروفات",
        "dash_cost": "بنية الإيراد: التكلفة مقابل النتيجة",
        "bench_chart_title": "النسب مقابل المعايير المرجعية",
            "bench_ours": "النسبة المحققة (نسبة لمعيارها)",
            "bench_ref": "المعيار المرجعي (1.00)",
            "bench_note": "المرساة = 1.00 · فوقه تحقيق للمعيار وتحته قصور — المراسي وفق المنهجية (نسبة التداول 2.0، تغطية الفوائد 3.0×، تحصيل ≤ 90 يومًا…) · • مستوفٍ · ≈ قريب · × غير مستوفٍ",
        }
    return {
        "deck_title": "Financial Presentation",
        "platform": "Smart Financial Platform",
        "tagline": "Your Smart AI Financial Analyst",
        "issued": "Created: {d}",
        "entity": "Entity: {name}",
        "period": "Analysis period: {p}",
        "source": "Prepared for: {name}",
        "exec_brief": "Executive Summary",
        "about_company": "About the company & activity",
        "activity": "Activity",
        "size": "Company size",
        "pattern": "Operating pattern",
        "results_summary": "Results summary",
        "strengths": "Strengths",
        "weaknesses": "Weaknesses",
        "kpis": "Key Indicators",
        "ratios": "Financial Ratios",
        "ratio_insights": "Ratio Analysis",
        "comparison": "Comparative Analysis",
        "yc_legend": "▲ improved · ▼ declined · ◄ flat · colour depth = change size",
        "yc_growth": "Annual Growth Comparison (value and YoY change)",
        "evo_title": "Revenue & Net Profit Evolution Across Years",
        "evo_revenue": "Revenue",
        "evo_net": "Net Profit",
        "what_q": "What is it?", "why_q": "Why it matters", "opinion_q": "Verdict:",
        "trends": "Analytical Charts",
        "score_title": "Financial Score",
        "scenarios": "Future Scenarios",
        "growth": "Growth",
        "next_rev": "Projected revenue",
        "next_net": "Projected net",
        "forecast": "Forecast",
        "advice": "Recommendations",
        "no_issues": "No negative indicators — keep periodic monitoring",
        "solutions": "Suggested solutions",
        "statements": "Financial Statements",
        "is_title": "Income Statement",
        "bs_title": "Statement of Financial Position",
        "cf_title": "Cash Flow Statement",
        "eq_title": "Changes in Equity",
        "item_col": "Item",
        "value_col": "Value",
        "current_col": "Current",
        "projected_col": "Projected",
        "delta_col": "Change %",
        "notes": "Notes",
        "critical": "Critical", "warning": "Warning", "info": "Positive",
        "ifrs_title": "Standards Framework (IFRS)",
        "dash_title": "Analytics Dashboard",
        "activity_title": "Cash Conversion Cycle & Components Trend",
        "dash_expenses": "Expense Mix",
        "dash_expenses_center": "Expenses",
        "dash_cost": "Revenue Composition: Cost vs Result",
        "bench_chart_title": "Ratios vs Reference Benchmarks",
        "bench_ours": "Achieved ratio (× its benchmark)",
        "bench_ref": "Reference benchmark (1.00)",
        "bench_note": "Benchmark = 1.00 · above means the benchmark is met, below means short of it — anchors per the adopted methodology (current 2.0, interest coverage 3.0×, collection ≤ 90 days...) · ✓ Aligned · ≈ Near · ✗ Off",
    }


def _slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _bg(slide, color) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _box(slide, kind: str, x, y, w, h, fill=None, line=None, line_w=None):
    shp = slide.shapes.add_shape(_SHAPE4[kind], x, y, w, h)
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = line_w or Pt(1)
    shp.shadow.inherit = False
    return shp


def _add_text(slide, left, top, width, height, text, size=14, color=INK,
              bold=False, align=PP_ALIGN.RIGHT, font=None) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = _shape(str(text))
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    _apply_font(run, font)
    return box


def _text_w(text: str, pt: float) -> float:
    """Approximate rendered width in inches (PIL + the Arabic TTF) for the
    marker legend's absolute segment layout; char-count fallback otherwise."""
    s = _shape(text)
    try:
        from PIL import ImageFont
        fp = _find_arabic_font() or "C:/Windows/Fonts/arial.ttf"
        scale = 8
        f = ImageFont.truetype(fp, max(int(pt * 96 / 72 * scale), 8))
        return f.getlength(s) / scale / 96 * 1.06 + 0.05
    except Exception:
        return 0.085 * len(s) * pt / 11.5 + 0.05


def _dir_marker(slide, x, y, direction: str, color, size_in: float = 0.115) -> None:
    """The platform's direction affordance as a REAL vector shape — majalla
    carries no geometric-arrow glyphs, so up/down are isosceles triangles
    (down = rotated 180 degrees) and flat is a neutral dash. Font-independent,
    drawn OVER the host cell/box."""
    s = Inches(size_in)
    if direction == "up":
        _box(slide, "tri", x, y, s, s, fill=color)
    elif direction == "down":
        _box(slide, "tri", x, y, s, s, fill=color).rotation = 180
    else:
        _box(slide, "rect", x, y + (s - Inches(size_in * 0.30)) // 2,
             Inches(size_in * 1.40), Inches(size_in * 0.30), fill=color)


def _marker_legend(slide, left, top, width, lang: str, L: dict,
                   size_pt: float = 9.5, color=MUTED, extra: str = "") -> None:
    """The platform's colour legend with the direction markers as REAL
    shapes: the words live in separate boxes anchored from the reading edge
    so each marker can sit beside its word without font-dependent spacing.
    ``extra`` appends a trailing text segment (forecast methodology note)."""
    align = PP_ALIGN.RIGHT if lang == "ar" else PP_ALIGN.LEFT
    mark_kind = {"\u25b2": "up", "\u25bc": "down", "\u25c4": "flat", "\u25ba": "flat"}
    mark_col = {"up": GREEN, "down": RED, "flat": MUTED}
    segs = []
    for part in str(L["yc_legend"]).split("·"):
        part = part.strip()
        if not part:
            continue
        if part[0] in mark_kind:
            segs.append(("mark", mark_kind[part[0]]))
            part = part[1:].strip()
        if part:
            segs.append(("word", part))
    if extra:
        segs.append(("word", str(extra)))
    gap = Inches(0.07)
    line_h = Inches(0.26)
    msize = Inches(0.095)
    cur = left + width if lang == "ar" else left
    for kind, val in segs:
        if kind == "mark":
            my = top + (line_h - msize) // 2
            _dir_marker(slide, cur - msize if lang == "ar" else cur, my,
                        val, mark_col[val], 0.095)
            cur = cur - msize - gap if lang == "ar" else cur + msize + gap
        else:
            w = Inches(_text_w(val, size_pt))
            bx = cur - w if lang == "ar" else cur
            _add_text(slide, bx, top, w, line_h, val, size=size_pt,
                      color=color, align=align)
            cur = bx - gap if lang == "ar" else cur + w + gap


def _content_header(slide, title: str, lang: str, L: dict, filename: str) -> None:
    """Template-style header: navy title on the right + gold underline bar +
    muted footer with platform / file name.

    The title is SHAPEd here (presentation forms + visual order) so Arabic
    renders connected and correctly ordered — raw logical Arabic would be
    displayed disjointed by PowerPoint. Text that is already shaped
    (contains presentation-form code points) passes through untouched, so
    pre-shaped labels are never double-shaped."""
    align = PP_ALIGN.RIGHT if lang == "ar" else PP_ALIGN.LEFT
    if (title and _RAW_ARABIC.search(title)
            and not any(0xFB50 <= ord(ch) <= 0xFEFF for ch in title)):
        title = _shape(title)
    _add_text(slide, Inches(0.6), Inches(0.28), Inches(12.1), Inches(0.6),
              title, size=26, color=TITLE, bold=True, align=align)
    # gold underline bar (starts from the right for AR)
    bar_x = Inches(10.55) if lang == "ar" else Inches(0.6)
    _box(slide, "rect", bar_x, Inches(0.92), Inches(2.15), Pt(3.2), fill=GOLD)
    # footer
    footer_y = Inches(7.08)
    line = _box(slide, "rect", Inches(0.6), footer_y - Pt(4), Inches(12.1), Pt(0.8), fill=LINE)
    left_text = L["platform"] if lang == "ar" else filename
    right_text = filename if lang == "ar" else L["platform"]
    _add_text(slide, Inches(0.6), footer_y, Inches(5.5), Inches(0.32),
              left_text, size=11, color=MUTED, align=PP_ALIGN.LEFT)
    _add_text(slide, Inches(7.2), footer_y, Inches(5.5), Inches(0.32),
              right_text, size=11, color=MUTED, align=PP_ALIGN.RIGHT)


def _kpi_card(slide, x, y, w, h, name, value_str, value_color, lang, accent=None):
    """Rounded KPI card with a coloured side accent (template style)."""
    card = _box(slide, "round", x, y, w, h, fill=PANEL, line=LINE, line_w=Pt(0.75))
    card.adjustments[0] = 0.08
    align = PP_ALIGN.RIGHT if lang == "ar" else PP_ALIGN.LEFT
    accent_w = Pt(3.5)
    if lang == "ar":
        ax = x + w - accent_w
    else:
        ax = x
    _box(slide, "rect", ax, y + Emu(20000), accent_w, h - Emu(40000),
         fill=accent or ACCENT)
    pad = Inches(0.22)
    _add_text(slide, x + pad, y + Inches(0.12), w - 2 * pad, Inches(0.4),
              name, size=14, color=MUTED, bold=True, align=align)
    _add_text(slide, x + pad, y + Inches(0.5), w - 2 * pad, Inches(0.75),
              value_str, size=27, color=value_color, bold=True, align=align)


def _chart_image(values: list, projections: list | None = None, title: str = "",
                 labels: list[str] | None = None) -> bytes | None:
    try:
        import matplotlib.pyplot as plt

        font_path = _find_arabic_font()
        if font_path:
            try:
                font_manager.fontManager.addfont(font_path)
                family = font_manager.FontProperties(fname=font_path).get_name()
                import matplotlib as mpl
                mpl.rcParams["font.family"] = family
                mpl.rcParams["axes.unicode_minus"] = False
            except Exception:
                pass

        hist = [float(v) for v in values]
        xs = list(range(1, len(hist) + 1))
        proj = [float(p["value"]) for p in (projections or [])]
        fig, ax = plt.subplots(figsize=(7.4, 2.1), dpi=160)
        ax.plot(xs, hist, color="#052F61", linewidth=2.4, marker="o", markersize=4)
        ax.fill_between(xs, hist, color="#052F61", alpha=0.10)
        if proj:
            px = list(range(len(hist), len(hist) + len(proj)))
            ax.plot([xs[-1]] + px, [hist[-1]] + proj, color="#EE6C4D",
                    linewidth=2.4, linestyle="--", marker="s", markersize=4)
        ax.grid(True, axis="y", alpha=0.25)
        if labels:
            hist_labels = [str(x) for x in labels[-len(hist):]]
            if len(hist_labels) == len(hist):
                ax.set_xticks(xs + list(range(len(hist) + 1,
                                           len(hist) + len(proj) + 1)))
                ax.set_xticklabels(hist_labels + [""] * len(proj),
                                   fontsize=8, color="#5E6B7A")
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=8, colors="#5E6B7A")
        if title:
            # matplotlib ≥3.10 shapes Arabic + bidi itself — pre-shaped text
            # gets reversed a second time (garbled chart titles)
            from .dashboard_charts import mpl_text
            ax.set_title(mpl_text(title), fontsize=11, color="#052F61", fontweight="bold")
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def _sales_mpl_chart(values_a: list, kind: str, labels: list[str] | None = None,
                     values_b: list | None = None, title_a: str = "",
                     title_b: str = "", bar_names: list[str] | None = None,
                     forecast: float | None = None) -> bytes | None:
    """Sales-deck matplotlib charts mirroring the live Recharts panel:
    area (monthly trend, blue stroke + slot forecast — same as the
    dashboard card), cbar (period comparison paired bars A gray / B
    blue), line2 (transactions + new customers), pie (region share
    donut), hbar (rep leaderboard). Arabic via ``mpl_text`` — matplotlib
    shapes itself; pre-shaped text gets double-reversed.
    """
    try:
        import matplotlib.pyplot as plt

        from .dashboard_charts import mpl_text

        font_path = _find_arabic_font()
        if font_path:
            try:
                font_manager.fontManager.addfont(font_path)
                family = font_manager.FontProperties(fname=font_path).get_name()
                import matplotlib as mpl
                mpl.rcParams["font.family"] = family
                mpl.rcParams["axes.unicode_minus"] = False
            except Exception:
                pass

        a = [float(v) for v in values_a]
        xs = list(range(1, len(a) + 1))
        if kind == "area":
            fig, ax = plt.subplots(figsize=(11.2, 2.9), dpi=130)
            ax.plot(xs, a, color="#2563eb", linewidth=2.5, marker="o", markersize=4)
            ax.fill_between(xs, a, color="#2563eb", alpha=0.14)
            if forecast is not None:
                # amber forecast slot, same shape as the financial chart
                px = [xs[-1], xs[-1] + 2]
                ax.plot(px, [a[-1], float(forecast)], color="#f59e0b",
                        linewidth=2.2, linestyle="--", marker="o",
                        markersize=4, markerfacecolor="none")
                ax.set_xlim(right=xs[-1] + 2)
            if labels:
                ax.set_xticks(xs)
                ax.set_xticklabels([str(x) for x in labels[-len(a):]], fontsize=9)
        elif kind == "cbar":
            # paired comparison bars: A gray vs B blue (dashboard cmp)
            b = [float(v) for v in (values_b or [])][:len(a)]
            fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=130)
            n = len(a)
            ypos = list(range(n))[::-1]
            h = min(0.36, 0.8 / n)
            ax.barh([y + h / 2 + 0.01 for y in ypos], a, height=h,
                    color="#94a3b8",
                    label=mpl_text(title_a) if title_a else None)
            if len(b) == n:
                ax.barh([y - h / 2 - 0.01 for y in ypos], b, height=h,
                        color="#2563eb",
                        label=mpl_text(title_b) if title_b else None)
            ax.set_yticks(ypos)
            ax.set_yticklabels(
                [mpl_text(str(n_)) for n_ in (bar_names or [""] * n)],
                fontsize=10)
            if title_a or title_b:
                ax.legend(fontsize=9, frameon=False, loc="lower right")
        elif kind == "line2":
            fig, ax = plt.subplots(figsize=(11.2, 3.4), dpi=130)
            ax.plot(xs, a, color="#8b5cf6", linewidth=2.5, marker="o", markersize=4,
                    label=mpl_text(title_a))
            b = [float(v) for v in (values_b or [])][:len(a)]
            if len(b) == len(a):
                ax.plot(xs, b, color="#f59e0b", linewidth=2.5, marker="s", markersize=4,
                        label=mpl_text(title_b))
            ax.legend(fontsize=9, frameon=False)
            if labels:
                ax.set_xticks(xs)
                ax.set_xticklabels([str(x) for x in labels[:len(a)]], fontsize=9)
        elif kind == "pie":
            fig, ax = plt.subplots(figsize=(5.4, 4.2), dpi=130)
            names = [str(n) for n in (bar_names or [])]
            palette = ["#2563eb", "#8b5cf6", "#06b6d4", "#f59e0b",
                       "#ec4899", "#10b981", "#f43f5e"]
            ax.pie(a, labels=[mpl_text(n) for n in names] or None,
                   autopct="%1.1f%%", pctdistance=0.75,
                   colors=[palette[i % len(palette)] for i in range(len(a))],
                   wedgeprops={"width": 0.45, "edgecolor": "white"},
                   textprops={"fontsize": 9})
        else:  # hbar
            fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=130)
            ypos = list(range(len(a)))[::-1]
            ax.barh(ypos, a, color="#2563eb", height=0.55)
            ax.set_yticks(ypos)
            ax.set_yticklabels([mpl_text(str(n)) for n in (bar_names or [])], fontsize=10)
        ax.grid(True, axis="x" if kind in ("hbar", "cbar") else "y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=9)
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def build_pptx_report(
    filename: str,
    result: dict,
    out_path: Path,
    lang: str = "ar",
    advisor: dict | None = None,
    statements: dict | None = None,
    notes: str | None = None,
    score: dict | None = None,
    scenarios: dict | None = None,
    brief: dict | None = None,
    ratio_insights: list | None = None,
    yearly_comparison: dict | None = None,
    band: str | None = None,
    period: str | None = None,
) -> Path:
    """Generate the template-styled PowerPoint deck."""
    L = _labels(lang)
    align = PP_ALIGN.RIGHT if lang == "ar" else PP_ALIGN.LEFT
    logo = Path(__file__).resolve().parent.parent / "app" / "assets" / "logo.png"
    if not logo.exists():
        logo = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo.png"

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    # ---- cover slide (navy, decorative bars, template style) ---------------
    s = _slide(prs)
    _bg(s, NAVY)
    # decorative accent bars like the reference cover
    _box(s, "rect", Inches(0.9), Inches(1.15), Inches(0.09), Inches(2.3), fill=GOLD)
    _box(s, "rect", Inches(1.12), Inches(1.45), Inches(0.05), Inches(1.7), fill=ORANGE)
    _box(s, "rect", Inches(11.2), Inches(5.4), Inches(1.25), Inches(0.09), fill=GOLD)
    if logo.exists():
        # white rounded plate behind the navy logo tile so it reads on navy
        plate = _box(s, "round", Inches(6.11), Inches(0.55), Inches(1.28), Inches(1.28),
                     fill=WHITE)
        plate.adjustments[0] = 0.22
        s.shapes.add_picture(str(logo), Inches(6.25), Inches(0.69), height=Inches(1.0))
    _add_text(s, Inches(1.35), Inches(1.25), Inches(10.4), Inches(1.0),
              L["deck_title"], size=44, color=WHITE, bold=True, align=align)
    _add_text(s, Inches(1.35), Inches(2.35), Inches(10.4), Inches(0.65),
              L["platform"], size=22, color=GOLD, bold=True, align=align)
    _add_text(s, Inches(1.35), Inches(2.95), Inches(10.4), Inches(0.35),
              L["tagline"], size=13,
              color=RGBColor(0xFF, 0xDD, 0x88), align=align)
    _add_text(s, Inches(1.35), Inches(3.35), Inches(10.4), Inches(0.6),
              L["entity"].format(name=filename), size=18,
              color=RGBColor(0xCC, 0xD8, 0xE8), align=align)
    if period:
        _add_text(s, Inches(1.35), Inches(3.95), Inches(10.4), Inches(0.45),
                  L["period"].format(p=period), size=14,
                  color=RGBColor(0xCC, 0xD8, 0xE8), align=align)
    _add_text(s, Inches(1.35), Inches(4.45), Inches(10.4), Inches(0.5),
              L["issued"].format(d=f"{date.today():%Y-%m-%d}"), size=13,
              color=RGBColor(0x9A, 0xAB, 0xC2), align=align)
    if band:
        _add_text(s, Inches(1.35), Inches(4.95), Inches(10.4), Inches(0.5),
                  band, size=13,
                  color=RGBColor(0x9A, 0xAB, 0xC2), align=align)
    # quality-gate warnings (incl. the W4 balance-sheet identity gap) surface
    # on the cover — the printed deck must not look cleaner than the platform
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else None
    if audit and (audit.get("warnings") or []):
        n_warn = len(audit["warnings"])
        first = str(audit["warnings"][0].get("ar") if lang == "ar"
                    else audit["warnings"][0].get("en"))
        warn_txt = (first if n_warn == 1
                    else (f"{first} — و{n_warn - 1} تنبيهات أخرى"
                          if lang == "ar" else f"{first} — and {n_warn - 1} more"))
        _add_text(s, Inches(1.35), Inches(5.45), Inches(10.4), Inches(0.75),
                  f"⚠ {warn_txt}", size=12, color=ORANGE, bold=True, align=align)

    # ---- IFRS framework slide -----------------------------------------------
    # DISTINCT name: the notes parameter below is the USER's free-text notes
    # — storing the IFRS applicability list in the same variable made the
    # notes slide print the raw repr of a list of dicts («:[{'code': 'IAS
    # 1'…» — the «strange data» on the notes slide).
    ifrs_list = detect_ifrs(result, statements)
    s = _slide(prs)
    _bg(s, WHITE)
    _content_header(s, L["ifrs_title"], lang, L, filename)
    _add_text(s, Inches(0.6), Inches(1.15), Inches(12.1), Inches(0.85),
              basis_of_preparation(lang), size=11.5, color=INK, align=align)
    y = 2.15
    for n in (ifrs_list or [])[:6]:
        code_w = Inches(1.5)
        x_code = SLIDE_W - Inches(0.6) - code_w if lang == "ar" else Inches(0.6)
        chip = _box(s, "round", x_code, Inches(y), code_w, Inches(0.5), fill=ACCENT)
        chip.adjustments[0] = 0.5
        _add_text(s, x_code, Inches(y + 0.05), code_w, Inches(0.4),
                  n["code"], size=13, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
        tx = Inches(0.6) if lang == "ar" else Inches(2.25)
        title_txt = n["ar"] if lang == "ar" else n["en"]
        why_txt = n["why_ar"] if lang == "ar" else n["why_en"]
        _add_text(s, tx, Inches(y + 0.02), Inches(10.5), Inches(0.46),
                  f"{title_txt} — {why_txt}", size=12, color=INK, align=align)
        y += 0.68

    # ---- executive brief slide ---------------------------------------------
    if brief:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["exec_brief"], lang, L, filename)
        company = brief.get("company") or {}

        # about-the-company panel
        _add_text(s, Inches(0.6), Inches(1.15), Inches(12.1), Inches(0.45),
                  L["about_company"], size=17, color=ACCENT, bold=True, align=align)
        rows = [
            (L["activity"], company.get("activity", "")),
            (L["size"], company.get("size", "")),
            (L["pattern"], company.get("pattern", "")),
        ]
        # «ملاءمة الأنشطة»: activity type vs its sector's turnover band
        fit = company.get("activity_fit") or {}
        if fit:
            rows.append((
                fit.get("title", ""),
                f"{fit.get('turnover_txt', '')} · {fit.get('range_txt', '')}"
                f" — {fit.get('verdict_label', '')}",
            ))
        y = Inches(1.7)
        for lbl, val in rows:
            if not val:
                continue
            lbl_w = Inches(1.9)
            _box(s, "rect", Inches(10.75) if lang == "ar" else Inches(0.6),
                 y, lbl_w, Inches(0.42), fill=PANEL)
            _add_text(s, Inches(10.75) if lang == "ar" else Inches(0.6),
                      y + Inches(0.02), lbl_w, Inches(0.38),
                      lbl, size=13, color=TITLE, bold=True, align=align)
            _add_text(s, Inches(0.6) if lang == "ar" else Inches(2.6),
                      y + Inches(0.02), Inches(10.05), Inches(0.38),
                      val, size=14, color=INK, align=align)
            y += Inches(0.5)

        # results chips
        results = brief.get("results") or []
        if results:
            _add_text(s, Inches(0.6), y + Inches(0.1), Inches(12.1), Inches(0.4),
                      L["results_summary"], size=17, color=ACCENT, bold=True, align=align)
            chip_y = y + Inches(0.55)
            per_row = 3
            cw, ch = Inches(3.9), Inches(0.95)
            for i, r in enumerate(results[:6]):
                row, col = divmod(i, per_row)
                x = Inches(0.6 + col * 4.1)
                if lang == "ar":
                    x = SLIDE_W - Inches(0.6 + (col + 1) * 4.1 + 0.2)
                color = RED if r.get("negative") else TITLE
                card = _box(s, "round", x, chip_y + row * Inches(1.1), cw, ch,
                            fill=PANEL, line=LINE, line_w=Pt(0.75))
                card.adjustments[0] = 0.10
                _add_text(s, x + Inches(0.15), chip_y + row * Inches(1.1) + Inches(0.06),
                          cw - Inches(0.3), Inches(0.35),
                          r["label"], size=12.5, color=MUTED, bold=True, align=align)
                _add_text(s, x + Inches(0.15), chip_y + row * Inches(1.1) + Inches(0.4),
                          cw - Inches(0.3), Inches(0.5),
                          r["value"], size=19, color=color, bold=True, align=align)

        # verdict paragraph
        if brief.get("verdict"):
            _add_text(s, Inches(0.6), Inches(6.35), Inches(12.1), Inches(0.6),
                      brief["verdict"], size=15, color=TITLE, bold=True, align=align)

    # ---- KPI slide ----------------------------------------------------------
    kpis = result.get("kpis") or {}
    if kpis:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["kpis"], lang, L, filename)
        entries = list(kpis.values())
        per_row = 3
        card_w, card_h = Inches(3.95), Inches(1.55)
        start_x, start_y = Inches(0.6), Inches(1.5)
        for idx, kpi in enumerate(entries[:9]):
            row, col = divmod(idx, per_row)
            x = start_x + col * (card_w + Inches(0.25))
            if lang == "ar":
                x = SLIDE_W - start_x - card_w - col * (card_w + Inches(0.25))
            y = start_y + row * (card_h + Inches(0.35))
            val = kpi.get("value")
            color = RED if isinstance(val, (int, float)) and val < 0 else TITLE
            _kpi_card(s, x, y, card_w, card_h,
                      kpi.get(lang) or kpi.get("en") or "",
                      _fmt(val), color, lang,
                      accent=GOLD if idx % 3 == 1 else ACCENT)

    # ---- ratios slide (COMPACT: every ratio must fit the slide) ---------------
    ratios = result.get("ratios") or {}
    if ratios:
        from .ratio_explain import _PERCENT_KEYS
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["ratios"], lang, L, filename)
        top = 1.35
        bottom_limit = 7.15  # footer sits below this
        avail_h = bottom_limit - top
        items = list(ratios.items())
        n = len(items)
        # Column count by density — every count gets a layout that keeps BOTH
        # label and value legible and KEPT ON THE SLIDE: ≤ 9 rows in one
        # full-width column, ≤ 16 in two, beyond that three (rows stay at the
        # comfortable 0.58" cap; the columns get narrower instead).
        n_cols = 1 if n <= 9 else (2 if n <= 16 else 3)
        rows_per_col = -(-n // n_cols)  # ceil
        row_h = min(0.58, avail_h / rows_per_col)
        col_w = 12.1 / n_cols
        # Unit rides WITH the value from the CANONICAL unit sets: percent
        # ratios show «30.40%», days show «45 يوم», working capital is a
        # money amount (no multiple) — every other ratio is an x-multiple.
        def _unit(rkey: str) -> str:
            if rkey in _PERCENT_KEYS:
                return "%"
            if rkey in DAYS_KEYS:
                return " يوم" if lang == "ar" else " days"
            if rkey == "working_capital":
                return ""
            return "x"

        def _label_sz(txt: str, box_w: float) -> float:
            """Largest size whose label wraps into ≤ 2 lines inside box_w —
            real glyph measurement (_text_w), not a char-count guess."""
            for sz in (14.5, 13.0, 12.0, 11.0, 10.5):
                hundredths = max(1, int(_text_w(txt, sz) * 100))
                lines = -(-hundredths // max(1, int(box_w * 100)))
                if lines <= 2:
                    return sz
            return 10.0

        pad = 0.35 if n_cols == 1 else 0.22
        vw_max = 2.0 if n_cols == 1 else (1.55 if n_cols == 2 else 1.25)
        for i, (rkey, r) in enumerate(items):
            # COLUMN-major packing (the old divmod(i, rows_per_col) put the
            # item INDEX remainder in x and marched half the ratios off the
            # slide's left edge once rows_per_col exceeded n_cols):
            # every ratio stays inside [0.6, 12.7] on every count.
            col = i // rows_per_col
            row = i % rows_per_col
            if lang == "ar":
                col = n_cols - 1 - col
            x = 0.6 + col * col_w
            y = top + row * row_h
            bg = PANEL if row % 2 == 0 else WHITE
            _box(s, "rect", Inches(x), Inches(y), Inches(col_w - 0.12),
                 Inches(row_h - 0.08), fill=bg, line=LINE, line_w=Pt(0.5))
            val = r.get("value")
            vcolor = RED if isinstance(val, (int, float)) and val < 0 else ACCENT
            unit = _unit(rkey)
            vw = min(vw_max, (col_w - pad - 0.2) * 0.42)
            lw = col_w - pad - vw - 0.2
            # the value's own digits may exceed vw at 3 columns («15034.60x») —
            # shrink-on-measure the same way the label does
            val_txt = (f"{round(val)}{unit}" if rkey in DAYS_KEYS
                       else f"{_fmt(val, 2)}{unit}")
            vsz = 16.5 if row_h >= 0.5 and col_w >= 5 else (
                14.0 if row_h >= 0.42 and col_w >= 4.5 else (
                    12.0 if row_h >= 0.4 else 10.5))
            while vw < _text_w(val_txt, vsz) and vsz > 9:
                vsz -= 0.5
            ls = min(_label_sz(r.get(lang) or r.get("en") or "", lw),
                     14.5 if row_h >= 0.5 else (12.5 if row_h >= 0.42 else 11))
            _add_text(s, Inches(x + pad), Inches(y + 0.03),
                      Inches(lw), Inches(row_h - 0.1),
                      r.get(lang) or r.get("en") or "", size=ls, color=INK, align=align)
            vx = (x + col_w - 0.12 - vw) if lang == "ar" else (x + pad)
            _add_text(s, Inches(vx), Inches(y + 0.02), Inches(vw), Inches(row_h - 0.1),
                      val_txt, size=vsz, color=vcolor, bold=True,
                      align=PP_ALIGN.LEFT if lang == "ar" else PP_ALIGN.RIGHT)

    # ---- benchmark comparison chart slide (columns vs reference anchors) ------
    if ratios:
        try:
            from .ratio_explain import _BENCHMARKS, _judge

            # Normalised alignment score per computable ratio: value ÷ anchor
            # (or anchor ÷ value for ceilings). 1.0 = exactly on benchmark;
            # > 1 = better than the anchor; < 1 = short of it.
            # Ceilings (anchor is a maximum — lower is better): debt levels,
            # collection/inventory/payment days, payables turnover and the
            # composite cycle. Floors (current ratio, coverage, DPO …) keep
            # value ÷ anchor.
            ceiling_ratios = {"debt_ratio", "debt_to_equity", "receivable_days",
                              "inventory_days", "payables_turnover",
                              "cash_conversion_cycle"}
            cats, mine, refs = [], [], []
            # every computed ratio with a reference anchor makes the chart —
            # PowerPoint spaces/rotates labels automatically
            for rkey in ratios.keys():
                if rkey not in _BENCHMARKS:
                    continue
                raw = _BENCHMARKS[rkey]["en"]
                import re as _re
                m = _re.search(r"(\d+(?:\.\d+)?)", raw)
                if not m:
                    continue
                anchor = float(m.group(1))
                val = ratios[rkey].get("value")
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    continue
                if val < 0:
                    continue  # margins/losses: axis is meaningless when negative
                norm = (anchor / val) if rkey in ceiling_ratios else (val / anchor)
                norm = max(0.0, min(norm, 2.0))
                label = ratios[rkey].get(lang) or ratios[rkey].get("en") or rkey
                cats.append(label)
                mine.append(round(norm, 2))
                refs.append(1.0)
            if len(cats) >= 2:
                s = _slide(prs)
                _bg(s, WHITE)
                _content_header(s, L.get("bench_chart_title") or "", lang, L, filename)
                chart_data = CategoryChartData()
                # RAW logical text: PowerPoint shapes and bidi-reorders
                # chart labels itself — pre-shaped text gets reversed a
                # second time (the «حروف مقطعة» chart bug)
                chart_data.categories = [str(c) for c in cats]
                chart_data.add_series(L.get("bench_ours") or "", mine)
                chart_data.add_series(L.get("bench_ref") or "", refs)
                gf = s.shapes.add_chart(
                    XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(1.25),
                    Inches(12.3), Inches(5.9), chart_data)
                chart = gf.chart
                chart.has_legend = True
                chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                chart.legend.include_in_layout = False
                chart.legend.font.size = Pt(12)
                _font_face(chart.legend.font, FONT_AR)
                # brand the two series: ours teal, reference amber
                ours = chart.plots[0].series[0]
                ours.format.fill.solid()
                ours.format.fill.fore_color.rgb = ACCENT
                ref = chart.plots[0].series[1]
                ref.format.fill.solid()
                ref.format.fill.fore_color.rgb = GOLD
                ref.format.line.color.rgb = WHITE
                # value labels on our series only
                ours.has_data_labels = True
                dl = ours.data_labels
                dl.show_value = True
                dl.number_format = "0.00"
                dl.number_format_is_linked = False
                dl.font.size = Pt(9)
                dl.font.bold = True
                try:
                    dl.position = XL_LABEL_POSITION.OUTSIDE_END
                except Exception:
                    pass
                va = chart.value_axis
                va.has_major_gridlines = True
                va.maximum_scale = 2.0
                va.minimum_scale = 0.0
                va.tick_labels.font.size = Pt(10)
                ca = chart.category_axis
                ca.tick_labels.font.size = Pt(9)
                _font_face(ca.tick_labels.font, FONT_AR)
                # footnote: the legend of the alignment rule (•/≈/×)
                _add_text(s, Inches(0.6), Inches(7.05), Inches(12.1),
                          Inches(0.35), L.get("bench_note") or "",
                          size=10, color=MUTED, align=align)
        except Exception:
            pass

    # ---- analytics dashboard slide (gauge / donut / composition) --------------
    try:
        from .dashboard_charts import (activity_lines, cost_stack,
                                       dashboard_payload, expense_donut,
                                       score_gauge, trend_line)

        dash = dashboard_payload(result, lang, score)
        has_gauge = dash.get("score") is not None
        has_donut = bool(dash.get("expenses")) and len(dash["expenses"]) >= 2
        stack_bytes = None
        if dash.get("cost_parts") and len(dash["cost_parts"]) >= 2:
            stack_bytes = cost_stack(dash["cost_parts"], L.get("dash_cost") or "")
        # working-capital heartbeat: collection period + inventory turnover
        # (and DPO/CCC when supported) — compute_activity_series values,
        # the same data the Excel activity chart draws
        from .analyzer import compute_activity_series
        act_bytes = activity_lines(
            compute_activity_series(result.get("metrics") or {}),
            title=L.get("activity_title") or "",
            labels=dash.get("period_labels"))
        if has_gauge or has_donut or stack_bytes or dash.get("trends"):
            s = _slide(prs)
            _bg(s, WHITE)
            _content_header(s, L.get("dash_title") or "", lang, L, filename)

            def _png_size(b: bytes) -> tuple[float, float]:
                import struct
                w, h = struct.unpack(">II", b[16:24])
                return float(w), float(h)

            def _place(b: bytes, x_in: float, y_in: float, w_in: float) -> None:
                pw, ph = _png_size(b)
                s.shapes.add_picture(io.BytesIO(b), Inches(x_in), Inches(y_in),
                                     width=Inches(w_in),
                                     height=Inches(w_in * ph / pw))

            # row 1: score gauge + expense-mix donut (RTL mirrors the x order)
            y1 = 1.25
            if has_gauge and has_donut:
                g = score_gauge(dash["score"], dash.get("grade_label") or "")
                d = expense_donut(dash["expenses"],
                                  center_label=L.get("dash_expenses_center") or "",
                                  title=L.get("dash_expenses") or "")
                if lang == "ar":
                    if g:
                        _place(g, SLIDE_W.inches - 0.6 - 3.5, y1, 3.5)
                    if d:
                        _place(d, SLIDE_W.inches - 0.6 - 3.5 - 0.15 - 5.1, y1 - 0.1, 5.1)
                else:
                    if g:
                        _place(g, 0.6, y1, 3.5)
                    if d:
                        _place(d, 0.6 + 3.5 + 0.15, y1 - 0.1, 5.1)
            elif has_gauge or has_donut:
                b = (score_gauge(dash["score"], dash.get("grade_label") or "")
                     if has_gauge else
                     expense_donut(dash["expenses"],
                                   center_label=L.get("dash_expenses_center") or "",
                                   title=L.get("dash_expenses") or ""))
                if b:
                    x = (SLIDE_W.inches - 0.6 - 5.1) if lang == "ar" else 0.6
                    _place(b, x, y1, 5.1)

            # row 2: revenue composition bar, or a labelled trend when no
            # composition is computable (the trends slide already carries lines)
            y2 = 4.05
            if stack_bytes:
                x = (SLIDE_W.inches - 0.6 - 11.9) if lang == "ar" else 0.6
                _place(stack_bytes, x, y2, 11.9)
            elif dash.get("trends"):
                t = dash["trends"][0]
                tb = trend_line(t["values"], labels=dash.get("period_labels"),
                                title=t["label"])
                if tb:
                    x = (SLIDE_W.inches - 0.6 - 9.2) if lang == "ar" else 0.6
                    _place(tb, x, y2 - 0.15, 9.2)

            # row 3: the working-capital heartbeat (DSO & inventory turnover
            # lines) when the analysis supports it
            if act_bytes:
                x = (SLIDE_W.inches - 0.6 - 11.9) if lang == "ar" else 0.6
                _place(act_bytes, x, 5.55, 11.9)
    except Exception:
        pass

    # ---- ratio insights slide (CMRRS cards — COMPACT: fit more than 4) --------
    if ratio_insights:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["ratio_insights"], lang, L, filename)
        # EVERY insight card the platform shows — the [:7] slice was dropping
        # cards with no slide overflow, making the deck thinner than the site
        top = 1.4
        bottom_limit = 7.15
        cards = list(ratio_insights)
        rows_h = min(1.28, (bottom_limit - top) / max(len(cards), 1))
        compact = rows_h < 0.95  # drop the «what» line when rows get tight
        # the deck splits ALL cards gracefully: a dense list reflows into
        # two balanced columns instead of shrinking to unreadable rows
        n_cols = 2 if rows_h < 0.62 else 1
        if n_cols == 2:
            # rebalance: better rows over two columns
            half = -(-len(cards) // 2)
            cards = [cards[:half], cards[half:]]
            rows_h = min(1.28, (bottom_limit - top) / max(half, 1))
        else:
            cards = [cards]
        compact = rows_h < 0.95
        for ci, col_cards in enumerate(cards):
            col_w = 12.1 / len(cards)
            x0 = 0.6 + ((len(cards) - 1 - ci) * col_w if lang == "ar" else ci * col_w)
            for i, card in enumerate(col_cards):
              y = top + i * rows_h
              color = {"good": GREEN, "bad": RED}.get(card.get("verdict"), ACCENT)
              bg = PANEL if i % 2 == 0 else WHITE
              bar = _box(s, "round", Inches(x0), Inches(y), Inches(col_w - 0.12),
                         Inches(rows_h - 0.1), fill=bg, line=LINE, line_w=Pt(0.5))
              bar.adjustments[0] = 0.12
              # Label and value in SEPARATE boxes so the number + unit never
              # drifts away from the label in RTL rendering.
              head_unit = "%" if card.get("is_percent") else (
                  (" يوم" if lang == "ar" else " days") if card.get("is_days") else "x")
              head_dec = 0 if card.get("is_days") else 2
              name_sz = 15 if rows_h >= 1.0 else (13 if rows_h >= 0.8 else 11.5)
              body_sz = 11 if rows_h >= 1.0 else 9.5
              lw = (col_w - 0.5) * 0.8
              vw = (col_w - 0.5) * 0.2
              _add_text(s, Inches(x0 + 0.25), Inches(y + 0.04), Inches(lw),
                        Inches(rows_h * 0.4),
                        card.get("label", ""), size=name_sz, color=color, bold=True, align=align)
              _add_text(s, Inches(x0 + 0.25 + lw) if lang == "ar" else Inches(x0 + 0.25),
                        Inches(y + 0.04), Inches(vw), Inches(rows_h * 0.4),
                        f"{card.get('value', 0):,.{head_dec}f}{head_unit}",
                        size=name_sz, color=color, bold=True,
                        align=PP_ALIGN.LEFT if lang == "ar" else PP_ALIGN.RIGHT)
              _add_text(s, Inches(x0 + 0.25), Inches(y + rows_h * 0.42), Inches(col_w - 0.5),
                        Inches(rows_h * 0.32),
                        f"{L['what_q']} {card.get('what', '')}", size=body_sz, color=INK, align=align)
              if not compact:
                  _add_text(s, Inches(x0 + 0.25), Inches(y + rows_h * 0.72), Inches(col_w - 0.5),
                            Inches(rows_h * 0.28),
                            f"{L['opinion_q']} {card.get('opinion', '')}", size=body_sz,
                            color=INK, align=align)

    # ---- yearly comparison slide (horizontal + vertical) ------------------------
    if yearly_comparison and yearly_comparison.get("rows"):
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["comparison"], lang, L, filename)
        cols = yearly_comparison["columns"]
        # colour legend — mirrors the platform's «دليل الألوان»; the direction
        # markers are REAL vector shapes beside their words (see _dir_marker)
        _marker_legend(s, Inches(0.6), Inches(1.02), Inches(12.1), lang, L)
        # rows grouped per statement with a full-width closing band — NOT
        # one mixed list: قائمة الدخل block, then قائمة المركز المالي block.
        # EVERY row renders (no truncation) — the platform shows all of them.
        stmt_titles = {"income": L["is_title"], "balance": L["bs_title"]}
        display = []   # ("band", title) | ("row", row)
        current_stmt = None
        for rw in yearly_comparison["rows"]:
            stmt = rw.get("stmt") or "income"
            if stmt != current_stmt:
                current_stmt = stmt
                display.append(("band", stmt_titles.get(stmt, "")))
            display.append(("row", rw))
        rows_n = len(display) + 1
        col_n = len(cols)
        table = s.shapes.add_table(rows_n, col_n, Inches(0.4), Inches(1.38),
                                   Inches(12.5), Inches(0.45) * rows_n).table
        # column widths MUST be ints (python-pptx XSD rejects floats with
        # TypeError) and must sum EXACTLY to the table width — integer
        # division per column with the remainder parked on the last column
        total_w = int(Inches(12.5))
        per_col = total_w // col_n
        widths = [per_col] * (col_n - 1) + [total_w - per_col * (col_n - 1)]
        for c in range(col_n):
            table.columns[c].width = widths[c]
        headers = list(cols)
        if lang == "ar":
            headers = list(reversed(headers))
        # absolute cell geometry for the direction-marker overlays
        tbl_x, tbl_y = Inches(0.4), Inches(1.38)
        row_off = [0]
        for _k in range(rows_n):
            row_off.append(row_off[-1] + int(table.rows[_k].height))

        def _tcell(cell, text, size=11.5, color=INK, bold=False, fill=None):
            cell.fill.solid()
            cell.fill.fore_color.rgb = fill or WHITE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = align
            run = p.add_run()
            run.text = _shape(str(text))
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
            _apply_font(run)

        def _blend(base: tuple, t: float, a0: float = 0.06, a1: float = 0.36) -> RGBColor:
            """Platform heatmap as a solid fill: alpha-over-white blend of the
            verdict colour, intensity t in [0,1]."""
            t = max(0.0, min(t, 1.0))
            a = a0 + (a1 - a0) * t
            return RGBColor(*(round(255 + (b - 255) * a) for b in base))

        for c, htxt in enumerate(headers):
            _tcell(table.cell(0, c), htxt, size=11.5, color=WHITE, bold=True, fill=NAVY)
        ri = 1
        n_data = 0
        for kind, r in display:
            if kind == "band":
                # closing band: statement title on ACCENT azure across the row
                for c in range(col_n):
                    _tcell(table.cell(ri, c), r if c == 0 else "",
                           size=12, color=WHITE, bold=True, fill=ACCENT)
                ri += 1
                continue
            i = ri
            verdict_color = {"good": GREEN, "bad": RED}.get(r.get("color"), INK)
            values = [r["label"], r["curr"], r["prev"], r["change"],
                      r["change_pct"], r["pct_curr"], r["pct_prev"]]
            vcolors = [INK, INK, MUTED, verdict_color, verdict_color, INK, MUTED]
            # heatmap fills — the platform's intensity rule: change columns
            # blend green/red by |change %| (full at ±25%), the vertical share
            # column blends neutral teal by its size (full at 100%)
            chg_t = min(abs(r.get("change_pct_val") or 0.0) / 25.0, 1.0)
            heat_base = (220, 38, 38) if r.get("color") == "bad" else (5, 150, 105)
            fills = [None, None, None,
                     _blend(heat_base, chg_t),
                     _blend(heat_base, chg_t),
                     _blend((15, 118, 110),
                            min(abs(r.get("pct_curr_val") or 0.0) / 100.0, 1.0),
                            0.03, 0.17),
                     None]
            if lang == "ar":
                values = list(reversed(values))
                vcolors = list(reversed(vcolors))
                fills = list(reversed(fills))
            n_data += 1
            stripe = PANEL if n_data % 2 == 1 else WHITE
            label_col = (col_n - 1) if lang == "ar" else 0
            for c, (v, cc) in enumerate(zip(values, vcolors)):
                if c == label_col:
                    # direction marker drawn as a REAL vector shape over the
                    # cell's leading margin (majalla carries no geometric
                    # arrow glyphs; the verdict colour carries the judgment)
                    # + the bold label — font-independent affordance
                    cell = table.cell(i, c)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = stripe
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                    tf = cell.text_frame
                    tf.word_wrap = True
                    p = tf.paragraphs[0]
                    p.alignment = align
                    pct_v = r.get("change_pct_val") or 0.0
                    if abs(pct_v) < 0.05:
                        direction, arrow_col = "flat", MUTED
                    else:
                        direction = "up" if pct_v > 0 else "down"
                        arrow_col = GREEN if r.get("color") == "good" else RED
                    msize = Inches(0.115)
                    m_y = tbl_y + row_off[i] + (row_off[i + 1] - row_off[i] - msize) // 2
                    if lang == "ar":
                        cell.margin_right = Inches(0.28)
                        c_edge = tbl_x + sum(widths[: c + 1])
                        _dir_marker(s, c_edge - Inches(0.055) - msize, m_y,
                                    direction, arrow_col)
                    else:
                        cell.margin_left = Inches(0.28)
                        c_edge = tbl_x + sum(widths[:c])
                        _dir_marker(s, c_edge + Inches(0.055), m_y,
                                    direction, arrow_col)
                    l_run = p.add_run()
                    l_run.text = _shape(str(v))
                    l_run.font.size = Pt(11.5)
                    l_run.font.bold = True
                    l_run.font.color.rgb = INK
                    _apply_font(l_run)
                    continue
                _tcell(table.cell(i, c), v, size=11.5, color=cc,
                       fill=fills[c] or stripe)
            ri += 1
        # methodology note under the table — same wording as the platform
        if yearly_comparison.get("note"):
            _add_text(s, Inches(0.6), Inches(6.6), Inches(12.1), Inches(0.4),
                      str(yearly_comparison["note"]), size=8.5, color=MUTED, align=align)

    # ---- annual growth slide (SAME data as the PDF report's growth table) ------
    # source of truth: yearly_comparison["years"] + rows[].points — the exact
    # payload the PDF's «مقارنة النمو السنوي» table renders: each item as a
    # per-year card row (value on top, YoY % below it coloured by the same
    # judgment rule: up good for non-costs, down good for costs). A python-
    # pptx TABLE can't span multiple cards per row, so each item is its own
    # one-row table on the slide, stacked like the statements slide — and
    # rows paginate onto continuation slides (7.5in of slide height bound).
    years = (yearly_comparison or {}).get("years") or []
    growth_rows = [r for r in ((yearly_comparison or {}).get("rows") or [])
                   if r.get("points")]
    if len(years) >= 3 and len(growth_rows) >= 2:
        growth_title = str((yearly_comparison or {}).get("growth_title")
                           or L["yc_growth"])
        cont_suffix = " (تابع)" if lang == "ar" else " (cont.)"
        top, card_h, row_step = 1.42, 0.62, 0.82
        # a year-header band precedes the card rows (PDF parity) — reserve
        # its height when computing the per-page row budget
        head_h = 0.50
        rows_per_slide = int((7.5 - top - head_h - 0.55) // row_step)  # note room below
        pages = [growth_rows[i:i + rows_per_slide]
                 for i in range(0, len(growth_rows), rows_per_slide)]
        n_years = len(years)
        fc_label = str((yearly_comparison or {}).get("forecast_label") or "")
        fc_note = str((yearly_comparison or {}).get("growth_note") or "")
        cells_n = 1 + n_years + (1 if fc_label else 0)
        total_w = int(Inches(12.5))
        per_col = total_w // cells_n
        widths = [per_col] * (cells_n - 1) + [total_w - per_col * (cells_n - 1)]

        def _gcell(cell, text, size=11.5, color=INK, bold=False, fill=WHITE):
            cell.fill.solid()
            cell.fill.fore_color.rgb = fill
            tf = cell.text_frame
            tf.word_wrap = True
            par = tf.paragraphs[0]
            par.alignment = align
            run = par.add_run()
            run.text = _shape(str(text))
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
            _apply_font(run)

        for pi, page_rows in enumerate(pages):
            s = _slide(prs)
            _bg(s, WHITE)
            _content_header(s, growth_title + (cont_suffix if pi else ""),
                            lang, L, filename)
            # year-header band — the PDF growth table's header row
            # (البند + one cell per year + forecast label) on EVERY page,
            # navy-filled like the comparison slide's header row
            head_cells = [str((yearly_comparison or {}).get("columns", [""])[0])] \
                + [str(y) for y in years]
            if fc_label:
                head_cells.append(fc_label)
            if lang == "ar":
                head_cells = list(reversed(head_cells))
            htbl = s.shapes.add_table(
                1, cells_n, Inches(0.4), Inches(top), Inches(12.5),
                Inches(0.38)).table
            for c in range(cells_n):
                htbl.columns[c].width = widths[c]
            for c, htxt in enumerate(head_cells):
                _gcell(htbl.cell(0, c), htxt, size=10.5, color=WHITE,
                       bold=True, fill=NAVY)
            for ri, r in enumerate(page_rows):
                y = Inches(top + head_h + ri * row_step)
                pts = r.get("points") or []
                # concept absent from early years: pad the LEADING slots
                # empty (same rule as the PDF table)
                pad = n_years - len(pts)
                table = s.shapes.add_table(
                    1, cells_n, Inches(0.4), y, Inches(12.5), Inches(card_h)
                ).table
                for c in range(cells_n):
                    table.columns[c].width = widths[c]

                stripe = PANEL if ri % 2 == 0 else WHITE
                # label cell — bold, striped, like the comparison slide's label
                _gcell(table.cell(0, 0), r["label"], size=11.5, color=INK,
                       bold=True, fill=stripe)
                for k in range(n_years):
                    cell = table.cell(0, k + 1)
                    if k < pad:
                        _gcell(cell, "", fill=stripe)
                        continue
                    pt = pts[k - pad]
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = WHITE
                    tf = cell.text_frame
                    tf.word_wrap = True
                    v_par = tf.paragraphs[0]
                    v_par.alignment = PP_ALIGN.CENTER
                    v_run = v_par.add_run()
                    v_run.text = _shape(str(pt["value"]))
                    v_run.font.size = Pt(11)
                    v_run.font.color.rgb = INK
                    _apply_font(v_run)
                    g = pt.get("growth")
                    if g:
                        # direction vs the PRIOR year decides the judgement
                        # colour — the PDF growth table's exact rule
                        prev_raw = pts[k - pad - 1]["raw"] if k - pad > 0 else None
                        if prev_raw:
                            rose = pt["raw"] > prev_raw
                            is_good = (not rose) if r.get("is_cost") else rose
                            g_col = GREEN if is_good else RED
                        else:
                            g_col = MUTED
                        g_par = tf.add_paragraph()
                        g_par.alignment = PP_ALIGN.CENTER
                        g_run = g_par.add_run()
                        g_run.text = _shape(str(g))
                        g_run.font.size = Pt(8.5)
                        g_run.font.color.rgb = g_col
                        _apply_font(g_run)
                if fc_label:
                    # next-year forecast column (mean historical growth) —
                    # amber fill + amber growth line = clearly an estimate
                    cell = table.cell(0, n_years + 1)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor(0xFE, 0xF3, 0xC7)
                    tf = cell.text_frame
                    tf.word_wrap = True
                    fc = r.get("forecast")
                    f_par = tf.paragraphs[0]
                    f_par.alignment = PP_ALIGN.CENTER
                    if fc:
                        v_run = f_par.add_run()
                        v_run.text = _shape(str(fc["value"]))
                        v_run.font.size = Pt(11)
                        v_run.font.color.rgb = INK
                        _apply_font(v_run)
                        g_par = tf.add_paragraph()
                        g_par.alignment = PP_ALIGN.CENTER
                        g_run = g_par.add_run()
                        g_run.text = _shape(str(fc["growth"]))
                        g_run.font.size = Pt(8.5)
                        g_run.font.color.rgb = ORANGE
                        _apply_font(g_run)
                    else:
                        d_run = f_par.add_run()
                        d_run.text = _shape("—")
                        d_run.font.size = Pt(11)
                        d_run.font.color.rgb = MUTED
                        _apply_font(d_run)
            # the deck's colour legend with REAL direction markers, verbatim
            # from the comparison slide — the forecast column adds its note
            note_y = Inches(top + len(page_rows) * row_step + 0.02)
            fc_extra = ""
            if fc_note:
                fc_extra = ((fc_label + ": ") if fc_label else "") + fc_note
            _marker_legend(s, Inches(0.6), note_y, Inches(12.1), lang, L,
                           size_pt=8.5, extra=fc_extra)    # ---- revenue & net-profit evolution slide (ALL years) ----------------------
    # The two bottom-line series EVERY deck must show, charted across every
    # captured year: revenue from the stored metrics, net profit via the
    # SAME IFRS 18 derivation as the growth table (net_profit_series). The
    # x axis carries the analysis's period labels; the trends slide below
    # skips these two so revenue never renders twice.
    result_metrics = result.get("metrics") or {}
    plabels = [str(x) for x in (result.get("period_labels") or [])]
    projections_map = {p["concept"]: p
                       for p in (advisor or {}).get("projections") or []}
    from .ratio_explain import net_profit_series

    evo: list[tuple[str, str, list]] = []
    rev_vals = [float(v) for v in (result_metrics.get("revenue") or [])]
    if len(rev_vals) >= 2:
        evo.append(("revenue", L["evo_revenue"], rev_vals))
    net_vals = [float(v) for v in net_profit_series(result)]
    if len(net_vals) >= 2:
        evo.append(("net_profit", L["evo_net"], net_vals))
    if evo:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["evo_title"], lang, L, filename)
        for idx, (concept, title, vals) in enumerate(evo[:2]):
            proj = projections_map.get(concept)
            img_bytes = _chart_image(
                vals,
                proj.get("projections") if proj else None,
                title,
                labels=plabels or None,
            )
            if img_bytes:
                s.shapes.add_picture(io.BytesIO(img_bytes), Inches(1.87),
                                     Inches(1.3 + idx * 2.9), width=Inches(9.6))

    # ---- trends ---------------------------------------------------------------
    series = result.get("series") or {}
    if series:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["trends"], lang, L, filename)
        skip = {c for c, _, _ in evo}
        others = [(c, se) for c, se in series.items() if c not in skip]
        n = min(len(others), 3)
        for idx, (concept, se) in enumerate(others[:n]):
            img_bytes = _chart_image(
                se.get("values") or [],
                (projections_map.get(concept) or {}).get("projections"),
                str(se.get(lang) or se.get("en") or ""),
                labels=plabels or None,
            )
            if img_bytes:
                y = Inches(1.25 + idx * 1.95)
                s.shapes.add_picture(io.BytesIO(img_bytes), Inches(2.3), y, width=Inches(8.7))

    # ---- score + scenarios ------------------------------------------------------
    if score and score.get("score") is not None:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["score_title"], lang, L, filename)
        grade = score.get("grade") or {}
        grade_color = {
            "#10b981": GREEN, "#22c55e": GREEN, "#f59e0b": GOLD,
            "#f97316": ORANGE, "#ef4444": RED,
        }.get(grade.get("color", ""), ACCENT)

        # score ring (oval with thick border)
        cx, cy, d = Inches(1.0), Inches(1.7), Inches(2.3)
        ring = _box(s, "oval", cx, cy, d, d, fill=WHITE, line=grade_color, line_w=Pt(10))
        _add_text(s, cx, cy + Inches(0.55), d, Inches(0.8),
                  f"{score['score']:.0f}", size=44, color=grade_color, bold=True,
                  align=PP_ALIGN.CENTER)
        _add_text(s, cx, cy + d + Inches(0.1), d, Inches(0.45),
                  grade.get(lang) or grade.get("en") or "", size=17,
                  color=grade_color, bold=True, align=PP_ALIGN.CENTER)

        # dimension bars on the right of the ring
        dims = score.get("dimensions") or []
        bar_x = Inches(3.7)
        bar_y = Inches(1.8)
        for i, dim in enumerate(dims[:4]):
            y = bar_y + i * Inches(0.75)
            _add_text(s, bar_x, y, Inches(3.0), Inches(0.4),
                      dim.get(lang) or dim.get("en") or dim.get("key", ""),
                      size=14, color=INK, bold=True, align=align)
            track_w = Inches(5.0)
            _box(s, "round", bar_x + Inches(3.1), y + Inches(0.08), track_w, Inches(0.26),
                 fill=RGBColor(0xE5, 0xE7, 0xEB))
            pct = max(0.0, min(1.0, dim["points"] / dim["weight"])) if dim["weight"] else 0
            _box(s, "round", bar_x + Inches(3.1), y + Inches(0.08),
                 Emu(int(track_w * pct)), Inches(0.26), fill=ACCENT)
            _add_text(s, bar_x + Inches(8.2), y, Inches(1.2), Inches(0.4),
                      f"{dim['points']:.0f}/{dim['weight']}", size=12.5,
                      color=MUTED, align=PP_ALIGN.LEFT)

        # scenario cards
        if scenarios and scenarios.get("scenarios"):
            _add_text(s, Inches(0.6), Inches(4.95), Inches(12.1), Inches(0.4),
                      L["scenarios"], size=17, color=ACCENT, bold=True, align=align)
            sc_bg = {"optimistic": (OPT_BG, GREEN), "realistic": (REAL_BG, ACCENT),
                     "conservative": (CONS_BG, ORANGE)}
            for i, sc in enumerate(scenarios["scenarios"][:3]):
                bg, accent = sc_bg.get(sc["key"], (PANEL, ACCENT))
                x = Inches(0.6 + i * 4.15)
                if lang == "ar":
                    x = SLIDE_W - Inches(0.6 + (i + 1) * 4.15 - 0.25)
                y = Inches(5.45)
                card = _box(s, "round", x, y, Inches(3.9), Inches(1.5),
                            fill=bg, line=LINE, line_w=Pt(0.75))
                card.adjustments[0] = 0.08
                _add_text(s, x + Inches(0.18), y + Inches(0.05), Inches(3.5), Inches(0.35),
                          sc.get(lang) or sc.get("en"), size=14, bold=True,
                          color=accent, align=align)
                _add_text(s, x + Inches(0.18), y + Inches(0.4), Inches(3.5), Inches(0.3),
                          f"{sc['growth_pct']:+.1f}% {L['growth']}", size=11.5,
                          color=MUTED, align=align)
                _add_text(s, x + Inches(0.18), y + Inches(0.68), Inches(3.5), Inches(0.35),
                          f"{L['next_rev']}: {_fmt(sc['revenue'])}", size=12,
                          color=INK, align=align)
                _add_text(s, x + Inches(0.18), y + Inches(1.02), Inches(3.5), Inches(0.35),
                          f"{L['next_net']}: {_fmt(sc['net'])}", size=12,
                          color=RED if sc["net"] < 0 else GREEN, bold=True, align=align)

    # ---- forecast table --------------------------------------------------------
    projections = (advisor or {}).get("projections") or []
    if projections:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["forecast"], lang, L, filename)
        rows_n = min(len(projections), 8)
        table = s.shapes.add_table(rows_n + 1, 4, Inches(0.6), Inches(1.5),
                                   Inches(12.1), Inches(0.62) * (rows_n + 1)).table
        # column widths: item, current, projected, change — ints summing to
        # the table width (float widths raise TypeError in python-pptx)
        widths = [Inches(4.3), Inches(2.8), Inches(3.4), Inches(1.6)]
        widths = [int(w) for w in widths]
        widths[-1] += int(Inches(12.1)) - sum(widths)
        if lang == "ar":
            widths = list(reversed(widths))
        for i, w in enumerate(widths):
            table.columns[i].width = w
        headers = [L["item_col"], L["current_col"], L["projected_col"],
                   L["delta_col"]]
        if lang == "ar":
            headers = list(reversed(headers))

        def _cell_style(cell, text, size=13, color=INK, bold=False,
                        fill=None, align_=None):
            cell.fill.solid()
            cell.fill.fore_color.rgb = fill or WHITE
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.08)
            cell.vertical_anchor = None
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = align_ or align
            run = p.add_run()
            run.text = _shape(str(text))
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
            _apply_font(run)

        for c, htxt in enumerate(headers):
            _cell_style(table.cell(0, c), htxt, size=13.5, color=WHITE,
                        bold=True, fill=NAVY)
        for i, p in enumerate(projections[:rows_n], start=1):
            last = p["projections"][-1] if p["projections"] else None
            trend_color = GREEN if p["trend"] == "up" else RED if p["trend"] == "down" else MUTED
            proj_txt = " → ".join(_fmt(x["value"]) for x in p["projections"])
            values = [
                p.get(lang) or p.get("en") or "",
                _fmt(p["values"][-1]),
                proj_txt,
                f"{last['change_pct']:+.1f}%" if last else "",
            ]
            if lang == "ar":
                values = list(reversed(values))
            colors_row = [INK, INK, INK, trend_color]
            if lang == "ar":
                colors_row = list(reversed(colors_row))
            fill = PANEL if i % 2 == 1 else WHITE
            for c, (v, ccol) in enumerate(zip(values, colors_row)):
                _cell_style(table.cell(i, c), v, size=12.5, color=ccol,
                            bold=(c == (0 if lang != "ar" else 3)), fill=fill)

    # ---- recommendations slide -------------------------------------------------
    advice = (advisor or {}).get("advice") or []
    if advice or (advisor or {}).get("headline"):
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["advice"], lang, L, filename)
        y = Inches(1.35)
        if (advisor or {}).get("headline"):
            _add_text(s, Inches(0.6), y, Inches(12.1), Inches(0.45),
                      advisor["headline"], size=16, color=TITLE, bold=True, align=align)
            y += Inches(0.6)
        sev_word = {"critical": L["critical"], "warning": L["warning"], "info": L["info"]}
        for a in advice[:8]:
            sev = a.get("severity", "info")
            bg = {"critical": RGBColor(0xFD, 0xEC, 0xEC),
                  "warning": RGBColor(0xFE, 0xF3, 0xC7),
                  "info": OPT_BG}.get(sev, WHITE)
            txt_color = {"critical": RED, "warning": RGBColor(0xB4, 0x53, 0x09),
                         "info": GREEN}.get(sev, INK)
            bar = _box(s, "round", Inches(0.6), y, Inches(12.1), Inches(0.58),
                       fill=bg)
            bar.adjustments[0] = 0.16
            _add_text(s, Inches(0.85), y + Inches(0.07), Inches(11.6), Inches(0.45),
                      f"[{sev_word.get(sev, '')}] {a.get(lang) or a.get('ar') or ''}",
                      size=13.5, color=txt_color, align=align)
            y += Inches(0.66)
        if not advice:
            _add_text(s, Inches(0.6), y, Inches(12.1), Inches(0.5),
                      L["no_issues"], size=14, color=MUTED, align=align)

    # ---- statements slides --------------------------------------------------------
    if statements:
        def _stmt_slide(title: str, sections: list[tuple[str, list[dict]]]) -> None:
            s = _slide(prs)
            _bg(s, WHITE)
            _content_header(s, f"{L['statements']} — {title}", lang, L, filename)
            x0 = Inches(0.6)
            avail = Inches(12.1)
            col_w = Emu(int(avail / max(1, len(sections)))) - Inches(0.3)
            for c, (sec_title, lines) in enumerate(sections):
                x = x0 + c * (col_w + Inches(0.3))
                if lang == "ar":
                    x = SLIDE_W - x0 - col_w - c * (col_w + Inches(0.3))
                if sec_title:
                    _add_text(s, x, Inches(1.2), col_w, Inches(0.4), sec_title,
                              size=16, color=ACCENT, bold=True, align=align)
                y = Inches(1.7)
                for ln in lines[:17]:
                    name = ln.get(lang) or ln.get("en") or ""
                    bold = bool(ln.get("bold"))
                    amount = ln.get("amount", 0)
                    row_bg = PANEL if bold else WHITE
                    _box(s, "rect", x, y, col_w, Inches(0.4),
                         fill=row_bg, line=LINE, line_w=Pt(0.4))
                    _add_text(s, x + Inches(0.12), y + Inches(0.015), col_w * 0.6,
                              Inches(0.36), name, size=12, bold=bold, color=INK, align=align)
                    _add_text(s, x + col_w * 0.62, y + Inches(0.015), col_w * 0.34,
                              Inches(0.36), _fmt(abs(amount)),
                              size=12, bold=bold,
                              color=RED if amount < 0 else TITLE,
                              align=PP_ALIGN.LEFT if lang == "ar" else PP_ALIGN.RIGHT)
                    y += Inches(0.44)

        isx = statements.get("income_statement") or {}
        if isx.get("lines"):
            _stmt_slide(L["is_title"], [("", isx["lines"])])
        bs = statements.get("balance_sheet") or {}
        if bs.get("assets", {}).get("lines"):
            _stmt_slide(L["bs_title"], [
                ("الأصول" if lang == "ar" else "Assets", bs["assets"]["lines"]),
                ("الالتزامات وحقوق الملكية" if lang == "ar" else "Liabilities & Equity",
                 bs["liabilities_equity"]["lines"]),
            ])
        cf = statements.get("cash_flow") or {}
        if cf.get("operating"):
            cf_lines = []
            # «other» = the file's own FX/other-effects block when stated
            for key in ("operating", "investing", "financing", "other"):
                act = cf.get(key) or {}
                cf_lines.extend(act.get("lines") or [])
            # close the walk like the UI and the PDF do
            nc = cf.get("net_change_label") or {}
            if cf.get("net_change") is not None:
                cf_lines.append({
                    "ar": nc.get("ar") or "صافي التغير في النقدية",
                    "en": nc.get("en") or "Net change in cash",
                    "amount": cf["net_change"],
                    "bold": True,
                })
            if cf.get("cash_balance") is not None:
                cf_lines.append({
                    "ar": "النقدية في نهاية الفترة",
                    "en": "Cash at end of period",
                    "amount": cf["cash_balance"],
                })
            _stmt_slide(L["cf_title"], [("", cf_lines)])
        eq = statements.get("equity_statement") or {}
        if eq.get("lines"):
            _stmt_slide(L["eq_title"], [("", eq["lines"])])

    # ---- notes ---------------------------------------------------------------
    # ONLY the user's free-text notes — a notes-less analysis gets NO notes
    # slide (the platform does not show one either), never rendered IFRS
    # metadata dressed as user notes.
    if notes and str(notes).strip():
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["notes"], lang, L, filename)
        _add_text(s, Inches(0.8), Inches(1.4), Inches(11.7), Inches(5.0),
                  str(notes), size=15, color=INK, align=align)

    prs.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# Sales-operations deck (kind == "sales" analyses — the sales dashboard)
# ---------------------------------------------------------------------------

from .sales_analyzer import slowdown_alert


def _sales_labels(lang: str) -> dict:
    if lang == "ar":
        return {
            "deck_title": "عرض تحليل المبيعات",
            "sub": "شبكة عمليات مبيعات (مناطق · مناديب · أشهر)",
            "kpis": "المؤشرات الرئيسية",
            "kpi1": "إجمالي المبيعات", "kpi2": "عدد العمليات",
            "kpi3": "متوسط العملية", "kpi4": "عملاء جدد",
            "unit": "ريال",
            "trend": "الاتجاه الشهري للمبيعات",
            "txn_new": "العمليات والعملاء الجدد شهريًا",
            "peak": "الذروة", "low": "الأدنى",
            "regions": "تحليل المناطق",
            "col_region": "المنطقة", "col_sales": "المبيعات",
            "col_share": "النصيب", "col_txn": "العمليات",
            "col_avg": "متوسط العملية", "col_growth": "النمو",
            "col_best": "أفضل مندوب",
            "reps": "ترتيب المندوبين",
            "col_rep": "المندوب", "col_rank": "#", "col_nc": "عملاء جدد",
            "products": "الأصناف الأكثر مبيعًا", "col_product": "الصنف",
            "col_top_month": "أفضل شهر",
            "products_note": "{n} صنفًا — مرتبة بالمبيعات",
            "compare": "مقارنة الفترات — أول 3 أشهر ضد آخر 3 أشهر",
            "cmp_metric": "المؤشر", "cmp_a": "الفترة الأولى", "cmp_b": "الفترة الأخيرة",
            "cmp_change": "التغير",
            "lbl_sales": "المبيعات", "lbl_txn": "العمليات",
            "lbl_avg": "متوسط العملية", "lbl_newc": "عملاء جدد",
            "forecast": "التنبؤ بالشهر القادم",
            "forecast_method": "تنبؤ خطي مرجّح على آخر الأشهر (+2% زخم)",
            "recs": "التوصيات", "strengths": "نقاط القوة", "weaknesses": "نقاط الضعف",
            "target_note": "ملاحظة الأهداف", "notes": "ملاحظات",
            "sd_title": "تنبيه التباطؤ وتشخيص المسبب الأرجح",
            "sd_main_neg": "تنبيه تباطؤ: النمو انخفض {n} أشهر متتالية — آخر شهر سالب ({to}%). تحقق من المسببات قبل نهاية الشهر الحالي.",
            "sd_main": "تنبيه تباطؤ: النمو الآني تراجع {n} أشهر متتالية ({frm}% → {to}%). الاتجاه يحتاج تدخلًا قبل أن يصبح سالبًا.",
            "sd_diag_label": "التشخيص الأكثر ترجيحًا:",
            "sd_region": "منطقة", "sd_rep": "المندوب",
            "sd_diag": "{label} {kind} {name} — نموه الشهري تراجع من {frm}% إلى {to}% (أشدّ تراجع بين {n} كيانًا نشطًا عبر {w0} → {w1}). المحرّك الأكبر: {lever} ({drop}%). راجع حساباته/حملاته أولًا هذا الشهر.",
            "sd_diag_none": "لا توجد منطقة أو مندوب واحد مسؤول واضح — الانخفاض موزّع، راجع العوامل العامة (الموسمية، الأسعار، الحملات).",
            "lever_txns": "عدد العمليات", "lever_ticket": "متوسط قيمة العملية",
            "sd_threshold": "العتبة: {n} أشهر متتالية",
        }
    return {
        "deck_title": "Sales Analysis Deck",
        "sub": "Sales operations grid (regions · reps · months)",
        "kpis": "Key Indicators",
        "kpi1": "Total sales", "kpi2": "Transactions",
        "kpi3": "Avg. ticket", "kpi4": "New customers",
        "unit": "SAR",
        "trend": "Monthly sales trend",
        "txn_new": "Transactions & new customers",
        "peak": "Peak", "low": "Low",
        "regions": "Regions",
        "col_region": "Region", "col_sales": "Sales", "col_share": "Share",
        "col_txn": "Txns", "col_avg": "Avg", "col_growth": "Growth",
        "col_best": "Best rep",
        "reps": "Sales representatives",
        "col_rep": "Rep", "col_rank": "#", "col_nc": "New",
        "products": "Top-selling products", "col_product": "Item",
        "col_top_month": "Top month",
        "products_note": "{n} items — ranked by sales",
        "compare": "Period comparison — first 3 vs last 3 months",
        "cmp_metric": "Metric", "cmp_a": "Period A", "cmp_b": "Period B",
        "cmp_change": "Change",
        "lbl_sales": "Sales", "lbl_txn": "Txns", "lbl_avg": "Avg ticket",
        "lbl_newc": "New customers",
        "forecast": "Next-month forecast",
        "forecast_method": "weighted linear projection (+2% momentum)",
        "recs": "Recommendations", "strengths": "Strengths",
        "weaknesses": "Weaknesses", "target_note": "Targets note", "notes": "Notes",
        "sd_title": "Slowdown alert & likely cause",
        "sd_main_neg": "Slowdown alert: growth fell {n} consecutive months — latest is negative ({to}%). Investigate before month-end.",
        "sd_main": "Slowdown alert: growth has declined {n} consecutive months ({frm}% → {to}%). Intervene before it turns negative.",
        "sd_diag_label": "Likely cause:",
        "sd_region": "Region", "sd_rep": "Rep",
        "sd_diag": "Likely cause: {kind} {name} — monthly growth slid from {frm}% to {to}% (steepest of {n} active entities over {w0} → {w1}). Main lever: {lever} ({drop}%). Review their accounts/campaigns first this month.",
        "sd_diag_none": "No single region or rep stands out — the decline is broad-based; review seasonality, pricing and campaigns.",
        "lever_txns": "transaction count", "lever_ticket": "average ticket",
        "sd_threshold": "Threshold: {n} consecutive months",
    }


def build_sales_pptx_report(
    filename: str,
    sales: dict,
    out_path: Path,
    lang: str = "ar",
    band: str | None = None,
    notes: str | None = None,
) -> Path:
    """PowerPoint deck for a SALES-grid analysis (result["kind"]=="sales").

    Mirrors the web sales dashboard and the sales PDF: KPI cards with
    growth chips, monthly trend chart (with the forecast slot), regions
    table, salespersons ranking, period comparison, forecast slide and
    strengths/weaknesses + recommendations. Same template style (navy
    cover, gold underline, Sakkal Majalla shaping) as the financial deck.

    Financial decks would render this payload as zero-value slides — the
    sales analysis carries no statements/ratios by design.
    """
    platform = (
        "المنصة المالية الذكية" if lang == "ar" else "Smart Financial Platform")
    L = _sales_labels(lang) | {"platform": platform}
    align = PP_ALIGN.RIGHT if lang == "ar" else PP_ALIGN.LEFT
    rtl = lang == "ar"

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    logo = Path(__file__).resolve().parent.parent / "app" / "assets" / "logo.png"
    if not logo.exists():
        logo = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo.png"

    # ---- cover ---------------------------------------------------------------
    s = _slide(prs)
    _bg(s, NAVY)
    _box(s, "rect", Inches(0.9), Inches(1.15), Inches(0.09), Inches(2.3), fill=GOLD)
    _box(s, "rect", Inches(1.12), Inches(1.45), Inches(0.05), Inches(1.7), fill=ORANGE)
    _box(s, "rect", Inches(11.2), Inches(5.4), Inches(1.25), Inches(0.09), fill=GOLD)
    if logo.exists():
        plate = _box(s, "round", Inches(6.11), Inches(0.55), Inches(1.28), Inches(1.28), fill=WHITE)
        plate.adjustments[0] = 0.22
        s.shapes.add_picture(str(logo), Inches(6.25), Inches(0.69), height=Inches(1.0))
    _add_text(s, Inches(1.35), Inches(1.25), Inches(10.4), Inches(1.0),
              L["deck_title"], size=44, color=WHITE, bold=True, align=align)
    _add_text(s, Inches(1.35), Inches(2.35), Inches(10.4), Inches(0.65),
              platform, size=22, color=GOLD, bold=True, align=align)
    _add_text(s, Inches(1.35), Inches(2.95), Inches(10.4), Inches(0.35),
              L["sub"], size=13, color=RGBColor(0xFF, 0xDD, 0x88), align=align)
    _add_text(s, Inches(1.35), Inches(3.35), Inches(10.4), Inches(0.6),
              f"{filename} — {date.today():%Y-%m-%d}", size=18,
              color=RGBColor(0xCC, 0xD8, 0xE8), align=align)
    if band:
        _add_text(s, Inches(1.35), Inches(4.45), Inches(10.4), Inches(0.5),
                  band, size=13, color=RGBColor(0x9A, 0xAB, 0xC2), align=align)

    total_sales = sales.get("total_sales") or 0
    total_txn = sales.get("total_transactions") or 0
    monthly = sales.get("monthly") or []
    fmt = _fmt
    from .report import _sales_period_compare as _period_compare

    # ---- KPI slide -----------------------------------------------------------
    s = _slide(prs)
    _bg(s, WHITE)
    _content_header(s, L["kpis"], lang, L, filename)
    cards = [
        (L["kpi1"], f"{fmt(total_sales)} {L['unit']}", ACCENT),
        (L["kpi2"], fmt(total_txn), GREEN),
        (L["kpi3"], f"{fmt(sales.get('avg_ticket_overall') or 0)} {L['unit']}", ORANGE),
        (L["kpi4"], fmt(sales.get("new_customers") or 0), GOLD),
    ]
    cw, ch = Inches(2.95), Inches(1.55)
    gap = Inches(0.22)
    total_w = cw * 4 + gap * 3
    start_x = (SLIDE_W - total_w) / 2
    for i, (name, value, color) in enumerate(cards):
        x = int(start_x + i * (cw + gap))
        _kpi_card(s, x, Inches(1.6), cw, ch, name, value, color, lang, accent=color)
    # growth chip under the cards (first→last month) + peak/low line
    if len(monthly) >= 2 and monthly[0].get("sales"):
        g = (monthly[-1]["sales"] - monthly[0]["sales"]) / monthly[0]["sales"] * 100
        _add_text(s, Inches(0.8), Inches(3.45), Inches(11.7), Inches(0.5),
                  (f"{('^' if g >= 0 else 'v')} {abs(g):.1f}% "
                   + ("من أول شهر لآخر شهر" if lang == "ar" else "first to last month")),
                  size=16, color=GREEN if g >= 0 else RED, bold=True, align=align)
    pk, lo = sales.get("peak_month"), sales.get("low_month")
    if pk and lo:
        _add_text(s, Inches(0.8), Inches(4.05), Inches(11.7), Inches(0.5),
                  (f"{L['peak']}: {pk['month']} ({fmt(pk['sales'])}) — "
                   f"{L['low']}: {lo['month']} ({fmt(lo['sales'])})"),
                  size=14, color=MUTED, align=align)

    def _tcell(cell, text, size=11, color=INK, bold=False, fill=WHITE):
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = _shape(str(text))
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        _apply_font(run)

    # slide order MIRRORS the live dashboard: trend → txns/newc →
    # region pie + regions table → rep leaderboard → period comparison →
    # forecast → recommendations → strengths/weaknesses
    monthly_labels = [str(m["month"]) for m in monthly]

    # ---- trend chart slide -----------------------------------------------------
    if monthly:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["trend"], lang, L, filename)
        fc0 = sales.get("forecast_next_month") or {}
        # blue dashboard trend, not the financial teal chart
        img = _sales_mpl_chart(
            [m.get("sales", 0) for m in monthly],
            kind="area",
            labels=monthly_labels,
            forecast=(fc0.get("sales") if fc0.get("sales") else None),
        )
        if img:
            s.shapes.add_picture(io.BytesIO(img), Inches(0.7), Inches(1.5), width=Inches(11.9))

    # ---- slowdown alert + likely-cause slide -----------------------------------
    # mirrors the live panel, which shows the alert inside the trend card:
    # the deck gives it its own slide right after the trend, red when the
    # latest month is already negative, amber for the pre-negative case
    _alert = slowdown_alert(sales)
    if _alert:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["sd_title"], lang, L, filename)
        sd = _alert["slowdown"]
        _p = lambda v: f"{v:.1f}"
        if sd["negative"]:
            main = L["sd_main_neg"].format(n=sd["months"], to=_p(sd["to"]))
        else:
            main = L["sd_main"].format(n=sd["months"],
                                       frm=_p(sd["from"]), to=_p(sd["to"]))
        top = _alert["top"]
        if top:
            kind = L["sd_region"] if top["kind"] == "region" else L["sd_rep"]
            diag = L["sd_diag"].format(
                label=L["sd_diag_label"], kind=kind, name=str(top["name"]),
                frm=_p(top["from"]), to=_p(top["to"]),
                n=_alert["candidates_n"], w0=_alert["window"][0],
                w1=_alert["window"][-1],
                lever=(L["lever_txns"] if _alert["lever"]["key"] == "txns"
                       else L["lever_ticket"]),
                drop=_p(_alert["lever"]["drop"]),
            )
        else:
            diag = L["sd_diag_none"]
        neg = sd["negative"]
        bgc = RGBColor(0xFE, 0xF2, 0xF2) if neg else RGBColor(0xFF, 0xFB, 0xEB)
        barc = RGBColor(0xDC, 0x26, 0x26) if neg else RGBColor(0xF5, 0x9E, 0x0B)
        txc = RGBColor(0x99, 0x1B, 0x1B) if neg else RGBColor(0x92, 0x40, 0x0E)
        _box(s, "round", Inches(0.8), Inches(1.9), Inches(11.7), Inches(2.1),
             fill=bgc, line=barc, line_w=Pt(1.25))
        _add_text(s, Inches(1.1), Inches(2.15), Inches(11.1), Inches(0.75),
                  main, size=15, color=txc, bold=True, align=align)
        _add_text(s, Inches(1.1), Inches(2.95), Inches(11.1), Inches(0.9),
                  diag, size=12.5, color=txc, align=align)
        _add_text(s, Inches(1.1), Inches(4.15), Inches(11.1), Inches(0.4),
                  L["sd_threshold"].format(n=_alert["threshold"]),
                  size=10, color=MUTED, align=align)

    # ---- transactions + new customers (two-series line) ------------------------
    if monthly and any(m.get("transactions") for m in monthly):
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["txn_new"], lang, L, filename)
        img = _sales_mpl_chart(
            [m.get("transactions", 0) for m in monthly],
            kind="line2",
            labels=monthly_labels,
            values_b=[m.get("new_customers", 0) for m in monthly],
            title_a=L["lbl_txn"],
            title_b=(L["col_nc"] if lang == "en" else "عملاء جدد"),
        )
        if img:
            s.shapes.add_picture(io.BytesIO(img), Inches(0.7), Inches(1.6), width=Inches(11.9))

    # ---- period comparison (table) ----------------------------------------------
    cmp_ = _period_compare(monthly) if monthly else None
    if cmp_:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["compare"], lang, L, filename)
        lbl = {"sales": L["lbl_sales"], "txn": L["lbl_txn"],
               "avg": L["lbl_avg"], "newc": L["lbl_newc"]}
        headers = [L["cmp_metric"], L["cmp_a"], L["cmp_b"], L["cmp_change"]]
        if rtl:
            headers = list(reversed(headers))
        table = s.shapes.add_table(len(cmp_["rows"]) + 1, 4, Inches(1.4),
                                   Inches(1.6), Inches(10.5),
                                   Inches(0.55) * (len(cmp_["rows"]) + 1)).table
        total_w = int(Inches(10.5))
        per_col = total_w // 4
        widths = [per_col] * 3 + [total_w - per_col * 3]
        for c in range(4):
            table.columns[c].width = widths[c]
        for c, h in enumerate(headers):
            _tcell(table.cell(0, c), h, size=12, color=WHITE, bold=True, fill=NAVY)
        for ri, row in enumerate(cmp_["rows"], 1):
            unit_suf = f" {L['unit']}" if row["key"] in ("sales", "avg") else ""
            vals = [lbl[row["key"]],
                    (fmt(row["a"]) + unit_suf) if row["a"] else "-",
                    (fmt(row["b"]) + unit_suf) if row["b"] else "-",
                    (f"{'+' if row['d'] >= 0 else ''}{row['d']}%"
                     if row["d"] is not None else "-")]
            if rtl:
                vals = list(reversed(vals))
            for c, v in enumerate(vals):
                dcolor = (GREEN if row["d"] >= 0 else RED) if (c == (0 if rtl else 3)
                           and row["d"] is not None) else INK
                _tcell(table.cell(ri, c), v, fill=PANEL if ri % 2 == 1 else WHITE,
                       color=dcolor, bold=(c == (0 if rtl else 3)))
        _add_text(s, Inches(0.6), Inches(6.55), Inches(12.1), Inches(0.4),
                  f"A: {cmp_['a_label']} — B: {cmp_['b_label']}",
                  size=10, color=MUTED, align=align)
        # paired A/B chart under the table (the dashboard's cmp chart)
        img = _sales_mpl_chart(
            [r.get("a") or 0 for r in cmp_["rows"]],
            kind="cbar",
            values_b=[r.get("b") or 0 for r in cmp_["rows"]],
            title_a=L["cmp_a"], title_b=L["cmp_b"],
            bar_names=[lbl[r["key"]] for r in cmp_["rows"]],
        )
        if img:
            s.shapes.add_picture(io.BytesIO(img), Inches(4.0), Inches(4.55), width=Inches(5.2))

    regions = sales.get("regions") or []
    reps = sales.get("reps") or []

    # ---- region share donut + regions table -------------------------------------------
    if regions:
        # the donut beside the regions table (dashboard's 🎯 card)
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["regions"], lang, L, filename)
        img = _sales_mpl_chart(
            [r.get("sales", 0) for r in regions],
            kind="pie", bar_names=[str(r["region"]) for r in regions],
        )
        if img:
            chart_x = Inches(7.0) if rtl else Inches(0.7)
            s.shapes.add_picture(io.BytesIO(img), chart_x, Inches(1.5), width=Inches(5.7))
        headers = [L["col_region"], L["col_sales"], L["col_share"], L["col_txn"],
                   L["col_avg"], L["col_growth"], L["col_best"]]
        if rtl:
            headers = list(reversed(headers))
        table = s.shapes.add_table(len(regions) + 1, len(headers),
                                   Inches(0.4), Inches(1.4),
                                   Inches(12.5), Inches(0.5) * (len(regions) + 1)).table
        total_w = int(Inches(12.5))
        per_col = total_w // len(headers)
        widths = [per_col] * (len(headers) - 1) + [total_w - per_col * (len(headers) - 1)]
        for c in range(len(headers)):
            table.columns[c].width = widths[c]

        for c, h in enumerate(headers):
            _tcell(table.cell(0, c), h, size=11.5, color=WHITE, bold=True, fill=NAVY)
        for ri, r in enumerate(regions, 1):
            g = r.get("growth")
            vals = [str(r["region"]), fmt(r.get("sales", 0)),
                    f"{r['share_pct']:.1f}%" if r.get("share_pct") is not None else "-",
                    fmt(r.get("transactions", 0)),
                    fmt(r["avg_ticket"]) if r.get("avg_ticket") else "-",
                    (f"{'+' if (g or 0) >= 0 else ''}{g}%" if g is not None else "-"),
                    str(r.get("best_rep") or "-")]
            if rtl:
                vals = list(reversed(vals))
            for c, v in enumerate(vals):
                _tcell(table.cell(ri, c), v,
                       fill=PANEL if ri % 2 == 1 else WHITE,
                       color=GREEN if ("%" in str(v) and not str(v).startswith("+")) else INK)

    # ---- rep leaderboard (horizontal bars + ranking table) ------------------------------
    if reps:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["reps"], lang, L, filename)
        img = _sales_mpl_chart(
            [r.get("sales", 0) for r in reps],
            kind="hbar", bar_names=[str(r["rep"]) for r in reps],
        )
        if img:
            s.shapes.add_picture(io.BytesIO(img), Inches(0.7), Inches(1.5), width=Inches(7.6))
        headers = [L["col_rank"], L["col_rep"], L["col_region"], L["col_sales"],
                   L["col_growth"], L["col_nc"]]
        if rtl:
            headers = list(reversed(headers))
        table = s.shapes.add_table(len(reps) + 1, len(headers),
                                   Inches(8.5) if rtl else Inches(0.4),
                                   Inches(1.45) if not rtl else Inches(1.45),
                                   Inches(4.3), Inches(0.5) * (len(reps) + 1)).table
        total_w = int(Inches(4.3))
        per_col = total_w // len(headers)
        widths = [per_col] * (len(headers) - 1) + [total_w - per_col * (len(headers) - 1)]
        for c in range(len(headers)):
            table.columns[c].width = widths[c]
        for c, h in enumerate(headers):
            _tcell(table.cell(0, c), h, size=10.5, color=WHITE, bold=True, fill=NAVY)
        for ri, r in enumerate(reps, 1):
            g = r.get("growth")
            vals = [str(ri), str(r["rep"]), str(r.get("region") or "-"),
                    fmt(r.get("sales", 0)),
                    (f"{'+' if (g or 0) >= 0 else ''}{g}%" if g is not None else "-"),
                    fmt(r.get("new_customers", 0))]
            if rtl:
                vals = list(reversed(vals))
            for c, v in enumerate(vals):
                _tcell(table.cell(ri, c), v, size=10,
                       fill=PANEL if ri % 2 == 1 else WHITE)
        note = sales.get("reps_target_note")
        if note:
            _add_text(s, Inches(0.6), Inches(6.55), Inches(12.1), Inches(0.4),
                      note, size=10, color=MUTED, align=align)

    # ---- top-selling products slide (the dashboard's 🛍️ card) -------------------------
    products = sales.get("products") or []
    if products:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["products"], lang, L, filename)
        _add_text(s, Inches(0.6), Inches(6.55), Inches(12.1), Inches(0.35),
                  L["products_note"].format(n=len(products)),
                  size=10, color=MUTED, align=align)
        top_p = products[:8]
        img = _sales_mpl_chart(
            [p.get("sales", 0) for p in top_p],
            kind="hbar", bar_names=[str(p["product"]) for p in top_p],
        )
        if img:
            s.shapes.add_picture(io.BytesIO(img), Inches(0.7), Inches(1.5), width=Inches(7.6))
        headers = [L["col_rank"], L["col_product"], L["col_sales"],
                   L["col_share"], L["col_txn"], L["col_top_month"]]
        if rtl:
            headers = list(reversed(headers))
        rows_n = min(len(products), 10)  # the slide holds 10 rows comfortably
        table = s.shapes.add_table(rows_n + 1, len(headers),
                                   Inches(8.5) if rtl else Inches(0.4),
                                   Inches(1.45),
                                   Inches(4.3), Inches(0.45) * (rows_n + 1)).table
        total_w = int(Inches(4.3))
        per_col = total_w // len(headers)
        widths = [per_col] * (len(headers) - 1) + [total_w - per_col * (len(headers) - 1)]
        for c in range(len(headers)):
            table.columns[c].width = widths[c]
        for c, h in enumerate(headers):
            _tcell(table.cell(0, c), h, size=10.5, color=WHITE, bold=True, fill=NAVY)
        for ri, p in enumerate(products[:rows_n], 1):
            vals = [str(ri), str(p["product"]), fmt(p.get("sales", 0)),
                    (f"{p['share_pct']:.1f}%" if p.get("share_pct") is not None else "-"),
                    fmt(p.get("transactions", 0)),
                    str(p.get("top_month") or "-")]
            if rtl:
                vals = list(reversed(vals))
            for c, v in enumerate(vals):
                _tcell(table.cell(ri, c), v, size=10,
                       fill=PANEL if ri % 2 == 1 else WHITE,
                       bold=(headers.index("#") if "#" in headers else -1) == c)

    # ---- strengths / weaknesses + recommendations -------------------------------------
    fc = sales.get("forecast_next_month") or {}
    if fc.get("sales"):
        # forecast slide (dashboard's 🔮 card) BEFORE recommendations —
        # the live order is forecast → recommendations → strengths/weaknesses
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["forecast"], lang, L, filename)
        g = fc.get("growth")
        _add_text(s, Inches(0.8), Inches(2.0), Inches(11.7), Inches(1.0),
                  f"{fmt(fc['sales'])} {L['unit']}"
                  + (f"   ({'+' if (g or 0) >= 0 else ''}{g}%)" if g is not None else ""),
                  size=34, color=ACCENT, bold=True, align=align)
        _add_text(s, Inches(0.8), Inches(3.1), Inches(11.7), Inches(0.4),
                  L["forecast_method"], size=11, color=MUTED, align=align)

    # ---- strengths / weaknesses + recommendations -------------------------------------
    strengths = sales.get("strengths") or []
    weaknesses = sales.get("weaknesses") or []
    recs = sales.get("recommendations") or []
    if strengths or weaknesses or recs:
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["recs"], lang, L, filename)
        y = 1.4
        if strengths or weaknesses:
            for t, txts, color in ((L["strengths"], strengths, GREEN),
                                   (L["weaknesses"], weaknesses, ORANGE)):
                if txts:
                    _add_text(s, Inches(0.8), Inches(y), Inches(11.7), Inches(0.4),
                              t, size=16, color=color, bold=True, align=align)
                    y += 0.45
                    for txt in txts[:3]:
                        _add_text(s, Inches(0.95), Inches(y), Inches(11.4), Inches(0.38),
                                  "• " + str(txt), size=13, color=INK, align=align)
                        y += 0.38
                    y += 0.15
        if recs:
            _add_text(s, Inches(0.8), Inches(min(y, 4.6)), Inches(11.7), Inches(0.4),
                      L["recs"], size=16, color=ACCENT, bold=True, align=align)
            y = min(y, 4.6) + 0.45
            for r_ in recs[:4]:
                txt = r_.get("ar") if lang == "ar" else r_.get("en")
                _add_text(s, Inches(0.95), Inches(y), Inches(11.4), Inches(0.55),
                          "• " + str(txt), size=12.5, color=INK, align=align)
                y += 0.55

    if notes and str(notes).strip():
        s = _slide(prs)
        _bg(s, WHITE)
        _content_header(s, L["notes"], lang, L, filename)
        _add_text(s, Inches(0.8), Inches(1.4), Inches(11.7), Inches(5.0),
                  str(notes), size=15, color=INK, align=align)

    prs.save(str(out_path))
    return out_path
