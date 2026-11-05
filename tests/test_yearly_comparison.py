"""Yearly comparative table (horizontal + vertical analysis)."""

from app.ratio_explain import build_yearly_comparison


def _result(metrics: dict):
    return {"metrics": metrics}


def _metrics():
    # consistent two-period P&L + balance sheet (CMRRS reference pattern)
    return {
        "revenue": [12_000_000.0, 15_000_000.0],
        "cogs": [8_400_000.0, 10_500_000.0],
        "opex": [1_800_000.0, 2_250_000.0],
        "net_profit": [1_800_000.0, 2_250_000.0],
        "assets": [22_000_000.0, 25_000_000.0],
        "liabilities": [9_000_000.0, 10_000_000.0],
        "equity": [13_000_000.0, 15_000_000.0],
    }


def test_rows_with_horizontal_and_vertical_columns():
    comp = build_yearly_comparison(_result(_metrics()), "ar")
    assert comp is not None
    by_key = {r["key"]: r for r in comp["rows"]}

    rev = by_key["revenue"]
    assert rev["change"] == "+3,000,000"
    assert rev["change_pct"] == "+25.0%"
    assert rev["pct_curr"] == "100.0%"
    assert rev["pct_prev"] == "100.0%"
    assert rev["color"] == "good"  # revenue up = improved

    cogs = by_key["cogs"]
    assert cogs["change_pct"] == "+25.0%"
    assert cogs["color"] == "bad"  # cost up = declined (even though margin held)

    liab = by_key["liabilities"]
    assert liab["pct_curr"] == "40.0%"  # vertical: % of total assets
    assert liab["color"] == "bad"  # liabilities up


def test_single_period_revenue_keeps_only_balance_sheet_rows():
    metrics = _metrics()
    metrics["revenue"] = [15_000_000.0]
    comp = build_yearly_comparison(_result(metrics), "ar")
    # P&L rows need a two-period revenue base for vertical percentages
    keys = {r["key"] for r in comp["rows"]}
    assert "revenue" not in keys and "cogs" not in keys
    assert {"assets", "liabilities", "equity"} <= keys


def test_cost_down_is_green():
    metrics = _metrics()
    metrics["cogs"] = [8_400_000.0, 7_500_000.0]  # cost decreased
    comp = build_yearly_comparison(_result(metrics), "ar")
    cogs = next(r for r in comp["rows"] if r["key"] == "cogs")
    assert cogs["change_pct"].startswith("-")
    assert cogs["color"] == "good"


def test_negative_profit_shows_parentheses_and_red():
    metrics = _metrics()
    metrics["net_profit"] = [500_000.0, -300_000.0]
    comp = build_yearly_comparison(_result(metrics), "ar")
    net = next(r for r in comp["rows"] if r["key"] == "net_profit")
    assert net["curr"].startswith("(") and net["curr"].endswith(")")
    assert net["change_pct"].startswith("-")
    assert net["color"] == "bad"


def test_english_labels_and_columns():
    comp = build_yearly_comparison(_result(_metrics()), "en")
    assert comp["columns"][0] == "Item"
    rev = next(r for r in comp["rows"] if r["key"] == "revenue")
    assert rev["label"] == "Revenue"


def test_zero_base_or_zero_prev_skipped_safely():
    metrics = _metrics()
    metrics["revenue"] = [0.0, 0.0]
    comp = build_yearly_comparison(_result(metrics), "ar")
    # zero base revenue cannot produce vertical percentages — but assets-based
    # rows still work; revenue row itself is dropped
    assert all(r["key"] != "revenue" for r in comp["rows"])


# ---------------------------------------------------------------------------
# multi-period support (history for the UI sparkline)

def _multi_metrics():
    return {
        "revenue": [8_000_000.0, 10_000_000.0, 12_000_000.0, 15_000_000.0],
        "cogs": [6_000_000.0, 7_200_000.0, 8_400_000.0, 10_500_000.0],
        "net_profit": [800_000.0, 1_200_000.0, 1_800_000.0, 2_250_000.0],
        "assets": [18_000_000.0, 20_000_000.0, 22_000_000.0, 25_000_000.0],
    }


def test_history_included_and_capped_at_six():
    metrics = _multi_metrics()
    metrics["revenue"] = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    comp = build_yearly_comparison(_result(metrics), "ar")
    rev = next(r for r in comp["rows"] if r["key"] == "revenue")
    assert len(rev["history"]) == 6          # capped
    assert rev["history"][-1] == 9.0          # latest kept


def test_periods_field_and_four_period_row():
    comp = build_yearly_comparison(_result(_multi_metrics()), "ar")
    assert comp["periods"] == 4
    rev = next(r for r in comp["rows"] if r["key"] == "revenue")
    assert rev["history"] == [8_000_000.0, 10_000_000.0, 12_000_000.0, 15_000_000.0]
    # table still compares the last two periods horizontally
    assert rev["change_pct"] == "+25.0%"


def test_two_periods_still_works_no_multi_flag():
    comp = build_yearly_comparison(_result(_metrics()), "ar")
    assert comp["periods"] == 2


# ---------------------------------------------------------------------------
# statement grouping (visual closure blocks in the reports)

def test_rows_carry_statement_group_markers():
    comp = build_yearly_comparison(_result(_metrics()), "ar")
    stmts = {r["key"]: r["stmt"] for r in comp["rows"]}
    assert stmts["revenue"] == "income"
    assert stmts["cogs"] == "income"
    assert stmts["net_profit"] == "income"
    assert stmts["assets"] == "balance"
    assert stmts["liabilities"] == "balance"
    assert stmts["equity"] == "balance"
    # rows stay ordered: the whole income block precedes the balance block
    order = [r["stmt"] for r in comp["rows"]]
    assert order == sorted(order, key=lambda s: 0 if s == "income" else 1)


def test_pdf_comparison_table_grouped_per_statement(tmp_path):
    """The PDF's yearly-comparison table renders a closing band before each
    statement's block, and the direction affordance is REAL vector geometry
    (filled triangles above the bold labels + a shape legend) — the PDF
    counterpart of the deck's _dir_marker shapes, never font glyphs."""
    import pdfplumber

    from app.report import build_report

    res = {
        "kpis": {}, "ratios": {}, "series": {},
        "metrics": _metrics(),
    }
    out = tmp_path / "ycmp.pdf"
    build_report(filename="ycmp.xlsx", result=res, out_path=out, lang="ar",
                 yearly_comparison=build_yearly_comparison(_result(_metrics()), "ar"))
    assert out.exists()
    with pdfplumber.open(str(out)) as pdf:
        text = " ".join((p.extract_text() or "") for p in pdf.pages)
    import arabic_reshaper
    from bidi.algorithm import get_display

    def _sh(s):
        return get_display(arabic_reshaper.reshape(s)).replace(" ", "")

    flat = text.replace(" ", "")
    assert _sh("قائمة الدخل") in flat
    assert _sh("قائمة المركز المالي") in flat
    # inside the yearly-comparison section itself: the income block opens
    # first, then the balance block (the titles recur in the IFRS notes and
    # the statements section, so scope the order check to the region — the
    # section title is the LAST occurrence of its phrase)
    ycmp_at = flat.rindex(_sh("تحليل المقارنة"))
    region = flat[ycmp_at:ycmp_at + 4000]
    assert region.index(_sh("قائمة الدخل")) < region.index(_sh("قائمة المركز المالي"))

    # 2. vector direction markers exist in the content stream: filled
    #    triangle paths (one per data row + 2 in the legend) drawn with the
    #    verdict colours — raw ▲▼◄► glyphs never reach the PDF text.
    with pdfplumber.open(str(out)) as pdf:
        all_curves, all_rects = [], []
        for p in pdf.pages:
            all_curves += p.curves
            all_rects += p.rects
    with pdfplumber.open(str(out)) as pdf:
        all_curves, all_rects = [], []
        for p in pdf.pages:
            all_curves += p.curves
            all_rects += p.rects
        all_marks = all_curves + all_rects

    #    pdfplumber reports fill colours as decimal floats, e.g.
    #    green #059669 → (0.0196, 0.5882, 0.4118) — match numerically, and
    #    gate on the marker SIZE (~4.2×3.2mm) so big section shapes never
    #    inflate the count.
    def _is_marker(obj, rgb, h_lo=4, h_hi=14):
        col = obj.get("non_stroking_color") or ()
        w = obj["x1"] - obj["x0"]
        h = obj["bottom"] - obj["top"]
        return (len(col) == 3 and obj.get("fill")
                and all(abs(a - b) < 0.01 for a, b in zip(col, rgb))
                and 7 <= w <= 20 and h_lo <= h <= h_hi)

    green = sum(1 for o in all_marks if _is_marker(o, (0.0196, 0.5882, 0.4118)))
    red = sum(1 for o in all_marks if _is_marker(o, (0.8627, 0.1490, 0.1490)))
    # flat dash: muted slate, ~1mm tall
    flat = sum(1 for o in all_marks
               if _is_marker(o, (0.3922, 0.4549, 0.5451), h_lo=1, h_hi=6))
    assert green >= 4, f"green direction triangles: only {green} found"
    assert red >= 3, f"red direction triangles: only {red} found"
    assert flat >= 1, "flat dash marker missing"
    flat_text = " ".join(text.split())
    for ch in ("\u25b2", "\u25bc", "\u25c4", "\u25ba", "^", "v", ">"):
        assert ch not in flat_text, f"text arrow leaked: {ch!r}"


def test_pptx_comparison_slide_grouped_per_statement(tmp_path):
    import re
    import zipfile
    from xml.sax.saxutils import unescape as _xml_unescape

    import arabic_reshaper
    from bidi.algorithm import get_display

    from app.pptx_report import build_pptx_report

    def _sh(s):
        return get_display(arabic_reshaper.reshape(s))

    out = tmp_path / "ycmp.pptx"
    build_pptx_report(filename="ycmp.xlsx", result={"kpis": {}, "ratios": {},
                                                    "series": {}, "metrics": _metrics()},
                      out_path=out, lang="ar",
                      yearly_comparison=build_yearly_comparison(_result(_metrics()), "ar"))
    z = zipfile.ZipFile(str(out))
    header_sh = _sh("تحليل المقارنة (أفقي وعمودي)")   # the comparison slide's header
    income_sh, balance_sh = _sh("قائمة الدخل"), _sh("قائمة المركز المالي")
    hit = None
    for n in z.namelist():
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
            # lxml serialises < > & inside run text as XML entities — the
            # parity contract is about the slide's TEXT CONTENT, so unescape
            # before matching (the ◄→< degradation mirrors to > in display).
            x = _xml_unescape(z.read(n).decode("utf-8", "ignore"))
            # the IFRS slide quotes both titles in its basis text — target
            # the slide whose header IS the comparison section
            if header_sh in x and income_sh in x and balance_sh in x:
                hit = x
                break
    assert hit, "comparison slide lacks the statement closing bands"
    assert hit.index(income_sh) < hit.index(balance_sh)


def test_pptx_comparison_slide_matches_platform_quality(tmp_path):
    """Platform-parity: EVERY row renders (no 7-row cap), the colour legend
    and the methodology note are present, the direction affordance is drawn
    as REAL triangle/dash shapes over the table (majalla lacks ▲▼◄► glyphs),
    and the heat fills tint the change columns."""
    import re
    import zipfile
    from xml.sax.saxutils import unescape as _xml_unescape

    import arabic_reshaper
    from bidi.algorithm import get_display

    from app import pptx_report
    from app.pptx_report import build_pptx_report

    def _sh(s):
        return pptx_report._shape(s)

    out = tmp_path / "ycmp_full.pptx"
    build_pptx_report(filename="ycmp.xlsx", result={"kpis": {}, "ratios": {},
                                                    "series": {}, "metrics": _metrics()},
                      out_path=out, lang="ar",
                      yearly_comparison=build_yearly_comparison(_result(_metrics()), "ar"))
    z = zipfile.ZipFile(str(out))
    header_sh = _sh("تحليل المقارنة (أفقي وعمودي)")
    hit = None
    for n in z.namelist():
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
            # lxml serialises < > & inside run text as XML entities — the
            # parity contract is about the slide's TEXT CONTENT, so unescape
            # before matching (the ◄→< degradation mirrors to > in display).
            x = _xml_unescape(z.read(n).decode("utf-8", "ignore"))
            if header_sh in x and _sh("حقوق الملكية") in x:
                hit = x
                break
    assert hit, "comparison slide not found"

    # 1. no truncation: the LAST row (equity — the old [:7] cap dropped it)
    assert _sh("حقوق الملكية") in hit
    for lbl in ("الإيرادات", "تكلفة الإيرادات", "مجمل الربح", "مصاريف التشغيل",
                "صافي الربح", "إجمالي الأصول", "إجمالي الالتزامات"):
        assert _sh(lbl) in hit, f"row missing: {lbl}"

    # 2. colour legend + methodology note (same wording as the platform) —
    #    the direction markers are REAL vector shapes now, so the words sit
    #    in separate anchored boxes (no ^v<> text substitutes anywhere)
    from pptx.util import Inches

    legend_words = ("تحسّن", "تراجع", "مستقر", "شدة اللون = حجم التغير")
    for word in legend_words:
        assert _sh(word) in hit, f"legend word missing: {word}"
    assert _sh("الأخضر = تحسن") in hit

    # 2b. direction markers are REAL shapes over the table: up/down isosceles
    #     triangles (down = rot 180°) + a flat dash — never font glyphs. The
    #     legend's own markers sit above the table top (1.38").
    sps = re.findall(r"<p:sp>.*?</p:sp>", hit, re.S)
    tris = [b for b in sps if 'prst="triangle"' in b]
    assert len(tris) >= 3, f"expected >=3 triangle markers, got {len(tris)}"
    assert any('rot="10800000"' in b for b in tris), "no down triangle drawn"
    tbl_top = int(Inches(1.38))

    def _xy(blk):
        m = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"', blk)
        return (int(m.group(1)), int(m.group(2)))

    legend_tris = [b for b in tris if _xy(b)[1] < tbl_top]
    row_tris = [b for b in tris if _xy(b)[1] >= tbl_top]
    assert len(legend_tris) == 2, "legend needs exactly up+down triangles"
    assert len(row_tris) >= 3, "row direction markers not drawn over the table"

    def _box_of(txt):
        for blk in sps:
            if f"<a:t>{_sh(txt)}</a:t>" in blk:
                x = re.search(r'<a:off x="(-?\d+)"', blk)
                cx = re.search(r'<a:ext cx="(\d+)"', blk)
                return (int(x.group(1)), int(cx.group(1)))
        return None

    boxes = [_box_of(w) for w in legend_words]
    assert all(b is not None for b in boxes), "legend word boxes missing"
    xs = [b[0] for b in boxes]
    assert xs[0] > xs[1] > xs[2] > xs[3], f"legend not RTL-anchored: {xs}"
    for k in range(3):
        assert boxes[k + 1][0] + boxes[k + 1][1] <= boxes[k][0] + int(0.02 * 914400), \
            f"legend word boxes {k}/{k + 1} overlap"

    # 3. arrows degrade to covered glyphs — raw ▲▼◄► never reach the XML
    for ch in ("\u25b2", "\u25bc", "\u25c4", "\u25ba"):
        assert ch not in hit

    # 4. heat fills: revenue +25% → full-intensity blend of the good colour
    #    (5,150,105) over white at a=0.36 → RGB(165,217,201)
    assert "A5D9C9" in hit
    #    cogs +25% (bad) → (242,177,177)
    assert "F2B1B1" in hit
