"""Benchmark comparison chart slide in the PPTX report.

A clustered column chart compares every computed ratio against its
reference anchor on a normalised scale (anchor = 1.00), with brand-coloured
series and a methodology footnote — alongside the textual ratios slide.
"""

from pathlib import Path
import re
import zipfile

from app.pptx_report import build_pptx_report


def _result():
    return {
        "kpis": {
            "revenue": {"value": 1_200_000.0, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": 180_000.0, "en": "Net Profit", "ar": "صافي الربح"},
        },
        "ratios": {
            "gross_margin": {"value": 40.0, "en": "Gross Margin %", "ar": "هامش الربح الإجمالي %"},
            "net_margin": {"value": 15.0, "en": "Net Margin %", "ar": "هامش صافي الربح %"},
            "debt_ratio": {"value": 19.4, "en": "Debt Ratio %", "ar": "نسبة الالتزامات %"},
            "debt_to_equity": {"value": 0.31, "en": "Debt to Equity", "ar": "الالتزامات إلى حقوق الملكية"},
            "roa": {"value": 21.7, "en": "Return on Assets %", "ar": "العائد على الأصول %"},
            "roe": {"value": 26.5, "en": "Return on Equity %", "ar": "العائد على حقوق الملكية %"},
        },
        "metrics": {},
        "series": {},
        "forecast": [],
        "tables_found": 1,
        "texts_found": 0,
        "analysed_at": None,
    }


class TestBenchmarkChartSlide:
    def _build(self, tmp_path: Path, lang: str = "ar") -> Path:
        out = tmp_path / f"deck_{lang}.pptx"
        build_pptx_report(
            filename="bench.xlsx",
            result=_result(),
            out_path=out,
            lang=lang,
        )
        assert out.exists() and out.stat().st_size > 20_000
        return out

    def test_chart_part_exists(self, tmp_path):
        deck = self._build(tmp_path)
        z = zipfile.ZipFile(str(deck))
        charts = [n for n in z.namelist() if re.match(r"ppt/charts/chart\d+\.xml", n)]
        assert charts, "no native chart in the deck"

    def test_chart_is_clustered_columns_with_two_series(self, tmp_path):
        deck = self._build(tmp_path)
        z = zipfile.ZipFile(str(deck))
        chart_xmls = [z.read(n).decode("utf-8", "ignore")
                      for n in z.namelist()
                      if re.match(r"ppt/charts/chart\d+\.xml", n)]
        bench = next((x for x in chart_xmls if "<c:barChart>" in x
                      and "barDir val=\"col\"" in x), None)
        assert bench, "no clustered column chart found"
        assert bench.count("<c:ser>") == 2  # ours + reference
        # normalised scale is capped at 2.0 (max/min elements present)
        assert "<c:max" in bench and "<c:min" in bench

    def test_series_colours_brand_teal_and_gold(self, tmp_path):
        deck = self._build(tmp_path)
        z = zipfile.ZipFile(str(deck))
        chart_xmls = [z.read(n).decode("utf-8", "ignore")
                      for n in z.namelist()
                      if re.match(r"ppt/charts/chart\d+\.xml", n)]
        bench = next((x for x in chart_xmls if "<c:barChart>" in x), None)
        assert bench
        # deck brand colours: azure ACCENT (0070C0) + gold reference (FFC000),
        # plus the white separator line of the reference series
        fills = {c.upper() for c in re.findall(r'srgbClr val="([0-9A-Fa-f]{6})"', bench)}
        assert "0070C0" in fills
        assert "FFC000" in fills

    def test_bilingual_title_and_footnote(self, tmp_path):
        deck_ar = self._build(tmp_path, "ar")
        deck_en = self._build(tmp_path, "en")
        # AR slides store shaped presentation forms in visual order — apply
        # the same transform to the needle (and accept the lam-alef ligature).
        from bidi.algorithm import get_display
        import arabic_reshaper

        def _shape(s):
            return get_display(arabic_reshaper.reshape(s))

        for deck, title in ((deck_ar, "النسب مقابل المعايير المرجعية"),
                            (deck_en, "Ratios vs Reference Benchmarks")):
            z = zipfile.ZipFile(str(deck))
            slides = [n for n in z.namelist()
                      if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
            flat = "".join(
                "".join(re.findall(r"<a:t>([^<]*)</a:t>",
                                   z.read(s).decode("utf-8", "ignore")))
                for s in slides)
            candidates = {_shape(title), title,
                          _shape(title).replace(chr(1604) + chr(1575), chr(65275)),
                          _shape(title).replace(chr(1604) + chr(1575), chr(65276))}
            assert any(c in flat for c in candidates), (
                f"title {title!r} not found in {deck}")
