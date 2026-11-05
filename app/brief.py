"""Executive summary + company activity profile (CMRRS-style report opening).

Everything is derived deterministically from the stored analysis result so the
brief recomputes together with manual value edits (same contract as
app/scoring.py and app/advisor.py).

The brief mirrors the structure used by professional Arabic financial reports
(cmrrs.net/report/demo):

- نبذة عن الشركة ونشاطها  — inferred business profile: activity type, size
  band, operating pattern, data coverage.
- ملخص النتائج — headline numbers with a verdict sentence, matching the
  dashboard's own metrics.
- نقاط القوة / نقاط الضعف — quick pros/cons derived from the ratios.
- خلاصة تنفيذية — one compact paragraph, ready for printing.
"""

from __future__ import annotations

from .hygiene import detect_broken_signs


def _kpi(result: dict, key: str) -> float | None:
    entry = (result.get("kpis") or {}).get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _ratio(result: dict, key: str) -> float | None:
    entry = (result.get("ratios") or {}).get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _fmt(n: float) -> str:
    try:
        return f"{float(n):,.0f}"
    except (TypeError, ValueError):
        return str(n)


def _size_band(revenue: float | None) -> tuple[str, str]:
    """Micro/small/medium/large by annual revenue, Arabic + English."""
    if revenue is None:
        return "غير محدد", "Undetermined"
    if revenue >= 100_000_000:
        return "شركة كبيرة", "Large company"
    if revenue >= 10_000_000:
        return "شركة متوسطة", "Medium-sized company"
    if revenue >= 1_000_000:
        return "شركة صغيرة", "Small company"
    return "نشاط ناشئ / متناهي الصغر", "Micro / early-stage business"


_ACTIVITY_LABELS = {
    "food": ("نشاط أغذية ومأكولات (مطاعم/مقهى)", "Food & beverage business"),
    "trade": ("نشاط تجاري ووساطة", "Trading business"),
    "pnl_only": ("نشاط تشغيلي بقائمة دخل (تجزئة/خدمات)", "Operating business (P&L driven)"),
    "industrial": ("نشاط منتجات وتصنيع (قوائم مالية كاملة)",
                   "Product/industrial activity (full statements)"),
    "generic": ("نشاط تجاري/خدمي", "Trading / services activity"),
}


def _activity_key(result: dict) -> str:
    """Machine key of the detected activity type (drives the sector bands)."""
    name = str(result.get("_filename") or "").lower()
    food_words = ("شاورما", "مطعم", "حلويات", "كنافة", "مقهى", "كافيه", "food", "restaurant", "cafe")
    trade_words = ("تجارة", "مكتب", "مؤسسة", "تريد", "trade", "trading", "est.")
    has_cogs = _kpi(result, "cogs") is not None
    has_assets = _kpi(result, "assets") is not None

    if any(w in name for w in food_words):
        return "food"
    if any(w in name for w in trade_words):
        return "trade"
    if has_cogs and not has_assets:
        return "pnl_only"
    if has_assets and has_cogs:
        return "industrial"
    return "generic"


def _infer_activity(result: dict) -> tuple[str, str]:
    """Best-effort activity type from available concepts + the file name."""
    return _ACTIVITY_LABELS[_activity_key(result)]


# Sector rule-of-thumb bands for inventory turnover (turns per year) — the
# «ملاءمة الأنشطة» check judges the computed turnover against the band of
# the activity DETECTED FROM THE DASHBOARD (food/trade/industrial/...).
# pnl_only has no balance sheet → the turnover is never measurable there.
_SECTOR_TURNOVER: dict[str, tuple[float, float] | None] = {
    "food": (12.0, 24.0),      # perishables: fast, tightly managed stock
    "trade": (6.0, 12.0),      # merchandising: mid velocity
    "industrial": (4.0, 8.0),  # manufacturing: slower cycles
    "generic": (4.0, 12.0),    # undetermined: the broad commerce band
    "pnl_only": None,          # turnover not measurable without a balance sheet
}


def build_activity_fit(result: dict, lang: str = "ar") -> dict:
    """«ملاءمة الأنشطة» — the detected activity type judged against its
    sector's expected inventory-turnover band. Deterministic; 'unknown'
    when the turnover is not measurable (services / no inventory balance)."""
    ar = lang == "ar"
    key = _activity_key(result)
    band = _SECTOR_TURNOVER.get(key)
    turnover = _ratio(result, "inventory_turnover")

    if turnover is None or band is None:
        verdict = "unknown"
    elif turnover < band[0]:
        verdict = "slow"
    elif turnover > band[1]:
        verdict = "fast"
    else:
        verdict = "fit"

    verdict_label = {
        "fit": ("ضمن النطاق القطاعي المتوقع لدوران المخزون",
                "Within the sector's expected inventory-turnover band"),
        "slow": ("أبطأ من القطاع — مخزون يحتجز رأس مال أكثر من عادته",
                 "Slower than the sector — inventory ties up more capital than usual"),
        "fast": ("أسرع من القطاع — كفاءة عالية، راجع كفاية المخزون",
                 "Faster than the sector — efficient, but review stock adequacy"),
        "unknown": ("غير قابل للقياس — لا يوجد رصيد مخزون (نشاط خدمي غالبًا)",
                    "Not measurable — no inventory balance (likely a services activity)"),
    }[verdict][0 if ar else 1]

    return {
        "key": key,
        "title": "ملاءمة النشاط القطاعية" if ar else "Activity fit (sector)",
        "activity": _ACTIVITY_LABELS[key][0 if ar else 1],
        "turnover_txt": f"{turnover:.1f}x" if turnover is not None else "—",
        "range_txt": ("—" if band is None else
                      _sector_range_txt(band, ar)),
        "verdict": verdict,
        "verdict_label": verdict_label,
    }


def _sector_range_txt(band: tuple[float, float], ar: bool) -> str:
    """«النطاق القطاعي: 4–8 دورة/سنة» — hoisted into a helper because
    python<3.12 rejects nested quotes inside f-string expressions."""
    head = "النطاق القطاعي" if ar else "Sector range"
    unit = "دورة/سنة" if ar else "turns/year"
    return f"{head}: {band[0]:g}–{band[1]:g} {unit}"


def _period_hint(result: dict) -> tuple[str, str]:
    """Series length as an operating-pattern line, Arabic + English."""
    rev_series = ((result.get("series") or {}).get("revenue") or {}).get("values") or []
    n = len([v for v in rev_series if isinstance(v, (int, float))])
    if n >= 6:
        return "بيانات متعددة الفترات تتيح قراءة الاتجاه الزمني بثقة", "Multi-period data enables a reliable trend read"
    if n >= 2:
        return "بيانات فترتين أو أكثر — الاتجاه المبدئي متاح مع حدود أقل ثقة", "Two or more periods — initial trend, lower confidence"
    return "فترة واحدة متاحة — القراءة لحظية دون اتجاه زمني", "Single period available — snapshot without a trend"


def _strengths_weaknesses(result: dict) -> tuple[list[str], list[str], list[str], list[str]]:
    """(strengths_ar, weaknesses_ar, strengths_en, weaknesses_en)."""
    s_ar: list[str] = []
    w_ar: list[str] = []
    s_en: list[str] = []
    w_en: list[str] = []

    gm = _ratio(result, "gross_margin")
    nm = _ratio(result, "net_margin")
    debt = _ratio(result, "debt_ratio")
    cash = _kpi(result, "cash")
    revenue = _kpi(result, "revenue")
    roe = _ratio(result, "roe")

    if roe is not None:
        if roe >= 15:
            s_ar.append(f"عائد جيد على استثمارات المساهمين (ROE {roe:.1f}%)")
            s_en.append(f"Good return on shareholders' investment (ROE {roe:.1f}%)")
        elif roe < 0:
            w_ar.append(f"عائد سالب على حقوق الملكية (ROE {roe:.1f}%)")
            w_en.append(f"Negative return on equity (ROE {roe:.1f}%)")

    if gm is not None:
        if gm >= 30:
            s_ar.append(f"ربحية أساسية قوية ({gm:.1f}%) تغطي المصاريف وتحقق ربحاً صافياً")
            s_en.append(f"Strong core profitability ({gm:.1f}%) — covers expenses and yields net profit")
        elif gm < 20:
            w_ar.append(f"هامش الربح الإجمالي منخفض ({gm:.1f}%) — تكلفة المبيعات تضغط على الربحية")
            w_en.append(f"Low gross margin ({gm:.1f}%) — cost of sales pressures profitability")

    if nm is not None:
        if nm >= 12:
            s_ar.append(f"ربحية صافية ممتازة ({nm:.1f}%)")
            s_en.append(f"Strong net profitability ({nm:.1f}%)")
        elif nm < 0:
            w_ar.append(f"خسارة صافية (هامش {nm:.1f}%) — استنزاف لحقوق الملكية إن استمرت")
            w_en.append(f"Net loss (margin {nm:.1f}%) — erodes equity if it persists")

    if debt is not None:
        if debt <= 40:
            s_ar.append(f"هيكل تمويلي متوازن (نسبة التزامات {debt:.1f}%)")
            s_en.append(f"Balanced financing structure (debt ratio {debt:.1f}%)")
        elif debt > 60:
            w_ar.append(f"مديونية مرتفعة ({debt:.1f}%) تزيد مخاطر الملاءة")
            w_en.append(f"High leverage ({debt:.1f}%) raises solvency risk")

    if cash is not None and revenue:
        share = cash / revenue * 100
        if share < 5:
            w_ar.append(f"النقدية ({_fmt(cash)}) تمثل {share:.1f}% من الإيراد — هامش سيولة ضيق")
            w_en.append(f"Cash ({_fmt(cash)}) is {share:.1f}% of revenue — thin liquidity buffer")
        elif share >= 15:
            s_ar.append(f"وضع نقدي مريح ({share:.1f}% من الإيراد)")
            s_en.append(f"Comfortable cash position ({share:.1f}% of revenue)")

    return s_ar, w_ar, s_en, w_en


def _headline_verdict(net: float | None, nm: float | None) -> tuple[str, str]:
    if nm is not None and nm < 0:
        return (
            "تشير النتائج إلى خسارة في الفترة الحالية تتطلب معالجة عاجلة لهيكل التكلفة والإيراد",
            "Results show a net loss in the current period requiring urgent cost/revenue action",
        )
    if nm is not None and nm >= 12:
        return (
            "أداء مالي قوي بربحية صافية ممتازة مع مقومات نمو",
            "Strong performance with excellent net profitability and growth potential",
        )
    return (
        "أداء مقبول مع مجال للتحسين في الربحية والكفاءة",
        "Acceptable performance with room to improve profitability and efficiency",
    )


def _has_broken_signs(result: dict) -> bool:
    """Raw values still contain mixed-sign series (legacy uncleaned rows)."""
    return bool(detect_broken_signs(result.get("metrics") or {}))


def build_executive_brief(result: dict, lang: str = "ar") -> dict | None:
    """Build the CMRRS-style opening block for an analysis.

    Returns None when there is no meaningful data at all.
    """
    revenue = _kpi(result, "revenue")
    net = _kpi(result, "net_profit")
    gross = _kpi(result, "gross_profit")
    nm = _ratio(result, "net_margin")
    gm = _ratio(result, "gross_margin")
    assets = _kpi(result, "assets")

    if revenue is None and net is None:
        return None

    activity_ar, activity_en = _infer_activity(result)
    size_ar, size_en = _size_band(revenue)
    pattern_ar, pattern_en = _period_hint(result)
    verdict_ar, verdict_en = _headline_verdict(net, nm)
    s_ar, w_ar, s_en, w_en = _strengths_weaknesses(result)

    # Broken revenue signs ⇒ the file needs review. Warn first (before any
    # strengths) in every language, so PDF/PPTX reports carry it too.
    if _has_broken_signs(result):
        w_ar.insert(0, "إشارات سالبة متكسرة في القيم المستخرجة — الملف يحتاج مراجعة")
        w_en.insert(0, "Broken signs in the extracted values — file needs review")

    # ---- ملخص النتائج (results summary) --------------------------------
    results_ar: list[dict] = []
    results_en: list[dict] = []
    if revenue is not None:
        results_ar.append({"label": "الإيرادات", "value": _fmt(revenue)})
        results_en.append({"label": "Revenue", "value": _fmt(revenue)})
    if gross is not None:
        results_ar.append({"label": "مجمل الربح", "value": _fmt(gross)})
        results_en.append({"label": "Gross Profit", "value": _fmt(gross)})
    if assets is not None:
        results_ar.append({"label": "إجمالي الأصول", "value": _fmt(assets)})
        results_en.append({"label": "Total Assets", "value": _fmt(assets)})
    if net is not None:
        results_ar.append({
            "label": "صافي الربح" if net >= 0 else "صافي الخسارة",
            "value": _fmt(abs(net)),
            "negative": net < 0,
        })
        results_en.append({
            "label": "Net Profit" if net >= 0 else "Net Loss",
            "value": _fmt(abs(net)),
            "negative": net < 0,
        })
    if gm is not None:
        results_ar.append({"label": "هامش الربح الإجمالي", "value": f"{gm:.1f}%"})
        results_en.append({"label": "Gross Margin", "value": f"{gm:.1f}%"})
    if nm is not None:
        results_ar.append({"label": "هامش صافي الربح", "value": f"{nm:.1f}%", "negative": nm < 0})
        results_en.append({"label": "Net Margin", "value": f"{nm:.1f}%", "negative": nm < 0})

    # ---- خلاصة تنفيذية (executive paragraph) ---------------------------
    if lang == "ar":
        exec_lines = [f"بلغت إيرادات النشاط {_fmt(revenue)}" if revenue is not None else ""]
        if net is not None:
            exec_lines.append(
                f"بانتقال إلى {('خسارة صافية قدرها ' + _fmt(abs(net))) if net < 0 else ('صافي ربح قدره ' + _fmt(net))}"
            )
        if nm is not None:
            exec_lines.append(f"بهامش صافي {nm:.1f}%")
        exec_lines.append(f"تصنف الشركة ضمن فئة {size_ar}")
        exec_lines.append(verdict_ar)
        paragraph = "، ".join(x for x in exec_lines if x) + "."
        company_card = {
            "activity": activity_ar,
            "size": size_ar,
            "pattern": pattern_ar,
        }
    else:
        paragraph = (
            f"Revenue of {_fmt(revenue)} with "
            + (f"a net {'loss' if (net or 0) < 0 else 'profit'} of {_fmt(abs(net or 0))} "
               f"({nm:.1f}% margin). " if net is not None and nm is not None else "")
            + f"The company classifies as {size_en}. {verdict_en}."
        )
        company_card = {
            "activity": activity_en,
            "size": size_en,
            "pattern": pattern_en,
        }

    # «ملاءمة الأنشطة»: the detected activity vs its sector's turnover band
    company_card["activity_fit"] = build_activity_fit(result, lang)

    return {
        "company": company_card,
        "results": results_ar if lang == "ar" else results_en,
        "strengths": s_ar if lang == "ar" else s_en,
        "weaknesses": w_ar if lang == "ar" else w_en,
        "verdict": verdict_ar if lang == "ar" else verdict_en,
        "paragraph": paragraph,
    }


# ---------------------------------------------------------------------------
# Key findings + strategic recommendations (CMRRS-style numbered closing)
# ---------------------------------------------------------------------------

def build_key_findings(result: dict, lang: str = "ar") -> list[str]:
    """Numbered key findings for the report closing (max 4, data-driven).

    Mirrors the reference report's "الاستنتاجات الرئيسية": one line per
    fact, strongest signal first — growth, profitability, liquidity,
    financing structure.
    """
    revenue = _kpi(result, "revenue")
    net = _kpi(result, "net_profit")
    nm = _ratio(result, "net_margin")
    gm = _ratio(result, "gross_margin")
    debt = _ratio(result, "debt_ratio")
    current = _ratio(result, "current_ratio")
    roe = _ratio(result, "roe")
    metrics = result.get("metrics") or {}

    def growth(concept: str) -> float | None:
        vals = [v for v in (metrics.get(concept) or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(vals) < 2 or not vals[-2]:
            return None
        return (vals[-1] - vals[-2]) / abs(vals[-2]) * 100

    rev_g = growth("revenue")
    net_g = growth("net_profit")

    ar: list[str] = []
    en: list[str] = []

    if rev_g is not None:
        ar.append(
            f"نمو قوي في الإيرادات بنسبة {rev_g:+.0f}% مع مواصلة النشاط للتوسع"
            if rev_g >= 10 else
            f"نمو معتدل في الإيرادات بنسبة {rev_g:+.0f}% خلال الفترة"
            if rev_g >= 2 else
            f"تراجع في الإيرادات بنسبة {rev_g:+.0f}% يستدعي مراجعة خطة المبيعات"
        )
        en.append(
            f"Strong revenue growth of {rev_g:+.0f}% as the business keeps expanding"
            if rev_g >= 10 else
            f"Moderate revenue growth of {rev_g:+.0f}% over the period"
            if rev_g >= 2 else
            f"Revenue declined {rev_g:+.0f}% — the sales plan needs review"
        )

    if net is not None and nm is not None and revenue:
        if nm >= 10 and net > 0:
            ar.append(f"ربحية صافية صحية ({nm:.1f}%) توازن مع نمو الإيراد")
            en.append(f"Healthy net profitability ({nm:.1f}%) aligned with revenue growth")
        elif nm < 0:
            ar.append(f"خسارة صافية (هامش {nm:.1f}%) تمثل العائق الأكبر أمام استدامة النشاط")
            en.append(f"Net loss ({nm:.1f}% margin) is the main barrier to sustainability")
        elif nm < 5:
            ar.append(f"هامش صافي ضيق ({nm:.1f}%) يحد من هامش الأمان التشغيلي")
            en.append(f"Thin net margin ({nm:.1f}%) limits the operating safety cushion")

    if gm is not None and nm is not None and gm > nm + 25:
        ar.append(
            f"فجوة كبيرة بين الهامش الإجمالي ({gm:.1f}%) والصافي ({nm:.1f}%) "
            "تشير إلى ثقل المصاريف التشغيلية"
        )
        en.append(
            f"Wide gap between gross ({gm:.1f}%) and net ({nm:.1f}%) margins "
            "points to heavy operating expenses"
        )

    if current is not None:
        if current >= 1.2:
            ar.append(f"سيولة قوية (نسبة تداول {current:.2f}x) تغطي الالتزامات قصيرة الأجل")
            en.append(f"Strong liquidity (current ratio {current:.2f}x) covers short-term obligations")
        elif current < 0.8:
            ar.append(f"سيولة متوترة (نسبة تداول {current:.2f}x) تحتاج إدارة نقد أدق")
            en.append(f"Strained liquidity (current ratio {current:.2f}x) needs tighter cash management")

    if debt is not None:
        if debt > 70:
            ar.append(f"نسبة التزامات مرتفعة ({debt:.1f}%) تجعل الهيكل التمويلي حساساً للصدمات")
            en.append(f"High debt ratio ({debt:.1f}%) makes the financing structure shock-sensitive")
        elif debt <= 40:
            ar.append(f"هيكل تمويلي متوازن (التزامات {debt:.1f}% من الأصول)")
            en.append(f"Balanced financing structure (liabilities at {debt:.1f}% of assets)")

    if roe is not None and roe >= 15:
        ar.append(f"عائد مجزي على استثمارات المساهمين (ROE {roe:.1f}%)")
        en.append(f"Rewarding return on shareholders' investment (ROE {roe:.1f}%)")

    if net_g is not None and rev_g is not None and net_g > rev_g + 5 and nm and nm > 0:
        ar.append("الربحية تنمو أسرع من الإيراد — رافعة تشغيلية إيجابية")
        en.append("Profit is growing faster than revenue — positive operating leverage")

    return (ar if lang == "ar" else en)[:4]


def build_strategic_recs(result: dict, lang: str = "ar") -> list[str]:
    """Numbered strategic recommendations for the report closing (max 4).

    Rule-based mirror of the findings: each weakness class maps to one
    directive, strengths map to a sustain/leverage directive.
    """
    nm = _ratio(result, "net_margin")
    gm = _ratio(result, "gross_margin")
    debt = _ratio(result, "debt_ratio")
    current = _ratio(result, "current_ratio")
    revenue = _kpi(result, "revenue")
    metrics = result.get("metrics") or {}

    def growth(concept: str) -> float | None:
        vals = [v for v in (metrics.get(concept) or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(vals) < 2 or not vals[-2]:
            return None
        return (vals[-1] - vals[-2]) / abs(vals[-2]) * 100

    rev_g = growth("revenue")

    ar: list[str] = []
    en: list[str] = []

    if rev_g is not None and rev_g >= 10:
        ar.append("الاستمرار في مراقبة المؤشرات المالية الرئيسية دورياً لتثبيت وتيرة النمو")
        en.append("Keep monitoring the key financial indicators periodically to lock in the growth pace")
    elif rev_g is not None and rev_g < 2:
        ar.append("إطلاق خطة لتنشيط المبيعات وتنويع مصادر الإيراد لمعالجة ركود النمو")
        en.append("Launch a sales-revival plan and diversify revenue streams to address stagnation")

    if nm is not None and nm < 0:
        ar.append("برنامج عاجل لخفض التكاليف وإعادة تسعير العروض لوقف النزيف الربحي")
        en.append("Urgent cost-reduction and re-pricing programme to stop the profit bleed")
    elif gm is not None and nm is not None and gm > nm + 25:
        ar.append("مراجعة المصاريف التشغيلية وضبطها بما يعيد جزءاً من الهامش الإجمالي إلى الصافي")
        en.append("Review and contain operating expenses to carry more gross margin into net profit")

    if current is not None and current < 1.0:
        ar.append("تشديد إدارة رأس المال العامل وتسريع تحصيل الذمم لتحسين السيولة")
        en.append("Tighten working-capital management and speed up receivables collection")

    if debt is not None and debt > 70:
        ar.append("إعادة هيكلة الالتزامات وتمويل جزء منها بحقوق ملكية لتخفيف المخاطر")
        en.append("Restructure liabilities and refinance part of them with equity to reduce risk")

    if len(ar) < 3:
        ar.append("بناء نموذج مالي دوري يربط الميزانية بالتدفق النقدي لدعم قرارات التوسع")
        en.append("Build a periodic financial model linking the budget to cash flow to support expansion decisions")
        ar.append("مقارنة النتائج شهرياً بالمستهدفات المعتمدة وتصحيح الانحرافات مبكراً")
        en.append("Compare monthly results against approved targets and correct deviations early")

    return (ar if lang == "ar" else en)[:4]
