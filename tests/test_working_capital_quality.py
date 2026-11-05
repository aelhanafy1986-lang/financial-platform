# -*- coding: utf-8 -*-
"""Working-capital (earnings) quality indicator — «مؤشر جودة رأس المال
العامل» in the PDF report.

Contract: the file's STATED operating cash flow (cf_operating, as captured
from «صافي التدفق النقدي من الأنشطة التشغيلية») is compared with net profit
per period as a cash-conversion ratio. Verdicts: Healthy ≥ 80%, Watch
50–80%, Weak < 50% — and a below-80% period anywhere flips the overall
opinion to «جودة الأرباح منخفضة». A file that states NO operating cash
flow gets NO indicator (a composed/derived flow would measure the
platform's own assumption, not the company's declared earnings quality).
Rendered as a five-column section in the PDF with red/amber verdict
colouring.
"""

import io

from app.ratio_explain import build_working_capital_quality

BASE = {
    "revenue": [500_000.0, 650_000.0, 800_000.0],
    "cogs": [300_000.0, 380_000.0, 460_000.0],
    "opex": [70_000.0, 85_000.0, 100_000.0],
}
# net: 130k / 185k / 240k


def _result(extra=None, labels=None) -> dict:
    metrics = dict(BASE)
    metrics.update(extra or {})
    return {"metrics": metrics, "period_labels": labels or []}


def _ratio_row(wcq, i):
    return wcq["rows"][i]["ratio_val"]


# ------------------------------------------------------------- builder ----

def test_healthy_conversion_when_cash_exceeds_profit():
    wcq = build_working_capital_quality(
        _result({"cf_operating": [150_000.0, 200_000.0, 260_000.0]}), "ar")
    assert wcq is not None
    assert [_r["ratio_val"] for _r in wcq["rows"]] == \
        [round(150 / 130, 2), round(200 / 185, 2), round(260 / 240, 2)]
    assert all(r["verdict"] == "ok" for r in wcq["rows"])
    assert wcq["low"] is False
    assert "جيدة" in wcq["opinion"] and "مدعومة بالنقد" in wcq["opinion"]


def test_erosion_detected_and_named_by_period():
    """2023 converts under half of its profit to cash → «ضعيف», the overall
    opinion flips to «جودة الأرباح منخفضة» naming that period, and the
    stored ``worst`` row is the 2023 one."""
    wcq = build_working_capital_quality(
        _result({"cf_operating": [150_000.0, 90_000.0, 260_000.0]},
                labels=["2022", "2023", "2024"]), "ar")
    assert wcq is not None
    r2023 = wcq["rows"][1]
    assert r2023["period"] == "2023"
    assert r2023["verdict"] == "bad"            # 90k / 185k = 48.6% < 50%
    assert wcq["low"] is True
    assert wcq["worst"]["period"] == "2023"
    assert "منخفضة" in wcq["opinion"] and "2023" in wcq["opinion"]
    assert "الذمم والمخزون" in wcq["opinion"] or "رأس المال العامل" \
        in wcq["opinion"]
    assert wcq["note"].startswith("المنهجية:")


def test_watch_band_between_50_and_80_percent():
    wcq = build_working_capital_quality(
        _result({"cf_operating": [100_000.0]}), "ar")   # 100/130 = 76.9%
    assert wcq["rows"][0]["verdict"] == "watch"
    assert wcq["low"] is True                            # still below 0.8

    wcq2 = build_working_capital_quality(
        _result({"cf_operating": [105_000.0]}), "ar")    # 105/130 = 80.8%
    assert wcq2["rows"][0]["verdict"] == "ok"
    assert wcq2["low"] is False


def test_negative_stated_flow_and_zero_profit_guards():
    """A negative stated operating flow scores «bad» with its sign kept, and
    a zero-profit period is skipped rather than dividing by zero."""
    wcq = build_working_capital_quality(
        _result({"cf_operating": [-20_000.0, 90_000.0],
                 "cogs": [300_000.0, 650_000.0],
                 "opex": [70_000.0, 0.0],
                 "revenue": [500_000.0, 650_000.0]}), "ar")
    # p1: net = 130k, cf −20k → ratio −15.4% «bad»; p2: cogs 650k swallows
    # revenue 650k → net 0 → skipped
    assert len(wcq["rows"]) == 1
    assert wcq["rows"][0]["ratio_val"] == round(-20_000 / 130_000, 2)
    assert wcq["rows"][0]["verdict"] == "bad"
    assert "(" in wcq["rows"][0]["cf_operating"]          # (20,000) style


def test_no_stated_flow_no_indicator():
    """Nothing declared → None (the composed CF must NOT fake the check);
    an explicitly DECLARED zero flow is still a declared figure — it renders
    with a 0% «ضعيف» row, never None (honest, not silent)."""
    assert build_working_capital_quality(_result(), "ar") is None
    assert build_working_capital_quality({}, "ar") is None
    declared_zero = build_working_capital_quality(
        _result({"cf_operating": [0.0, 0.0]}), "ar")
    assert declared_zero is not None
    assert [r["ratio"] for r in declared_zero["rows"]] == ["0%", "0%"]
    assert all(r["verdict"] == "bad" for r in declared_zero["rows"])
    assert declared_zero["low"] is True


def test_english_labels_and_verdicts():
    wcq = build_working_capital_quality(
        _result({"cf_operating": [50_000.0]}, labels=["2024"]), "en")
    assert wcq["title"] == "Working-Capital Quality Indicator"
    assert wcq["rows"][0]["period"] == "2024"
    assert "eroding" in wcq["opinion"] or "quality" in wcq["opinion"]
    assert "Method:" in wcq["note"]


# ------------------------------------------------------------- rendering ----

def test_pdf_renders_wcq_section_with_colouring(tmp_path, monkeypatch):
    from app.analyzer import compute_series
    import app.report as report

    real = report._rtl_table
    captured = []

    def spy(data, rtl=True, col_widths=None, extra=None, repeat_rows=1):
        captured.append((data, col_widths, extra))
        return real(data, rtl, col_widths=col_widths, extra=extra,
                    repeat_rows=repeat_rows)

    monkeypatch.setattr(report, "_rtl_table", spy)

    result = _result({"cf_operating": [150_000.0, 90_000.0, 260_000.0]},
                     labels=["2022", "2023", "2024"])
    result["kpis"] = {}
    result["ratios"] = {}
    result["series"] = compute_series(result["metrics"])
    out = tmp_path / "r.pdf"
    report.build_report("شركة اختبار", result, out, "ar")
    assert out.exists() and out.stat().st_size > 0

    # Arabic headers arrive SHAPED (presentation forms) and the verdict
    # glyphs swap to their substitutes (✓→•, ✗→×) — match the table by its
    # 5-column shape + a verdict cell (× / • / ≈ / shaped ضعيف fragments).
    verdict_marks = ("×", "\u2022", "≈")
    hits = [c for c in captured if c[0] and len(c[0][0]) == 5
            and any(isinstance(cell, str)
                    and any(m in cell for m in verdict_marks)
                    for row in c[0][1:] for cell in row[4:5])]
    assert hits, "working-capital quality table missing from the PDF"
    data, widths, extra = hits[0]
    assert data[2][0] == "2023" and data[2][3] == "49%"      # 90k / 185k
    # the verdict cell arrives SHAPED (visual order): «ضعيف ✗» renders as
    # the glyph-substituted mark at the START of the visual-order string
    assert str(data[2][4]).startswith(("×", "\u00d7"))
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm
    red_cmds = [cmd for cmd in (extra or [])
                if cmd[0] == "TEXTCOLOR" and cmd[3] == HexColor("#dc2626")]
    assert red_cmds, "weak verdict must be red in the PDF"
    assert sum(w for w in widths) <= 178 * mm + 1


def test_pdf_skips_wcq_when_nothing_stated(tmp_path, monkeypatch):
    from app.analyzer import compute_series
    import app.report as report

    seen = []

    real_section = report._section

    def spy_section(story, title, key="", rtl=True):
        seen.append(str(key))
        return real_section(story, title, key, rtl)

    monkeypatch.setattr(report, "_section", spy_section)

    result = _result(labels=["2024", "2025", "2026"])
    result["kpis"] = {}
    result["ratios"] = {}
    result["series"] = compute_series(result["metrics"])
    out = tmp_path / "r.pdf"
    report.build_report("شركة اختبار", result, out, "ar")
    assert out.exists() and out.stat().st_size > 0
    assert "wcq" not in seen, "indicator must not render without stated CF"
