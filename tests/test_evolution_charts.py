# -*- coding: utf-8 -*-
"""Line charts for revenue & net-profit evolution across ALL years.

Contract (both report surfaces — PDF report and PPTX deck):
- the evolution charts render FIRST in the charts section: revenue from the
  stored metrics (every captured year, no 2-period collapse), net profit
  via the SAME IFRS 18 chain the growth table reads (net_profit_series) —
  net profit was NEVER charted before (compute_series omits it),
- the x axis carries the analysis's period labels (one tick per year),
- the generic series charts skip revenue/net profit — no duplicated chart,
- a PDF whose net profit is absent derives it (chain arithmetic asserted),
- the PPTX evolution slide carries exactly two chart images.
"""

import pytest

from app.ratio_explain import build_yearly_comparison, net_profit_series

THREE_YEAR_METRICS = {
    "revenue": [12_000_000.0, 15_000_000.0, 18_000_000.0],
    "cogs": [8_400_000.0, 10_500_000.0, 12_600_000.0],
    "opex": [1_800_000.0, 2_250_000.0, 2_700_000.0],
    "assets": [22_000_000.0, 25_000_000.0, 28_000_000.0],
    "liabilities": [9_000_000.0, 10_000_000.0, 11_000_000.0],
    "equity": [13_000_000.0, 15_000_000.0, 17_000_000.0],
}
# derived net = revenue − cogs − opex (+investment −finance −taxes)
DERIVED_NET = [12_000_000 - 8_400_000 - 1_800_000,
               15_000_000 - 10_500_000 - 2_250_000,
               18_000_000 - 12_600_000 - 2_700_000]

PERIOD_LABELS = ["2022", "2023", "2024"]


def _result(net_stored: bool = False) -> dict:
    metrics = dict(THREE_YEAR_METRICS)
    if net_stored:
        metrics["net_profit"] = [1_700_000.0, 2_100_000.0, 2_600_000.0]
    return {"metrics": metrics, "period_labels": list(PERIOD_LABELS)}


# ------------------------------------------------------------ data layer ----

def test_net_profit_series_derives_ifrs18_chain():
    assert net_profit_series(_result()) == DERIVED_NET


def test_net_profit_series_prefers_stored_metrics():
    assert net_profit_series(_result(net_stored=True)) == \
        [1_700_000.0, 2_100_000.0, 2_600_000.0]


def test_net_profit_series_empty_without_two_periods():
    assert net_profit_series({"metrics": {"revenue": [1.0]}}) == []
    assert net_profit_series({}) == []


def test_growth_table_still_reads_derived_net(tmp_path):
    """The extracted helper keeps the growth table's net row identical."""
    comp = build_yearly_comparison(_result(), "ar")
    net_rows = [r for r in comp["rows"] if r["key"] == "net_profit"]
    assert net_rows and net_rows[0]["history"] == DERIVED_NET


# ------------------------------------------------------------- PDF report ----

def test_pdf_renders_evolution_charts_first_no_duplicates(monkeypatch, tmp_path):
    """Spy on report._chart: the FIRST two charts are revenue + net profit
    (full 3-year values, period labels on the axis), revenue is NOT charted
    again by the generic loop, and the derived net values match the chain."""
    import app.report as report

    real_chart = report._chart
    calls: list[dict] = []

    def spy(values, projections=None, title="", font_path=None, labels=None):
        calls.append({"title": str(title), "values": list(values),
                      "labels": list(labels) if labels else None})
        return real_chart(values, projections, title, font_path=font_path,
                          labels=labels)

    monkeypatch.setattr(report, "_chart", spy)

    result = _result()  # net profit ABSENT → derived
    result["kpis"] = {}
    result["ratios"] = {}
    from app.analyzer import compute_series
    result["series"] = compute_series(result["metrics"])

    out = tmp_path / "r.pdf"
    report.build_report("شركة اختبار", result, out, "ar")
    assert out.exists() and out.stat().st_size > 0

    assert calls, "no charts rendered at all"
    assert calls[0]["title"] == "الإيرادات"
    assert calls[0]["values"] == THREE_YEAR_METRICS["revenue"]
    assert calls[0]["labels"] == PERIOD_LABELS  # year ticks on the axis
    assert calls[1]["title"] == "صافي الربح"
    assert calls[1]["values"] == DERIVED_NET    # the IFRS 18 chain
    # revenue charted EXACTLY once (evolution chart; generic loop skips it)
    assert sum(1 for c in calls if c["title"] == "الإيرادات") == 1
    # net profit charted exactly once too
    assert sum(1 for c in calls if c["title"] == "صافي الربح") == 1


# ------------------------------------------------------------------ deck ----

def _deck_metrics(net_stored: bool = False) -> dict:
    metrics = dict(THREE_YEAR_METRICS)
    if net_stored:
        metrics["net_profit"] = [1_700_000.0, 2_100_000.0, 2_600_000.0]
    return metrics


def test_deck_evolution_slide_two_charts_labels(tmp_path):
    """The deck's evolution slide: title + exactly TWO chart images, and the
    trends slide no longer carries a duplicated revenue chart."""
    import io
    import re
    import zipfile

    from app import pptx_report
    from app.analyzer import compute_series

    result = _result()
    result["kpis"] = {}
    result["ratios"] = {}
    result["series"] = compute_series(result["metrics"])
    out = tmp_path / "deck.pptx"
    pptx_report.build_pptx_report(
        filename="w.xlsx", result=result, out_path=out, lang="ar",
        yearly_comparison=build_yearly_comparison(result, "ar"),
    )
    z = zipfile.ZipFile(str(out))
    sh = pptx_report._shape
    evo, trends = [], []
    for n in z.namelist():
        if not re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
            continue
        x = z.read(n).decode("utf-8", "ignore")
        if sh("تطور الإيرادات وصافي الربح عبر السنوات") in x:
            evo.append(x)
        if sh("الرسوم البيانية التحليلية") in x:
            trends.append(x)
    assert len(evo) == 1, "evolution slide missing or duplicated"
    assert evo[0].count("<p:pic>") == 2, "evolution slide must hold TWO charts"
    assert trends, "trends slide lost"
    assert trends[0].count("<p:pic>") <= 3


def test_deck_evolution_uses_stored_net(tmp_path):
    """With a stored net_profit series the chart plots THOSE values (the
    derived chain is only a fallback)."""
    import app.report as report  # noqa: F401  (import sanity only)
    from app import pptx_report

    seen = {}

    real = pptx_report._chart_image

    def spy(values, projections=None, title="", labels=None):
        seen[title] = list(values)
        return real(values, projections, title, labels=labels)

    pptx_report._chart_image = spy
    try:
        result = _result(net_stored=True)
        result["kpis"] = {}
        result["ratios"] = {}
        result["series"] = __import__(
            "app.analyzer", fromlist=["compute_series"]
        ).compute_series(result["metrics"])
        out = tmp_path / "d2.pptx"
        pptx_report.build_pptx_report(
            filename="w.xlsx", result=result, out_path=out, lang="ar",
            yearly_comparison=build_yearly_comparison(result, "ar"),
        )
    finally:
        pptx_report._chart_image = real
    assert seen.get("صافي الربح") == [1_700_000.0, 2_100_000.0, 2_600_000.0]
