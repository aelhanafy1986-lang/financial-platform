"""Glyph guard: report endpoints refuse to build (422, clear bilingual
error) when any text carries a character the embedded TTF cannot render —
instead of serving a PDF full of hollow boxes."""

import io
from pathlib import Path

import pdfplumber
import pytest
from fontTools.ttLib import TTFont
from openpyxl import Workbook

from app.report import UnsupportedGlyphError, _shape


def _demo(client) -> int:
    return client.post("/api/demo").json()["id"]


class TestReportGlyphGuard:
    def test_emoji_display_name_refused_with_clear_error(self, client):
        aid = _demo(client)
        client.patch(
            f"/api/analyses/{aid}", json={"display_name": "شركة التجزئة 😀"}
        )
        res = client.get(
            f"/api/analyses/{aid}/report?lang=ar", headers=client.auth_headers
        )
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert "لا يدعم المحارف" in detail
        assert "U+1F600" in detail
        # a refused build never wrote a cached PDF
        from app import main as app_main

        assert not any(app_main.REPORTS.glob(f"report_{aid}_*.pdf"))

    def test_english_error_message(self, client):
        aid = _demo(client)
        client.patch(f"/api/analyses/{aid}", json={"display_name": "تحليل 語"})
        res = client.get(
            f"/api/analyses/{aid}/report?lang=en", headers=client.auth_headers
        )
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert "does not support" in detail
        assert "U+8A9E" in detail

    def test_notes_with_unsupported_char_refused(self, client):
        aid = _demo(client)
        # ✓ is a KNOWN symbol — substituted to • before the check, so the
        # error must name only the genuinely unsupported character
        client.patch(
            f"/api/analyses/{aid}",
            json={"notes": "ملاحظة ✓ عادية ثم رمز 😀 في النهاية"},
        )
        res = client.get(
            f"/api/analyses/{aid}/report?lang=ar", headers=client.auth_headers
        )
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert "U+2713" not in detail
        assert "U+1F600" in detail

    def test_supported_text_still_builds(self, client):
        aid = _demo(client)
        client.patch(
            f"/api/analyses/{aid}",
            json={
                "display_name": "شركة الرياض للتجارة — 2024",
                "notes": "ملاحظة: ✓ الربح تجاوز 15% من الإيرادات «نمو ممتاز»",
            },
        )
        res = client.get(
            f"/api/analyses/{aid}/report?lang=ar", headers=client.auth_headers
        )
        assert res.status_code == 200
        assert res.content[:5] == b"%PDF-"
        with pdfplumber.open(io.BytesIO(res.content)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        # the PDF stores shaped presentation forms — compare shaped
        assert _shape("شركة الرياض للتجارة") in text

    def test_stats_builder_refuses_bad_name(self, tmp_path):
        """The stats report's saved-analyses list shapes every name — a
        glyph the font cannot render must abort the build before bytes."""
        from app.report import UnsupportedGlyphError, build_stats_report

        payload = {
            "analyses": [{"id": 1, "name": "اسم ⭐ سيئ", "created_at": None,
                          "edited": False}],
            "concepts": {"revenue": {
                "first": {"name": "a", "value": 1.0},
                "last": {"name": "b", "value": 2.0},
                "trend": "up", "change_pct": 100.0,
            }},
        }
        with pytest.raises(UnsupportedGlyphError) as ei:
            build_stats_report(payload, tmp_path / "stats.pdf", "ar")
        assert "U+2B50" in ei.value.message("ar")
        assert not (tmp_path / "stats.pdf").exists()

    def test_compare_report_refuses_bad_name(self, client):
        a, b = _demo(client), _demo(client)
        client.patch(f"/api/analyses/{a}", json={"display_name": "اسم 🎯 سيئ"})
        res = client.get(
            f"/api/compare/{a}/{b}/report?lang=ar", headers=client.auth_headers
        )
        assert res.status_code == 422
        assert "U+1F3AF" in res.json()["detail"]


class TestChartGlyphGuard:
    """matplotlib chart texts are guarded against the font matplotlib
    ITSELF resolves (findfont of the registered family) — which may pick
    different files than the reportlab TTF the text layer checks."""

    def test_mpl_text_refuses_unsupported_char(self):
        from app.dashboard_charts import UnsupportedGlyphError, mpl_text

        with pytest.raises(UnsupportedGlyphError) as ei:
            mpl_text("اتجاه 😀 الإيراد")
        assert ei.value.kind == "chart"
        assert "U+1F600" in ei.value.message("ar")
        assert "chart font" in ei.value.message("en")

    def test_mpl_text_substitutes_known_symbols(self):
        from app.dashboard_charts import mpl_text

        out = mpl_text("اتجاه ✓ الإيراد")  # ✓ → • (a glyph the font HAS)
        assert "\u2713" not in out and "\u2022" in out

    def test_trend_line_refuses_and_produces_nothing(self):
        from app.dashboard_charts import trend_line

        with pytest.raises(UnsupportedGlyphError):
            trend_line([1.0, 2.0, 3.0], title="اتجاه 😀")

    def test_supported_arabic_title_renders_png(self):
        from app.dashboard_charts import trend_line

        img = trend_line([1.0, 2.0, 3.0], title="اتجاه الإيراد — 2024")
        assert img is not None and img.startswith(b"\x89PNG")

    def test_coverage_derived_from_mpl_own_files(self):
        from app.dashboard_charts import mpl_font_coverage, mpl_font_info

        _, paths = mpl_font_info()
        assert paths and all(Path(p).exists() for p in paths)
        union: set[int] = set()
        for p in paths:
            union |= set(TTFont(str(p)).getBestCmap().keys())
        assert set(mpl_font_coverage()) == union

    def test_pptx_refuses_bad_concept_label(self, client):
        """A user-corrected concept label reaches the deck's trends chart
        title (series name) — the chart font cannot render an emoji, so
        the whole deck is refused with a clear error."""
        # a real multi-series analysis: mangled cost row assigned to cogs
        wb = Workbook()
        ws = wb.active
        ws.title = "قائمة الدخل"
        ws.append(["البيان", "2023", "2024"])
        ws.append(["الإيرادات", 1000000, 1500000])
        ws.append(["تكلفة البيعات", 400000, 600000])
        ws.append(["صافي الربح", 600000, 900000])
        buf = io.BytesIO()
        wb.save(buf)
        up = client.post(
            "/api/upload",
            files={"files": ("m.xlsx", io.BytesIO(buf.getvalue()))},
            headers=client.auth_headers,
        )
        assert up.status_code == 200
        aid = up.json()["uploaded"][0]["id"]
        client.patch(
            f"/api/analyses/{aid}", json={"review_rows": {"r0": {"to": "cogs"}}}
        )
        client.patch(
            f"/api/analyses/{aid}",
            json={"concepts": {"cogs": {"label": "تكلفة 😀"}}},
        )
        res = client.get(
            f"/api/analyses/{aid}/pptx?lang=ar", headers=client.auth_headers
        )
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert "U+1F600" in detail
        from app import main as app_main

        assert not any(app_main.REPORTS.glob(f"pptx_{aid}_*.pptx"))
