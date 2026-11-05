# -*- coding: utf-8 -*-
"""Every character of the report generators' texts must be COVERED by the
font actually used to render it.

Root cause pinned here (and must never regress): both report engines draw
text with Sakkal Majalla (``C:/Windows/Fonts/majalla.ttf``). Majalla's
character map does NOT carry symbols like ✓ ✗ → Δ ● — reportlab draws
them as hollow boxes and extracts them as ``\\x00`` from the produced
PDF, and PowerPoint shows the same tofu. ``report.py`` guards this with
``_GLYPH_SUBS`` (symbols → glyphs the font HAS); the test enforces the
same contract for BOTH generators BEFORE anything reaches a report:

1. every string literal in report.py / pptx_report.py is collected (AST
   walk — the modules' own texts, labels, notes and headers),
2. each literal is passed through that module's own ``_shape`` (glyph
   substitution + reshaping + bidi — exactly what reaches the renderer),
3. every resulting character must exist in the union character map of the
   resolved regular+bold font files (the modules' own ``_find_arabic_font``
   resolver, so the test checks the font that will actually be used),
4. the substitution tables themselves must map only to covered glyphs (a
   substitution pointing at another missing glyph would still tofu).

Runtime-interpolated values (user data, labels.py strings) flow through
the same ``_shape`` at render time; these tests pin the module-owned text
and the substitution mechanism that protects those values too.
"""

import ast
from pathlib import Path

import pytest

from fontTools.ttLib import TTFont

from app import dashboard_charts, pptx_report, report
from app.fonts import RENDER_SKIP_CODEPOINTS

_ROOT = Path(__file__).resolve().parents[1]
_CONTROL = {"\n", "\t", "\r"}


def _literals(rel_path: str) -> set[str]:
    """All str constants of a module (its own texts), AST-collected."""
    tree = ast.parse((_ROOT / rel_path).read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _cmap_union(paths: list) -> set[int]:
    cmap: set[int] = set()
    for p in paths:
        if p:
            cmap |= set(TTFont(str(p)).getBestCmap().keys())
    return cmap


def _font_paths() -> list:
    """Regular+bold files as resolved by the modules themselves."""
    reg, bold = report._find_arabic_font()
    return [reg, bold]


@pytest.fixture(scope="module")
def font_cmap() -> set[int]:
    reg, bold = report._find_arabic_font()
    if not reg:
        pytest.skip("no Arabic TTF on this machine — font map unavailable")
    return _cmap_union([reg, bold])


def _missing_chars(shaped_texts, cmap: set[int]) -> dict[str, str]:
    """{unsupported char: first literal it appears in} over shaped text.

    Honors the render contract's skip set: control/format codepoints
    (bidi, joiners, variation selectors like the \uFE0F after ⚠) never
    render as glyphs themselves, so they are never tofu offenders."""
    missing: dict[str, str] = {}
    for text in shaped_texts:
        for ch in text:
            if ch in _CONTROL or ch in RENDER_SKIP_CODEPOINTS:
                continue
            if ord(ch) not in cmap:
                missing.setdefault(ch, text)
    return missing


def _assert_covered(module, rel_path: str, cmap: set[int],
                    shaper=None) -> None:
    literals = sorted(_literals(rel_path))
    assert literals, f"{rel_path} yielded no text literals"
    shaped = [(shaper or module._shape)(s) for s in literals]
    missing = _missing_chars(shaped, cmap)
    assert not missing, (
        f"{rel_path}: {len(missing)} character(s) NOT covered by the report "
        "font — they would render as hollow boxes (tofu). Map them in "
        "_GLYPH_SUBS or replace the literal: "
        + ", ".join(f"U+{ord(c):04X} {c!r} (e.g. {src[:40]!r})"
                    for c, src in sorted(missing.items()))
    )


def test_report_texts_covered_by_font(font_cmap):
    """Every report.py literal, after its own _shape, exists in the font."""
    _assert_covered(report, "app/report.py", font_cmap)


@pytest.fixture(scope="module")
def mpl_font_cmap():
    """Coverage of the font matplotlib ACTUALLY resolves for the chart
    family — via matplotlib's own findfont, which may select different
    files than the reportlab TTF the text-layer check uses."""
    coverage = dashboard_charts.mpl_font_coverage()
    if not coverage:
        pytest.skip("no matplotlib Arabic font — chart coverage unavailable")
    return coverage


def test_dashboard_chart_texts_covered_by_mpl_font(mpl_font_cmap):
    """Every dashboard_charts literal, after mpl_text, exists in the font
    matplotlib itself resolved for the charts (NOT the reportlab pick)."""
    _assert_covered(dashboard_charts, "app/dashboard_charts.py",
                    mpl_font_cmap, shaper=dashboard_charts.mpl_text)


def test_mpl_coverage_derived_from_mpl_own_resolution(mpl_font_cmap):
    """Pin the derivation: the chart coverage is the union cmap of the
    files matplotlib's findfont returns for the registered family."""
    from matplotlib import font_manager

    family, paths = dashboard_charts.mpl_font_info()
    assert paths, "matplotlib resolved no font files for its own family"
    assert all(Path(p).exists() for p in paths)
    resolved = font_manager.findfont(
        font_manager.FontProperties(family=family))
    assert resolved in paths
    union: set[int] = set()
    for p in paths:
        union |= set(TTFont(str(p)).getBestCmap().keys())
    assert set(mpl_font_cmap) == union


def test_pptx_report_texts_covered_by_font(font_cmap):
    """Every pptx_report.py literal, after its own _shape, in the font."""
    _assert_covered(pptx_report, "app/pptx_report.py", font_cmap)


def test_glyph_substitutions_target_covered_glyphs(font_cmap):
    """A substitution mapping to another missing glyph would still tofu:
    every _GLYPH_SUBS TARGET must be in the font's character map, and the
    KEYS it replaces must genuinely be absent (otherwise the mapping is
    silently degrading supported symbols)."""
    for module in (report, pptx_report, dashboard_charts):
        subs = getattr(module, "_GLYPH_SUBS", None)
        assert subs, f"{module.__name__} lost its _GLYPH_SUBS guard"
        for bad, good in subs.items():
            assert ord(good) in font_cmap, (
                f"{module.__name__}._GLYPH_SUBS maps {bad!r} → {good!r} "
                f"(U+{ord(good):04X}) which the font does NOT carry either"
            )
            assert bad != good


def test_shape_of_arabic_presentation_forms_is_idempotent(font_cmap):
    """Already-shaped text must pass through _shape untouched (the double-
    shaping guard) AND stay covered — the pipeline's own output re-enters
    the pipeline when a report embeds a previously rendered string."""
    sample = report._shape("صافي الربح ✓")
    assert pptx_report._shape(sample) == sample
    assert all(ord(c) in font_cmap for c in sample if c not in _CONTROL)


# Platform-wide text sources: labels/messages/advice that render INSIDE
# reports through the reportlab text layer (report._shape — the same
# substitution + shaping contract) or the deck's shaping. An uncovered
# character there must be caught statically, before any report renders it.
_PLATFORM_TEXT_MODULES = ("labels", "audit", "hygiene", "advisor")


@pytest.mark.parametrize("modname", _PLATFORM_TEXT_MODULES)
def test_platform_texts_covered_by_font(font_cmap, modname):
    """labels.py / audit.py / hygiene.py / advisor.py: every label,
    quality-gate message, data-quality template and advice string — after
    the report shaping pipeline — exists in the report font."""
    import importlib

    module = importlib.import_module(f"app.{modname}")
    _assert_covered(module, f"app/{modname}.py", font_cmap,
                    shaper=report._shape)
