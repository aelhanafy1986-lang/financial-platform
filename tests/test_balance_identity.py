"""Balance-sheet identity check (W4): الأصول = الالتزامات + حقوق الملكية.

After every upload/reanalysis the gate asserts the identity on the latest
period; a gap over 2% of total assets means the extracted balance sheet
does not hold together — the analysis saves WITH a warning (shown in the
UI badge, the PDF header band and the PPTX cover) instead of silently
accepting suspect figures."""

from app.audit import check_balance_sheet_identity, run_quality_gate


def _result(assets, liabilities, equity, revenue=None, net=None) -> dict:
    metrics = {"assets": [assets], "liabilities": [liabilities], "equity": [equity]}
    if revenue is not None:
        metrics["revenue"] = [revenue]
    if net is not None:
        metrics["net_profit"] = [net]
    return {"metrics": metrics}


class TestBalanceIdentity:
    def test_balanced_passes_silent(self):
        res = _result(10_000_000.0, 4_000_000.0, 6_000_000.0)
        assert check_balance_sheet_identity(res) is None
        gate = run_quality_gate(res)
        assert not gate["fatal"]
        codes = [w["code"] for w in res["audit"]["warnings"]]
        assert "W4" not in codes

    def test_small_gap_within_tolerance(self):
        # 1% of assets: inside the 2% threshold → no warning
        res = _result(10_000_000.0, 4_000_000.0, 5_900_000.0)
        assert check_balance_sheet_identity(res) is None

    def test_gap_over_threshold_warns(self):
        # المراعي shape: liabilities+equity overshoot assets by ~8%
        res = _result(666_336.0, 4_245_868.0, 3_718_852.0,
                      revenue=19_575_585.0, net=2_051_529.0)
        gap = check_balance_sheet_identity(res)
        assert gap is not None
        assert gap["gap_pct"] > 2.0
        gate = run_quality_gate(res)
        assert not gate["fatal"]  # warned, not rejected
        w4 = next(w for w in res["audit"]["warnings"] if w["code"] == "W4")
        assert "غير متوازنة" in w4["ar"]
        assert "suspect" in w4["en"]

    def test_missing_side_never_asserts(self):
        # balance-sheet-only file (no revenue) with only two of the totals
        res = {"metrics": {"assets": [5_000_000.0], "equity": [2_000_000.0]}}
        assert check_balance_sheet_identity(res) is None
        gate = run_quality_gate(res)
        assert not gate["fatal"]

    def test_check_only_mode_also_flags(self):
        res = _result(666_336.0, 4_245_868.0, 3_718_852.0)
        run_quality_gate(res, apply_repairs=False)
        assert any(w["code"] == "W4" for w in res["audit"]["warnings"])


class TestWarningsReachReports:
    def test_pdf_renders_the_warning_band(self, tmp_path):
        from app.report import build_report

        res = _result(666_336.0, 4_245_868.0, 3_718_852.0,
                      revenue=19_575_585.0, net=2_051_529.0)
        run_quality_gate(res)
        out = tmp_path / "w4.pdf"
        build_report(filename="bs.xlsx", result=res, out_path=out, lang="ar")
        assert out.exists()
        import pdfplumber

        with pdfplumber.open(str(out)) as pdf:
            text = " ".join((p.extract_text() or "") for p in pdf.pages[:1])
        flat = text.replace(" ", "")
        # Arabic in PDFs is display-shaped — match the same way
        import arabic_reshaper
        from bidi.algorithm import get_display

        def _sh(s):
            return get_display(arabic_reshaper.reshape(s)).replace(" ", "")

        assert _sh("غير متوازنة") in flat or "W4" in flat

    def test_pptx_cover_carries_the_warning(self, tmp_path):
        from app.pptx_report import build_pptx_report, _shape

        res = _result(666_336.0, 4_245_868.0, 3_718_852.0,
                      revenue=19_575_585.0, net=2_051_529.0)
        run_quality_gate(res)
        out = tmp_path / "w4.pptx"
        build_pptx_report(filename="bs.xlsx", result=res, out_path=out, lang="ar")
        import zipfile

        z = zipfile.ZipFile(str(out))
        cover = z.read("ppt/slides/slide1.xml").decode("utf-8", "ignore")
        # ⚠ degrades to «!» via _GLYPH_SUBS (majalla lacks the glyph) — in
        # the visual-order run it lands at either end of the shaped text
        assert "⚠" in cover or "!" in cover
        assert _shape("غير متوازنة") in cover
