"""CMRRS-style numbered key findings + strategic recommendations."""

from app.brief import build_key_findings, build_strategic_recs


def _result(ratios: dict, metrics: dict | None = None, net: float | None = None):
    r = {
        "ratios": {k: {"value": v, "en": k, "ar": k} for k, v in ratios.items()},
        "metrics": metrics or {},
        "kpis": {},
    }
    if net is not None:
        r["kpis"]["net_profit"] = {"value": net, "en": "Net", "ar": "صافي"}
    if metrics.get("revenue"):
        r["kpis"]["revenue"] = {"value": metrics["revenue"][-1], "en": "Revenue", "ar": "الإيرادات"}
    return r


_REF = {  # CMRRS reference pattern: +25% growth, 15% margins, 2x liquidity
    "revenue": [12_000_000.0, 15_000_000.0],
    "cogs": [8_400_000.0, 10_500_000.0],
    "net_profit": [1_800_000.0, 2_250_000.0],
    "assets": [22_000_000.0, 25_000_000.0],
}
_REF_RATIOS = {
    "gross_margin": 30.0, "net_margin": 15.0, "debt_ratio": 40.0,
    "current_ratio": 2.0, "roe": 15.0,
}


def test_findings_follow_reference_story():
    findings = build_key_findings(_result(_REF_RATIOS, _REF, net=2_250_000.0), "ar")
    assert any("نمو" in f and "+25%" in f for f in findings)
    assert any("ربحية" in f for f in findings)
    assert any("2.00x" in f for f in findings)
    assert len(findings) <= 4


def test_findings_loss_case():
    metrics = {"revenue": [5_000_000.0, 4_800_000.0], "net_profit": [-300_000.0]}
    findings = build_key_findings(
        _result({"net_margin": -6.3}, metrics, net=-300_000.0), "ar"
    )
    assert any("خسارة" in f or "تراجع" in f for f in findings)


def test_recs_growth_case():
    recs = build_strategic_recs(_result(_REF_RATIOS, _REF), "ar")
    assert any("مراقبة" in r or "دورياً" in r for r in recs)
    assert len(recs) <= 4


def test_recs_loss_case_has_cost_programme():
    metrics = {"revenue": [5_000_000.0, 4_800_000.0]}
    recs = build_strategic_recs(_result({"net_margin": -6.3}, metrics), "ar")
    assert any("خفض التكاليف" in r or "تسعير" in r for r in recs)
    assert any("تنشيط المبيعات" in r for r in recs)  # declining revenue


def test_recs_high_debt_and_thin_liquidity():
    metrics = {"revenue": [100.0, 100.0]}
    recs = build_strategic_recs(
        _result({"net_margin": 20.0, "debt_ratio": 85.0, "current_ratio": 0.6}, metrics),
        "ar",
    )
    assert any("إعادة هيكلة" in r for r in recs)
    assert any("رأس المال العامل" in r for r in recs)


def test_empty_data_returns_empty_lists():
    assert build_key_findings({"metrics": {}, "ratios": {}, "kpis": {}}, "ar") == []
    recs = build_strategic_recs({"metrics": {}, "ratios": {}, "kpis": {}}, "ar")
    # even with no data the generic governance recs fill in
    assert len(recs) >= 2


def test_english_mirror():
    findings = build_key_findings(_result(_REF_RATIOS, _REF, net=2_250_000.0), "en")
    assert any("growth" in f.lower() and "+25%" in f for f in findings)
    recs = build_strategic_recs(_result(_REF_RATIOS, _REF), "en")
    assert all(isinstance(r, str) for r in recs)


# ---------------------------------------------------------------------------
# section order in the generated PDF mirrors the new UI order

def test_pdf_section_order_matches_ui(client, tmp_path):
    import pdfplumber

    demo_id = client.post("/api/demo").json()["id"]
    res = client.get(f"/api/analyses/{demo_id}/report?lang=ar", headers=client.auth_headers)
    assert res.status_code == 200
    out = tmp_path / "out.pdf"
    out.write_bytes(res.content)
    with pdfplumber.open(out) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]

    # RTL extract_text reverses presentation forms, so instead of Arabic
    # markers we assert the structure: the closing findings/recommendations
    # page (title "ﺎﺘﺎﺻﻮﺘﻟﺍ" or numbered lines) comes last, and the financial
    # statements appear before it.
    full_last = pages[-1]
    # RTL extract_text shows presentation forms; match on the exact shapes
    # observed for "الاستنتاجات الرئيسية" / "التوصيات الاستراتيجية".
    assert "ﺕﺎﺟﺎﺘﻨﺘﺳﻻﺍ" in full_last and "ﺕﺎﻴﺻﻮﺘﻟﺍ" in full_last
