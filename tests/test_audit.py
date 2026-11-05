"""Quality-gate tests: every production failure class becomes a rule.

Covers the failure classes seen in real files (دفتر «التقرير عام 2024»):
wholesale-negative cost/revenue conventions, gross/net incoherence (the
161%-margin bug), note-cell year leaks, empty extractions, unbalanced
financial statements — plus gate integration on the recomputation path.
"""

from app.audit import run_quality_gate, validate_statements


def _result(metrics: dict, **extra) -> dict:
    result = {"metrics": dict(metrics)}
    result.update(extra)
    return result


class TestFatal:
    def test_no_metrics_is_fatal(self):
        result = {"kpis": {}, "series": {}}
        report = run_quality_gate(result)
        assert report["fatal"] is True
        assert report["ok"] is False
        assert [i["code"] for i in result["audit"]["errors"]] == ["C7"]

    def test_zero_revenue_is_fatal(self):
        result = _result({"revenue": [0], "cogs": [0], "opex": [0]})
        report = run_quality_gate(result)
        assert report["fatal"] is True
        assert any(i["code"] == "C5" for i in result["audit"]["errors"])

    def test_gross_above_revenue_is_fatal(self):
        # the 161%-margin bug, with no cogs to repair from
        result = _result({"revenue": [1_000_000], "gross_profit": [2_620_000], "net_profit": [2_500_000]})
        report = run_quality_gate(result)
        assert report["fatal"] is True
        assert any(i["code"] == "C3" for i in result["audit"]["errors"])

    def test_net_above_revenue_without_opex_is_fatal(self):
        result = _result({"revenue": [1_000], "net_profit": [1_500]})
        report = run_quality_gate(result)
        assert report["fatal"] is True
        assert any(i["code"] == "C4" for i in result["audit"]["errors"])


class TestRepair:
    def test_wholesale_negative_costs_repaired(self):
        """The exact 161%-margin bug: negative cogs/opex + incoherent gross."""
        result = _result({
            "revenue": [876_206.95],
            "cogs": [-610_000.0],
            "opex": [-430_000.0],
            "gross_profit": [1_486_206.95],
            "net_profit": [916_206.95],
        })
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert report["repairs"] >= 3
        # values were rebuilt from revenue − cogs − opex
        assert abs(result["metrics"]["gross_profit"][-1] - 266_206.95) < 1
        assert abs(result["kpis"]["net_profit"]["value"] + 163_793.05) < 1
        assert abs(result["ratios"]["gross_margin"]["value"] - 30.4) < 0.5
        assert not any(i["code"] == "C3" for i in result["audit"]["errors"])

    def test_wholesale_negative_revenue_repaired(self):
        """The −13.5M revenue symptom: whole series in expense convention."""
        result = _result({"revenue": [-13_500_000.0], "cogs": [9_000_000.0]})
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert report["repairs"] >= 1
        assert result["kpis"]["revenue"]["value"] == 13_500_000.0

    def test_gross_incoherence_rederived(self):
        result = _result({
            "revenue": [1_000], "cogs": [300], "gross_profit": [900], "opex": [200],
        })
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert result["metrics"]["gross_profit"][-1] == 700
        # net was also re-derived: gross − opex
        assert result["kpis"]["net_profit"]["value"] == 500

    def test_stated_net_survives_partial_chain_without_gross(self):
        """«الراشد January-2026» multi-company workbook: the face states its
        own bottom line (net after below-the-tax-line manager commissions)
        while the capture saw only opex/tax rows and no gross line. The
        chain has no top — summing the present components treats the
        missing gross as zero and must NOT overwrite the stated net.
        """
        result = _result({
            "revenue": [762_284.99],
            "cogs": [488_864.43],
            "opex": [260_631.13],
            "tax_expense": [2_557.89],
            "net_profit": [6_650.51],   # stated, includes manager commissions
        })
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert report["repairs"] == 0
        assert result["metrics"]["net_profit"] == [6_650.51]
        # and R2 does not synthesize a gross top for R3 to chain off
        assert "gross_profit" not in result["metrics"]

    def test_gross_not_fabricated_when_absent(self):
        """R2 repairs a stored-but-wrong gross; it never synthesizes one
        from mismatched-length tails (revenue 2 periods vs cogs 1)."""
        result = _result({
            "revenue": [-0.64, 762_284.99],  # polluted pre-fix shape
            "cogs": [488_864.43],
        })
        run_quality_gate(result)
        assert "gross_profit" not in result["metrics"]

    def test_metadata_survives_repairs(self):
        """_sheet binding, period labels and data_quality must survive the
        gate's internal recomputations (split workbooks depend on it)."""
        result = _result(
            {"revenue": [876_206.95], "cogs": [-610_000.0], "opex": [-430_000.0]},
            _sheet="شاورما لايك",
            period_labels=["2024"],
            data_quality={"auto_fixed": True, "fixed_concepts": ["cogs"], "fixed_values": 1},
        )
        run_quality_gate(result)
        assert result["_sheet"] == "شاورما لايك"
        assert result["period_labels"] == ["2024"]
        assert result["data_quality"]["fixed_concepts"] == ["cogs"]
        assert "audit" in result


class TestWarnings:
    def test_yearlike_revenue_warns_not_fatal(self):
        result = _result({"revenue": [2024]})
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert report["warnings"] == 1
        assert result["audit"]["warnings"][0]["code"] == "W1"

    def test_deep_loss_margin_warns(self):
        result = _result({"revenue": [1_000], "cogs": [300], "opex": [100_000], "gross_profit": [700], "net_profit": [-99_300]})
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert any(i["code"] == "W2" for i in result["audit"]["warnings"])

    def test_missing_revenue_warns(self):
        result = _result({"assets": [500_000], "liabilities": [200_000]})
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert any(i["code"] == "W3" for i in result["audit"]["warnings"])


class TestCleanPasses:
    def test_coherent_result_untouched(self):
        result = _result({
            "revenue": [3_153_287.03],
            "cogs": [2_400_000.0],
            "opex": [958_015.58],
            "gross_profit": [753_287.03],
            "net_profit": [-204_728.55],
        })
        report = run_quality_gate(result)
        assert report["fatal"] is False
        assert report["repairs"] == 0
        assert report["warnings"] == 0
        assert result["audit"]["ok"] is True
        assert abs(result["kpis"]["net_profit"]["value"] + 204_728.55) < 1

    def test_audit_block_bilingual(self):
        result = _result({"revenue": [2024]})
        run_quality_gate(result)
        issue = result["audit"]["warnings"][0]
        assert issue["ar"] and issue["en"] and issue["code"] == "W1"


class TestCheckOnly:
    """apply_repairs=False — the legacy-row backfill mode: full rule set
    evaluated against the values AS STORED, would-be repairs reported as
    warnings, and zero mutation of the historical figures."""

    def test_no_numbers_are_touched(self):
        metrics = {
            "revenue": [-13_500_000.0],
            "cogs": [9_000_000.0],
            "gross_profit": [22_500_000.0],  # incoherent exactly as stored
        }
        result = _result(metrics)
        report = run_quality_gate(result, apply_repairs=False)
        # every stored number is exactly as it was
        assert result["metrics"] == metrics
        # would-be repairs are warnings, never applied
        codes = [i["code"] for i in result["audit"]["warnings"]]
        assert "R1" in codes and "R2" in codes
        assert result["audit"]["repairs"] == []
        assert result["audit"]["mode"] == "check_only"
        assert report["repairs"] == 0
        # stored corruption stays visible: negative revenue is a C5 error here
        assert report["fatal"] is True
        assert any(i["code"] == "C5" for i in result["audit"]["errors"])

    def test_fatal_still_reported_against_stored_values(self):
        # the 161%-margin shape, evaluated as stored (no repair first)
        result = _result({
            "revenue": [876_206.95],
            "cogs": [-610_000.0],
            "opex": [-430_000.0],
            "gross_profit": [1_486_206.95],
            "net_profit": [916_206.95],
        })
        report = run_quality_gate(result, apply_repairs=False)
        assert report["fatal"] is True  # C3 against the stored figures
        assert any(i["code"] == "C3" for i in result["audit"]["errors"])
        # figures untouched
        assert result["metrics"]["revenue"] == [876_206.95]
        assert result["metrics"]["cogs"] == [-610_000.0]
        assert result["metrics"]["gross_profit"] == [1_486_206.95]

    def test_clean_legacy_row_gets_green_record(self):
        result = _result({
            "revenue": [3_153_287.03],
            "cogs": [2_400_000.0],
            "gross_profit": [753_287.03],
            "opex": [958_015.58],
            "net_profit": [-204_728.55],
        })
        report = run_quality_gate(result, apply_repairs=False)
        assert report["fatal"] is False
        assert result["audit"]["ok"] is True
        assert result["audit"]["mode"] == "check_only"
        assert result["metrics"]["revenue"] == [3_153_287.03]


class TestStatementsGate:
    def _statements(self, balanced=True, tie=True):
        rev, cogs, gross = 1_000.0, 400.0, (600.0 if tie else 900.0)
        opex, net = 250.0, gross - 250.0
        assets = 800.0
        liab_eq = assets if balanced else assets - 120.0
        return {
            "trial_balance": {"balanced": balanced, "total_debit": 900, "accounts": [{"account": "1", "debit": 900, "credit": 900}]},
            "income_statement": {
                "revenue": rev, "cogs": cogs, "gross_profit": gross, "opex": opex, "net_profit": net,
            },
            "balance_sheet": {
                "balanced": abs(assets - liab_eq) < 0.01,
                "difference": round(assets - liab_eq, 2),
                "assets": {"total": assets},
                "liabilities_equity": {"total": liab_eq},
            },
        }

    def test_valid_statements_pass(self):
        assert validate_statements(self._statements()) == []

    def test_unbalanced_balance_sheet_rejected(self):
        problems = validate_statements(self._statements(balanced=False))
        assert any("الميزانية" in p for p in problems)

    def test_incoherent_income_rejected(self):
        problems = validate_statements(self._statements(tie=False))
        assert any("قائمة الدخل" in p for p in problems)


# ---------------------------------------------------------------------------
# OCR read-confidence (W3)
# ---------------------------------------------------------------------------

def test_ocr_suspect_patterns_flagged_w3():
    """OCR-sourced series with read-corruption digit patterns (zigzag
    groups, tiny odd remainders) raise a W3 warning naming the affected
    concepts — and a clean text-layer extraction raises nothing."""
    from app.audit import _suspect_ocr_value, flag_suspect_ocr_numbers

    # pattern verdicts
    assert _suspect_ocr_value(494949.0) is True     # zigzag 4/9
    assert _suspect_ocr_value(163.0) is True        # odd 3-digit remainder
    assert _suspect_ocr_value(4245868.0) is False   # real amount shape
    assert _suspect_ocr_value(150000.0) is False    # round clean figure
    assert _suspect_ocr_value(163524.0) is False    # even 3-digit tail

    # flagged for OCR results, silent for text-layer ones
    result = _result(
        {"revenue": [19_575_585.0, 1_872_225_849.0][:2],
         "tax_expense": [163.0, 0.0][:2]},
        _ocr_used=True,
    )
    # make the series realistic: a zigzag tax tail and an odd remainder
    result["metrics"] = {
        "revenue": [19_575_585.0, 18_722_258.0],
        "tax_expense": [249659.0, 494949.0],
    }
    n = flag_suspect_ocr_numbers(result)
    assert n >= 1
    assert result["ocr_confidence"]["suspect"] is True
    assert "tax_expense" in result["ocr_confidence"]["suspect_concepts"]

    clean = _result({"revenue": [19_575_585.0], "tax_expense": [249659.0]},
                    _ocr_used=False)
    assert flag_suspect_ocr_numbers(clean) == 0
    assert "ocr_confidence" not in clean


def test_ocr_misattributed_series_flagged_w3():
    """A concept series carrying more non-zero readings than any plausible
    period count is OCR row-soup (rows collapsed into the wrong concept):
    it is flagged even when every digit pattern looks innocent. A series
    at the threshold stays clean."""
    from app.audit import flag_suspect_ocr_numbers

    # 7 non-zero readings of «cash» from a 2-year balance sheet → soup
    soup = _result(
        {"revenue": [19_575_585.0, 18_722_258.0],
         "cash": [27465.0, 54083.0, 6611.0, 45120.0, 939710.0, 68595.0, 4311.0]},
        _ocr_used=True,
    )
    assert flag_suspect_ocr_numbers(soup) >= 1
    assert soup["ocr_confidence"]["suspect"] is True
    assert "cash" in soup["ocr_confidence"]["suspect_concepts"]
    # exactly 6 non-zero readings is still plausible → not flagged
    edge = _result(
        {"cash": [27465.0, 54083.0, 6611.0, 45120.0, 939710.0, 68595.0]},
        _ocr_used=True,
    )
    assert flag_suspect_ocr_numbers(edge) == 0
    assert edge["ocr_confidence"]["suspect"] is False
    # zeros do not count toward the threshold
    zeros = _result({"cash": [0.0] * 8 + [27465.0]}, _ocr_used=True)
    assert flag_suspect_ocr_numbers(zeros) == 0


def test_gate_flags_ocr_w3_and_counts_it():
    """run_quality_gate on an OCR result emits the W3 warning into the
    audit log and counts it in the gate report's warnings."""
    result = _result(
        {"revenue": [19_575_585.0, 18_722_258.0],
         "opex": [2789745.0, 469022.0],
         "tax_expense": [249659.0, 494949.0]},
        _ocr_used=True,
    )
    report = run_quality_gate(result)
    assert report["fatal"] is False
    codes = [i["code"] for i in result["audit"]["warnings"]]
    assert "W3" in codes
    assert report["warnings"] == len(result["audit"]["warnings"])


def test_recompute_preserves_audit_and_quality():
    """recompute_result must keep data_quality + audit + _sheet so the gate
    can run repeatedly (reanalyze → user edit → recompute chains)."""
    from app.analyzer import recompute_result

    result = _result(
        {"revenue": [1_000], "cogs": [400]},
        _sheet="ورقة 1",
        data_quality={"auto_fixed": True, "fixed_concepts": ["revenue"], "fixed_values": 1},
        audit={"ok": True, "errors": [], "warnings": [], "repairs": []},
    )
    recomputed = recompute_result(result)
    assert recomputed["_sheet"] == "ورقة 1"
    assert recomputed["data_quality"]["fixed_concepts"] == ["revenue"]
    assert recomputed["audit"]["ok"] is True
