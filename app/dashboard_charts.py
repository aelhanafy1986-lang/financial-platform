"""Analytical dashboard charts (matplotlib → PNG) shared by the PDF and PPTX
reports — modelled on the reference dashboards the client shared: a score
gauge, an expense-composition donut, ratio bullet bars against benchmark
anchors, value-labelled trend lines and a cost-composition stack.

All builders return raw PNG bytes so either report can embed them as images.
Labels are bilingual with proper Arabic shaping (presentation forms + visual
order) and the deck's brand palette, on a clean grid with data labels — no
chartjunk.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from matplotlib import font_manager

from .fonts import (RENDER_SKIP_CODEPOINTS, UnsupportedGlyphError,
                    ttf_coverage)

# ---- brand palette (matches the deck & PDF identity) -----------------------
NAVY = "#0B2545"
TITLE = "#052F61"
ACCENT = "#0070C0"
GOLD = "#FFC000"
TEAL = "#0F766E"
GREEN = "#059669"
RED = "#DC2626"
MUTED = "#64748B"
GRID = "#E2E8F0"
GHOST = "#E8EDF3"
SOFT = "#F0FDFA"
DONUT_COLORS = [NAVY, ACCENT, TEAL, GOLD, "#5E6B7A", "#93C5FD", "#F59E0B"]

_VERDICT_COLORS = {"good": GREEN, "neutral": GOLD, "bad": RED}

# Same symbol substitutions the reportlab text layer applies: the Arabic
# TTFs carry no ✓ ✗ → ● glyphs, and matplotlib would draw them as hollow
# boxes inside the chart PNG exactly the same way.
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

# Same ceiling set as the deck's benchmark chart: anchors that are MAXIMUMS
# (lower is better) normalise as anchor ÷ value; floors as value ÷ anchor.
CEILING_RATIOS = {
    "debt_ratio", "debt_to_equity", "receivable_days", "inventory_days",
    "payables_turnover", "cash_conversion_cycle",
}

_FONT_PATH: str | None = None


def find_arabic_font() -> str | None:
    """Locate an Arabic-capable TTF for matplotlib text (idempotent)."""
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


def _setup_mpl():
    """Register the Arabic font and neutralise minus signs; returns plt."""
    import matplotlib.pyplot as plt

    font_path = find_arabic_font()
    if font_path:
        try:
            font_manager.fontManager.addfont(font_path)
            family = font_manager.FontProperties(fname=font_path).get_name()
            import matplotlib as mpl
            mpl.rcParams["font.family"] = family
            mpl.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass
    return plt


def _shape(text: str) -> str:
    """Presentation forms + visual order (idempotent, like pptx_report)."""
    if not text:
        return text
    text = str(text)
    if any(0xFB50 <= ord(ch) <= 0xFEFF for ch in text):
        return text
    return get_display(arabic_reshaper.reshape(text))


def mpl_text(text: str) -> str:
    """Text as matplotlib wants it, per ITS OWN text engine.

    matplotlib ≥3.10 shapes Arabic and applies bidi reordering itself —
    feeding it pre-shaped visual-order text (the legacy workaround for
    older matplotlib) gets REVERSED a second time and garbles every chart
    title/label (the «حروف مقطعة» report bug). Older matplotlib needs the
    reshaping. Version-detected so both environments render connected,
    correctly-ordered Arabic.

    The result is glyph-guarded against matplotlib's OWN resolved font
    (findfont of the registered family — it may select different files
    than the reportlab TTF): a character outside it would print as a
    hollow box inside the PNG, so the build is refused.
    """
    if not text:
        return text
    text = str(text)
    if any(c in text for c in _GLYPH_SUBS):
        for bad, good in _GLYPH_SUBS.items():
            if bad in text:
                text = text.replace(bad, good)
    import matplotlib as mpl
    try:
        major_minor = tuple(int(x) for x in mpl.__version__.split(".")[:2])
    except Exception:
        major_minor = (3, 11)
    out = str(text) if major_minor >= (3, 10) else _shape(text)
    _check_chart_glyphs(out, text)
    return out


# ---------------------------------------------------------------------------
# Chart glyph guard: matplotlib resolves the registered family through its
# OWN font manager — the files it picks may differ from the reportlab TTF
# (different variant, different directory), so the charts check coverage
# against what findfont ACTUALLY returns for regular + bold weights.
# ---------------------------------------------------------------------------

_MPL_FONT_CACHE: dict[str, tuple[str, list[str]]] = {}


def mpl_font_info() -> tuple[str, list[str]]:
    """(family, [font files]) matplotlib will draw chart text with —
    resolved through matplotlib's own font manager, never assumed to
    match the reportlab choice."""
    _setup_mpl()
    import matplotlib as mpl

    family = mpl.rcParams["font.family"]
    fam = family[0] if isinstance(family, (list, tuple)) and family else str(family)
    cached = _MPL_FONT_CACHE.get(fam)
    if cached is None:
        paths: list[str] = []
        for props in (font_manager.FontProperties(family=fam),
                      font_manager.FontProperties(family=fam, weight="bold")):
            try:
                p = font_manager.findfont(props, fallback_to_default=False)
            except Exception:
                p = ""
            if p and p not in paths:
                paths.append(p)
        cached = (fam, paths)
        _MPL_FONT_CACHE[fam] = cached
    return cached


def mpl_font_coverage() -> frozenset:
    """Codepoints the resolved matplotlib font(s) render. Empty when
    coverage is unavailable — the guard then stays off."""
    _, paths = mpl_font_info()
    coverage: frozenset = frozenset()
    for p in paths:
        coverage = coverage | ttf_coverage(p)
    return coverage


def _check_chart_glyphs(shaped: str, source: str) -> None:
    """Refuse chart text the resolved matplotlib font cannot render —
    matplotlib would print it as hollow boxes inside the PNG. Raises the
    shared UnsupportedGlyphError (a BaseException on purpose) so it cuts
    through every ``except Exception: return None`` chart builder."""
    coverage = mpl_font_coverage()
    if not coverage:
        return  # coverage unknown — guard disabled
    hits: dict[str, int] = {}
    for ch in shaped:
        cp = ord(ch)
        if cp in coverage or ch in RENDER_SKIP_CODEPOINTS:
            continue
        hits[ch] = hits.get(ch, 0) + 1
    if hits:
        raise UnsupportedGlyphError(
            hits,
            {ch: " ".join(str(source).split())[:120] for ch in hits},
            kind="chart",
        )


def _compact(v: float) -> str:
    """56.26M / 251K style value labels, like the reference dashboards."""
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:,.2f}M" if a < 10_000_000 else f"{v / 1_000_000:,.1f}M"
    if a >= 1_000:
        return f"{v / 1_000:,.0f}K"
    return f"{v:,.0f}"


def _finish(fig, dpi: int = 150) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def score_gauge(score: float, grade_label: str = "") -> bytes | None:
    """Half-donut gauge with red/amber/green bands, a needle at the score and
    the big value below — the reference dashboards' KPI speedometer."""
    try:
        plt = _setup_mpl()
        import numpy as np

        score = max(0.0, min(float(score), 100.0))
        fig, ax = plt.subplots(figsize=(3.4, 2.3), dpi=150)
        ax.set_aspect("equal")
        ax.axis("off")

        # bands: 0-50 red, 50-75 amber, 75-100 green (semicircle 180°→0°)
        bands = [(180, 90, RED), (90, 45, GOLD), (45, 0, GREEN)]
        for t0, t1, color in bands:
            theta = np.radians(np.linspace(t0, t1, 40))
            ax.fill_between(
                0.78 * np.cos(theta), 0.78 * np.sin(theta), 0.52 * np.sin(theta),
                color=color, alpha=0.92, linewidth=0)
        # subtle rim
        theta = np.radians(np.linspace(180, 0, 80))
        ax.plot(0.80 * np.cos(theta), 0.80 * np.sin(theta), color=GRID, lw=1)

        # needle at the score
        angle = np.radians(180 - score * 1.8)
        ax.annotate("", xy=(0.68 * np.cos(angle), 0.68 * np.sin(angle)),
                    xytext=(0, 0),
                    arrowprops=dict(arrowstyle="-|>", color=NAVY, lw=2.2))
        ax.add_artist(plt.Circle((0, 0), 0.055, color=NAVY, zorder=5))

        ax.text(0, -0.16, f"{score:.1f}", ha="center", va="center",
                fontsize=21, fontweight="bold", color=TITLE)
        if grade_label:
            ax.text(0, -0.42, mpl_text(grade_label), ha="center", va="center",
                    fontsize=10, color=MUTED)
        ax.set_xlim(-1.0, 1.0)
        ax.set_ylim(-0.55, 0.92)
        return _finish(fig)
    except Exception:
        return None


def expense_donut(components: list[tuple[str, float]], center_label: str = "",
                  title: str = "") -> bytes | None:
    """Donut of expense composition with white % labels and a legend — the
    reference dashboards' «Purchases by Region» ring."""
    try:
        plt = _setup_mpl()
        parts = [(lbl, float(v)) for lbl, v in components if float(v) > 0]
        if len(parts) < 2:
            return None
        fig, ax = plt.subplots(figsize=(4.6, 2.6), dpi=150)
        labels = [mpl_text(lbl) for lbl, _ in parts]
        values = [v for _, v in parts]
        total = sum(values)
        wedges, _, autos = ax.pie(
            values, colors=DONUT_COLORS[:len(values)], startangle=90,
            counterclock=False, wedgeprops=dict(width=0.42, edgecolor="white"),
            autopct=lambda p: f"{p:.0f}%", pctdistance=0.79)
        for t in autos:
            t.set_color("white")
            t.set_fontsize(8.5)
            t.set_fontweight("bold")
        if center_label:
            ax.text(0, 0.08, mpl_text(center_label), ha="center", va="center",
                    fontsize=8.5, color=MUTED)
            ax.text(0, -0.14, _compact(total), ha="center", va="center",
                    fontsize=14, fontweight="bold", color=TITLE)
        ax.legend(wedges, [f"{lbl} · {_compact(v)}" for lbl, v in zip(labels, values)],
                  loc="center left", bbox_to_anchor=(1.02, 0.5),
                  frameon=False, fontsize=8.5)
        if title:
            ax.set_title(mpl_text(title), fontsize=11, color=TITLE, fontweight="bold")
        return _finish(fig)
    except Exception:
        return None


def ratio_bullets(rows: list[dict], title: str = "") -> bytes | None:
    """Horizontal bullet bars: each ratio normalised against its benchmark
    anchor (1.0 = exactly on it), anchor marked by a dashed line and the bar
    coloured by its verdict — the reference dashboards' «Performance VS
    Quota». rows: {label, norm (0..2), verdict}."""
    try:
        plt = _setup_mpl()
        rows = [r for r in rows
                if isinstance(r.get("norm"), (int, float)) and 0 < r["norm"] <= 2.0]
        if len(rows) < 2:
            return None
        fig, ax = plt.subplots(figsize=(7.4, 0.62 * len(rows) + 1.0), dpi=150)
        ys = list(range(len(rows)))
        for y, r in zip(ys, rows):
            ax.barh(y, 2.0, color=GHOST, height=0.62, zorder=1)
            ax.barh(y, r["norm"], color=_VERDICT_COLORS.get(r.get("verdict"), ACCENT),
                    height=0.62, zorder=2)
            ax.text(min(r["norm"] + 0.04, 2.0), y, f"{r['norm']:.2f}x",
                    va="center", ha="left", fontsize=9, fontweight="bold",
                    color=TITLE, zorder=4)
        ax.axvline(1.0, color=NAVY, linestyle="--", linewidth=1.4, zorder=3)
        ax.text(1.0, len(rows) - 0.28, mpl_text("المرساة = 1.00") if any(
            "\u0600" <= ch <= "\u06FF" for ch in title) else "anchor = 1.00",
            ha="center", va="bottom", fontsize=8, color=NAVY)
        ax.set_yticks(ys)
        ax.set_yticklabels([mpl_text(r["label"]) for r in rows], fontsize=9.5)
        ax.invert_yaxis()
        ax.set_xlim(0, 2.35)
        ax.set_xticks([0, 0.5, 1.0, 1.5, 2.0])
        ax.grid(True, axis="x", alpha=0.3, color=GRID)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(length=0)
        if title:
            ax.set_title(mpl_text(title), fontsize=11, color=TITLE,
                         fontweight="bold")
        return _finish(fig)
    except Exception:
        return None


def trend_line(values: list[float], labels: list[str] | None = None,
               projections: list[float] | None = None, title: str = "",
               color: str = TITLE) -> bytes | None:
    """Trend line with a value card on every point (the reference dashboards'
    «Revenue by Month name»), dashed projection segment in gold."""
    try:
        plt = _setup_mpl()
        vals = [float(v) for v in values]
        if len(vals) < 2:
            return None
        xs = list(range(1, len(vals) + 1))
        proj = [float(p) for p in (projections or [])]
        fig, ax = plt.subplots(figsize=(7.4, 2.5), dpi=150)
        ax.plot(xs, vals, color=color, linewidth=2.4, marker="o", markersize=5,
                zorder=3)
        ax.fill_between(xs, vals, color=color, alpha=0.10, zorder=1)
        for x, v in zip(xs, vals):
            ax.annotate(_compact(v), (x, v), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=8,
                        fontweight="bold", color=color)
        if proj:
            px = list(range(len(vals), len(vals) + len(proj)))
            ax.plot([xs[-1]] + px, [vals[-1]] + proj, color=GOLD,
                    linewidth=2.4, linestyle="--", marker="s", markersize=4,
                    zorder=3)
            for x, v in zip(px, proj):
                ax.annotate(_compact(v), (x, v), textcoords="offset points",
                            xytext=(0, 8), ha="center", fontsize=8,
                            fontweight="bold", color="#B45309")
        ticks = xs + list(range(len(vals) + 1, len(vals) + len(proj) + 1))
        if labels and len(labels) >= len(ticks):
            ax.set_xticks(ticks)
            ax.set_xticklabels([mpl_text(str(l)) for l in labels[:len(ticks)]],
                               fontsize=8)
        else:
            ax.set_xticks(ticks)
        ax.grid(True, axis="y", alpha=0.3, color=GRID)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=8, colors=MUTED)
        if title:
            ax.set_title(mpl_text(title), fontsize=11, color=TITLE,
                         fontweight="bold")
        return _finish(fig)
    except Exception:
        return None


def activity_lines(act: dict | None, title: str = "",
                   labels: list[str] | None = None) -> bytes | None:
    """Working-capital heartbeat line chart from compute_activity_series:
    one line per available series — collection period (days), inventory
    turnover (x), payment period (days) and the CCC — across periods.
    Days and turns are both small numbers, so ONE shared axis stays
    readable (the Excel activity chart's same layout). A None hole in a
    series is skipped (gap), never plotted as 0."""
    try:
        plt = _setup_mpl()
        act = act or {}
        present = [(key, act[key]) for key in
                   ("receivable_days", "inventory_turnover",
                    "days_payable", "cash_conversion_cycle")
                   if isinstance(act.get(key), dict)
                   and any(v is not None for v in (act[key].get("values") or []))]
        if len(present) < 1:
            return None
        n = max(len((s or {}).get("values") or []) for _, s in present)
        if n < 2:
            return None  # a single period is a dot, not a trend
        fig, ax = plt.subplots(figsize=(7.4, 2.5), dpi=150)
        for i, (key, s) in enumerate(present):
            color = DONUT_COLORS[i % len(DONUT_COLORS)]
            xs, ys = [], []
            for x, v in enumerate(s.get("values") or [], 1):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    xs.append(x)
                    ys.append(float(v))
            if len(xs) < 2:
                continue  # a series with one computable period adds no line
            # the series name follows the chart's language: the Arabic name
            # on an Arabic chart, the English one on an English chart
            lbl = s.get("ar") if any(
                "\u0600" <= ch <= "\u06FF" for ch in (title or "")) else s.get("en")
            ax.plot(xs, ys, color=color, linewidth=2.2, marker="o",
                    markersize=4.5, zorder=3, label=mpl_text(lbl or key))
            for x, v in zip(xs, ys):
                ax.annotate(f"{v:,.1f}", (x, v), textcoords="offset points",
                            xytext=(0, 8), ha="center", fontsize=7.5,
                            fontweight="bold", color=color)
        ax.set_xticks(list(range(1, n + 1)))
        if labels and len(labels) >= n:
            ax.set_xticklabels([mpl_text(str(l)) for l in labels[:n]], fontsize=8)
        ax.grid(True, axis="y", alpha=0.3, color=GRID)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(labelsize=8, colors=MUTED)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14),
                      ncol=min(4, len(present)), frameon=False, fontsize=8.5)
        if title:
            ax.set_title(mpl_text(title), fontsize=11, color=TITLE,
                         fontweight="bold")
        return _finish(fig)
    except Exception:
        return None


def cost_stack(parts: list[tuple[str, float]], title: str = "") -> bytes | None:
    """Single 100% horizontal composition bar with white % labels inside and a
    legend below — the reference dashboards' «Open case status» bar."""
    try:
        plt = _setup_mpl()
        parts = [(lbl, float(v)) for lbl, v in parts if float(v) > 0]
        total = sum(v for _, v in parts)
        if len(parts) < 2 or total <= 0:
            return None
        fig, ax = plt.subplots(figsize=(7.4, 1.55), dpi=150)
        left = 0.0
        for i, (lbl, v) in enumerate(parts):
            frac = v / total * 100
            ax.barh(0, frac, left=left, color=DONUT_COLORS[i % len(DONUT_COLORS)],
                    height=0.55, edgecolor="white")
            if frac >= 6:
                ax.text(left + frac / 2, 0, f"{frac:.0f}%", ha="center",
                        va="center", color="white", fontsize=9.5,
                        fontweight="bold")
            left += frac
        ax.set_xlim(0, 100)
        ax.set_yticks([])
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=8,
                           color=MUTED)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.legend(
            handles=[plt.Rectangle((0, 0), 1, 1,
                                   color=DONUT_COLORS[i % len(DONUT_COLORS)])
                     for i in range(len(parts))],
            labels=[mpl_text(lbl) for lbl, _ in parts],
            loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=min(4, len(parts)),
            frameon=False, fontsize=8.5)
        if title:
            ax.set_title(mpl_text(title), fontsize=11, color=TITLE,
                         fontweight="bold")
        return _finish(fig)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data extraction from a stored analysis result
# ---------------------------------------------------------------------------

def _latest(result: dict, key: str) -> float | None:
    vals = [v for v in ((result.get("metrics") or {}).get(key) or [])
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return vals[-1] if vals else None


_EXPENSE_CONCEPTS = [
    ("cogs", {"ar": "تكلفة المبيعات", "en": "Cost of Sales"}),
    ("opex", {"ar": "المصاريف التشغيلية", "en": "Operating Expenses"}),
    ("finance_cost", {"ar": "مصاريف التمويل", "en": "Finance Costs"}),
    ("tax_expense", {"ar": "الزكاة والضرائب", "en": "Zakat & Taxes"}),
]


def expense_components(result: dict, lang: str) -> list[tuple[str, float]]:
    """Positive expense pieces from the latest period (never guessed)."""
    out = []
    for key, lab in _EXPENSE_CONCEPTS:
        v = _latest(result, key)
        if v is not None and v > 0:
            out.append((lab.get(lang) or lab["en"], v))
    return out


def cost_composition(result: dict, lang: str) -> list[tuple[str, float]]:
    """Revenue split into cost of sales + operating expenses + the positive
    result, per the reference dashboards' composition bar. Finance costs and
    taxes are deliberately excluded — for file-based analyses they are often
    already inside opex, and double counting would push the bar past 100%.
    When costs exceed revenue (a loss) no composition bar is returned — a
    share-of-revenue view would be misleading (the donut shows the mix)."""
    revenue = _latest(result, "revenue")
    if not revenue or revenue <= 0:
        return []
    pieces: list[tuple[str, float]] = []
    used = 0.0
    for key, lab in (("cogs", {"ar": "تكلفة المبيعات", "en": "Cost of Sales"}),
                     ("opex", {"ar": "المصاريف التشغيلية", "en": "Operating Expenses"})):
        v = _latest(result, key)
        if v is not None and v > 0:
            pieces.append((lab.get(lang) or lab["en"], v))
            used += v
    net = _latest(result, "net_profit")
    if net is not None and net > 0:
        pieces.append(({"ar": "صافي الربح", "en": "Net Profit"}.get(lang)
                       or "Net Profit", net))
        used += net
    remainder = revenue - used
    if remainder < -revenue * 0.005:
        return []  # loss-making: costs exceed revenue
    if remainder > revenue * 0.01:
        pieces.append(({"ar": "بنود أخرى", "en": "Other items"}.get(lang)
                       or "Other items", remainder))
    return pieces if len(pieces) >= 2 else []


_ANCHOR_RE = re.compile(r"(\d+(?:\.\d+)?)")


def ratio_bullet_rows(result: dict, lang: str) -> list[dict]:
    """Every computable ratio with a reference anchor, normalised to
    anchor = 1.00 and coloured by its gate verdict (mirrors the deck's
    benchmark chart so the two always agree)."""
    from .ratio_explain import _BENCHMARKS, _judge

    ratios = result.get("ratios") or {}
    rows = []
    for rkey, entry in ratios.items():
        if rkey not in _BENCHMARKS or not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            continue  # negatives hide the axis, zero divides the normalisation
        m = _ANCHOR_RE.search(_BENCHMARKS[rkey]["en"])
        if not m:
            continue
        anchor = float(m.group(1))
        if anchor <= 0:
            continue
        norm = (anchor / value) if rkey in CEILING_RATIOS else (value / anchor)
        rows.append({
            "key": rkey,
            "label": entry.get(lang) or entry.get("en") or rkey,
            "value": value,
            "norm": round(max(0.0, min(norm, 2.0)), 2),
            "verdict": _judge(rkey, value),
        })
    return rows


def revenue_trend(result: dict, lang: str) -> dict | None:
    """Revenue series + linear-regression projections for the WEB analytics
    dashboard — the SAME series and forecast methodology as the deck's
    evolution slide (trend_line with the gold dashed projection segment).
    Sourced from the advisor's _forecast_horizon so the platform and the
    presentation can never disagree on the projected numbers."""
    from .advisor import _forecast_horizon

    s = (result.get("series") or {}).get("revenue")
    vals = [float(v) for v in ((s or {}).get("values") or [])
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(vals) < 2:
        return None  # a single period is a dot, not a trend
    proj = next((p for p in _forecast_horizon(result)
                 if p.get("concept") == "revenue"), None)
    if not proj or not proj.get("projections"):
        return None
    return {
        "label": s.get(lang) or s.get("en") or ("الإيراد" if lang == "ar" else "Revenue"),
        "values": vals,
        "projections": [{"value": p["value"]} for p in proj["projections"]],
        "period_labels": [str(x) for x in (result.get("period_labels") or [])],
    }


def dashboard_payload(result: dict, lang: str, score: dict | None = None) -> dict:
    """Everything the dashboard section needs, gathered in one pass — each
    piece is optional so partial data still renders a useful dashboard."""
    series = result.get("series") or {}
    trends = []
    for concept in ("revenue", "assets", "liabilities", "cash"):
        s = series.get(concept)
        if not s:
            continue
        vals = [v for v in (s.get("values") or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(vals) >= 2:
            trends.append({
                "concept": concept,
                "values": vals,
                "label": s.get(lang) or s.get("en") or concept,
            })
        if len(trends) >= 2:
            break
    period_labels = (result.get("period_labels") or []) or None
    score_value = score.get("score") if isinstance(score, dict) else None
    grade = (score or {}).get("grade")
    grade_label = grade.get(lang) if isinstance(grade, dict) else (grade or "")
    return {
        "score": score_value if isinstance(score_value, (int, float)) else None,
        "grade_label": grade_label or "",
        "expenses": expense_components(result, lang),
        "bullets": ratio_bullet_rows(result, lang),
        "trends": trends,
        "cost_parts": cost_composition(result, lang),
        "period_labels": period_labels,
        # revenue trend + forecast for the web dashboard (deck's trend_line)
        "revenue_trend": revenue_trend(result, lang),
    }
