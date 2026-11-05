"""Interest coverage ratio (per the ratio reference set adopted from the
methodology in Qoyod's financial-analysis guide): EBIT / interest burden,
with the IFRS 18 financing-category finance_cost preferred over raw interest
capture. Also guards the ratio-explain card and the standard reference.
"""

from app.analyzer import compute_kpis, compute_ratios
from app.ifrs import RATIO_STANDARDS
from app.ratio_explain import build_ratio_insights


def _metrics(net, fin=None, interest=None):
    m = {"revenue": [1_000_000.0], "net_profit": [net]}
    if fin is not None:
        m["finance_cost"] = [fin]
    if interest is not None:
        m["interest"] = [interest]
    return m


class TestInterestCoverage:
    def test_computed_from_finance_cost(self):
        ratios = compute_ratios(_metrics(net=100_000.0, fin=50_000.0))
        # EBIT = 100k + 50k = 150k / 50k = 3.0x
        assert ratios["interest_coverage"]["value"] == 3.0
        assert ratios["interest_coverage"]["ar"] == "تغطية الفوائد (x)"

    def test_computed_from_interest_fallback(self):
        ratios = compute_ratios(_metrics(net=80_000.0, interest=20_000.0))
        # EBIT = 100k / 20k = 5.0x
        assert ratios["interest_coverage"]["value"] == 5.0

    def test_finance_cost_wins_over_interest(self):
        ratios = compute_ratios(_metrics(net=100_000.0, fin=40_000.0, interest=10_000.0))
        # EBIT = 140k / 40k = 3.5x (the interest capture is ignored)
        assert ratios["interest_coverage"]["value"] == 3.5

    def test_omitted_without_interest_burden(self):
        ratios = compute_ratios(_metrics(net=100_000.0))
        assert "interest_coverage" not in ratios

    def test_negative_interest_ignored(self):
        ratios = compute_ratios(_metrics(net=100_000.0, fin=-50_000.0))
        assert "interest_coverage" not in ratios

    def test_kpis_untouched_by_financing_items(self):
        kpis = compute_kpis(_metrics(net=100_000.0, fin=50_000.0))
        assert kpis["net_profit"]["value"] == 100_000.0


class TestCardAndReference:
    def test_card_present_with_reference(self):
        result = {
            "ratios": {"interest_coverage": {"value": 3.0,
                                             "en": "Interest Coverage (x)",
                                             "ar": "تغطية الفوائد (x)"}},
            "metrics": {},
        }
        ar = build_ratio_insights(result, lang="ar")
        assert ar[0]["key"] == "interest_coverage"
        assert "IFRS 18" in ar[0]["ifrs"]
        en = build_ratio_insights(dict(result), lang="en")
        assert "IFRS 18" in en[0]["ifrs"]

    def test_card_verdicts(self):
        def cards(value):
            result = {"ratios": {"interest_coverage": {"value": value}},
                      "metrics": {}}
            return build_ratio_insights(result)[0]

        assert cards(4.0)["verdict"] == "good"
        assert cards(1.0)["verdict"] == "bad"
        assert cards(2.0)["verdict"] == "neutral"

    def test_standard_registered(self):
        assert "interest_coverage" in RATIO_STANDARDS
        assert RATIO_STANDARDS["interest_coverage"]["code"] == "IFRS 18 · IFRS 9"
