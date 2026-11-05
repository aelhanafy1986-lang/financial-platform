"""PDF report generation with full Arabic RTL support — dashboard-styled.

Arabic text needs two extra steps for PDFs: reshaping (joining letters) and
bidi reordering. We register Sakkal Majalla (the classic Arabic report font,
matching the platform's reference deck), then Amiri/Noto Naskh, then
Tahoma/Arial as fallbacks.

Reports follow the dashboard's teal visual identity and mirror exactly what
the web app shows: KPI card grid, coloured section headers, striped tables,
embedded charts (history + projections), the CMRRS-style executive opening
(نبذة عن الشركة + ملخص النتائج), the financial score with scenarios,
recommendations with severity colours, and the full financial statements when
a trial balance was provided. A4 print-ready with brand header/footer.
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display

from .ifrs import basis_of_preparation, detect_applicable as detect_ifrs
from .ratio_explain import BADGES, build_benchmark_alignment
from matplotlib import font_manager, use as mpl_use
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Polygon
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
import threading
from reportlab.pdfbase.ttfonts import TTFont

from .fonts import (RENDER_SKIP_CODEPOINTS, UnsupportedGlyphError,
                    ttf_coverage)
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

mpl_use("Agg")

_FONT_PATH: str | None = None
_FONT_BOLD_PATH: str | None = None
_FONT_NAME: str = "Helvetica"
_FONT_BOLD_NAME: str = "Helvetica-Bold"

TEAL = colors.HexColor("#0f766e")
TEAL_DARK = colors.HexColor("#115e59")
TEAL_SOFT = colors.HexColor("#f0fdfa")
INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")
GREEN = colors.HexColor("#059669")
RED = colors.HexColor("#dc2626")
AMBER = colors.HexColor("#b45309")
AMBER_BG = colors.HexColor("#fef3c7")
RED_BG = colors.HexColor("#fef2f2")
GREEN_BG = colors.HexColor("#ecfdf5")
BLUE_BG = colors.HexColor("#eff6ff")
ORANGE_BG = colors.HexColor("#fff7ed")


def _find_arabic_font() -> tuple[str, str | None]:
    """Locate regular + bold TTF fonts with Arabic glyphs. Cached."""
    global _FONT_PATH, _FONT_BOLD_PATH
    if _FONT_PATH is not None:
        return _FONT_PATH, _FONT_BOLD_PATH

    regular: Path | None = None
    bold: Path | None = None

    pairs = [
        (Path("C:/Windows/Fonts/majalla.ttf"), Path("C:/Windows/Fonts/majallab.ttf")),
        (Path("C:/Windows/Fonts/tahoma.ttf"), Path("C:/Windows/Fonts/tahomabd.ttf")),
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    ]
    for reg, bld in pairs:
        if reg.exists():
            regular, bold = reg, (bld if bld.exists() else None)
            break

    if regular is None:
        try:
            for f in font_manager.findSystemFonts():
                name = Path(f).name.lower()
                if "amiri" in name or "notonaskh" in name or "noto-naskh" in name:
                    regular = Path(f)
                    break
        except Exception:
            pass

    _FONT_PATH = str(regular) if regular else ""
    _FONT_BOLD_PATH = str(bold) if bold else None
    return _FONT_PATH, _FONT_BOLD_PATH


# Symbols the Arabic TTFs (Majalla…) do NOT carry — reportlab draws them as
# empty boxes (extracts as \x00): a check/miss/cross/bullet/arrow must map to
# a glyph the font HAS, otherwise every verdict line and table cell breaks.
_GLYPH_SUBS = {
    "\u2713": "\u2022",  # ✓ → •
    "\u2717": "\u00d7",  # ✗ → ×
    "\u2192": "\u2013",  # → → –
    "\u25cf": "\u2022",  # ● → •
    "\u2588": "\u2022",  # █ → •
    "\u2591": "\u00b7",  # ░ → ·
    "\u26a0": "!",       # ⚠ → ! (majalla has no warning sign)
    # trend arrows (labels.py chips) — majalla carries no geometric arrows
    "\u25b2": "^",       # ▲ → ^
    "\u25bc": "v",       # ▼ → v
    "\u25c4": "<",       # ◄ → <
    "\u25ba": ">",       # ► → >
}


def _shape(text: str) -> str:
    """Reshape + bidi so Arabic renders connected and in visual order.

    Digits stay LTR inside the visual line (bidi handles the ordering).
    Symbols the Arabic font lacks (✓ ✗ → ● …) are mapped to supported
    glyphs first — an unmappable codepoint renders as a hollow box.

    While a report build holds the glyph guard open, any REMAINING
    character the embedded TTF cannot render is recorded thread-locally;
    the builder flushes right before doc.build and refuses the report.
    """
    if not text:
        return text
    original = str(text)
    text = original
    if any(c in text for c in _GLYPH_SUBS):
        for bad, good in _GLYPH_SUBS.items():
            if bad in text:
                text = text.replace(bad, good)
    shaped = get_display(arabic_reshaper.reshape(text))
    _glyph_check(shaped, original)
    return shaped


# ---------------------------------------------------------------------------
# Glyph guard: a report whose text carries a character the embedded TTF
# cannot render would print it as a hollow box («مربع فارغ»). While a
# builder holds the guard open, _shape records every offender on the
# build's thread; the builder flushes right BEFORE doc.build so a refused
# report never reaches bytes, the reports cache, or the response.
# The error/coverage machinery itself lives in app/fonts.py — shared with
# the matplotlib chart guard, whose font may differ from reportlab's.
# ---------------------------------------------------------------------------

_SKIP_CODEPOINTS = RENDER_SKIP_CODEPOINTS
_GLYPH_GUARD = threading.local()


def _font_coverage() -> frozenset:
    """Codepoints the reportlab TTF renders (the regular and bold faces
    of the Majalla pair share one cmap — verified identical)."""
    return ttf_coverage(_FONT_PATH)


def _glyph_check(shaped: str, source: str) -> None:
    """Record characters the active build's font cannot render."""
    hits = getattr(_GLYPH_GUARD, "hits", None)
    if hits is None:
        return  # no report build in progress on this thread
    coverage = _font_coverage()
    if not coverage:
        return  # coverage unknown — guard disabled
    for ch in shaped:
        cp = ord(ch)
        if cp in coverage or cp in _SKIP_CODEPOINTS:
            continue
        hits[ch] = hits.get(ch, 0) + 1
        _GLYPH_GUARD.samples.setdefault(
            ch, " ".join(str(source).split())[:120])


def glyph_guard_begin() -> None:
    """Open the glyph guard on this thread for one report build."""
    _GLYPH_GUARD.hits = {}
    _GLYPH_GUARD.samples = {}


def glyph_guard_flush() -> None:
    """Refuse the build when the open guard recorded unrenderable
    characters; the guard closes either way."""
    hits = dict(getattr(_GLYPH_GUARD, "hits", None) or {})
    samples = dict(getattr(_GLYPH_GUARD, "samples", None) or {})
    _GLYPH_GUARD.hits = None
    _GLYPH_GUARD.samples = None
    if hits:
        raise UnsupportedGlyphError(hits, samples)


def _register_font() -> str:
    """Register the TTFs with reportlab and matplotlib; return font name."""
    global _FONT_NAME, _FONT_BOLD_NAME
    font_path, bold_path = _find_arabic_font()
    if not font_path:
        return "Helvetica"
    _FONT_NAME = "Auto"
    _FONT_BOLD_NAME = "Auto-Bold"
    pdfmetrics.registerFont(TTFont("Auto", font_path))
    if bold_path:
        pdfmetrics.registerFont(TTFont("Auto-Bold", bold_path))
        try:
            registerFontFamily("Auto", normal="Auto", bold="Auto-Bold",
                               italic="Auto", boldItalic="Auto-Bold")
        except Exception:
            pass
    else:
        _FONT_BOLD_NAME = "Auto"
    try:
        font_manager.fontManager.addfont(font_path)
        family = font_manager.FontProperties(fname=font_path).get_name()
        import matplotlib as mpl

        mpl.rcParams["font.family"] = family
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
    return _FONT_NAME


def _rt(text: str, base_style: ParagraphStyle) -> Paragraph:
    """RTL-aware paragraph: reshaped text + right alignment for Arabic."""
    return Paragraph(_shape(text), base_style)


def _table_style(extra: list | None = None) -> TableStyle:
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TEAL_SOFT]),
        # header text is drawn pre-shaped by the caller; keep it LTR-aligned
        # cells start right-aligned and get mirrored by the caller for AR
    ]
    if extra:
        style += extra
    return TableStyle(style)


def _flip(style_commands: list, n_cols: int) -> list:
    """Mirror table style commands horizontally for RTL tables."""
    flipped = []
    for cmd in style_commands:
        op = cmd[0]
        if op in ("BACKGROUND", "TEXTCOLOR", "FONTNAME", "FONTSIZE",
                  "TEXTCOLOR", "ALIGN", "LINEBELOW", "LINEABOVE",
                  "LINEBEFORE", "LINEAFTER", "ROWBACKGROUNDS"):
            try:
                (c0, r0), (c1, r1) = cmd[1], cmd[2]
                mc0, mc1 = n_cols - 1 - c0, n_cols - 1 - c1
                new = [op, (min(mc0, mc1), r0), (max(mc0, mc1), r1)] + list(cmd[3:])
                flipped.append(tuple(new))
                continue
            except Exception:
                pass
        flipped.append(cmd)
    return flipped


_RAW_ARABIC = re.compile(r"[\u0621-\u064A]")


def _rtl_table(data: list, rtl: bool, col_widths: list | None = None,
               extra: list | None = None, repeat_rows: int = 1) -> Table:
    """Build a table with right-aligned cells and mirrored styling for AR.

    Cells holding raw (logical-order) Arabic are shaped automatically, so raw
    column headers (item/value/…) and any unshaped leak render connected and
    in visual order. Cell text with logical Arabic maps to presentation forms
    and never matches _RAW_ARABIC, so it is never double-shaped.
    """
    data = [
        [_shape(c) if isinstance(c, str) and _RAW_ARABIC.search(c) else c
         for c in row]
        for row in data
    ]
    if rtl:
        data = [list(reversed(row)) for row in data]
        if col_widths:
            col_widths = list(reversed(col_widths))
        if extra:
            extra = _flip(extra, len(data[0]))
    table = Table(data, colWidths=col_widths, hAlign="RIGHT" if rtl else "LEFT",
                  repeatRows=repeat_rows)
    table.setStyle(_table_style(extra))
    return table


def _section(story: list, title: str, key: str = "", rtl: bool = True) -> None:
    story.append(Paragraph(
        _shape(title),
        ParagraphStyle(
            f"h2-{key or title[:8]}-{len(story)}",
            fontName=_FONT_BOLD_NAME, fontSize=14, leading=20,
            textColor=TEAL_DARK, spaceBefore=8, spaceAfter=4,
            alignment=TA_RIGHT if rtl else TA_LEFT,
        ),
    ))


def _para(text: str, rtl: bool = True, size: float = 10.5, leading: float = 16,
          color=INK, bold: bool = False, style_key: str = "p") -> Paragraph:
    return Paragraph(
        _shape(text),
        ParagraphStyle(
            style_key, fontName=_FONT_BOLD_NAME if bold else _FONT_NAME,
            fontSize=size, leading=leading, textColor=color,
            alignment=TA_RIGHT if rtl else TA_LEFT,
        ),
    )


def _kpi_cards(story: list, kpis: dict, lang: str, rtl: bool) -> None:
    """Dashboard-style KPI card grid (2 columns)."""
    entries = list(kpis.values())
    rows = []
    for i in range(0, len(entries), 2):
        pair = entries[i : i + 2]
        if rtl:
            pair = list(reversed(pair))
        row = []
        for kpi in pair:
            name = kpi.get(lang) or kpi.get("en") or ""
            value = f"{kpi['value']:,.0f}"
            neg = isinstance(kpi.get("value"), (int, float)) and kpi["value"] < 0
            value_color = "#dc2626" if neg else "#0f766e"
            row.append(
                Paragraph(
                    f"{_shape(str(name))}<br/><font size=15 color={value_color}><b>{value}</b></font>",
                    ParagraphStyle(
                        f"kpi-{i}-{len(row)}", fontName=_FONT_NAME,
                        fontSize=10, leading=15, alignment=TA_RIGHT if rtl else TA_LEFT,
                    ),
                )
            )
        if len(row) == 1:
            row.append("")
        rows.append(row)
    grid = Table(rows, colWidths=[85 * mm, 85 * mm],
                 hAlign="RIGHT" if rtl else "LEFT")
    style: list = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 3, colors.white),
    ]
    accent_side = "LINEAFTER" if rtl else "LINEBEFORE"
    for r in range(len(rows)):
        for c in range(2):
            style.append(("BACKGROUND", (c, r), (c, r), TEAL_SOFT))
            style.append(("BOX", (c, r), (c, r), 0.75, LINE))
            style.append((accent_side, (c, r), (c, r), 3, TEAL))
    grid.setStyle(TableStyle(style))
    story.append(grid)
    story.append(Spacer(1, 5 * mm))


def _chart(values: list, projections: list | None = None, title: str = "",
           font_path: str | None = None,
           labels: list[str] | None = None) -> Image | None:
    """Area chart of history + dashed projection segment, as an Image flowable.

    ``labels`` (optional) names the historical x positions — the evolution
    charts pass the analysis's period labels so every year is readable on
    the axis; the projection slots stay unlabelled (the dashed segment).

    The title must go through ``mpl_text`` (NOT the reportlab ``_shape``):
    matplotlib ≥3.10 shapes Arabic and applies bidi itself — pre-shaped
    visual-order text gets reversed a second time and garbles the chart
    title (the «حروف مقطعة» chart bug)."""
    try:
        import matplotlib.pyplot as plt

        hist = [float(v) for v in values]
        xs = list(range(1, len(hist) + 1))
        proj = [float(p["value"]) for p in (projections or [])]
        fig, ax = plt.subplots(figsize=(4.6, 1.7), dpi=150)
        ax.plot(xs, hist, color="#0f766e", linewidth=2, marker="o", markersize=3)
        ax.fill_between(xs, hist, color="#0f766e", alpha=0.12)
        if proj:
            px = list(range(len(hist), len(hist) + len(proj)))
            ax.plot([xs[-1]] + px, [hist[-1]] + proj, color="#f59e0b",
                    linewidth=2, linestyle="--", marker="s", markersize=3)
        ax.set_xticks(xs + list(range(len(hist) + 1, len(hist) + len(proj) + 1)))
        if labels:
            hist_labels = [str(x) for x in labels[-len(hist):]]
            if len(hist_labels) == len(hist):
                ax.set_xticklabels(hist_labels + [""] * len(proj), fontsize=6)
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=6)
        if title:
            from .dashboard_charts import mpl_text
            ax.set_title(mpl_text(title), fontsize=8, color="#334155")
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return Image(buf, width=118 * mm, height=44 * mm)
    except Exception:
        return None


def _sales_chart(values_a: list, labels: list[str], values_b: list | None = None,
                 title_a: str = "", title_b: str = "", kind: str = "area",
                 bar_names: list[str] | None = None,
                 forecast: float | None = None) -> Image | None:
    """Sales-dashboard charts (mirroring the live Recharts panel:

    - kind="area": sales area chart (the trend card, blue as the
      dashboard stroke + translucent fill, optional amber forecast slot),
    - kind="cbar": the period-comparison grouped bars (A gray #94a3b8
      vs B blue #2563eb — the dashboard cmp chart),
    - kind="line2": TWO series line chart — transactions + new
      customers (the operations card),
    - kind="pie": region-share donut (the regions card),
    - kind="hbar": horizontal rep leaderboard bars (the ranking card).

    Arabic titles/labels go through ``mpl_text`` (matplotlib's own shaping
    engine), NOT reportlab's pre-shaped `_shape` — the same guard the
    financial chart uses (pre-shaped text gets double-reversed).
    """
    try:
        import matplotlib.pyplot as plt

        from .dashboard_charts import mpl_text

        a = [float(v) for v in values_a]
        xs = list(range(1, len(a) + 1))
        if kind == "area":
            fig, ax = plt.subplots(figsize=(7.4, 2.6), dpi=150)
            ax.plot(xs, a, color="#2563eb", linewidth=2.4, marker="o", markersize=4)
            ax.fill_between(xs, a, color="#2563eb", alpha=0.14)
            if forecast is not None:
                # amber forecast slot (same shape as the financial chart):
                # dashed connector from the last month to the projected month
                px = [xs[-1], xs[-1] + 2]
                ax.plot(px, [a[-1], float(forecast)], color="#f59e0b",
                        linewidth=2.2, linestyle="--", marker="o",
                        markersize=4, markerfacecolor="none")
                ax.set_xlim(right=xs[-1] + 2)
            if labels:
                lab = [str(x) for x in labels[-len(a):]]
                if len(lab) == len(a):
                    ax.set_xticks(xs)
                    ax.set_xticklabels(lab, fontsize=7)
            if bar_names:
                pass
        elif kind == "cbar":
            # the dashboard's period-comparison chart: paired bars per
            # metric — first period A in gray, latest period B in blue
            b = [float(v) for v in (values_b or [])][:len(a)]
            fig, ax = plt.subplots(figsize=(7.4, 1.9), dpi=150)
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
                fontsize=7)
            if title_a or title_b:
                ax.legend(fontsize=7, frameon=False, loc="lower right")
        elif kind == "line2":
            b = [float(v) for v in (values_b or [])][:len(a)]
            fig, ax = plt.subplots(figsize=(7.4, 2.6), dpi=150)
            ax.plot(xs[:len(a)], a, color="#8b5cf6", linewidth=2.4, marker="o", markersize=4,
                    label=mpl_text(title_a))
            if len(b) == len(a):
                ax.plot(xs, b, color="#f59e0b", linewidth=2.4, marker="s", markersize=4,
                        label=mpl_text(title_b))
            ax.legend(fontsize=7, frameon=False)
            if labels:
                lab = [str(x) for x in labels[-len(a):]]
                if len(lab) == len(a):
                    ax.set_xticks(xs)
                    ax.set_xticklabels(lab, fontsize=7)
        elif kind == "pie":
            fig, ax = plt.subplots(figsize=(4.6, 2.8), dpi=150)
            names = [str(n) for n in (bar_names or [])]
            palette = ["#2563eb", "#8b5cf6", "#06b6d4", "#f59e0b",
                       "#ec4899", "#10b981", "#f43f5e"]
            wedges, _txts, autotexts = ax.pie(
                a, labels=[mpl_text(n) for n in names] or None,
                autopct="%1.1f%%", pctdistance=0.75,
                colors=[palette[i % len(palette)] for i in range(len(a))],
                wedgeprops={"width": 0.45, "edgecolor": "white"},
                textprops={"fontsize": 7})
            for t in autotexts:
                t.set_fontsize(6.5)
        else:  # hbar
            fig, ax = plt.subplots(figsize=(4.6, 2.6), dpi=150)
            names = [mpl_text(str(n)) for n in (bar_names or [])]
            ypos = list(range(len(a)))[::-1]
            ax.barh(ypos, a, color="#2563eb", height=0.55)
            ax.set_yticks(ypos)
            ax.set_yticklabels(names, fontsize=7)
        ax.grid(True, axis="x" if kind == "hbar" else "y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=7)
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        w_mm, h_mm = (170, 60) if kind in ("area", "line2") else (88, 54)
        return Image(buf, width=w_mm * mm, height=h_mm * mm)
    except Exception:
        return None


def _png_dims(data: bytes) -> tuple[int, int]:
    """Pixel size from a PNG's IHDR header (for aspect-true placement)."""
    import struct
    try:
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    except Exception:
        return 600, 400


def _fit_image(data: bytes | None, width_mm: float) -> Image | None:
    """Image flowable at `width_mm` with the PNG's own aspect ratio —
    CAPPED by the frame's usable height as well: tall charts (the bullet
    bars grow with row count) previously exceeded the frame and reportlab
    aborted the whole PDF with LayoutError (image too large on page)."""
    if not data:
        return None
    try:
        w, h = _png_dims(data)
        if w <= 0 or h <= 0:
            return None
        width = width_mm * mm
        height = width_mm * mm * h / w
        # usable A4 frame height minus the frame's own padding (6pt × 2)
        # and a safety hairline: 297mm page − 14/18mm margins ≈ 739pt frame
        max_h = (297.0 - 14.0 - 18.0) * mm - 16
        if height > max_h:
            height = max_h
            width = max_h * w / h
        return Image(io.BytesIO(data), width=width, height=height)
    except Exception:
        return None


def _dashboard_section(story: list, result: dict, score: dict | None,
                       L: dict, lang: str, rtl: bool) -> None:
    """لوحة المؤشرات التحليلية — reference-dashboards style: a score gauge,
    an expense-mix donut, benchmark bullet bars, a revenue-composition bar
    and a value-labelled revenue trend, embedded as crisp chart images."""
    from .dashboard_charts import (activity_lines, cost_stack,
                                   dashboard_payload, expense_donut,
                                   ratio_bullets, score_gauge, trend_line)

    data = dashboard_payload(result, lang, score)
    if not any((data.get("score") is not None, data.get("expenses") and
                len(data["expenses"]) >= 2, data.get("bullets"),
                data.get("cost_parts"), data.get("trends"))):
        return
    _section(story, L["dash_section"], "dash", rtl)

    # top row: score gauge + expense-mix donut, side by side
    left_img = right_img = None
    if data.get("score") is not None:
        left_img = _fit_image(
            score_gauge(data["score"], data.get("grade_label") or ""), 82)
    if data.get("expenses") and len(data["expenses"]) >= 2:
        right_img = _fit_image(
            expense_donut(data["expenses"],
                          center_label=L["dash_expenses_center"],
                          title=L["dash_expenses"]), 94)
    if left_img and right_img:
        row = [left_img, right_img] if not rtl else [right_img, left_img]
        grid = Table([row], colWidths=[89 * mm, 89 * mm],
                     hAlign="RIGHT" if rtl else "LEFT")
        grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "RIGHT" if rtl else "LEFT"),
            ("ALIGN", (1, 0), (1, 0), "LEFT" if rtl else "RIGHT"),
        ]))
        story.append(grid)
    elif left_img or right_img:
        story.append(left_img or right_img)
    story.append(Spacer(1, 3 * mm))

    # benchmark bullet bars (the alignment story at a glance)
    if data.get("bullets"):
        img = _fit_image(ratio_bullets(data["bullets"], L["dash_bullets"]), 168)
        if img:
            story.append(img)
            story.append(Spacer(1, 3 * mm))

    # revenue composition bar
    if data.get("cost_parts") and len(data["cost_parts"]) >= 2:
        img = _fit_image(cost_stack(data["cost_parts"], L["dash_cost"]), 168)
        if img:
            story.append(img)
            story.append(Spacer(1, 3 * mm))

    # value-labelled revenue trend (when multi-period data exists)
    if data.get("trends"):
        t = data["trends"][0]
        img = _fit_image(trend_line(
            t["values"], labels=data.get("period_labels"), title=t["label"]), 168)
        if img:
            story.append(img)
            story.append(Spacer(1, 2 * mm))

    # working-capital heartbeat: collection period & inventory turnover (and
    # the payment period + CCC the analysis supports) across periods —
    # compute_activity_series' per-period values, same data as the Excel chart
    from .analyzer import compute_activity_series
    act_img = _fit_image(
        activity_lines(compute_activity_series(result.get("metrics") or {}),
                       title=L["activity_title"],
                       labels=data.get("period_labels")), 168)
    if act_img:
        story.append(act_img)
        story.append(Spacer(1, 2 * mm))


def _labels(lang: str) -> dict:
    if lang == "ar":
        return {
            "title": "التقرير المالي",
            "period": "فترة التحليل",
            "entity": "المنشأة: {name}",
            "issued": "تم إنشاؤه",
            "tagline": "محلّلك المالي المدعوم بالذكاء الاصطناعي",
            "language": "لغة التقرير",
            "source": "المصدر: {name}",
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
            "key_findings": "الاستنتاجات الرئيسية",
            "strategic_recs": "التوصيات الاستراتيجية",
            "ratio_insights": "تحليل النسب المالية",
            "what_q": "ما هي؟",
            "why_q": "ما فائدتها؟",
            "opinion_q": "الرأي:",
            "ifrs_title": "الإطار المعياري — المعايير الدولية لإعداد التقارير المالية (IFRS)",
            "bench_title": "مواءمة النسب مع المعايير المرجعية",
            "bench_col_ratio": "النسبة", "bench_col_value": "القيمة",
            "bench_col_ref": "المعيار المرجعي", "bench_col_status": "الحالة",
            "bench_note": "المراسئ وفق منهجية التحليل المعتمدة: نسبة التداول المثالية 2.0، تغطية الفوائد ≥ 3.0x، فترة تحصيل ≤ 90 يومًا، مديونية ≤ 70%... — ✓ مستوفٍ · ≈ قريب · ✗ غير مستوفٍ.",
            "ifrs_col_code": "المرجع",
            "ifrs_col_std": "المعيار",
            "ifrs_col_rel": "وجه الانطباق على هذا التحليل",
            "ifrs_ref": "المرجع المعياري:",
            "check_col": "البند",
            "check_result_col": "النتيجة",
            "consistency": "التحقق من صحة الأرقام",
            "wcq_period": "الفترة", "wcq_net": "صافي الربح",
            "wcq_cf": "التدفق التشغيلي المُعلن",
            "wcq_ratio": "نسبة التحويل",
            "wcq_verdict": "الحكم",
            "wcq_verdicts": {"ok": "مستوفٍ ✓", "watch": "للمراقبة ≈", "bad": "ضعيف ✗"},
            "series": "الرسوم البيانية التحليلية",
            "evo_title": "تطور الإيرادات وصافي الربح عبر السنوات",
            "evo_revenue": "الإيرادات",
            "evo_net": "صافي الربح",
            "dash_section": "لوحة المؤشرات التحليلية",
            "dash_expenses": "توزيع المصروفات",
            "dash_expenses_center": "المصروفات",
            "dash_bullets": "النسب مقابل المعايير المرجعية (المرسى = 1.00)",
            "dash_cost": "بنية الإيراد: التكلفة مقابل النتيجة",
            "activity_title": "تطور دورة التحول النقدي ومكوناتها عبر الفترات",
            "score_section": "التقييم المالي",
            "scenarios_section": "السيناريوهات المستقبلية",
            "score_lbl": "الدرجة",
            "grade_lbl": "التقدير",
            "scenarios": "السيناريوهات",
            "scenario_growth": "النمو",
            "scenario_rev": "الإيراد المتوقع",
            "scenario_net": "صافي الربح المتوقع",
            "forecast": "التنبؤات والتوقعات المستقبلية",
            "forecast_note": "القيم المتوقعة تقديرية (انحدار خطي) وتظهر بالخط البرتقالي المتقطع في الرسم",
            "item_col": "البند",
            "ratio_col": "النسبة",
            "value_col": "القيمة",
            "change_col": "التغير المتوقع",
            "trend_col": "الاتجاه",
            "current_col": "الحالي",
            "projected_col": "متوقع",
            "up": "صاعد",
            "down": "هابط",
            "flat": "مستقر",
            "advice": "التوصيات",
            "critical": "حرج",
            "warning": "تنبيه",
            "info": "إيجابي",
            "solutions": "حلول مقترحة عند التدني أو الخسارة",
            "no_issues": "لا توجد مؤشرات سلبية — استمر في المتابعة الدورية",
            "statements": "القوائم المالية",
            "is_title": "قائمة الدخل",
            "bs_title": "قائمة المركز المالي",
            "bs_assets": "الأصول",
            "bs_liab_eq": "الالتزامات وحقوق الملكية",
            "cf_title": "قائمة التدفقات النقدية",
            "eq_title": "قائمة التغير في حقوق الملكية",
            "balanced": "متوازنة ✓",
            "derived_balanced": "القوائم متوازنة — مبنية من مقاييس الملف ✓",
            "derived_unbalanced":
                "القوائم غير متوازنة — مبنية من مقاييس الملف (الفرق: {diff:,.2f})",
            "unbalanced": "غير متوازنة (الفرق: {diff:,.2f})",
            "total": "الإجمالي",
            "tb_title": "ميزان المراجعة",
            "tb_balanced": "الميزان متوازن ✓",
            "detail": "التفاصيل",
            "notes": "ملاحظات",
            "ifrs_prepared": "مُعد وفق IFRS",
            "mgmt_signature": "توقيع الإدارة",
            "sig_date": "التاريخ",
        }
    return {
        "title": "Financial Report",
        "period": "Analysis period",
        "entity": "Entity: {name}",            "issued": "Created",
            "tagline": "Your Smart AI Financial Analyst",
            "language": "Report language",
        "source": "Source: {name}",
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
        "key_findings": "Key Findings",
        "strategic_recs": "Strategic Recommendations",
        "ratio_insights": "Ratio Analysis",
        "what_q": "What is it?",
        "why_q": "Why it matters:",
        "opinion_q": "Verdict:",
        "ifrs_title": "Standards Framework — International Financial Reporting Standards (IFRS)",
        "bench_title": "Ratio Alignment with Reference Benchmarks",
        "bench_col_ratio": "Ratio", "bench_col_value": "Value",
        "bench_col_ref": "Reference", "bench_col_status": "Status",
        "bench_note": "Anchors follow the adopted analysis methodology: ideal current ratio 2.0, interest coverage ≥ 3.0×, collection ≤ 90 days, leverage ≤ 70%... — ✓ Aligned · ≈ Near · ✗ Off benchmark.",
        "ifrs_col_code": "Ref.",
        "ifrs_col_std": "Standard",
        "ifrs_col_rel": "Relevance to this analysis",
        "ifrs_ref": "IFRS reference:",
        "check_col": "Check",
        "check_result_col": "Result",
        "consistency": "Consistency checks",
        "wcq_period": "Period", "wcq_net": "Net profit",
        "wcq_cf": "Stated operating cash flow",
        "wcq_ratio": "Conversion",
        "wcq_verdict": "Verdict",
        "wcq_verdicts": {"ok": "Healthy ✓", "watch": "Watch ≈", "bad": "Weak ✗"},
        "series": "Analytical Charts",
        "evo_title": "Revenue & Net Profit Evolution Across Years",
        "evo_revenue": "Revenue",
        "evo_net": "Net Profit",
            "dash_section": "Analytics Dashboard",
            "dash_expenses": "Expense Mix",
            "dash_expenses_center": "Expenses",
            "dash_bullets": "Ratios vs Reference Benchmarks (anchor = 1.00)",
            "dash_cost": "Revenue Composition: Cost vs Result",
            "activity_title": "Cash Conversion Cycle & Components Trend",
            "score_section": "Financial Score",
        "scenarios_section": "Future Scenarios",
        "score_lbl": "Score",
        "grade_lbl": "Grade",
        "scenarios": "Scenarios",
        "scenario_growth": "Growth",
        "scenario_rev": "Projected revenue",
        "scenario_net": "Projected net",
        "forecast": "Forecast & Projections",
        "forecast_note": "Projected values are estimates (linear regression); dashed orange in chart",
        "item_col": "Item",
        "ratio_col": "Ratio",
        "value_col": "Value",
        "change_col": "Expected Change",
        "trend_col": "Trend",
        "current_col": "Current",
        "projected_col": "Projected",
        "up": "Up",
        "down": "Down",
        "flat": "Flat",
        "advice": "Recommendations",
        "critical": "Critical",
        "warning": "Warning",
        "info": "Positive",
        "solutions": "Suggested solutions for losses / weak results",
        "no_issues": "No negative indicators — keep periodic monitoring",
        "statements": "Financial Statements",
        "is_title": "Income Statement",
        "bs_title": "Statement of Financial Position",
        "bs_assets": "Assets",
        "bs_liab_eq": "Liabilities & Equity",
        "cf_title": "Cash Flow Statement",
        "eq_title": "Statement of Changes in Equity",            "balanced": "Balanced ✓",
            "derived_balanced": "Statements balanced — built from the file's own figures ✓",
            "derived_unbalanced":
                "Statements unbalanced — built from the file's own figures (gap: {diff:,.2f})",
        "unbalanced": "Unbalanced (difference: {diff:,.2f})",
        "total": "Total",
        "tb_title": "Trial Balance",
        "tb_balanced": "Trial balance is balanced ✓",
        "detail": "Details",
        "notes": "Notes",
        "ifrs_prepared": "Prepared in accordance with IFRS",
        "mgmt_signature": "Management signature",
        "sig_date": "Date",
    }


def _comparison_labels(lang: str) -> dict:
    if lang == "ar":
        return {
            "title": "تقرير المقارنة المالية",
            "vs": "مقارنة بين {a} و {b}",
            "kpis": "مقارنة المؤشرات الرئيسية",
            "ratios": "مقارنة النسب المالية",
            "series": "مقارنة الرسوم البيانية التحليلية",
            "item": "البند",
            "base_col": "المرجع",
            "target_col": "المقارن",
            "change_col": "نسبة التغير",
            "up": "صاعد",
            "down": "هابط",
            "flat": "مستقر",
        }
    return {
        "title": "Financial Comparison Report",
        "vs": "Comparing {a} and {b}",
        "kpis": "Key Indicators Comparison",
        "ratios": "Financial Ratios Comparison",
        "series": "Analytical Charts Comparison",
        "item": "Item",
        "base_col": "Baseline",
        "target_col": "Comparison",
        "change_col": "Change %",
        "up": "Up",
        "down": "Down",
        "flat": "Flat",
    }


def _row_scalars(row: dict) -> tuple[float | None, float | None]:
    """Scalar base/target for either row shape (kpi rows or series rows)."""
    if "base" in row and "target" in row:
        return row["base"], row["target"]
    base_values = row.get("base_values") or []
    target_values = row.get("target_values") or []
    base = base_values[-1] if base_values else None
    target = target_values[-1] if target_values else None
    return base, target


def _delta_table(
    heading: str,
    rows: dict,
    L: dict,
    lang: str,
    rtl: bool,
    story: list,
    as_percent: bool = False,
) -> None:
    """Append one side-by-side delta table (heading + rows) to the story."""
    if not rows:
        return
    _section(story, heading, "cmp", rtl)
    data = [[L["item"], L["base_col"], L["target_col"], L["change_col"]]]
    change_rows = []
    for i, row in enumerate(rows.values()):
        base, target = _row_scalars(row)
        if base is None or target is None:
            continue
        name = row.get(lang) or row["en"]
        change = row["change_pct"]
        if as_percent:
            delta = target - base
            change_text = f"{delta:+.1f} pt"
        else:
            change_text = f"{change:+.1f}%"
        trend = L["up"] if change > 0.05 else (L["down"] if change < -0.05 else L["flat"])
        data.append([
            _shape(str(name)),
            f"{base:,.2f}",
            f"{target:,.2f}",
            _shape(change_text + " — " + trend),
        ])
        change_rows.append((i + 1, change))
    extra = []
    for grid_row, change in change_rows:
        color = GREEN if change > 0.05 else RED if change < -0.05 else MUTED
        col = 0 if rtl else 3  # change column flips with the table
        extra.append(("TEXTCOLOR", (col, grid_row), (col, grid_row), color))
    story.append(_rtl_table(data, rtl, col_widths=[52 * mm, 42 * mm, 42 * mm, 42 * mm]))
    story.append(Spacer(1, 6 * mm))


def build_comparison_report(payload: dict, out_path: Path, lang: str = "ar") -> Path:
    """Generate the side-by-side comparison PDF from a compare_analyses payload."""
    _register_font()
    glyph_guard_begin()

    L = _comparison_labels(lang)
    rtl = lang == "ar"

    title_style = ParagraphStyle(
        "title", fontName=_FONT_BOLD_NAME, fontSize=20, leading=26,
        textColor=TEAL_DARK, alignment=TA_RIGHT if rtl else TA_LEFT)
    body = ParagraphStyle("body", fontName=_FONT_NAME, fontSize=11, leading=16,
                          alignment=TA_RIGHT if rtl else TA_LEFT)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []

    story.append(Paragraph(_shape(L["title"]), title_style))
    sub = L["vs"].format(a=payload["base"]["filename"], b=payload["target"]["filename"])
    story.append(Paragraph(_shape(sub), body))
    story.append(Spacer(1, 8 * mm))

    _delta_table(L["kpis"], payload.get("kpis", {}), L, lang, rtl, story)
    _delta_table(L["ratios"], payload.get("ratios", {}), L, lang, rtl, story, as_percent=True)

    # series: delta table + dual mini-charts
    series = payload.get("series", {})
    if series:
        _delta_table(L["series"], series, L, lang, rtl, story)
        for concept, s in list(series.items())[:4]:
            img = _chart(
                (s.get("base_values") or [])[-6:],
                None,
                str(s.get(lang) or s["en"]),
            )
            if img:
                story.append(img)
                story.append(Spacer(1, 3 * mm))

    glyph_guard_flush()
    doc.build(story)
    return out_path


# ---------------------------------------------------------------------------
# Main analysis report (dashboard-styled, CMRRS-style opening)
# ---------------------------------------------------------------------------

def _logo_image() -> Image | None:
    """Platform logo (PNG render of the SVG) for report headers, if available."""
    logo = Path(__file__).resolve().parent.parent / "app" / "assets" / "logo.png"
    if not logo.exists():
        logo = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo.png"
    if not logo.exists():
        return None
    try:
        return Image(str(logo), width=16 * mm, height=16 * mm)
    except Exception:
        return None


def _brand_header(L: dict, filename: str, lang: str, rtl: bool,
                  band: str | None = None, period: str | None = None,
                  audit: dict | None = None) -> list:
    """Light-grey brand band: logo + platform + report title + meta row.
    Grey (not the old teal/green) so the coloured logo stays legible.
    When the quality gate stored warnings (audit["warnings"]), an amber
    band under the header lists them — the printed report must not look
    cleaner than the platform's own verdict."""
    from datetime import date

    logo = _logo_image()
    platform_name = "المنصة المالية الذكية" if lang == "ar" else "Smart Financial Platform"

    head = [
        Paragraph(_shape(platform_name), ParagraphStyle(
            "tb", fontName=_FONT_NAME, fontSize=10, leading=13, textColor=TEAL_DARK)),
        Paragraph(_shape(L["tagline"]), ParagraphStyle(
            "tg", fontName=_FONT_NAME, fontSize=8.5, leading=11,
            textColor=colors.HexColor("#b45309"))),
        Paragraph(_shape(L["title"]), ParagraphStyle(
            "th", fontName=_FONT_BOLD_NAME, fontSize=17, leading=22, textColor=INK)),
        Paragraph(_shape(L["entity"].format(name=filename)), ParagraphStyle(
            "ts", fontName=_FONT_NAME, fontSize=10, leading=14, textColor=INK)),
    ]

    def _meta(text: str, style_name: str) -> Paragraph:
        return Paragraph(_shape(text), ParagraphStyle(
            style_name, fontName=_FONT_NAME, fontSize=9, leading=12,
            textColor=MUTED, alignment=TA_RIGHT if rtl else TA_LEFT))

    meta = [
        _meta(f"{L['issued']}: {date.today():%Y-%m-%d}", "m1"),
    ]
    if period:
        meta.append(_meta(f"{L['period']}: {period}", "mp"))
    meta.append(
        _meta(f"{L['language']}: {'العربية' if lang == 'ar' else 'English'}", "m2"))
    if band:
        meta.append(_meta(band, "mb"))
    inner = [head, meta]
    header = Table(
        [[inner, logo or ""]],
        colWidths=[150 * mm, 28 * mm] if logo else [178 * mm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef1f5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    out: list = [header]
    if audit:
        for w in (audit.get("warnings") or [])[:4]:
            msg = str(w.get("ar") if lang == "ar" else w.get("en"))
            out.append(Paragraph(
                _shape(f"⚠ {msg}"),
                ParagraphStyle(
                    "audit-warn", fontName=_FONT_NAME, fontSize=9, leading=13,
                    textColor=AMBER, alignment=TA_RIGHT if rtl else TA_LEFT,
                    backColor=AMBER_BG, borderPadding=(4, 6),
                    spaceBefore=2),
            ))
    out.append(Spacer(1, 5 * mm))
    return out


def _benchmark_section(story: list, alignment: dict | None,
                       L: dict, lang: str, rtl: bool) -> None:
    """Benchmark-alignment table (مواءمة معيارية): every computed ratio
    against its reference anchor (ideal current ratio 2, interest coverage
    3x, ...) with a colour-coded verdict."""
    if not alignment or not alignment.get("rows"):
        return
    _section(story, L["bench_title"], "bench", rtl)
    rows = [[L["bench_col_ratio"], L["bench_col_value"],
             L["bench_col_ref"], L["bench_col_status"]]]
    color_map = {"good": GREEN, "neutral": AMBER, "bad": RED}
    extra = []
    for i, r in enumerate(alignment["rows"], 1):
        rows.append([
            _shape(str(r["label"])),
            r["value"],
            _shape(str(r["benchmark"])),
            _shape(f"{r['symbol']} {r['status']}"),
        ])
        extra.append(("TEXTCOLOR", (3, i), (3, i), color_map[r["verdict"]]))
    story.append(_rtl_table(rows, rtl,
                            col_widths=[52 * mm, 30 * mm, 66 * mm, 30 * mm],
                            extra=extra))
    small = ParagraphStyle(
        "bench-note", fontName=_FONT_NAME, fontSize=8.5, leading=12,
        textColor=MUTED, alignment=TA_RIGHT if rtl else TA_LEFT)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(_shape(L["bench_note"]), small))
    story.append(Spacer(1, 4 * mm))


_YCMP_TREND_LABELS = {
    "ar": {"up": "تحسّن", "down": "تراجع", "flat": "مستقر",
           "depth": "شدة اللون = حجم التغير",
           "note": ("الأخضر = تحسن", "الأحمر = تراجع")},
    "en": {"up": "improved", "down": "declined", "flat": "flat",
           "depth": "colour depth = change size",
           "note": ("Green = improved", "Red = declined")},
}


def _dir_drawing(direction: str, color, w: float = 4.2 * mm,
                 h: float = 3.2 * mm) -> Drawing:
    """The platform's direction affordance as a REAL vector drawing —
    majalla carries no geometric-arrow glyphs, so up/down are filled
    isosceles triangles and flat is a neutral dash. Font-independent
    (the PDF counterpart of the deck's _dir_marker shapes)."""
    d = Drawing(w, h)
    if direction == "up":
        d.add(Polygon(points=[0, 0, w, 0, w / 2.0, h], fillColor=color,
                      strokeColor=None))
    elif direction == "down":
        d.add(Polygon(points=[0, h, w, h, w / 2.0, 0], fillColor=color,
                      strokeColor=None))
    else:
        d.add(Polygon(points=[0, h / 2.0 - 0.5 * mm, w, h / 2.0 - 0.5 * mm,
                              w, h / 2.0 + 0.5 * mm, 0, h / 2.0 + 0.5 * mm],
                      fillColor=color, strokeColor=None))
    return d


def _dir_cell(direction: str, label: str, color, rtl: bool) -> list:
    """Trend label cell: a vector direction shape stacked above the bold
    label — the platform's ▲/▼/◄► affordance with real geometry, no glyphs.
    (Every item in a ReportLab list-cell must be a flowable, so the label
    is wrapped in a Paragraph.)"""
    return [
        _dir_drawing(direction, color),
        Paragraph(
            _shape(str(label)),
            ParagraphStyle(
                "ycmp-dir-label", fontName=_FONT_BOLD_NAME, fontSize=8.5,
                leading=11, alignment=TA_RIGHT if rtl else TA_LEFT,
            ),
        ),
    ]


def _dir_legend(lang: str, rtl: bool) -> Table:
    """«دليل الاتجاه» strip above the yearly comparison: real triangle/dash
    shapes beside their words (separate cells, no nested tables) + the
    colour-depth rule — mirroring the deck's _marker_legend."""
    T = _YCMP_TREND_LABELS[lang]
    cells = [
        _dir_drawing("up", GREEN), _shape(T["up"]),
        _dir_drawing("down", RED), _shape(T["down"]),
        _dir_drawing("flat", MUTED), _shape(T["flat"]),
        _shape(T["depth"]),
    ]
    if lang == "ar":
        cells.append(_shape(f"{T['note'][0]} · {T['note'][1]}"))
    widths = [7 * mm, 14 * mm, 7 * mm, 14 * mm, 7 * mm, 15 * mm, 30 * mm]
    if lang == "ar":
        widths.append(34 * mm)
    if rtl:
        cells = list(reversed(cells))
        widths = list(reversed(widths))
    table = Table([cells], colWidths=widths,
                  hAlign="RIGHT" if rtl else "LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#475569")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


def _yearly_comparison_section(story: list, comp: dict | None, L: dict,
                               lang: str, rtl: bool) -> None:
    """CMRRS-style horizontal + vertical comparative table."""
    if not comp or not comp.get("rows"):
        return
    _section(story, comp["title"], "ycmp", rtl)
    # colour legend with REAL direction shapes above the table — mirrors
    # the platform's «دليل الألوان» and the deck's shape legend
    story.append(_dir_legend(lang, rtl))
    story.append(Spacer(1, 2 * mm))

    header = list(comp["columns"])
    change_col = 4   # التغير بالقيمة (بعد إزاحة عمود الاتجاه)
    pct_col = 5      # التغير بالنسبة
    # rows grouped per statement into SEPARATE closed blocks — NOT one
    # mixed list: قائمة الدخل table, then قائمة المركز المالي table, each
    # opened by its own caption (visual closure between the two statements)
    stmt_titles = {"income": L["is_title"], "balance": L["bs_title"]}
    groups: list[tuple[str, list]] = []
    for row in comp["rows"]:
        stmt = row.get("stmt") or "income"
        if not groups or groups[-1][0] != stmt:
            groups.append((stmt, []))
        groups[-1][1].append(row)

    for gi, (stmt, group_rows) in enumerate(groups):
        story.append(Paragraph(
            _shape(str(stmt_titles.get(stmt, ""))),
            ParagraphStyle(
                f"ycmp-band-{gi}", fontName=_FONT_BOLD_NAME, fontSize=10.5,
                leading=15, textColor=TEAL_DARK,
                alignment=TA_RIGHT if rtl else TA_LEFT,
                spaceBefore=5 if gi else 1, spaceAfter=3,
            ),
        ))
        data = [[_shape(str(h)) for h in header]]
        g_good, g_bad = [], []
        for i, row in enumerate(group_rows):
            pct_val = float(row.get("change_pct_val") or 0.0)
            if abs(pct_val) < 0.05:
                direction, v_color = "flat", MUTED
            else:
                direction = "up" if pct_val > 0 else "down"
                v_color = GREEN if row.get("color") == "good" else RED
            cells = [
                _dir_cell(direction, row["label"], v_color, rtl),
                row["curr"], row["prev"],
                row["change"], row["change_pct"],
                row["pct_curr"], row["pct_prev"],
            ]
            data.append(cells)
            if row.get("color") == "good":
                g_good.append(i + 1)
            elif row.get("color") == "bad":
                g_bad.append(i + 1)

        extra = [
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (1, 1), (1, -1), _FONT_BOLD_NAME),
        ]
        for r in g_good:
            extra.append(("TEXTCOLOR", (change_col, r), (pct_col, r), GREEN))
        for r in g_bad:
            extra.append(("TEXTCOLOR", (change_col, r), (pct_col, r), RED))

        story.append(_rtl_table(
            data, rtl,
            col_widths=[32 * mm, 26 * mm, 26 * mm, 26 * mm, 22 * mm, 21 * mm, 20 * mm],
            extra=extra,
        ))
        story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        _shape(str(comp.get("note", ""))),
        ParagraphStyle("ycmp-note", fontName=_FONT_NAME, fontSize=8, leading=11,
                       alignment=TA_RIGHT if rtl else TA_LEFT),
    ))
    story.append(Spacer(1, 4 * mm))

    # ---- annual growth table (multi-year statements) ----------------------
    years = comp.get("years") or []
    growth_rows = [r for r in (comp.get("rows") or []) if r.get("points")]
    if len(years) >= 2 and len(growth_rows) >= 2:
        _section(story, str(comp.get("growth_title") or ""), "ygr", rtl)
        n = len(years)
        has_fc = bool(comp.get("forecast_label"))
        head = [str(comp["columns"][0])] + [str(y) for y in years]
        if has_fc:
            head.append(str(comp["forecast_label"]))
        gdata = [[_shape(h) for h in head]]
        cell_style = ParagraphStyle(
            "ygr-cell", fontName=_FONT_NAME, fontSize=8.5, leading=10.5,
            alignment=TA_CENTER)
        for r in growth_rows:
            pts = r.get("points") or []
            # concept absent from early years: pad the leading cells empty
            cells: list = ([_shape(str(r["label"]))]
                           + [""] * (len(years) - len(pts)))
            for k, p in enumerate(pts):
                g = p.get("growth")
                if not g:
                    cells.append(str(p["value"]))
                    continue
                # direction vs the PRIOR year decides the judgement colour
                prev_raw = pts[k - 1]["raw"] if k > 0 else None
                if prev_raw:
                    rose = p["raw"] > prev_raw
                    is_good = (not rose) if r.get("is_cost") else rose
                    color = "#059669" if is_good else "#dc2626"
                else:
                    color = "#334155"
                cells.append(Paragraph(
                    f"{p['value']}<br/><font size=7 color={color}>{g}</font>",
                    cell_style))
            if has_fc:
                fc = r.get("forecast")
                if fc:
                    # amber = forecast (same colour as the deck's dashed
                    # projection lines) — clearly an estimate, not a fact
                    cells.append(Paragraph(
                        f"{fc['value']}<br/>"
                        f"<font size=7 color=#f59e0b>{fc['growth']}</font>",
                        cell_style))
                else:
                    cells.append("—")
            gdata.append(cells)
        if has_fc:
            # fit A4's 174mm usable width: narrower label + year columns so
            # the forecast column fits without overflowing the margins
            col_widths = ([28 * mm]
                          + [((174 - 28 - 24) / n) * mm for _ in range(n)]
                          + [24 * mm])
        else:
            col_widths = [34 * mm] + [24 * mm] * n
        story.append(_rtl_table(
            gdata, rtl,
            col_widths=col_widths,
            extra=[("FONTSIZE", (0, 0), (-1, -1), 8.5),
                   ("FONTNAME", (0, 1), (0, -1), _FONT_BOLD_NAME)],
        ))
        story.append(Spacer(1, 3 * mm))
        if comp.get("growth_note"):
            story.append(Paragraph(
                _shape(str(comp["growth_note"])),
                ParagraphStyle("ygr-note", fontName=_FONT_NAME, fontSize=8,
                               leading=11, textColor=MUTED,
                               alignment=TA_RIGHT if rtl else TA_LEFT),
            ))
        story.append(Spacer(1, 4 * mm))


def _ifrs_section(story: list, L: dict, lang: str, rtl: bool,
                  result: dict, statements: dict | None) -> None:
    """IFRS framework section: basis of preparation + the standards this
    analysis actually touches (detected from its concepts/statements)."""
    standards = detect_ifrs(result, statements)
    _section(story, L["ifrs_title"], "ifrs", rtl)
    basis_style = ParagraphStyle(
        "ifrs-basis", fontName=_FONT_NAME, fontSize=9.5, leading=14.5,
        alignment=TA_RIGHT if rtl else TA_LEFT, textColor=INK)
    story.append(Paragraph(_shape(basis_of_preparation(lang)), basis_style))
    story.append(Spacer(1, 3 * mm))
    rows = [[L["ifrs_col_code"], L["ifrs_col_std"], L["ifrs_col_rel"]]]
    for s in standards:
        title = s["ar"] if lang == "ar" else s["en"]
        why = s["why_ar"] if lang == "ar" else s["why_en"]
        rows.append([s["code"], _shape(str(title)), _shape(str(why))])
    story.append(_rtl_table(rows, rtl, col_widths=[24 * mm, 62 * mm, 92 * mm]))
    story.append(Spacer(1, 4 * mm))


def _ratio_insights_section(story: list, insights: list | None, checks: list | None,
                            L: dict, lang: str, rtl: bool) -> None:
    """CMRRS-style interpretive ratio cards + statement consistency checks."""
    if not insights and not checks:
        return
    _section(story, L["ratio_insights"], "rins", rtl)
    small = ParagraphStyle("small-rins", fontName=_FONT_NAME, fontSize=9, leading=13,
                           alignment=TA_RIGHT if rtl else TA_LEFT)

    if checks:
        rows = [[L["check_col"], L["check_result_col"]]]
        bad_rows = []
        for i, c in enumerate(checks):
            rows.append([
                _shape(str(c["label"])),
                _shape(("✓" if c["ok"] else "✗") + " " + str(c["detail"])),
            ])
            if not c["ok"]:
                bad_rows.append(i + 1)
        extra = [("TEXTCOLOR", (0, r), (-1, r), GREEN if True else RED) for r in []]
        extra = [("TEXTCOLOR", (1, r), (1, r), RED) for r in bad_rows]
        story.append(_rtl_table(rows, rtl, col_widths=[62 * mm, 116 * mm], extra=extra))
        story.append(Spacer(1, 4 * mm))

    for card in insights or []:
        color = {"good": GREEN, "bad": RED, "neutral": MUTED}.get(card["verdict"], MUTED)
        if card.get("is_percent"):
            val_txt = f"{card['value']:,.2f}%"
        elif card.get("is_days"):
            val_txt = f"{card['value']:,.0f} {'يوم' if lang == 'ar' else 'days'}"
        else:
            val_txt = f"{card['value']:,.2f}x"
        head = Paragraph(
            f"<b>{_shape(str(card['label']))}</b>  "
            f"<font size=12 color={color}><b>{val_txt}</b></font>",
            ParagraphStyle(f"ri-h-{card['key']}", fontName=_FONT_BOLD_NAME,
                           fontSize=11, leading=15, alignment=TA_RIGHT if rtl else TA_LEFT),
        )
        # AR (visual order): body first in the string so the label draws at the
        # line start (right side). EN keeps label-first reading order.
        # Verdict badge (جيد/متوسط/ضعيف): ONE chip style for every rating —
        # solid platform teal with white text — so all cards carry the same
        # badge colour and their labels do the rating work. Badge sits at the
        # line end of the header row, mirroring the web cards.
        b = BADGES.get(card["verdict"], BADGES["neutral"])
        btxt = _shape(b["ar"]) if lang == "ar" else b["en"]
        badge = Paragraph(btxt, ParagraphStyle(
            "badge-rins", fontName=_FONT_BOLD_NAME, fontSize=9.5, leading=13,
            alignment=TA_CENTER, textColor=colors.white))
        what_body = _shape(str(card['what']))
        why_body = _shape(str(card['why']))
        op_body = _shape(str(card['opinion']))
        lbl_what = _shape(L['what_q']) if rtl else L['what_q']
        lbl_why = _shape(L['why_q']) if rtl else L['why_q']
        lbl_op = _shape(L['opinion_q']) if rtl else L['opinion_q']
        what = Paragraph(
            f"{what_body} {lbl_what}" if rtl else f"{lbl_what} {what_body}", small)
        why = Paragraph(
            f"{why_body} {lbl_why}" if rtl else f"{lbl_why} {why_body}", small)
        op = Paragraph(
            f"<font color={color}>{op_body}</font> {lbl_op}" if rtl
            else f"{lbl_op} <font color={color}>{op_body}</font>", small)
        if card.get("ifrs"):
            ref_val = _shape(str(card["ifrs"])) if rtl else str(card["ifrs"])
            ref_lbl = _shape(L["ifrs_ref"]) if rtl else L["ifrs_ref"]
            ref = Paragraph(
                f"<font size=8.5 color={MUTED}>{ref_lbl} {ref_val}</font>", small)
            box_rows = [[head, badge], [what, ""], [why, ""], [op, ""],
                        [ref, ""]]
        else:
            box_rows = [[head, badge], [what, ""], [why, ""], [op, ""]]
        box = Table(
            box_rows,
            colWidths=[148 * mm, 30 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), TEAL_SOFT),
                ("BOX", (0, 0), (-1, -1), 0.75, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (0, 0), (0, -1), "RIGHT" if rtl else "LEFT"),
                # unified badge chip: solid teal block at the header's end
                ("BACKGROUND", (1, 0), (1, 0), TEAL),
                ("BOX", (1, 0), (1, 0), 0.5, TEAL_DARK),
                ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("LEFTPADDING", (1, 0), (1, 0), 4),
                ("RIGHTPADDING", (1, 0), (1, 0), 4),
                ("TOPPADDING", (1, 0), (1, 0), 5),
                ("BOTTOMPADDING", (1, 0), (1, 0), 5),
            ]),
            hAlign="RIGHT" if rtl else "LEFT",
        )
        story.append(box)
        story.append(Spacer(1, 3 * mm))


def _wc_quality_section(story: list, wcq: dict | None, L: dict,
                        lang: str, rtl: bool) -> None:
    """«مؤشر جودة رأس المال العامل»: the stated operating cash flow vs net
    profit per period — a conversion table + verdict colouring + the
    methodology note. Skipped entirely when the file states no operating
    cash flow (wcq is None)."""
    if not wcq or not wcq.get("rows"):
        return
    _section(story, str(wcq["title"]), "wcq", rtl)
    small = ParagraphStyle(
        "wcq-small", fontName=_FONT_NAME, fontSize=9, leading=13,
        alignment=TA_RIGHT if rtl else TA_LEFT)

    head = [L["wcq_period"], L["wcq_net"], L["wcq_cf"], L["wcq_ratio"],
            L["wcq_verdict"]]
    data = [[_shape(str(h)) for h in head]]
    v_bad, v_watch = [], []
    for i, r in enumerate(wcq["rows"]):
        data.append([
            _shape(str(r["period"])), r["net_profit"], r["cf_operating"],
            r["ratio"], _shape(L["wcq_verdicts"][r["verdict"]]),
        ]
        + ([] if len(head) == 5 else [""]))
        if r["verdict"] == "bad":
            v_bad.append(i + 1)
        elif r["verdict"] == "watch":
            v_watch.append(i + 1)
    extra = []
    for r in v_bad:
        extra.append(("TEXTCOLOR", (3, r), (4, r), RED))
        extra.append(("FONTNAME", (3, r), (4, r), _FONT_BOLD_NAME))
    for r in v_watch:
        extra.append(("TEXTCOLOR", (3, r), (4, r), AMBER))
        extra.append(("FONTNAME", (3, r), (4, r), _FONT_BOLD_NAME))
    story.append(_rtl_table(
        data, rtl,
        col_widths=[36 * mm, 40 * mm, 46 * mm, 28 * mm, 28 * mm],
        extra=extra,
    ))
    story.append(Spacer(1, 2.5 * mm))

    color = RED if wcq.get("low") else GREEN
    story.append(Paragraph(
        f"<font color={color}><b>{_shape(str(wcq['opinion']))}</b></font>",
        small))
    story.append(Paragraph(_shape(str(wcq["note"])), small))
    story.append(Spacer(1, 4 * mm))


def _closing_sections(story: list, findings: list | None, recs: list | None,
                      L: dict, lang: str, rtl: bool) -> None:
    """CMRRS-style numbered closing: key findings + strategic recommendations."""
    if not findings and not recs:
        return
    num_style = ParagraphStyle(
        "closing-num", fontName=_FONT_NAME, fontSize=10, leading=17,
        alignment=TA_RIGHT if rtl else TA_LEFT,
    )

    if findings:
        _section(story, L["key_findings"], "kfind", rtl)
        for i, f in enumerate(findings, 1):
            story.append(Paragraph(_shape(f"{i}. {f}"), num_style))
        story.append(Spacer(1, 4 * mm))

    if recs:
        _section(story, L["strategic_recs"], "srecs", rtl)
        for i, r in enumerate(recs, 1):
            story.append(Paragraph(_shape(f"{i}. {r}"), num_style))
        story.append(Spacer(1, 2 * mm))


def _executive_brief_section(story: list, brief: dict | None, L: dict,
                             lang: str, rtl: bool) -> None:
    """CMRRS-style opening: about-the-company card + results summary + strengths."""
    if not brief:
        return
    _section(story, L["exec_brief"], "exec", rtl)

    # about-the-company card (grey box, like the reference report)
    company = brief.get("company") or {}
    about_rows = []
    for lbl_key, val_key in (
        ("activity", "activity"),
        ("size", "size"),
        ("pattern", "pattern"),
    ):
        label = L[lbl_key]
        value = company.get(val_key) or ""
        if value:
            about_rows.append([_shape(label), _shape(str(value))])
    # «ملاءمة الأنشطة»: the detected activity vs its sector's turnover band
    fit = company.get("activity_fit") or {}
    if fit:
        about_rows.append([
            _shape(fit.get("title", "")),
            _shape(f"{fit.get('turnover_txt', '')} · {fit.get('range_txt', '')}"
                   f" — {fit.get('verdict_label', '')}"),
        ])
    if about_rows:
        t = _rtl_table(about_rows, rtl, col_widths=[38 * mm, 140 * mm], extra=[
            ("BACKGROUND", (0, 0), (0, -1), TEAL_SOFT),
            ("FONTNAME", (0, 0), (0, -1), _FONT_BOLD_NAME),
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ], repeat_rows=0)
        story.append(t)
        story.append(Spacer(1, 3 * mm))

    # results summary chips (2-col mini cards)
    results = brief.get("results") or []
    if results:
        _section(story, L["results_summary"], "res", rtl)
        rows = []
        pair = []
        for r in results:
            color = "#dc2626" if r.get("negative") else "#0f766e"
            pair.append(Paragraph(
                f"{_shape(str(r['label']))}<br/><font size=13 color={color}><b>{r['value']}</b></font>",
                ParagraphStyle(f"res-{len(rows)}-{len(pair)}", fontName=_FONT_NAME,
                               fontSize=9.5, leading=13, alignment=TA_RIGHT if rtl else TA_LEFT),
            ))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            pair.append("")
            rows.append(pair)
        grid = Table(rows, colWidths=[85 * mm, 85 * mm], hAlign="RIGHT" if rtl else "LEFT")
        style = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        for r in range(len(rows)):
            for c in range(2):
                style.append(("BACKGROUND", (c, r), (c, r), colors.HexColor("#f8fafc")))
                style.append(("BOX", (c, r), (c, r), 0.75, LINE))
        grid.setStyle(TableStyle(style))
        story.append(grid)
        story.append(Spacer(1, 3 * mm))

    # strengths / weaknesses two columns
    strengths = brief.get("strengths") or []
    weaknesses = brief.get("weaknesses") or []
    if strengths or weaknesses:
        cell_style = ParagraphStyle("sw", fontName=_FONT_NAME, fontSize=9.5,
                                    leading=14, alignment=TA_RIGHT if rtl else TA_LEFT)
        left_items = [
            Paragraph("• " + _shape(str(s)), cell_style) for s in (strengths or ["—"])
        ]
        right_items = [
            Paragraph("• " + _shape(str(w)), cell_style) for w in (weaknesses or ["—"])
        ]
        head_style = ParagraphStyle("swh", fontName=_FONT_BOLD_NAME, fontSize=10.5,
                                    leading=14, alignment=TA_RIGHT if rtl else TA_LEFT)
        sw_table = Table(
            [[Paragraph(_shape("✓ " + L["strengths"]), head_style),
              Paragraph(_shape("! " + L["weaknesses"]), head_style)],
             [left_items, right_items]],
            colWidths=[89 * mm, 89 * mm],
            hAlign="RIGHT" if rtl else "LEFT",
        )
        sw_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), GREEN_BG),
            ("BACKGROUND", (1, 0), (1, -1), ORANGE_BG),
            ("BACKGROUND", (0, 1), (0, 1), colors.white),
            ("BACKGROUND", (1, 1), (1, 1), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ]))
        story.append(sw_table)
        story.append(Spacer(1, 3 * mm))

    # executive paragraph (the CMRRS "خلاصة التنفيذ" equivalent)
    if brief.get("paragraph"):
        p = Table([[Paragraph(_shape(str(brief["paragraph"])), ParagraphStyle(
            "exsum", fontName=_FONT_NAME, fontSize=10, leading=15,
            alignment=TA_RIGHT if rtl else TA_LEFT,
        ))]], colWidths=[178 * mm], hAlign="RIGHT" if rtl else "LEFT")
        p.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BLUE_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(p)
        story.append(Spacer(1, 5 * mm))


def _score_section(story: list, score: dict | None, scenarios: dict | None,
                   L: dict, lang: str, rtl: bool) -> None:
    """Financial score panel + scenarios table mirroring the dashboard."""
    if not score or score.get("score") is None:
        return
    _section(story, L["score_section"], "score", rtl)
    grade = score.get("grade") or {}
    grade_word = grade.get(lang) or grade.get("en") or ""
    grade_hex = {"#10b981": "#059669", "#22c55e": "#059669"}.get(
        grade.get("color", ""), grade.get("color", "#b45309"))

    head = Table(
        [[
            Paragraph(
                f"<font size=22 color={grade_hex}><b>{score['score']:.1f}</b></font><br/>"
                + _shape(f"{L['score_lbl']} / 100"),
                ParagraphStyle("sc1", fontName=_FONT_NAME, fontSize=10, leading=14,
                               alignment=TA_CENTER),
            ),
            Paragraph(
                _shape(f"{L['grade_lbl']}: ") + f"<font color={grade_hex}><b>{_shape(grade_word)}</b></font>",
                ParagraphStyle("sc2", fontName=_FONT_NAME, fontSize=12, leading=16,
                               alignment=TA_CENTER),
            ),
        ]],
        colWidths=[89 * mm, 89 * mm], hAlign="RIGHT" if rtl else "LEFT",
    )
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(head)
    story.append(Spacer(1, 2 * mm))

    # dimension bars
    dims = score.get("dimensions") or []
    if dims:
        bar_style = ParagraphStyle("dim", fontName=_FONT_NAME, fontSize=9.5,
                                   leading=13, alignment=TA_RIGHT if rtl else TA_LEFT)
        dim_rows = []
        for d in dims:
            pct = d["points"] / d["weight"] * 100 if d["weight"] else 0
            dim_rows.append([
                Paragraph(_shape(str(d.get(lang) or d.get("en") or d["key"])), bar_style),
                f"{d['points']:.0f}/{d['weight']}",
                _bar(min(max(pct, 0), 100)),
            ])
        t = _rtl_table(dim_rows, rtl, col_widths=[40 * mm, 22 * mm, 116 * mm], extra=[
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ], repeat_rows=0)
        story.append(t)

    # scenarios
    if scenarios and scenarios.get("scenarios"):
        story.append(Spacer(1, 3 * mm))
        _section(story, L["scenarios_section"], "scn", rtl)
        data = [[L["scenarios"], L["scenario_growth"], L["scenario_rev"], L["scenario_net"]]]
        row_colors = []
        for i, s in enumerate(scenarios["scenarios"]):
            name = s.get(lang) or s.get("en") or s["key"]
            data.append([
                _shape(str(name)),
                _shape(f"{s['growth_pct']:+.1f}%"),
                f"{s['revenue']:,.0f}",
                f"{s['net']:,.0f}",
            ])
            bg = {"optimistic": GREEN_BG, "realistic": BLUE_BG,
                  "conservative": ORANGE_BG}.get(s["key"], colors.white)
            row_colors.append((("BACKGROUND", (0, i + 1), (-1, i + 1), bg),))
        extra = [cmd for group in row_colors for cmd in group]
        story.append(_rtl_table(
            data, rtl,
            col_widths=[40 * mm, 36 * mm, 51 * mm, 51 * mm],
            extra=extra,
        ))
    story.append(Spacer(1, 5 * mm))


def _bar(pct: float, width: str = "100%", color: str = "#0f766e") -> str:
    """HTML-free horizontal bar via a nested single-cell table string is not
    possible; instead return a shaped block string used with a monospace-free
    trick: reportlab Paragraph cannot draw bars, so we emulate with a coloured
    font-size-0 spacer + inline <font> background is unavailable. We therefore
    render the bar as a nested Table in the cell (built by the caller)."""
    # Fallback textual representation (used when a nested table is overkill)
    filled = int(round(pct / 10))
    # •/· ARE carried by the Arabic TTFs; the block glyphs █/░ are not and
    # rendered as boxes in the score bars.
    return "•" * filled + "·" * (10 - filled)


def build_report(
    filename: str,
    result: dict,
    out_path: Path,
    lang: str = "ar",
    notes: str | None = None,
    advisor: dict | None = None,
    statements: dict | None = None,
    score: dict | None = None,
    scenarios: dict | None = None,
    brief: dict | None = None,
    ratio_insights: list | None = None,
    consistency_checks: list | None = None,
    yearly_comparison: dict | None = None,
    key_findings: list | None = None,
    strategic_recs: list | None = None,
    band: str | None = None,
    period: str | None = None,
    audit: dict | None = None,
) -> Path:
    """Generate the styled PDF: executive brief, KPI cards, ratios, charts +
    projections, score & scenarios, recommendations with solutions,
    statements, notes. A4 print-ready with a brand banner and footer.
    ``audit`` (the stored quality-gate record) renders its warnings as an
    amber band under the report header."""
    _register_font()
    glyph_guard_begin()

    L = _labels(lang)
    rtl = lang == "ar"
    platform_name = "المنصة المالية الذكية" if lang == "ar" else "Smart Financial Platform"

    title_style = ParagraphStyle(
        "title", fontName=_FONT_BOLD_NAME, fontSize=20, leading=26,
        textColor=TEAL_DARK, alignment=TA_RIGHT if rtl else TA_LEFT)
    body = ParagraphStyle("body", fontName=_FONT_NAME, fontSize=11, leading=16,
                          alignment=TA_RIGHT if rtl else TA_LEFT)
    small = ParagraphStyle("small", fontName=_FONT_NAME, fontSize=9, leading=13,
                           alignment=TA_RIGHT if rtl else TA_LEFT, textColor=MUTED)
    bullet = ParagraphStyle("bullet", fontName=_FONT_NAME, fontSize=10, leading=15,
                            alignment=TA_RIGHT if rtl else TA_LEFT)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=14 * mm, bottomMargin=18 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"{L['title']} — {filename}",
        author=platform_name,
    )
    story = []

    # ---- brand header band --------------------------------------------------
    if audit is None:
        audit = result.get("audit") if isinstance(result.get("audit"), dict) else None
    story += _brand_header(L, filename, lang, rtl, band=band, period=period,
                           audit=audit)

    # ---- IFRS framework: basis of preparation + applicable standards --------
    _ifrs_section(story, L, lang, rtl, result, statements)

    # ---- executive brief (CMRRS-style opening) -------------------------------
    _executive_brief_section(story, brief, L, lang, rtl)

    # ---- KPI cards ---------------------------------------------------------
    kpis = result.get("kpis", {})
    if kpis:
        _section(story, L["kpis"], "kpis", rtl)
        _kpi_cards(story, kpis, lang, rtl)

    # ---- analytics dashboard (gauge / donut / bullets / stack / trend) ------
    _dashboard_section(story, result, score, L, lang, rtl)

    # ---- ratios table ------------------------------------------------------
    ratios = result.get("ratios", {})
    if ratios:
        _section(story, L["ratios"], "ratios", rtl)
        data = [[L["ratio_col"], L["value_col"]]]
        neg_rows = []
        for i, ratio in enumerate(ratios.values()):
            name = ratio.get(lang) or ratio["en"]
            value = ratio["value"]
            data.append([_shape(str(name)), f"{value:,.2f}"])
            if isinstance(value, (int, float)) and value < 0:
                neg_rows.append(i + 1)
        extra = [("TEXTCOLOR", (0, r), (-1, r), RED) for r in neg_rows]
        # full A4 content width: an over-wide label column starves the value
        # column and the table looks broken next to every other full-width
        # table in this report (analysis, comparison, statements …)
        table = _rtl_table(data, rtl, col_widths=[120 * mm, 50 * mm], extra=extra)
        story.append(table)
        story.append(Spacer(1, 5 * mm))

    # ---- ratio insights (CMRRS-style cards) + consistency checks -----------
    if ratio_insights or consistency_checks:
        _ratio_insights_section(story, ratio_insights, consistency_checks, L, lang, rtl)

    # ---- working-capital (earnings) quality indicator -----------------------
    from .ratio_explain import build_working_capital_quality

    _wc_quality_section(story, build_working_capital_quality(result, lang),
                        L, lang, rtl)

    # ---- benchmark alignment (المواءمة المعيارية) ---------------------------
    if result.get("ratios"):
        _benchmark_section(story, build_benchmark_alignment(result, lang),
                           L, lang, rtl)

    # ---- horizontal & vertical comparative table ---------------------------
    _yearly_comparison_section(story, yearly_comparison, L, lang, rtl)

    # ---- charts (trends) -----------------------------------------------------
    advisor = advisor or {}
    projections_map = {
        p["concept"]: p for p in (advisor.get("projections") or [])
    }
    series = result.get("series", {})
    if series:
        _section(story, L["series"], "series", rtl)
        # «تطور الإيرادات وصافي الربح» FIRST — the two bottom-line series
        # every report must show, across ALL captured years (metrics hold
        # every extracted period; net profit derives via the SAME IFRS 18
        # chain the growth table uses). The generic loop below skips them —
        # no duplicated revenue chart.
        from .ratio_explain import net_profit_series

        metrics = result.get("metrics") or {}
        plabels = [str(x) for x in (result.get("period_labels") or [])]
        evo: list[tuple[str, str, list]] = []
        rev_vals = [float(v) for v in (metrics.get("revenue") or [])]
        if len(rev_vals) >= 2:
            evo.append(("revenue", L["evo_revenue"], rev_vals))
        net_vals = [float(v) for v in net_profit_series(result)]
        if len(net_vals) >= 2:
            evo.append(("net_profit", L["evo_net"], net_vals))
        for concept, title, vals in evo:
            proj = projections_map.get(concept)
            img = _chart(
                vals,
                proj.get("projections") if proj else None,
                title,
                labels=plabels or None,
            )
            if img:
                story.append(img)
                story.append(Spacer(1, 2 * mm))
        skip = {c for c, _, _ in evo}
        others = [(c, s) for c, s in series.items() if c not in skip]
        for concept, s in others[:6]:
            proj = projections_map.get(concept)
            img = _chart(
                s.get("values") or [],
                proj.get("projections") if proj else None,
                str(s.get(lang) or s["en"]),
                labels=plabels or None,
            )
            if img:
                story.append(img)
                story.append(Spacer(1, 2 * mm))
        story.append(Spacer(1, 3 * mm))

    # ---- financial score + scenarios (before forecast, like the UI) ---------
    _score_section(story, score, scenarios, L, lang, rtl)

    if projections_map:
        _section(story, L["forecast"], "fc", rtl)
        story.append(Paragraph(_shape(L["forecast_note"]), small))
        story.append(Spacer(1, 2 * mm))
        data = [[L["item_col"], L["current_col"], L["projected_col"], L["change_col"], L["trend_col"]]]
        trend_colors = []
        for i, (concept, p) in enumerate(projections_map.items()):
            last_proj = p["projections"][-1] if p["projections"] else None
            if not last_proj:
                continue
            trend_word = L["up"] if p["trend"] == "up" else (L["down"] if p["trend"] == "down" else L["flat"])
            proj_txt = " – ".join(f"{x['value']:,.0f}" for x in p["projections"])
            data.append([
                _shape(str(p.get("ar") if lang == "ar" else p.get("en"))),
                f"{p['values'][-1]:,.0f}",
                proj_txt,
                f"{last_proj['change_pct']:+.1f}%",
                _shape(trend_word),
            ])
            color = GREEN if p["trend"] == "up" else RED if p["trend"] == "down" else MUTED
            trend_colors.append((i + 1, color))
        extra = []
        for row, color in trend_colors:
            col = 3 if not rtl else 1  # change_pct column flips in RTL
            extra.append(("TEXTCOLOR", (col, row), (col, row), color))
        story.append(_rtl_table(data, rtl, extra=extra))
        story.append(Spacer(1, 5 * mm))

    # ---- recommendations + solutions ----------------------------------------
    advice = advisor.get("advice") or []
    _section(story, L["advice"], "adv", rtl)
    if advisor.get("headline"):
        story.append(_para(str(advisor["headline"]), rtl, bold=True, style_key="hd"))
        story.append(Spacer(1, 2 * mm))
    if not advice:
        story.append(_para(L["no_issues"], rtl, style_key="noadv"))
    sev_word = {"critical": L["critical"], "warning": L["warning"], "info": L["info"]}
    sev_hex = {"critical": "#dc2626", "warning": "#b45309", "info": "#059669"}
    for a in advice:
        sev = a.get("severity", "info")
        bg = {"critical": RED_BG, "warning": AMBER_BG, "info": GREEN_BG}.get(sev, colors.white)
        text = (
            f"<font color='{sev_hex.get(sev, '#666666')}'><b>[{_shape(sev_word.get(sev, ''))}]</b></font> "
            + _shape(str(a.get(lang) if lang in a else a["ar"]))
        )
        row = Table([[Paragraph(text, ParagraphStyle(
            f"adv-{a['key']}", fontName=_FONT_NAME, fontSize=10, leading=15,
            alignment=TA_RIGHT if rtl else TA_LEFT,
        ))]], colWidths=[178 * mm], hAlign="RIGHT" if rtl else "LEFT")
        row.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(row)
        story.append(Spacer(1, 1.5 * mm))

    solutions = advisor.get("solutions") or []
    if solutions:
        story.append(Spacer(1, 2 * mm))
        _section(story, L["solutions"], "sol", rtl)
        for s in solutions:
            story.append(Paragraph("• " + _shape(str(s)), bullet))

    story.append(Spacer(1, 4 * mm))

    # ---- financial statements ------------------------------------------------
    if statements:
        story.append(PageBreak())
        _section(story, L["statements"], "st", rtl)
        tb = statements.get("trial_balance", {})
        if tb:
            bal = tb.get("balanced")
            unbalanced_txt = L["unbalanced"].format(
                diff=abs(tb.get("total_debit", 0) - tb.get("total_credit", 0)))
            # metrics-derived statements have no trial balance — say what
            # they ARE instead of claiming a TB check that never happened
            if statements.get("derived_from_metrics"):
                txt = (L["derived_balanced"] if bal
                       else L["derived_unbalanced"].format(
                           diff=abs(tb.get("total_debit", 0)
                                    - tb.get("total_credit", 0))))
            else:
                txt = L["tb_balanced"] if bal else unbalanced_txt
            story.append(Paragraph(_shape(txt), small))

        # income statement
        is_data = statements.get("income_statement", {})
        if is_data.get("lines"):
            _section(story, L["is_title"], "is", rtl)
            data = [[L["item_col"], L["value_col"]]]
            bold_rows = []
            neg_rows = []
            for i, ln in enumerate(is_data["lines"]):
                data.append([
                    _shape(str(ln.get(lang) or ln.get("en"))),
                    f"{ln['amount']:,.2f}",
                ])
                if ln.get("bold"):
                    bold_rows.append(i + 1)
                if ln.get("amount", 0) < 0:
                    neg_rows.append(i + 1)
            extra = [
                ("BACKGROUND", (0, r), (-1, r), TEAL_SOFT) for r in bold_rows
            ] + [
                ("TEXTCOLOR", (0, r), (-1, r), RED) for r in neg_rows
            ]
            table = _rtl_table(data, rtl, col_widths=[110 * mm, 40 * mm], extra=extra)
            story.append(table)
            story.append(Spacer(1, 4 * mm))

        # balance sheet
        bs = statements.get("balance_sheet", {})
        if bs.get("assets", {}).get("lines"):
            _section(story, L["bs_title"], "bs", rtl)
            bal_word = L["balanced"] if bs.get("balanced") else L["unbalanced"].format(
                diff=abs(bs.get("difference", 0)))
            story.append(Paragraph(_shape(bal_word), small))
            story.append(Spacer(1, 2 * mm))
            a_lines = bs["assets"]["lines"]
            le_lines = bs["liabilities_equity"]["lines"]
            n = max(len(a_lines), len(le_lines))
            data = [[L["bs_assets"], L["value_col"], L["bs_liab_eq"], L["value_col"]]]
            for i in range(n):
                a = a_lines[i] if i < len(a_lines) else None
                le = le_lines[i] if i < len(le_lines) else None
                data.append([
                    _shape(str(a.get(lang) or a.get("en"))) if a else "",
                    f"{a['amount']:,.2f}" if a else "",
                    _shape(str(le.get(lang) or le.get("en"))) if le else "",
                    f"{le['amount']:,.2f}" if le else "",
                ])
            ta = bs["assets"].get("total")
            tl = bs["liabilities_equity"].get("total")
            total_lbl = _shape(L["total"])
            data.append([
                total_lbl,
                f"{ta:,.2f}" if ta is not None else "",
                total_lbl,
                f"{tl:,.2f}" if tl is not None else "",
            ])
            table = _rtl_table(data, rtl, extra=[
                ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), TEAL_SOFT),
            ])
            story.append(table)
            story.append(Spacer(1, 4 * mm))

        # cash flow by activity
        cf = statements.get("cash_flow", {})
        if cf.get("operating"):
            _section(story, L["cf_title"], "cf", rtl)
            for key, total_label in (
                ("operating", "صافي التدفق التشغيلي" if lang == "ar" else "Net operating flow"),
                ("investing", "صافي التدفق الاستثماري" if lang == "ar" else "Net investing flow"),
                ("financing", "صافي التدفق التمويلي" if lang == "ar" else "Net financing flow"),
                # the file's own FX/other-effects block (US-GAAP statements):
                # absent on TB-derived faces — skipped, never a 0.00 row
                ("other", "صافي أثر العملات والبنود الأخرى" if lang == "ar"
                 else "Net FX and other effects"),
            ):
                act = cf.get(key) or {}
                if not act:
                    continue
                if act.get("label"):
                    story.append(Paragraph(
                        _shape(str(act["label"].get(lang) or act["label"]["en"])),
                        ParagraphStyle(f"cf-{key}", fontName=_FONT_NAME, fontSize=10.5,
                                       leading=15, alignment=TA_RIGHT if rtl else TA_LEFT,
                                       textColor=MUTED),
                    ))
                data = [[L["item_col"], L["value_col"]]]
                for ln in act.get("lines") or []:
                    data.append([
                        _shape(str(ln.get(lang) or ln.get("en"))),
                        f"{ln['amount']:,.2f}",
                    ])
                data.append([_shape(total_label), f"{act.get('total', 0):,.2f}"])
                table = _rtl_table(data, rtl, col_widths=[110 * mm, 40 * mm], extra=[
                    ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), TEAL_SOFT),
                ])
                story.append(table)
                story.append(Spacer(1, 2 * mm))
            nc = cf.get("net_change_label") or {}
            cash_word = "رصيد النقدية" if lang == "ar" else "Cash balance"
            summary_line = (
                str(nc.get(lang) or nc.get("en") or "")
                + f": {cf.get('net_change', 0):,.2f} — {cash_word}: {cf.get('cash_balance', 0):,.2f}"
            )
            story.append(Paragraph(_shape(summary_line), body))
            story.append(Spacer(1, 4 * mm))

        # statement of changes in equity
        eq = statements.get("equity_statement", {})
        if eq.get("lines"):
            _section(story, L["eq_title"], "eq", rtl)
            data = [[L["item_col"], L["value_col"]]]
            bold_rows = []
            for i, ln in enumerate(eq["lines"]):
                data.append([
                    _shape(str(ln.get(lang) or ln.get("en"))),
                    f"{ln['amount']:,.2f}",
                ])
                if ln.get("bold"):
                    bold_rows.append(i + 1)
            data.append([
                _shape("إجمالي حقوق الملكية" if lang == "ar" else "Total equity"),
                f"{eq.get('total', 0):,.2f}",
            ])
            table = _rtl_table(data, rtl, col_widths=[110 * mm, 40 * mm], extra=[
                ("BACKGROUND", (0, r), (-1, r), TEAL_SOFT)
                for r in bold_rows + [len(data) - 1]
            ])
            story.append(table)
            story.append(Spacer(1, 4 * mm))

    # ---- CMRRS-style numbered closing: findings + recommendations -----------
    if key_findings or strategic_recs:
        story.append(PageBreak())
        _closing_sections(story, key_findings, strategic_recs, L, lang, rtl)

    # ---- notes (user free-text notes) ----------------------------------------
    if notes:
        _section(story, L["notes"], "notes", rtl)
        for line in str(notes).splitlines() or [str(notes)]:
            story.append(Paragraph(_shape(str(line)), body))

    # ---- closing: management signature + preparation date ---------------------
    sig_cells = [
        Paragraph(_shape(f"{L['mgmt_signature']}: " + "." * 42), body),
        Paragraph(_shape(f"{L['sig_date']}: {date.today().strftime('%Y/%m/%d')}"), body),
    ]
    sig_widths = [95 * mm, 55 * mm]
    if rtl:
        sig_cells.reverse()
        sig_widths.reverse()
    sig = Table([sig_cells], colWidths=sig_widths, hAlign="RIGHT" if rtl else "LEFT")
    sig.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(sig)

    def _footer(canvas, doc_) -> None:
        """Brand footer on every page: platform name + page number."""
        canvas.saveState()
        canvas.setFont(_FONT_NAME, 8)
        canvas.setFillColor(MUTED)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(16 * mm, 14 * mm, (210 - 16) * mm, 14 * mm)
        canvas.drawRightString(178 * mm if not rtl else 32 * mm, 9.5 * mm, _shape(platform_name))
        # IFRS compliance note — centred in the footer of every printed page
        canvas.drawCentredString(105 * mm, 9.5 * mm, _shape(L["ifrs_prepared"]))
        canvas.drawString(32 * mm if not rtl else 178 * mm, 9.5 * mm, f"{doc_.page}")
        canvas.restoreState()

    glyph_guard_flush()
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path


# ---------------------------------------------------------------------------
# Cross-analysis statistics report
# ---------------------------------------------------------------------------

def _stats_labels(lang: str) -> dict:
    if lang == "ar":
        return {
            "title": "تقرير الإحصاءات العامة",
            "sub": "مقارنة تطور البنود عبر كل التحليلات",
            "concept": "البند",
            "oldest": "أقدم تحليل",
            "latest": "أحدث تحليل",
            "value": "القيمة",
            "change": "التغير",
            "up": "صاعد",
            "down": "هابط",
            "flat": "مستقر",
            "analyses": "التحليلات المحفوظة",
            "nothing": "لا توجد بيانات كافية",
        }
    return {
        "title": "Statistics Report",
        "sub": "Concept evolution across all analyses",
        "concept": "Concept",
        "oldest": "Oldest",
        "latest": "Latest",
        "value": "Value",
        "change": "Change",
        "up": "Up",
        "down": "Down",
        "flat": "Flat",
        "analyses": "Saved analyses",
        "nothing": "Not enough data",
    }


def build_stats_report(payload: dict, out_path: Path, lang: str = "ar") -> Path:
    """Cross-analysis statistics PDF: per-concept first/last/change + chart."""
    _register_font()
    glyph_guard_begin()
    L = _stats_labels(lang)
    rtl = lang == "ar"

    title_style = ParagraphStyle(
        "title", fontName=_FONT_BOLD_NAME, fontSize=19, leading=25,
        textColor=TEAL_DARK, alignment=TA_RIGHT if rtl else TA_LEFT)
    body = ParagraphStyle("body", fontName=_FONT_NAME, fontSize=11, leading=16,
                          alignment=TA_RIGHT if rtl else TA_LEFT)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []
    story.append(Paragraph(_shape(L["title"]), title_style))
    story.append(Paragraph(_shape(L["sub"]), body))
    story.append(Spacer(1, 6 * mm))

    concepts = [
        c for c in (payload.get("concepts") or {}).values()
        if c.get("first") and c.get("last") and c["first"].get("name") != c["last"].get("name")
    ]
    if not concepts:
        story.append(Paragraph(_shape(L["nothing"]), body))
        glyph_guard_flush()
        doc.build(story)
        return out_path

    data = [[L["concept"], L["oldest"], L["value"], L["latest"], L["value"], L["change"]]]
    colors_rows = []
    for i, c in enumerate(concepts):
        change = c.get("change_pct")
        trend_word = L["up"] if c["trend"] == "up" else (L["down"] if c["trend"] == "down" else L["flat"])
        data.append([
            _shape(str(c.get("label") if lang == "ar" else c.get("label_en"))),
            _shape(str(c["first"]["name"])),
            f"{c['first']['value']:,.0f}",
            _shape(str(c["last"]["name"])),
            f"{c['last']['value']:,.0f}",
            _shape(f"{change:+.1f}% — {trend_word}") if change is not None else "—",
        ])
        colors_rows.append((i + 1, GREEN if c["trend"] == "up" else RED if c["trend"] == "down" else MUTED))
    extra = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        # change column is last in LTR, first in RTL (flipped by _rtl_table)
        *[("TEXTCOLOR", (5 if not rtl else 0, r), (5 if not rtl else 0, r), col)
          for r, col in colors_rows],
    ]
    story.append(_rtl_table(data, rtl, extra=extra))
    story.append(Spacer(1, 6 * mm))

    # evolution chart per concept (first vs last as two points + trend)
    for c in concepts[:6]:
        img = _chart(
            [c["first"]["value"], c["last"]["value"]],
            None,
            str(c.get("label") if lang == "ar" else c.get("label_en")),
        )
        if img:
            story.append(img)
            story.append(Spacer(1, 2 * mm))

    # saved analyses list
    _section(story, L["analyses"], "an", rtl)
    analyses = payload.get("analyses") or []
    for a in analyses[:20]:
        story.append(Paragraph(
            "• " + _shape(str(a.get("name", ""))),
            ParagraphStyle("an-item", fontName=_FONT_NAME, fontSize=9.5, leading=14),
        ))

    glyph_guard_flush()
    doc.build(story)
    return out_path


# ---------------------------------------------------------------------------
# Sales-operations PDF (kind === "sales" analyses — the sales dashboard)
# ---------------------------------------------------------------------------

_SALES_L = {
    "ar": {
        "title": "تقرير تحليل المبيعات",
        "sub": "شبكة عمليات مبيعات (مناطق · مناديب · أشهر) — محللة كبانات عمليات وليست قوائم مالية",
        "kpi1": "إجمالي المبيعات", "kpi2": "عدد العمليات",
        "kpi3": "متوسط العملية", "kpi4": "عملاء جدد",
        "unit": "ريال",
        "first_last": "من أول شهر لآخر شهر", "last_month": "آخر شهر",
        "trend": "الاتجاه الشهري", "txn_new": "العمليات والعملاء الجدد شهريًا",
        "next": "التالي (predict)", "peak": "الذروة", "low": "الأدنى",
        "regions": "تحليل المناطق",
        "col_region": "المنطقة", "col_sales": "المبيعات", "col_share": "النصيب",
        "col_txn": "العمليات", "col_avg": "متوسط العملية", "col_growth": "النمو",
        "col_best": "أفضل مندوب", "col_nc": "عملاء جدد", "col_ach": "تحقيق الهدف",
        "reps": "ترتيب المندوبين",
        "col_rep": "المندوب", "col_rank": "#", "col_region2": "المنطقة",
        "products": "الأصناف الأكثر مبيعًا", "col_product": "الصنف",
        "col_top_month": "أفضل شهر", "products_note": "{n} صنفًا — مرتبة بالمبيعات",
        "compare": "مقارنة الفترات — أول 3 أشهر ضد آخر 3 أشهر",
        "cmp_metric": "المؤشر", "cmp_a": "الفترة الأولى (أ)", "cmp_b": "الفترة الأخيرة (ب)",
        "cmp_change": "التغير",
        "lbl_sales": "المبيعات", "lbl_txn": "العمليات", "lbl_avg": "متوسط العملية",
        "lbl_newc": "عملاء جدد",
        "forecast": "التنبؤ بالشهر القادم",
        "forecast_method": "تنبؤ خطي مرجّح على آخر الأشهر",
        "no_forecast": "بيانات غير كافية للتنبؤ",
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
    },
    "en": {
        "title": "Sales Analysis Report",
        "sub": "Sales operations grid (regions · reps · months) — analysed as sales operations, not financial statements",
        "kpi1": "Total sales", "kpi2": "Transactions",
        "kpi3": "Avg. ticket", "kpi4": "New customers",
        "unit": "SAR",
        "first_last": "first to last month", "last_month": "last month",
        "trend": "Monthly sales trend", "txn_new": "Transactions and new customers",
        "next": "Next (forecast)", "peak": "Peak", "low": "Low",
        "regions": "Regions", "col_region": "Region", "col_sales": "Sales",
        "col_share": "Share", "col_txn": "Txns", "col_avg": "Avg",
        "col_growth": "Growth", "col_best": "Best rep", "col_nc": "New", "col_ach": "Achievement",
        "reps": "Sales representatives",
        "col_rep": "Rep", "col_rank": "#", "col_region2": "Region",
        "products": "Top-selling products", "col_product": "Item",
        "col_top_month": "Top month", "products_note": "{n} items — ranked by sales",
        "compare": "Period comparison — first 3 vs last 3 months",
        "cmp_metric": "Metric", "cmp_a": "Period A", "cmp_b": "Period B",
        "cmp_change": "Change",
        "lbl_sales": "Sales", "lbl_txn": "Txns", "lbl_avg": "Avg ticket",
        "lbl_newc": "New customers",
        "forecast": "Next-month forecast",
        "forecast_method": "weighted linear projection of recent months",
        "no_forecast": "not enough data to forecast",
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
    },
}


from .sales_analyzer import slowdown_alert


def _sales_period_compare(monthly: list) -> dict | None:
    """Split monthly rows into first-3 vs last-3 comparison (>=4 months)."""
    if len(monthly) < 4:
        return None
    half = min(3, len(monthly) // 2)
    A = monthly[:half]
    B = monthly[-half:]

    def _d(a: float, b: float) -> float | None:
        return round((b - a) / a * 100, 1) if a else None

    sA, txA = sum(m.get("sales", 0) for m in A), sum(m.get("transactions", 0) for m in A)
    sB, txB = sum(m.get("sales", 0) for m in B), sum(m.get("transactions", 0) for m in B)
    ncA = sum(m.get("new_customers", 0) for m in A)
    ncB = sum(m.get("new_customers", 0) for m in B)
    avgA = round(sA / txA, 2) if txA else None
    avgB = round(sB / txB, 2) if txB else None
    return {
        "a_label": f"{A[0]['month']} - {A[-1]['month']}",
        "b_label": f"{B[0]['month']} - {B[-1]['month']}",
        "rows": [
            {"key": "sales", "a": sA, "b": sB, "d": _d(sA, sB)},
            {"key": "txn", "a": txA, "b": txB, "d": _d(txA, txB)},
            {"key": "avg", "a": avgA, "b": avgB, "d": _d(avgA or 0, avgB or 0) if avgA else None},
            {"key": "newc", "a": ncA, "b": ncB, "d": _d(ncA, ncB)},
        ],
    }


def _sales_slowdown_block(story: list, alert: dict, L: dict, rtl: bool) -> None:
    """The live panel's slowdown alert + likely-cause diagnosis, as a
    coloured callout under the trend chart: red when the latest month is
    already negative, amber for the pre-negative case — exactly the two
    tints the panel uses (sa-alert-slowdown). Text mirrors the on-screen
    sentences verbatim."""
    sd = alert["slowdown"]
    _p = lambda v: f"{v:.1f}"
    if sd["negative"]:
        main = L["sd_main_neg"].format(n=sd["months"], to=_p(sd["to"]))
    else:
        main = L["sd_main"].format(n=sd["months"],
                                   frm=_p(sd["from"]), to=_p(sd["to"]))
    top = alert["top"]
    if top:
        kind = L["sd_region"] if top["kind"] == "region" else L["sd_rep"]
        diag = L["sd_diag"].format(
            label=L["sd_diag_label"], kind=kind, name=str(top["name"]),
            frm=_p(top["from"]), to=_p(top["to"]),
            n=alert["candidates_n"], w0=alert["window"][0],
            w1=alert["window"][-1],
            lever=(L["lever_txns"] if alert["lever"]["key"] == "txns"
                   else L["lever_ticket"]),
            drop=_p(alert["lever"]["drop"]),
        )
    else:
        diag = L["sd_diag_none"]

    neg = sd["negative"]
    bgc = colors.HexColor("#fef2f2") if neg else colors.HexColor("#fffbeb")
    barc = colors.HexColor("#dc2626") if neg else colors.HexColor("#f59e0b")
    txc = colors.HexColor("#991b1b") if neg else colors.HexColor("#92400e")
    txt_style = ParagraphStyle(
        "sd-main", fontName=_FONT_NAME, fontSize=9.5, leading=14,
        textColor=txc, alignment=TA_RIGHT if rtl else TA_LEFT)
    diag_style = ParagraphStyle(
        "sd-diag", fontName=_FONT_NAME, fontSize=8.8, leading=13.5,
        textColor=colors.HexColor("#78350f") if not neg else colors.HexColor("#7f1d1d"),
        alignment=TA_RIGHT if rtl else TA_LEFT)
    w = A4[0] - (16 + 16) * mm
    box = Table(
        [[Paragraph(_shape(main), txt_style)],
         [Paragraph(_shape(diag), diag_style)],
         [Paragraph(_shape(L["sd_threshold"].format(n=alert["threshold"])),
                    ParagraphStyle("sd-th", fontName=_FONT_NAME, fontSize=7.5,
                                   leading=10, textColor=colors.HexColor("#a16207"),
                                   alignment=TA_RIGHT if rtl else TA_LEFT))]],
        colWidths=[w])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bgc),
        ("LINEBEFORE" if rtl else "LINEAFTER", (0, 0), (0, -1), 3, barc),
        ("BOX", (0, 0), (-1, -1), 0.5, barc),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(box)


def build_sales_report(filename: str, sales: dict, out_path: Path,
                       lang: str = "ar", band: str | None = None,
                       notes: str | None = None) -> Path:
    """PDF for a sales-grid analysis (result["kind"]=="sales").

    Mirrors the web sales dashboard: KPI cards with growth, monthly trend
    chart + transactions chart, regions table with shares, salespersons
    ranking, first-3-vs-last-3 period comparison, next-month forecast and
    strengths/weaknesses + recommendations. Arabic RTL via the same
    shaping/guard machinery as the financial report.
    """
    _register_font()
    glyph_guard_begin()

    L = _SALES_L[lang]
    rtl = lang == "ar"
    platform = "المنصة المالية الذكية" if lang == "ar" else "Smart Financial Platform"
    fmt = lambda n: f"{n:,.0f}"

    body = ParagraphStyle("sbody", fontName=_FONT_NAME, fontSize=11, leading=16,
                          alignment=TA_RIGHT if rtl else TA_LEFT)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=14 * mm, bottomMargin=18 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"{L['title']} - {filename}", author=platform,
    )
    story: list = []

    head_style = ParagraphStyle(
        "sh", fontName=_FONT_NAME, fontSize=10, leading=13, textColor=TEAL_DARK,
        alignment=TA_RIGHT if rtl else TA_LEFT)
    story.append(Paragraph(_shape(platform), head_style))
    story.append(Paragraph(
        _shape(L["title"]),
        ParagraphStyle("s-t", fontName=_FONT_BOLD_NAME, fontSize=17, leading=22,
                       textColor=INK, alignment=TA_RIGHT if rtl else TA_LEFT)))
    story.append(Paragraph(_shape(L["sub"]), ParagraphStyle(
        "s-sub", fontName=_FONT_NAME, fontSize=9, leading=12, textColor=MUTED,
        alignment=TA_RIGHT if rtl else TA_LEFT)))
    story.append(Paragraph(_shape(f"{filename} - {date.today():%Y-%m-%d}"
                                  + (f" - {band}" if band else "")), body))
    story.append(Spacer(1, 5 * mm))

    total_sales = sales.get("total_sales") or 0
    total_txn = sales.get("total_transactions") or 0
    monthly = sales.get("monthly") or []

    # ---- KPI cards (HTML labels, like the financial report's grid) -----
    def _growth_chip(g: float, *when: str) -> str:
        """Inline font tag: + ^/v n.n% when — arrows get shaped safely later."""
        w = f" {L[when[0]]}" if when else ""
        return (f"<br/><font size=8><b>{('^' if g >= 0 else 'v')} "
                f"{abs(g):.1f}%{w}</b></font>")

    entries = []
    for k, lbl in (("total_sales", L["kpi1"]), ("total_transactions", L["kpi2"]),
                   ("avg_ticket_overall", L["kpi3"]), ("new_customers", L["kpi4"])):
        v = sales.get(k)
        val = fmt(v) if v else "0"
        unit = f" {L['unit']}" if k in ("total_sales", "avg_ticket_overall") and v else ""
        # coloured delta chips under total sales + transactions
        extra = ""
        if k == "total_sales" and len(monthly) >= 2 and monthly[0].get("sales"):
            g = (monthly[-1]["sales"] - monthly[0]["sales"]) / monthly[0]["sales"] * 100
            extra = _growth_chip(g, "first_last")
        elif k == "total_transactions" and monthly:
            g = monthly[-1].get("growth")
            if g is not None:
                extra = _growth_chip(g, "last_month")

        entries.append(Paragraph(
            f"{_shape(str(lbl))}<br/><font size=15 color=#0f766e><b>{val}{unit}</b></font>{extra}",
            ParagraphStyle(
                f"sk-{k}", fontName=_FONT_NAME, fontSize=10, leading=15,
                alignment=TA_RIGHT if rtl else TA_LEFT)))
    rows = []
    for i in range(0, len(entries), 2):
        pair = entries[i : i + 2]
        if rtl:
            pair = list(reversed(pair))
        pair += [""] * (2 - len(pair))
        rows.append(pair)
    grid = Table(rows, colWidths=[85 * mm, 85 * mm], hAlign="RIGHT" if rtl else "LEFT")
    _kpi_style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 3, colors.white),
    ]
    for r in range(len(rows)):
        for c in range(2):
            _kpi_style += [
                ("BACKGROUND", (c, r), (c, r), TEAL_SOFT),
                ("BOX", (c, r), (c, r), 0.75, LINE),
                ("LINEAFTER" if rtl else "LINEBEFORE", (c, r), (c, r), 3, TEAL),
            ]
    grid.setStyle(TableStyle(_kpi_style))
    story.append(grid)
    story.append(Spacer(1, 5 * mm))

    # section order MIRRORS the live sales dashboard (SalesAnalysis.tsx):
    # trend → transactions/new customers → period comparison → region pie
    # + regions table → rep leaderboard (bars + table) → forecast →
    # recommendations → strengths/weaknesses
    monthly_labels = [str(m["month"]) for m in monthly]

    # ---- 1. monthly trend (area, with forecast slot) -------------------------
    if monthly:
        _section(story, L["trend"], "s-trend", rtl)
        fc0 = sales.get("forecast_next_month") or {}
        # the live dashboard draws this card with the BLUE stroke +
        # translucent area (#2563eb) — not the financial teal chart
        img = _sales_chart(
            [m.get("sales", 0) for m in monthly],
            monthly_labels,
            kind="area",
            forecast=(fc0.get("sales") if fc0.get("sales") else None),
        )
        if img:
            story.append(img)
            pk, lo = sales.get("peak_month"), sales.get("low_month")
            if pk and lo:
                story.append(Paragraph(_shape(
                    f"{L['peak']}: {pk['month']} ({fmt(pk['sales'])})  —  "
                    f"{L['low']}: {lo['month']} ({fmt(lo['sales'])})"), body))
            # the live panel places the slowdown alert + likely-cause
            # diagnosis right under the trend card — mirror that placement
            alert = slowdown_alert(sales)
            if alert:
                story.append(Spacer(1, 2 * mm))
                _sales_slowdown_block(story, alert, L, rtl)
            story.append(Spacer(1, 5 * mm))

    # ---- 2. transactions + new customers (two-series line) -------------------
    if monthly and any(m.get("transactions") for m in monthly):
        _section(story, L["txn_new"], "s-txn", rtl)
        img = _sales_chart(
            [m.get("transactions", 0) for m in monthly],
            monthly_labels,
            values_b=[m.get("new_customers", 0) for m in monthly],
            title_a=L["lbl_txn"],
            title_b=(L["col_nc"] if lang == "en" else "عملاء جدد"),
            kind="line2",
        )
        if img:
            story.append(img)
            story.append(Spacer(1, 5 * mm))

    # ---- 3. period comparison (table + paired bars) ---------------------------
    cmp_ = _sales_period_compare(monthly)
    if cmp_:
        _section(story, L["compare"], "s-cmp", rtl)
        lbl = {"sales": L["lbl_sales"], "txn": L["lbl_txn"],
               "avg": L["lbl_avg"], "newc": L["lbl_newc"]}
        data = [[L["cmp_metric"], L["cmp_a"], L["cmp_b"], L["cmp_change"]]]
        for row in cmp_["rows"]:
            unit_suf = f" {L['unit']}" if row["key"] in ("sales", "avg") else ""
            data.append([
                lbl[row["key"]],
                (fmt(row["a"]) + unit_suf) if row["a"] else "-",
                (fmt(row["b"]) + unit_suf) if row["b"] else "-",
                (f"{'+' if row['d'] >= 0 else ''}{row['d']}%"
                 if row["d"] is not None else "-"),
            ])
        color_rows = []
        for i, row in enumerate(cmp_["rows"], 1):
            if row["d"] is not None:
                color_rows.append(("TEXTCOLOR", (3, i), (3, i),
                                   GREEN if row["d"] >= 0 else RED))
        pkg = ParagraphStyle(
            "s-cmp-sub", fontName=_FONT_NAME, fontSize=9, leading=12,
            textColor=MUTED, alignment=TA_RIGHT if rtl else TA_LEFT)
        story.append(Paragraph(_shape(
            f"A: {cmp_['a_label']}  —  B: {cmp_['b_label']}"), pkg))
        story.append(Spacer(1, 2 * mm))
        story.append(_rtl_table(data, rtl,
                                col_widths=[40 * mm, 50 * mm, 50 * mm, 30 * mm],
                                extra=color_rows))
        # paired A/B bar chart under the table (the dashboard's cmp chart)
        def _cmp_row(key: str) -> dict:
            return next(r for r in cmp_["rows"] if r["key"] == key)

        img = _sales_chart(
            [_cmp_row("avg").get("a") or 0,
             _cmp_row("txn").get("a") or 0,
             _cmp_row("newc").get("a") or 0],
            [],
            values_b=[_cmp_row("avg").get("b") or 0,
                      _cmp_row("txn").get("b") or 0,
                      _cmp_row("newc").get("b") or 0],
            title_a=L["cmp_a"], title_b=L["cmp_b"],
            kind="cbar", bar_names=[
                L["lbl_avg"], L["lbl_txn"], L["lbl_newc"]],
        )
        if img:
            story.append(Spacer(1, 3 * mm))
            story.append(img)
        story.append(Spacer(1, 5 * mm))

    regions = sales.get("regions") or []

    # ---- 4. region share donut + regions table (side by side visually) -------
    if regions:
        _section(story, L["regions"], "s-reg", rtl)
        img = _sales_chart(
            [r.get("sales", 0) for r in regions],
            [], kind="pie",
            bar_names=[str(r["region"]) for r in regions],
        )
        if img:
            story.append(img)
            story.append(Spacer(1, 3 * mm))
        data = [[L["col_region"], L["col_sales"], L["col_share"],
                 L["col_txn"], L["col_avg"], L["col_growth"], L["col_best"]]]
        for r in regions:
            g = r.get("growth")
            data.append([
                str(r["region"]), fmt(r.get("sales", 0)),
                f"{r['share_pct']:.1f}%" if r.get("share_pct") is not None else "-",
                fmt(r.get("transactions", 0)),
                fmt(r["avg_ticket"]) if r.get("avg_ticket") else "-",
                (f"{'+' if (g or 0) >= 0 else ''}{g}%" if g is not None else "-"),
                str(r.get("best_rep") or "-"),
            ])
        story.append(_rtl_table(data, rtl,
                                col_widths=[30 * mm, 28 * mm, 18 * mm,
                                            20 * mm, 26 * mm, 20 * mm, 26 * mm],
                                extra=[("FONTSIZE", (0, 0), (-1, -1), 9)]))
        story.append(Spacer(1, 5 * mm))

    # ---- 5. rep leaderboard (horizontal bars + ranking table) ------------------
    reps = sales.get("reps") or []
    if reps:
        _section(story, L["reps"], "s-reps", rtl)
        img = _sales_chart(
            [r.get("sales", 0) for r in reps],
            [], kind="hbar",
            bar_names=[str(r["rep"]) for r in reps],
        )
        if img:
            story.append(img)
            story.append(Spacer(1, 3 * mm))
        has_t = any(r.get("achievement_pct") is not None for r in reps)
        data = [[L["col_rank"], L["col_rep"], L["col_region2"], L["col_sales"],
                 L["col_growth"], L["col_nc"]] + ([L["col_ach"]] if has_t else [])]
        for i, r in enumerate(reps, 1):
            g = r.get("growth")
            data.append(
                [str(i), str(r["rep"]), str(r.get("region") or "-"),
                 fmt(r.get("sales", 0)),
                 (f"{'+' if (g or 0) >= 0 else ''}{g}%" if g is not None else "-"),
                 fmt(r.get("new_customers", 0))]
                + ([f"{r['achievement_pct']:.1f}%" if r.get("achievement_pct") is not None else "-"]
                   if has_t else [])
            )
        story.append(_rtl_table(data, rtl,
                                extra=[("FONTSIZE", (0, 0), (-1, -1), 9)]))
        note = sales.get("reps_target_note")
        if note:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(_shape(note), ParagraphStyle(
                "st-note", fontName=_FONT_NAME, fontSize=8.5, leading=12,
                textColor=MUTED, alignment=TA_RIGHT if rtl else TA_LEFT)))
        story.append(Spacer(1, 5 * mm))

    # ---- top-selling products (hbar + table — the dashboard's 🛍️ card) ----------
    products = sales.get("products") or []
    if products:
        _section(story, L["products"], "s-products", rtl)
        story.append(Paragraph(_shape(L["products_note"].format(n=len(products))),
                               ParagraphStyle("s-pn", fontName=_FONT_NAME,
                                              fontSize=8.5, leading=12,
                                              textColor=MUTED,
                                              alignment=TA_RIGHT if rtl else TA_LEFT)))
        top_p = products[:8]
        img = _sales_chart(
            [p.get("sales", 0) for p in top_p],
            [], kind="hbar",
            bar_names=[str(p["product"]) for p in top_p],
        )
        if img:
            story.append(img)
            story.append(Spacer(1, 3 * mm))
        data = [[L["col_rank"], L["col_product"], L["col_sales"],
                 L["col_share"], L["col_txn"], L["col_avg"], L["col_top_month"]]]
        for i, p in enumerate(products, 1):
            data.append([
                str(i), str(p["product"]), fmt(p.get("sales", 0)),
                (f"{p['share_pct']:.1f}%" if p.get("share_pct") is not None else "-"),
                fmt(p.get("transactions", 0)),
                fmt(p["avg_ticket"]) if p.get("avg_ticket") else "-",
                str(p.get("top_month") or "-"),
            ])
        story.append(_rtl_table(data, rtl,
                                extra=[("FONTSIZE", (0, 0), (-1, -1), 9)]))
        story.append(Spacer(1, 5 * mm))

    # ---- forecast ------------------------------------------------------------
    fc = sales.get("forecast_next_month") or {}
    if fc.get("sales"):
        _section(story, L["forecast"], "s-fc", rtl)
        g = fc.get("growth")
        story.append(Paragraph(
            f"<font size=15 color=#0f766e><b>{fmt(fc['sales'])} {L['unit']}</b></font>"
            + (f"  <font size=10><b>{('+' if (g or 0) >= 0 else '')}{g}%</b></font>"
               if g is not None else ""),
            body))
        if fc.get("method"):
            story.append(Paragraph(_shape(L["forecast_method"]), ParagraphStyle(
                "s-fm", fontName=_FONT_NAME, fontSize=8.5, leading=12,
                textColor=MUTED, alignment=TA_RIGHT if rtl else TA_LEFT)))
        story.append(Spacer(1, 3 * mm))

    # ---- strengths / weaknesses + recommendations -----------------------------
    strengths = sales.get("strengths") or []
    weaknesses = sales.get("weaknesses") or []
    recs = sales.get("recommendations") or []
    if strengths or weaknesses:
        _section(story, f"{L['strengths']} / {L['weaknesses']}", "s-sw", rtl)
        for s in strengths:
            story.append(Paragraph("- " + _shape(str(s)), body))
        for w in weaknesses:
            story.append(Paragraph("- " + _shape(str(w)), ParagraphStyle(
                "s-wk", parent=body, textColor=AMBER)))
        story.append(Spacer(1, 3 * mm))
    if recs:
        _section(story, L["recs"], "s-recs", rtl)
        for r_ in recs:
            txt = r_.get("ar") if lang == "ar" else r_.get("en")
            story.append(Paragraph("- " + _shape(str(txt)), body))

    if notes:
        _section(story, L["notes"], "s-notes", rtl)
        story.append(Paragraph(_shape(notes), body))

    glyph_guard_flush()
    doc.build(story)
    return out_path
