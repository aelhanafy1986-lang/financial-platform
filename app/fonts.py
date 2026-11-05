"""Shared font-coverage machinery for the report generators.

reportlab (PDF text) and matplotlib (chart PNGs embedded in the PDF/PPTX)
resolve fonts through DIFFERENT paths: the family registered with
matplotlib may select different font files than the reportlab TTF, so
each generator must check the text it draws against its OWN effective
font — a character outside that font prints as a hollow box (tofu).
"""

from fontTools.ttLib import TTFont as _TTFont

_COVERAGE_CACHE: dict[str, frozenset] = {}


def ttf_coverage(path) -> frozenset:
    """Codepoints a TTF renders. Empty when coverage is unavailable —
    callers keep their guard OFF instead of rejecting blindly."""
    if not path:
        return frozenset()
    key = str(path)
    cached = _COVERAGE_CACHE.get(key)
    if cached is None:
        try:
            cached = frozenset(_TTFont(key, fontNumber=0).getBestCmap().keys())
        except Exception:
            cached = frozenset()
        _COVERAGE_CACHE[key] = cached
    return cached


# Control/format codepoints that never render as glyphs: whitespace,
# bidi/isolates, zero-width joiners — never counted as unsupported.
# Built via chr() so no importing module's string LITERALS carry
# uncovered codepoints (the font-coverage contract walks every literal).
RENDER_SKIP_CODEPOINTS = frozenset(
    "\n\r\t " + "".join(map(chr, (
        0x00A0, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
        0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF, 0xFE0F,
    )))
)


class UnsupportedGlyphError(BaseException):
    """A report (or one of its embedded charts) carries characters the
    rendering font cannot display — the build is refused instead of
    serving hollow boxes.

    Inherits BaseException DELIBERATELY: every chart/report builder wraps
    its body in ``except Exception: return None`` graceful degradation,
    and a refusal must cut through ALL of those layers to the endpoint —
    never be swallowed into a silently-missing chart. No handler in the
    app catches bare BaseException (verified), so the only paths that
    stop this error are the explicit endpoint-level refusals.
    """

    def __init__(self, hits: dict[str, int], samples: dict[str, str],
                 kind: str = "text"):
        self.hits = hits        # character -> occurrence count
        self.samples = samples  # character -> first source text (truncated)
        self.kind = kind        # "text" (reportlab) | "chart" (matplotlib)
        super().__init__(self.message("ar"))

    def _listed(self) -> str:
        return ", ".join(f"'{ch}' (U+{ord(ch):04X}) ×{count}"
                         for ch, count in self.hits.items())

    def message(self, lang: str) -> str:
        sample = next(iter(self.samples.values()), "")
        if lang == "en":
            what = ("one of its embedded charts carries characters the "
                    "chart font does not support" if self.kind == "chart"
                    else "the embedded font does not support these characters")
            out = f"Report build refused: {what}: {self._listed()}"
            if sample:
                out += f' — first seen in: "{sample}"'
            return out + (" — fix the source (analysis name, notes or "
                          "data) and rebuild")
        what = ("أحد الرسوم التحليلية المضمّنة يحمل محارف لا يدعمها خط الرسم"
                if self.kind == "chart"
                else "الخط المضمّن لا يدعم المحارف التالية")
        out = f"رفض بناء التقرير: {what}: {self._listed()}"
        if sample:
            out += f" — أول ظهور في: «{sample}»"
        return out + (" — صحّح المصدر (اسم التحليل أو الملاحظات أو "
                      "البيانات) ثم أعد المحاولة")
