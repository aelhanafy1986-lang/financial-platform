"""IFRS knowledge-base tests — the platform's standards backbone.

Covers applicability detection (concepts, statement buckets, ledger
keywords), the always-on IAS 1 umbrella, IFRS 18 presence, bilingual basis
of preparation, ratio-to-standard attribution, and the ratio-insights
integration.
"""

from app.ifrs import (
    IFRS_LIBRARY,
    RATIO_STANDARDS,
    basis_of_preparation,
    detect_applicable,
    framework_note,
    ratio_reference,
)

PLATFORM_RATIOS = [
    "gross_margin", "net_margin", "debt_ratio", "debt_to_equity",
    "current_ratio", "quick_ratio", "roa", "roe", "asset_turnover",
]


def _result(metrics: dict) -> dict:
    return {"metrics": metrics}


class TestDetection:
    def test_ias1_is_always_present(self):
        notes = detect_applicable({})
        assert [n["code"] for n in notes][0] == "IAS 1"

    def test_revenue_triggers_ifrs15_cash_triggers_ias7(self):
        notes = detect_applicable(_result({"revenue": [1000], "cash": [500]}))
        codes = [n["code"] for n in notes]
        assert "IFRS 15" in codes
        assert "IAS 7" in codes

    def test_statement_buckets_trigger_their_standards(self):
        st = {
            "balance_sheet": {
                "assets": {"detail": {"receivables": [], "inventory": [], "fixed_assets": []}},
                "liabilities_equity": {"detail": {"loans": []}},
            },
        }
        codes = [n["code"] for n in detect_applicable({}, st)]
        assert "IFRS 9" in codes  # receivables + loans
        assert "IAS 2" in codes   # inventory
        assert "IAS 16" in codes  # fixed assets

    def test_ledger_keyword_rent_triggers_ifrs16(self):
        st = {"trial_balance": {"accounts": [
            {"account": "مصروف الإيجار", "debit": 100, "credit": 0},
        ]}}
        codes = [n["code"] for n in detect_applicable({}, st)]
        assert "IFRS 16" in codes

    def test_every_detected_entry_carries_reason_and_gist(self):
        for n in detect_applicable(_result({"revenue": [1000], "cogs": [400]})):
            assert n["why_ar"] and n["why_en"]
            assert n["gist_ar"] and n["gist_en"]
            assert n["ar"] and n["en"]

    def test_library_contains_core_standards_including_ifrs18(self):
        codes = {s["code"] for s in IFRS_LIBRARY}
        assert {"IAS 1", "IAS 2", "IAS 7", "IAS 16", "IAS 36", "IAS 37",
                "IAS 38", "IFRS 9", "IFRS 13", "IFRS 15", "IFRS 16",
                "IFRS 18"} <= codes


class TestTexts:
    def test_basis_is_bilingual_and_names_the_framework(self):
        ar, en = basis_of_preparation("ar"), basis_of_preparation("en")
        assert "IFRS" in ar and "IFRS" in en
        assert "الاستحقاق" in ar and "accrual" in en
        assert "IAS 1" in ar and "IAS 7" in ar

    def test_framework_note_packages_basis_and_standards(self):
        note = framework_note(_result({"revenue": [10]}), lang="ar")
        assert note["basis"].startswith("أُعدّ هذا التحليل")
        codes = [s["code"] for s in note["standards"]]
        assert "IFRS 15" in codes
        note_en = framework_note(_result({"revenue": [10]}), lang="en")
        entry = next(s for s in note_en["standards"] if s["code"] == "IFRS 15")
        assert "Revenue" in entry["title"]


class TestRatioAttribution:
    def test_every_platform_ratio_has_a_standard(self):
        for key in PLATFORM_RATIOS:
            assert key in RATIO_STANDARDS, key
            ref = ratio_reference(key, "ar")
            assert ref and "IAS" in ref
            assert ratio_reference(key, "en")

    def test_unknown_ratio_returns_none(self):
        assert ratio_reference("unknown_ratio", "ar") is None


class TestIntegration:
    def test_ratio_insight_cards_carry_their_reference(self):
        from app.ratio_explain import build_ratio_insights

        result = {"ratios": {"gross_margin": {"value": 30.4},
                             "net_margin": {"value": -6.5}},
                  "metrics": {}}
        cards = build_ratio_insights(result, lang="ar")
        assert cards and all("ifrs" in c for c in cards)
        gm = next(c for c in cards if c["key"] == "gross_margin")
        assert "IAS 2" in gm["ifrs"]
        nm = next(c for c in cards if c["key"] == "net_margin")
        assert "IAS 1" in nm["ifrs"]

    def test_cards_bilingual_reference(self):
        from app.ratio_explain import build_ratio_insights

        result = {"ratios": {"roa": {"value": 4.0}}, "metrics": {}}
        ar = build_ratio_insights(result, lang="ar")[0]["ifrs"]
        en = build_ratio_insights(result, lang="en")[0]["ifrs"]
        assert "IAS 16" in ar and "IAS 16" in en
        assert ar != en  # عربي/إنجليزي في الوصف
