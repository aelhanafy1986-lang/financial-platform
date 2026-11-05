"""Broken-sign cleaning + data-quality warnings."""

from app.analyzer import recompute_result
from app.hygiene import (
    backfill_warnings,
    clean_result,
    data_quality_warnings,
    detect_broken_signs,
    fix_broken_signs,
)


# -- detection ---------------------------------------------------------------


def test_detect_mixed_sign_revenue():
    metrics = {"revenue": [100.0, -50_023_397.75, 5_021_467.23]}
    assert detect_broken_signs(metrics) == ["revenue"]


def test_detect_skips_all_negative_wholesale_convention():
    # every value negative (wholesale convention) → not flagged
    metrics = {"revenue": [-100.0, -200.0], "cash": [-50.0]}
    assert detect_broken_signs(metrics) == []


def test_detect_ignores_net_profit_and_unknown_concepts():
    metrics = {"net_profit": [100.0, -50.0], "equity": [10.0, -5.0]}
    assert detect_broken_signs(metrics) == []


def test_clean_series_never_flagged():
    assert detect_broken_signs({"revenue": [100.0, 200.0]}) == []


# -- repair --------------------------------------------------------------------


def test_fix_flips_negatives_to_absolute():
    metrics = {"revenue": [5_891.06, 5_029_288.81, -5_023_397.75, 5_021_467.23]}
    cleaned, fixed = fix_broken_signs(metrics)
    assert fixed == 1
    assert cleaned["revenue"] == [5_891.06, 5_029_288.81, 5_023_397.75, 5_021_467.23]
    # input not mutated
    assert metrics["revenue"][2] == -5_023_397.75


def test_fix_all_negative_nature_concept_flips_only_with_positives():
    # all-negative assets stay untouched (no positive anchor)…
    cleaned, fixed = fix_broken_signs({"assets": [-100.0, -200.0]})
    assert fixed == 0 and cleaned["assets"] == [-100.0, -200.0]
    # …but a single negative among positives is flipped
    cleaned, fixed = fix_broken_signs({"assets": [100.0, -200.0]})
    assert fixed == 1 and cleaned["assets"] == [100.0, 200.0]


def test_fix_leaves_mixed_nature_liabilities_majority_rule():
    # liabilities: majority positive → flip
    cleaned, fixed = fix_broken_signs({"liabilities": [100.0, 200.0, -50.0]})
    assert fixed == 1 and cleaned["liabilities"] == [100.0, 200.0, 50.0]
    # majority negative → wholesale convention, untouched
    cleaned, fixed = fix_broken_signs({"liabilities": [-100.0, -200.0, 50.0]})
    assert fixed == 0 and cleaned["liabilities"] == [-100.0, -200.0, 50.0]


# -- clean_result on stored results -------------------------------------------


def _result_with_revenue(values):
    return {
        "metrics": {"revenue": list(values), "net_profit": [-80_000.0]},
        "kpis": {
            "revenue": {"value": values[-1], "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": -80_000.0, "en": "Net Loss", "ar": "صافي الخسارة"},
        },
        "ratios": {},
        "series": {"revenue": {"values": list(values), "en": "Revenue", "ar": "الإيرادات"}},
    }


def test_clean_result_fixes_and_records_quality_block():
    result = _result_with_revenue([5_891.06, 5_029_288.81, -5_023_397.75, 5_021_467.23])
    clean_result(result)
    assert result["metrics"]["revenue"] == [5_891.06, 5_029_288.81, 5_023_397.75, 5_021_467.23]
    dq = result["data_quality"]
    assert dq["auto_fixed"] is True
    assert dq["fixed_concepts"] == ["revenue"]
    assert dq["fixed_values"] == 1
    # raw extraction archived for the user's reset button
    assert result["original_metrics"]["revenue"][2] == -5_023_397.75


def test_clean_result_skips_clean_series():
    result = _result_with_revenue([100.0, 200.0, 300.0])
    clean_result(result)
    assert "data_quality" not in result


def test_clean_result_noop_without_metrics():
    result = {"kpis": {}, "ratios": {}}
    assert clean_result(result) is result
    assert "data_quality" not in result


def test_recompute_after_clean_keeps_series_positive():
    result = _result_with_revenue([1000.0, -500.0, 800.0])
    clean_result(result)
    recomputed = recompute_result(result)
    assert all(v > 0 for v in recomputed["series"]["revenue"]["values"])


# -- warnings --------------------------------------------------------------


def test_warnings_ar_and_en():
    result = {"data_quality": {"fixed_concepts": ["revenue", "cogs"], "fixed_values": 3, "auto_fixed": True}}
    ar = data_quality_warnings(result, "ar")
    en = data_quality_warnings(result, "en")
    assert len(ar) == len(en) == 1
    assert "الإيرادات" in ar[0] and "مراجعة" in ar[0]
    assert "Revenue" in en[0] and "manual review" in en[0]


def test_warning_flagged_variant_for_legacy_rows():
    result = {"data_quality": {"fixed_concepts": ["revenue"], "auto_fixed": False}}
    ar = data_quality_warnings(result, "ar")
    en = data_quality_warnings(result, "en")
    assert "إعادة تحليل" in ar[0]
    assert "Reanalyze" in en[0]


def test_warnings_empty_when_clean():
    assert data_quality_warnings({"metrics": {}}, "ar") == []


# -- backfill ----------------------------------------------------------------


def test_backfill_flags_legacy_rows(tmp_path, monkeypatch):
    import json
    import sqlite3

    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE analyses (id INTEGER PRIMARY KEY, result_json TEXT)"
    )
    broken = json.dumps({"metrics": {"revenue": [100.0, -50.0]}})
    clean = json.dumps({"metrics": {"revenue": [100.0, 50.0]}})
    already = json.dumps(
        {"metrics": {"revenue": [100.0, -50.0]}, "data_quality": {"fixed_concepts": ["revenue"]}}
    )
    con.executemany(
        "INSERT INTO analyses (result_json) VALUES (?)",
        [(broken,), (clean,), (already,)],
    )
    con.commit()
    con.close()

    # redirect the module's default path for this call
    import app.hygiene as hygiene

    monkeypatch.setattr(hygiene, "DB_PATH", db)
    assert hygiene.backfill_warnings(db) == 1  # only the un-flagged broken row

    con = sqlite3.connect(db)
    rows = [json.loads(r[0]) for r in con.execute("SELECT result_json FROM analyses")]
    con.close()
    assert rows[0]["data_quality"]["auto_fixed"] is False
    assert rows[0]["data_quality"]["fixed_concepts"] == ["revenue"]
    assert rows[1].get("data_quality") is None  # clean row untouched
    # already-flagged row kept its original block
    assert rows[2]["data_quality"]["fixed_concepts"] == ["revenue"]
