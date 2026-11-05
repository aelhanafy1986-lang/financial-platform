"""CMRRS-style ratio insights + consistency checks."""

from app.ratio_explain import (
    BADGES,
    build_consistency_checks,
    build_ratio_insights,
    _judge,
)
from app.analyzer import compute_ratios


def _result(ratios: dict, metrics: dict | None = None) -> dict:
    return {
        "ratios": {k: {"value": v, "en": k, "ar": k} for k, v in ratios.items()},
        "metrics": metrics or {},
    }


# -- verdict rules -------------------------------------------------------------


def test_judge_margin_thresholds():
    assert _judge("net_margin", 15.0) == "good"
    assert _judge("net_margin", -18.0) == "bad"
    assert _judge("net_margin", 10.0) == "neutral"


def test_judge_leverage_lower_is_better():
    assert _judge("debt_ratio", 40.0) == "good"
    assert _judge("debt_ratio", 90.0) == "bad"
    assert _judge("debt_to_equity", 0.67) == "good"
    assert _judge("debt_to_equity", 2.5) == "bad"


def test_judge_liquidity_bands():
    assert _judge("current_ratio", 2.0) == "good"
    assert _judge("current_ratio", 0.5) == "bad"
    assert _judge("current_ratio", 1.0) == "neutral"


# -- cards ----------------------------------------------------------------


def test_cards_only_for_present_ratios():
    cards = build_ratio_insights(_result({"net_margin": 15.0}), "ar")
    assert [c["key"] for c in cards] == ["net_margin"]
    assert cards[0]["verdict"] == "good"
    assert "ما هي" not in cards[0]["what"]  # plain text, no label duplication
    assert cards[0]["why"] and cards[0]["opinion"]


def test_cards_percent_flag():
    cards = build_ratio_insights(
        _result({"net_margin": 15.0, "current_ratio": 2.0}), "en"
    )
    by_key = {c["key"]: c for c in cards}
    assert by_key["net_margin"]["is_percent"] is True
    assert by_key["current_ratio"]["is_percent"] is False


def test_cards_carry_unified_badge_labels():
    """Every card carries the unified HUD badge (جيد/متوسط/ضعيف) — one label
    per verdict class, bilingual, straight from the BADGES source."""
    # net_margin 15 ≥ 12 → good; current_ratio 1.0 sits between 0.8 and 1.2
    # → neutral; interest_coverage 0.5 < 1.5 → bad
    cards = build_ratio_insights(
        _result({"net_margin": 15.0, "current_ratio": 1.0,
                 "interest_coverage": 0.5}),
        "ar",
    )
    by_key = {c["key"]: c for c in cards}
    assert by_key["net_margin"]["badge"] == {"ar": "جيد", "en": "Good"}
    assert by_key["current_ratio"]["badge"] == {"ar": "متوسط", "en": "Average"}
    assert by_key["interest_coverage"]["badge"] == {"ar": "ضعيف", "en": "Weak"}
    # the badge set is exactly the three unified ratings — no other labels exist
    assert set(BADGES) == {"good", "neutral", "bad"}


def test_pdf_ratio_cards_render_the_badge(tmp_path):
    """The redesigned PDF card shows its verdict badge chip — the shaped
    Arabic rating word (or the English one) reaches the page text."""
    import pdfplumber
    import arabic_reshaper
    from bidi.algorithm import get_display

    from app.report import build_report, _shape

    metrics = {
        "revenue": [15_000_000.0],
        "net_profit": [2_250_000.0],
        "gross_profit": [4_500_000.0],
        "assets": [25_000_000.0],
        "liabilities": [10_000_000.0],
        "equity": [15_000_000.0],
    }
    result = {
        "kpis": {
            "revenue": {"value": 15_000_000.0, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": 2_250_000.0, "en": "Net Profit", "ar": "صافي الربح"},
        },
        "ratios": compute_ratios(metrics),
        "metrics": metrics,
        "series": {},
        "forecast": [],
        "tables_found": 1,
        "texts_found": 0,
        "analysed_at": None,
    }
    out = tmp_path / "badges.pdf"
    build_report(
        filename="badges.xlsx",
        result=result,
        out_path=out,
        lang="ar",
        ratio_insights=build_ratio_insights(result, "ar"),
        consistency_checks=None,
    )
    assert out.exists()
    with pdfplumber.open(str(out)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    flat = "".join(text.split())
    # at least one badge reached a card header (net_margin 15% → جيد)
    assert _shape("جيد") in flat


def test_cards_broken_signs_note_added():
    metrics = {"revenue": [100.0, -50.0], "assets": [10.0, 20.0]}
    cards = build_ratio_insights(
        _result({"roa": 9.0, "net_margin": 15.0}, metrics), "ar"
    )
    by_key = {c["key"]: c for c in cards}
    assert "متكسرة" in by_key["roa"]["opinion"]
    assert "متكسرة" not in by_key["net_margin"]["opinion"]


# -- new ratios in analyzer ------------------------------------------------


def test_compute_ratios_liquidity_and_returns():
    metrics = {
        "revenue": [15_000_000.0],
        "net_profit": [2_250_000.0],
        "assets": [25_000_000.0],
        "liabilities": [10_000_000.0],
        "equity": [15_000_000.0],
        "current_assets": [20_000_000.0],
        "inventory": [7_500_000.0],
    }
    ratios = compute_ratios(metrics)
    assert ratios["current_ratio"]["value"] == 2.0
    assert ratios["quick_ratio"]["value"] == 1.25
    assert ratios["roa"]["value"] == 9.0
    assert ratios["roe"]["value"] == 15.0
    assert ratios["asset_turnover"]["value"] == 0.6


def test_compute_ratios_skip_when_denominator_missing():
    ratios = compute_ratios({"revenue": [100.0], "net_profit": [10.0]})
    assert "roa" not in ratios and "roe" not in ratios
    assert "current_ratio" not in ratios


# -- consistency checks ------------------------------------------------------


def test_checks_all_pass_on_consistent_statements():
    result = {
        "metrics": {
            "revenue": [15_000_000.0],
            "opex": [2_250_000.0],
            "assets": [25_000_000.0],
            "liabilities": [10_000_000.0],
            "equity": [15_000_000.0],
        },
        "kpis": {"gross_profit": {"value": 4_500_000.0}},
        "ratios": {
            "net_margin": {"value": 15.0},
            "gross_margin": {"value": 30.0},
        },
    }
    checks = build_consistency_checks(result, "ar")
    by_label = {c["label"]: c for c in checks}
    assert by_label["الإيرادات ≥ الربح الإجمالي"]["ok"] is True
    assert by_label["الأصول = الالتزامات + حقوق الملكية"]["ok"] is True
    assert by_label["هامش صافي الربح ≤ الهامش الإجمالي"]["ok"] is True


def test_checks_catch_unbalanced_balance_sheet():
    result = {
        "metrics": {
            "assets": [25_000_000.0],
            "liabilities": [10_000_000.0],
            "equity": [20_000_000.0],  # 10M off-balance
        },
        "ratios": {},
    }
    checks = build_consistency_checks(result, "en")
    balance = [c for c in checks if "Assets" in c["label"]]
    assert balance and balance[0]["ok"] is False


def test_checks_empty_when_no_data():
    assert build_consistency_checks({"metrics": {}, "ratios": {}}, "ar") == []
