# -*- coding: utf-8 -*-
"""Next-year forecast column in the growth table (mean historical growth).

The growth table now carries a FORECAST column: for every row, the mean of
its historical YoY rates is applied to its latest value — «متوسط النمو
التاريخي» — labelled with the period AFTER the last one (bumping the
trailing number: «2024»→«2025», «عام 2024»→«عام 2025», «الفترة 3»→«الفترة
4»), and footnoted as an estimate. Rendered in the PDF's growth table
(column widths recomputed to stay inside A4's 174mm) and in the PPTX
growth slide (amber cell + methodology note). Rows with a zero latest
value forecast nothing («—»).
"""

from app.ratio_explain import build_yearly_comparison, net_profit_series

THREE_YEAR_METRICS = {
    "revenue": [12_000_000.0, 15_000_000.0, 18_000_000.0],
    "cogs": [8_400_000.0, 10_500_000.0, 12_600_000.0],
    "opex": [1_800_000.0, 2_250_000.0, 2_700_000.0],
    "assets": [22_000_000.0, 25_000_000.0, 28_000_000.0],
    "liabilities": [9_000_000.0, 10_000_000.0, 11_000_000.0],
    "equity": [13_000_000.0, 15_000_000.0, 17_000_000.0],
}


def _result(labels=None, metrics=None) -> dict:
    return {
        "metrics": dict(metrics or THREE_YEAR_METRICS),
        "period_labels": list(labels) if labels else [],
    }


def _fc(comp, key):
    return next(r for r in comp["rows"] if r["key"] == key).get("forecast")


# ------------------------------------------------------------ arithmetic ----

def test_forecast_is_mean_of_historical_growth():
    comp = build_yearly_comparison(_result(), "ar")
    # revenue: +25.0% then +20.0% → mean 22.5% → 18M × 1.225 = 22,050,000
    fc = _fc(comp, "revenue")
    assert fc["value"] == "22,050,000"
    assert fc["growth"] == "+22.5%"
    assert fc["raw"] == 22_050_000.0
    # cogs (a cost) is forecast with the SAME rule — no judgment flipping
    fc_cogs = _fc(comp, "cogs")
    assert fc_cogs["value"] == "15,435,000"   # 12.6M × 1.225
    assert fc_cogs["growth"] == "+22.5%"


def test_forecast_label_bumps_trailing_number():
    comp = build_yearly_comparison(
        _result(labels=["2022", "2023", "2024"]), "ar")
    assert comp["forecast_label"] == "2025"

    comp = build_yearly_comparison(
        _result(labels=["عام 2022", "عام 2023", "عام 2024"]), "ar")
    assert comp["forecast_label"] == "عام 2025"

    comp = build_yearly_comparison(
        _result(labels=["الفترة 1", "الفترة 2", "الفترة 3"]), "ar")
    assert comp["forecast_label"] == "الفترة 4"


def test_forecast_label_falls_back_without_trailing_number():
    comp = build_yearly_comparison(
        _result(labels=["2022م", "2023م", "2024م"]), "ar")
    assert comp["forecast_label"] == "توقع"


def test_zero_latest_value_forecasts_nothing():
    """Net profit hits exactly zero in the latest year (revenue 18M − cogs
    18M) → no forecast («—»), while revenue still forecasts normally."""
    metrics = dict(THREE_YEAR_METRICS)
    metrics["cogs"] = [3_000_000.0, 3_000_000.0, 18_000_000.0]
    metrics["opex"] = [0.0, 0.0, 0.0]
    # sanity: the derived chain really ends at zero
    assert net_profit_series(_result(metrics=metrics))[-1] == 0.0
    comp = build_yearly_comparison(_result(metrics=metrics), "ar")
    assert _fc(comp, "revenue") is not None
    assert _fc(comp, "net_profit") is None


def test_growth_note_present_with_table():
    comp = build_yearly_comparison(_result(), "ar")
    assert comp["growth_note"]
    assert "متوسط النمو" in comp["growth_note"]


def test_two_periods_no_forecast_label():
    """No growth table → no forecast column (same threshold as the table)."""
    metrics = {
        "revenue": [12_000_000.0, 15_000_000.0],
        "cogs": [8_400_000.0, 10_500_000.0],
        "opex": [1_800_000.0, 2_250_000.0],
        "assets": [22_000_000.0, 25_000_000.0],
        "liabilities": [9_000_000.0, 10_000_000.0],
        "equity": [13_000_000.0, 15_000_000.0],
    }
    comp = build_yearly_comparison(_result(metrics=metrics), "ar")
    assert not comp.get("years")
    assert not comp.get("forecast_label")


# ------------------------------------------------------------- rendering ----

def test_pdf_growth_table_has_forecast_column(monkeypatch, tmp_path):
    """The PDF's growth table gains the forecast column and its widths are
    recomputed to stay inside A4's 174mm usable width."""
    from app.analyzer import compute_series

    import app.report as report

    real = report._rtl_table
    captured = []

    def spy(data, rtl=True, col_widths=None, extra=None, repeat_rows=1):
        captured.append((data, col_widths))
        return real(data, rtl, col_widths=col_widths, extra=extra,
                    repeat_rows=repeat_rows)

    monkeypatch.setattr(report, "_rtl_table", spy)

    result = _result(labels=["2022", "2023", "2024"])
    result["kpis"] = {}
    result["ratios"] = {}
    result["series"] = compute_series(result["metrics"])
    out = tmp_path / "r.pdf"
    report.build_report("شركة اختبار", result, out, "ar",
                        yearly_comparison=build_yearly_comparison(result, "ar"))
    assert out.exists() and out.stat().st_size > 0

    from reportlab.lib.units import mm
    hits = [(d, w) for d, w in captured
            if "2025" in [str(c) for c in d[0]] and len(d[0]) == 5]
    assert hits, "growth table with forecast column missing from the PDF"
    data, widths = hits[0]
    assert len(widths) == 5
    assert sum(w for w in widths) <= 174 * mm + 1
    # the forecast header cell is the LAST logical column
    assert str(data[0][-1]) == "2025"


def test_deck_growth_slide_has_forecast_cell(tmp_path):
    import io
    import re
    import zipfile

    from app import pptx_report
    from app.analyzer import compute_series

    result = _result(labels=["2022", "2023", "2024"])
    result["kpis"] = {}
    result["ratios"] = {}
    result["series"] = compute_series(result["metrics"])
    comp = build_yearly_comparison(result, "ar")

    out = tmp_path / "deck.pptx"
    pptx_report.build_pptx_report(
        filename="w.xlsx", result=result, out_path=out, lang="ar",
        yearly_comparison=comp,
    )
    z = zipfile.ZipFile(str(out))
    sh = pptx_report._shape
    slides = [z.read(n).decode("utf-8", "ignore")
              for n in z.namelist()
              if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
              and sh(comp["growth_title"]) in z.read(n).decode("utf-8", "ignore")]
    assert slides, "growth slide missing"
    joined = "\n".join(slides)
    # the forecast VALUE lands on the slide with the amber methodology note
    assert "22,050,000" in joined
    assert sh(comp["growth_note"]) in joined
    # every growth card-row table now has label + 3 years + forecast = 5 cols
    for tbl in re.findall(r"<a:tbl>.*?</a:tbl>", joined, flags=re.S):
        cols = len(re.findall(r"<a:gridCol[^>]*>", tbl))
        assert cols == 1 + len(comp["years"]) + 1
