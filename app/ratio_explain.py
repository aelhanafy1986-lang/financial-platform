"""CMRRS-style ratio explanations: ما هي؟ / ما فائدتها؟ / الرأي.

Adds the reference report's interpretive layer: each financial ratio gets a
"what is it / why it matters / the verdict" card, so the platform explains
numbers the way the CMRRS demo report does (cmrrs.net/report/demo), instead
of only listing them.

Verdicts are deterministic threshold rules per ratio; everything derives
from the stored analysis result, same contract as app/scoring.py.
"""

from __future__ import annotations

import re

from .hygiene import detect_broken_signs
from .ifrs import RATIO_STANDARDS
from .ratio_labels import ratio_label

_AR = {
    "net_margin": {
        "what": "النسبة المئوية من الإيرادات التي تتحول إلى صافي ربح بعد كل التكاليف والمصاريف.",
        "why": "تقييم الأداء المالي النهائي للشركة.",
        "good": "أداء مالي متسماً مع هامش صحي.",
        "bad": "هامش سالب أو ضعيف — إيرادات لا تغطي التكاليف، راجع الهيكل التشغيلي.",
    },
    "gross_margin": {
        "what": "النسبة المئوية من الإيرادات المتبقية بعد تكلفة المبيعات، قبل المصاريف التشغيلية.",
        "why": "قياس الربحية الأساسية للنشاط.",
        "good": "ربحية أساسية قوية تغطي المصاريف وتحقق ربحاً صافياً.",
        "bad": "هامش منخفض — راجع التسعير أو تكلفة المبيعات.",
    },
    "debt_to_equity": {
        "what": "مقارنة الالتزامات بحقوق الملكية — درجة الاعتماد على الدين مقابل التمويل الذاتي.",
        "why": "قياس مستوى المخاطر المالية.",
        "good": "توازن جيد بين الدين والتمويل الذاتي.",
        "bad": "اعتماد كبير على الدين مقابل حقوق ملكية ضعيفة.",
    },
    "debt_ratio": {
        "what": "نسبة إجمالي الالتزامات إلى إجمالي الأصول — ما نسبة الأصول الممولة بالدَين.",
        "why": "قياس حجم الالتزامات مقارنة بحجم الشركة.",
        "good": "هيكل تمويلي متوازن — الاعتماد على الدين في حدود آمنة.",
        "bad": "نسبة التزامات مرتفعة — ضغط على الملاءة المالية.",
    },
    "current_ratio": {
        "what": "القدرة على سداد الالتزامات قصيرة الأجل من الأصول المتداولة.",
        "why": "قياس قوة السيولة قصيرة الأجل.",
        "good": "سيولة جيدة لتغطية الالتزامات القصيرة.",
        "bad": "سيولة ضعيفة — خطر في الالتزامات القصيرة.",
    },
    "quick_ratio": {
        "what": "مثل نسبة التداول لكن بدون المخزون — اختبار سيولة أكثر صرامة.",
        "why": "قياس السيولة الفعلية بسرعة.",
        "good": "سيولة سريعة جيدة.",
        "bad": "سيولة سريعة ضعيفة.",
    },
    "roa": {
        "what": "كفاءة استخدام الأصول لتحقيق الأرباح.",
        "why": "مقياس إنتاجية الأصول.",
        "good": "استخدام فعال للأصول.",
        "bad": "أصول غير مستغلة بالكامل.",
    },
    "roe": {
        "what": "مقدار الربح الذي تحققه الشركة مقابل كل ريال مستثمر من المساهمين.",
        "why": "قياس العائد على استثمار المساهمين.",
        "good": "عائد جيد على استثمارات المساهمين.",
        "bad": "عائد ضعيف على استثمارات المساهمين.",
    },
    "asset_turnover": {
        "what": "كفاءة استخدام الأصول في توليد الإيرادات.",
        "why": "قياس نشاط الأصول.",
        "good": "كفاءة استخدام أصول جيدة.",
        "bad": "يمكن تحسين كفاءة استخدام الأصول.",
    },
    "operating_margin": {
        "what": "النسبة المئوية من الإيرادات المتبقية بعد طرح المصاريف التشغيلية.",
        "why": "قياس ربحية النشاط الأساسي قبل الفوائد والضرائب.",
        "good": "ربحية تشغيلية صحية تغطي الالتزامات غير التشغيلية.",
        "bad": "هامش تشغيلي ضعيف — راجع المصاريف التشغيلية.",
    },
    "roce": {
        "what": "العائد الذي تحققه الشركة على رأس المال المستخدم (ETBIT مقابل رأس المال).",
        "why": "قياس كفاءة استثمار رأس المال المشغّل.",
        "good": "عائد أعلى من كلفة رأس المال — استثمار مجدٍ.",
        "bad": "عائد منخفض على رأس المال المستخدم.",
    },
    "roic": {
        "what": "العائد بعد الضرائب على رأس المال المستثمر في النشاط.",
        "why": "قياس الخلق الفعلي للقيمة بعد الضرائب.",
        "good": "عائد يتجاوز استثمار المساهمين بعد الضرائب.",
        "bad": "عائد بعد الضرائب أقل من كلفة رأس المال.",
    },
    "equity_ratio": {
        "what": "نسبة حصة حقوق الملكية من إجمالي الأصول (مكمّل نسبة الالتزامات).",
        "why": "قياس متانة الهيكل التمويلي الذاتي.",
        "good": "التحف الذاتي قوي — أعتماد قليل على الدين.",
        "bad": "التحف الذاتي ضعيف — اعتماد كبير على الدين.",
    },
    "interest_coverage": {
        "what": "كم مرة تغطي الأرباح قبل الفوائد والضرائب (EBIT) مصاريف التمويل المستحقة.",
        "why": "قياس قدرة الشركة على سداد أعباء الدين من أرباحها التشغيلية.",
        "good": "أرباح تشغيلية تغطي أعباء التمويل بأريحية — هامش أمان مريح للدائنين.",
        "bad": "أرباح بالكاد تغطي (أو لا تغطي) الفوائد — خطر تعثر في خدمة الدين، راجع هيكل التمويل.",
    },
    "receivables_turnover": {
        "what": "كم مرة يُحصّل رصيد المدينين خلال السنة (الإيراد ÷ المدينون).",
        "why": "قياس سرعة تحويل المبيعات الآجلة إلى نقد — نبض السيولة التشغيلية.",
        "good": "تحصيل سريع — المدينون يتحولون إلى نقد بكفاءة.",
        "bad": "دوران بطيء — مبالغ كبيرة محتبسة لدى العملاء، راجع سياسة الائتمان والتحصيل.",
    },
    "receivable_days": {
        "what": "متوسط عدد الأيام اللازمة لتحصيل المدينين (المدينون × 365 ÷ الإيراد).",
        "why": "قياس فترة التحصيل الفعلية مقابل سياسة الائتمان المعلنة.",
        "good": "فترة تحصيل قصيرة — سياسة ائتمان منضبطة وسيولة مريحة.",
        "bad": "فترة تحصيل طويلة — ضغط على السيولة وخطر تعثر، شدّد شروط البيع الآجل.",
    },
    "inventory_turnover": {
        "what": "كم مرة يُباع المخزون ويُستبدل خلال السنة (تكلفة المبيعات ÷ المخزون).",
        "why": "قياس كفاءة إدارة المخزون وسرعة حركة البضاعة.",
        "good": "حركة مخزون صحية — رأس مال عامل محتجز بالحد الأدنى.",
        "bad": "مخزون راكد — مخزونات متكدسة أو سلع بطيئة الحركة، راجع المشتريات والتسعير.",
    },
    "inventory_days": {
        "what": "متوسط عدد الأيام التي يبقى فيها المخزون قبل بيعه (المخزون × 365 ÷ تكلفة المبيعات).",
        "why": "قياس طول فترة احتجاز رأس المال في المخزون — ضلع من أضلاع دورة التحول النقدي.",
        "good": "مخزون يتحول إلى مبيعات بسرعة — دورة تشغيل قصيرة.",
        "bad": "فترة بقاء مخزون طويلة — نقدية محتبسة في البضاعة، راجع المشتريات والحركة.",
    },
    "payables_turnover": {
        "what": "كم مرة يُسدَّد رصيد الدائنين خلال السنة (تكلفة المبيعات ÷ الدائنون).",
        "why": "قياس سرعة السداد للموردين — الضلع الثالث في دورة رأس المال العامل.",
        "good": "سداد منضبط يستفيد من فترة ائتمان الموردين دون تأخير يهدد التوريد.",
        "bad": "سداد متسرع أو مضطرب — إما إهدار للائتمان المتاح أو توتر في العلاقة مع الموردين.",
    },
    "days_payable": {
        "what": "متوسط عدد الأيام التي تستغرقها الشركة لسداد مستحقات مورديها (الدائنون × 365 ÷ تكلفة المبيعات).",
        "why": "قياس فترة الائتمان المستفادة من الموردين — كل يوم إضافي يخفف حاجة التمويل.",
        "good": "فترة سداد مريحة تموّل جزءًا من رأس المال العامل من ائتمان الموردين.",
        "bad": "سداد أسرع من الفترة المتاحة — ضغط غير لازم على النقدية، راجع شروط الشراء.",
    },
    "cash_conversion_cycle": {
        "what": "الدورة الكاملة للنقد: فترة التحصيل + فترة بقاء المخزون − فترة السداد — كم يومًا تحتاج الشركة لتحويل رأس المال العامل إلى نقد مجددًا.",
        "why": "المقياس المجمع لكفاءة رأس المال العامل: كل يوم في الدورة هو تمويل إضافي مطلوب.",
        "good": "دورة قصيرة (أو سالبة) — النقد يعود بسرعة وتُموّل العمليات ذاتيًا.",
        "bad": "دورة طويلة — احتياج تمويلي متزايد يضغط على السيولة، عالج أطول ضلع أولًا.",
    },
}

_EN = {
    "gross_margin": {
        "what": "Profitability before operating expenses — profit from the core activity.",
        "why": "Measures core-activity efficiency and pricing versus cost.",
        "good": "Healthy gross margin — the core activity is profitable.",
        "bad": "Low margin — review pricing or cost of sales.",
    },
    "net_margin": {
        "what": "Percentage of revenue that becomes net profit after all costs.",
        "why": "Evaluates the company's final financial performance.",
        "good": "Solid financial performance with a healthy margin.",
        "bad": "Liabilities exceed assets — structural weakness.",
    },
    "debt_to_equity": {
        "what": "Liabilities compared to equity — reliance on debt versus self-funding.",
        "why": "Measures financial risk level.",
        "good": "Good balance between debt and equity.",
        "bad": "Heavy reliance on debt over weak equity.",
    },
    "debt_ratio": {
        "what": "Total liabilities relative to total assets — how much of the assets are debt-funded.",
        "why": "Measures obligations relative to company size.",
        "good": "Balanced financing structure — debt within safe limits.",
        "bad": "High debt ratio — pressure on solvency.",
    },
    "current_ratio": {
        "what": "Ability to pay short-term obligations from current assets.",
        "why": "Measures short-term liquidity strength.",
        "good": "Good liquidity covering short-term obligations.",
        "bad": "Weak liquidity — short-term risk.",
    },
    "quick_ratio": {
        "what": "Like the current ratio but excluding inventory — a stricter liquidity test.",
        "why": "Measures effective liquidity quickly.",
        "good": "Good quick liquidity.",
        "bad": "Weak quick liquidity.",
    },
    "roa": {
        "what": "Efficiency of assets in generating profit.",
        "why": "Measures asset productivity.",
        "good": "Effective asset utilisation.",
        "bad": "Assets are underutilised.",
    },
    "roe": {
        "what": "Profit earned per unit of shareholders' invested money.",
        "why": "Measures return on shareholders' investment.",
        "good": "Good return on shareholders' investment.",
        "bad": "Weak return on shareholders' investment.",
    },
    "asset_turnover": {
        "what": "Efficiency of assets in generating revenue.",
        "why": "Measures asset activity.",
        "good": "Good asset-utilisation efficiency.",
        "bad": "Asset utilisation efficiency can be improved.",
    },
    "interest_coverage": {
        "what": "How many times operating profit (EBIT) covers the finance costs due.",
        "why": "Measures the ability to service debt from operating earnings.",
        "good": "Operating earnings comfortably cover financing charges — a comfortable safety margin for creditors.",
        "bad": "Earnings barely cover (or fall short of) interest — debt-service risk, review the financing structure.",
    },
    "receivables_turnover": {
        "what": "How many times the receivables balance is collected per year (revenue ÷ receivables).",
        "why": "Measures how fast credit sales turn into cash — the pulse of operating liquidity.",
        "good": "Fast collection — receivables convert to cash efficiently.",
        "bad": "Slow turnover — large amounts trapped with customers, review credit and collection policy.",
    },
    "receivable_days": {
        "what": "Average number of days to collect receivables (receivables × 365 ÷ revenue).",
        "why": "Measures the actual collection period against the stated credit policy.",
        "good": "Short collection period — disciplined credit policy and comfortable liquidity.",
        "bad": "Long collection period — liquidity pressure and default risk, tighten credit terms.",
    },
    "inventory_turnover": {
        "what": "How many times inventory is sold and replaced per year (cost of sales ÷ inventory).",
        "why": "Measures inventory management efficiency and stock velocity.",
        "good": "Healthy stock movement — working capital held to a minimum.",
        "bad": "Stagnant inventory — piled-up stock or slow-moving items, review purchasing and pricing.",
    },
    "inventory_days": {
        "what": "Average number of days inventory is held before it is sold (inventory × 365 ÷ cost of sales).",
        "why": "Measures how long capital is tied up in stock — a leg of the cash conversion cycle.",
        "good": "Inventory converts to sales quickly — a short operating cycle.",
        "bad": "Long inventory holding period — cash trapped in stock, review purchasing and movement.",
    },
    "payables_turnover": {
        "what": "How many times the payables balance is paid per year (cost of sales ÷ payables).",
        "why": "Measures the pace of supplier payments — the third leg of the working-capital cycle.",
        "good": "Disciplined payments that use the available supplier credit without straining it.",
        "bad": "Rushed or erratic payments — either wasting available credit or straining supplier relations.",
    },
    "days_payable": {
        "what": "Average number of days the company takes to pay its suppliers (payables × 365 ÷ cost of sales).",
        "why": "Measures the credit period taken from suppliers — every extra day eases the funding need.",
        "good": "Comfortable payment period — supplier credit partly funds working capital.",
        "bad": "Paying faster than the credit available — needless cash pressure, review purchase terms.",
    },
    "cash_conversion_cycle": {
        "what": "The full cash cycle: collection days + inventory days − payment days — how many days working capital takes to turn back into cash.",
        "why": "The composite working-capital efficiency measure: every day in the cycle is additional funding required.",
        "good": "Short (or negative) cycle — cash returns quickly and operations self-fund.",
        "bad": "Long cycle — a growing funding need that pressures liquidity; fix the longest leg first.",
    },
}

# (key, weight-class thresholds) — verdict thresholds per ratio.
_THRESHOLDS = {
    "gross_margin": {"good": 20.0},
    "net_margin": {"good": 12.0, "bad": 0.0},
    "debt_ratio": {"bad": 70.0},
    "debt_to_equity": {"bad": 1.5},
    "current_ratio": {"good": 1.2, "bad": 0.8},
    "quick_ratio": {"good": 0.8, "bad": 0.5},
    "roa": {"good": 3.0},
    "roe": {"good": 10.0},
    "asset_turnover": {"bad": 0.4},
    "operating_margin": {"good": 8.0},
    "roce": {"good": 8.0},
    "roic": {"good": 8.0},
    "equity_ratio": {"good": 30.0},
    # (percent-type ratios — the unit rule at the cards' build site reads
    # from the _PERCENT_KEYS frozenset, kept as the single source of truth)
    "interest_coverage": {"good": 3.0, "bad": 1.5},
    "receivables_turnover": {"bad": 4.0},
    "receivable_days": {"good": 45.0, "bad": 90.0},
    "inventory_turnover": {"bad": 4.0},
    "inventory_days": {"good": 45.0, "bad": 90.0},
    "payables_turnover": {"good": 12.0, "bad": 24.0},
    "days_payable": {"good": 30.0, "bad": 15.0},
    "cash_conversion_cycle": {"good": 90.0, "bad": 180.0},
}

# Ratios expressed in DAYS — the unit formatting rule shared by the
# interpretive cards, the Excel/PPTX ratio tables and the PDF alignment
# section (percent-type and x-multiple ratios are handled separately).
DAYS_KEYS = frozenset({
    "receivable_days", "inventory_days", "days_payable",
    "cash_conversion_cycle",
})

# Ratios expressed in PERCENT — the single source of truth for unit
# formatting everywhere (cards, PDF insight/alignment sections, Excel and
# PPTX tables). Everything else renders as an x-multiple.
_PERCENT_KEYS = frozenset({
    "gross_margin", "net_margin", "debt_ratio", "roa", "roe",
    "operating_margin", "roce", "roic", "equity_ratio",
    # المسمى الموحد للنسبة نفسها يحمل «%» («نسبة الأصول المتداولة إلى
    # إجمالي الأصول %») — الوحدة من نوعها لا مضاعف، فتصير «36.23%» في
    # البطاقات وPDF وExcel وشريحة النسب لا «36.23x».
    "current_assets_share",
})


# Unified verdict badges (جيد/متوسط/ضعيف) — the single label set shared by
# the PDF insight cards and any other renderer of the cards; every verdict
# class maps to exactly one of these three ratings, so all cards carry the
# same badge vocabulary in the same platform style.
BADGES: dict[str, dict[str, str]] = {
    "good": {"ar": "جيد", "en": "Good"},
    "neutral": {"ar": "متوسط", "en": "Average"},
    "bad": {"ar": "ضعيف", "en": "Weak"},
}


def _judge(key: str, value: float) -> str:
    """'good' | 'bad' | 'neutral' for a ratio value (percents for margins,
    x-multiples for liquidity/leverage)."""
    t = _THRESHOLDS.get(key, {})
    if key in ("receivable_days", "inventory_days", "payables_turnover",
               "cash_conversion_cycle"):
        # days & payables turnover: LOWER is better — good at or under the
        # target, bad past it (a negative CCC is the best case and passes).
        if t.get("good") is not None and value <= t["good"]:
            return "good"
        if t.get("bad") is not None and value > t["bad"]:
            return "bad"
        return "neutral"
    if key in ("debt_ratio", "debt_to_equity"):
        if value <= t.get("bad", 70.0 if key == "debt_ratio" else 1.5):
            return "good"
        return "bad"
    good, bad = t.get("good"), t.get("bad")
    if good is not None and value >= good:
        return "good"
    if bad is not None and value < bad:
        return "bad"
    if good is not None:
        return "neutral"  # between good and bad thresholds
    return "neutral"


def _ratio_value(result: dict, key: str) -> float | None:
    entry = (result.get("ratios") or {}).get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_ratio_insights(result: dict, lang: str = "ar") -> list[dict]:
    """CMRRS-style cards for every ratio present in the result.

    Each card: {key, label, value (formatted), verdict, verdict_class,
    what, why, opinion}. Only ratios actually computable from the file.
    """
    ratios = result.get("ratios") or {}
    if not isinstance(ratios, dict):
        return []
    broken = detect_broken_signs(result.get("metrics") or {})

    texts = _AR if lang == "ar" else _EN

    def _ifrs_ref(key: str) -> str:
        """كل نسبة تحمل مرجعها المعياري (IFRS) — الركيزة المعيارية للمنصة."""
        e = RATIO_STANDARDS.get(key)
        if not e:
            return "IAS 1"
        return f"{e['code']} — {e['ar'] if lang == 'ar' else e['en']}"
    order = [
        "gross_margin", "net_margin", "operating_margin", "roa", "roe",
        "roce", "roic", "debt_ratio",
        "debt_to_equity", "equity_ratio", "current_ratio", "quick_ratio", "asset_turnover",
        "interest_coverage", "receivables_turnover", "receivable_days",
        "inventory_turnover", "inventory_days", "payables_turnover",
        "days_payable", "cash_conversion_cycle",
    ]

    cards = []
    for key in order:
        entry = ratios.get(key)
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        verdict = _judge(key, value)
        t = texts.get(key) or {}
        if verdict == "good":
            opinion = t.get("good", "")
            cls = "good"
        elif verdict == "bad":
            opinion = t.get("bad", "")
            cls = "bad"
        else:
            # neutral: no strong opinion, describe the level instead
            opinion = (
                f"القيمة {value:.1f}% — ضمن المستوى المقبول مع إمكانية التحسن."
                if lang == "ar"
                else f"{value:.1f} — acceptable level with room to improve."
            )
            cls = "neutral"
        # Data-quality guard: broken signs in the source file invalidate the
        # raw-asset/liability denominators (mirrors the reference report's
        # consistency checks) — the card keeps the value but flags it.
        if broken and key in ("roa", "roe", "current_ratio", "quick_ratio",
                              "asset_turnover", "debt_ratio", "debt_to_equity",
                              "receivables_turnover", "receivable_days",
                              "inventory_turnover", "inventory_days",
                              "payables_turnover", "days_payable",
                              "cash_conversion_cycle"):
            note = (
                " (قيم مستخرجة من ملف فيه إشارات متكسرة — راجع قبل الاعتماد)"
                if lang == "ar" else
                " (derived from a file with broken signs — verify first)"
            )
            opinion += note
        cards.append({
            "key": key,
            "label": entry.get(lang) or ratio_label(key, lang) or key,
            "value": value,
            "is_percent": key in _PERCENT_KEYS,
            "is_days": key in DAYS_KEYS,
            "verdict": cls,
            "badge": BADGES[cls],
            "what": t.get("what", ""),
            "why": t.get("why", ""),
            "opinion": opinion,
            "ifrs": _ifrs_ref(key),
        })
    return cards


# Reference anchors per ratio — the methodology's benchmark values shown
# verbatim in the alignment section (the ideal current ratio of 2, interest
# coverage of 3x, collection within 90 days, ...). The verdict itself reuses
# the same gate thresholds as the interpretive cards.
_BENCHMARKS: dict[str, dict[str, str]] = {
    "gross_margin": {"ar": "≥ 20% من الإيراد", "en": "≥ 20% of revenue"},
    "net_margin": {"ar": "≥ 12% من الإيراد", "en": "≥ 12% of revenue"},
    "debt_ratio": {"ar": "≤ 70% من الأصول", "en": "≤ 70% of assets"},
    "debt_to_equity": {"ar": "≤ 1.5 ضعف حقوق الملكية", "en": "≤ 1.5× equity"},
    "current_ratio": {"ar": "≥ 2.0 (المثالية وفق المنهجية)", "en": "≥ 2.0 (methodology ideal)"},
    "quick_ratio": {"ar": "≥ 1.0", "en": "≥ 1.0"},
    "roa": {"ar": "≥ 3% من الأصول", "en": "≥ 3% of assets"},
    "roe": {"ar": "≥ 10% من حقوق الملكية", "en": "≥ 10% of equity"},
    "operating_margin": {"ar": "≥ 10% من الإيراد", "en": "≥ 10% of revenue"},
    "roce": {"ar": "≥ 10% من رأس المال المستخدم", "en": "≥ 10% of capital employed"},
    "roic": {"ar": "≥ 10% من رأس المال المستثمر", "en": "≥ 10% of invested capital"},
    "equity_ratio": {"ar": "≥ 50% من الأصول (تمويل ذاتي) ", "en": "≥ 50% of assets (own funding)"},
    "asset_turnover": {"ar": "≥ 0.4 ضعف الأصول", "en": "≥ 0.4× assets"},
    "interest_coverage": {"ar": "≥ 3.0 ضعف الفوائد", "en": "≥ 3.0× interest"},
    "receivables_turnover": {"ar": "≥ 4 مرات سنويًا", "en": "≥ 4 turns a year"},
    "receivable_days": {"ar": "≤ 90 يومًا (المستهدف ≤ 45)", "en": "≤ 90 days (target ≤ 45)"},
    "inventory_turnover": {"ar": "≥ 4 مرات سنويًا", "en": "≥ 4 turns a year"},
    "inventory_days": {"ar": "≤ 90 يومًا (المستهدف ≤ 45)", "en": "≤ 90 days (target ≤ 45)"},
    "payables_turnover": {"ar": "≤ 12 دورة سنويًا (سداد خلال ~30 يومًا)",
                          "en": "≤ 12 turns a year (payment ~30 days)"},
    "days_payable": {"ar": "≥ 30 يومًا من ائتمان الموردين", "en": "≥ 30 days of supplier credit"},
    "cash_conversion_cycle": {"ar": "≤ 90 يومًا للدورة كاملة", "en": "≤ 90 days for the full cycle"},
}

_BENCH_STATUS = {
    "good": {"ar": "مستوفٍ", "en": "Aligned", "sym": "✓"},
    "neutral": {"ar": "قريب من المعيار", "en": "Near benchmark", "sym": "≈"},
    "bad": {"ar": "غير مستوفٍ", "en": "Off benchmark", "sym": "✗"},
}


def build_benchmark_alignment(result: dict, lang: str = "ar") -> dict | None:
    """Benchmark-alignment summary (مواءمة معيارية): every computed ratio
    against its reference anchor. None when no ratios are computable."""
    ratios = result.get("ratios") or {}
    if not isinstance(ratios, dict) or not ratios:
        return None
    rows = []
    for key, bench in _BENCHMARKS.items():
        entry = ratios.get(key)
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        verdict = _judge(key, value)
        st = _BENCH_STATUS[verdict]
        if key in _PERCENT_KEYS:
            val_txt = f"{value:,.2f}%"
        elif key in DAYS_KEYS:
            val_txt = f"{value:,.0f}" + (" يوم" if lang == "ar" else " days")
        else:
            val_txt = f"{value:,.2f}x"
        rows.append({
            "key": key,
            "label": entry.get(lang) or key,
            "value": val_txt,
            "benchmark": bench[lang],
            "status": st[lang],
            "symbol": st["sym"],
            "verdict": verdict,
        })
    if not rows:
        return None
    title = ("مواءمة النسب مع المعايير المرجعية" if lang == "ar"
             else "Ratio Alignment with Reference Benchmarks")
    return {"title": title, "rows": rows}


def _series_raw(metrics: dict, concept: str) -> list[float]:
    return [float(v) for v in (metrics.get(concept) or [])
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def net_profit_series(result: dict) -> list[float]:
    """Net profit per period (oldest → latest).

    The stored ``metrics["net_profit"]`` when present; otherwise the IFRS 18
    chain — revenue − cogs − opex + investment income − finance costs −
    taxes — applied period by period. Shared by the growth table and the
    reports' «تطور الإيرادات وصافي الربح» charts so every surface reads the
    SAME bottom line.
    """
    metrics = result.get("metrics") or {}
    nums = _series_raw(metrics, "net_profit")
    if nums:
        return nums
    rev = _series_raw(metrics, "revenue")
    cogs = _series_raw(metrics, "cogs")
    if len(rev) < 2 or len(cogs) < 2:
        return []
    op = _series_raw(metrics, "opex")
    fn = _series_raw(metrics, "finance_cost")
    tx = _series_raw(metrics, "tax_expense")
    ii = _series_raw(metrics, "investment_income")
    n = min(len(rev), len(cogs))
    return [
        rev[i] - cogs[i]
        - (op[i] if i < len(op) else 0.0)
        + (ii[i] if i < len(ii) else 0.0)
        - (fn[i] if i < len(fn) else 0.0)
        - (tx[i] if i < len(tx) else 0.0)
        for i in range(n)
    ]


def build_yearly_comparison(result: dict, lang: str = "ar") -> dict | None:
    """CMRRS-style comparative table: horizontal + vertical analysis.

    For every P&L / balance-sheet concept with two periods:
    - أفقي: التغير بالقيمة والنسبة بين الفترتين
    - عمودي: كل بند كنسبة من إيراد فترته (قائمة الدخل) أو من إجمالي
      الأصول (الميزانية)

    Colors are judgment-based (unlike the reference's mechanical sign rule):
    revenue/profit up = green; costs down = green.
    Returns None when fewer than two periods exist.
    """
    metrics = result.get("metrics") or {}

    def series(concept: str) -> list[float]:
        nums = _series_raw(metrics, concept)
        if concept == "gross_profit" and not nums:
            # derive from detail rows like the reference's قائمة الدخل
            rev = _series_raw(metrics, "revenue")
            cogs = _series_raw(metrics, "cogs")
            if len(rev) >= 2 and len(cogs) >= 2:
                nums = [r - c for r, c in zip(rev, cogs)]
        if concept == "net_profit" and not nums:
            # derived bottom line per period (the IFRS 18 chain) — the SAME
            # helper the reports' evolution charts read
            nums = net_profit_series(result)
        return nums

    # (concept, label_ar, label_en, is_cost, base) — base: 'revenue' | 'assets'
    items = [
        ("revenue", "الإيرادات", "Revenue", False, "revenue"),
        ("cogs", "تكلفة الإيرادات", "Cost of Sales", True, "revenue"),
        ("gross_profit", "مجمل الربح", "Gross Profit", False, "revenue"),
        ("opex", "مصاريف التشغيل", "Operating Expenses", True, "revenue"),
        ("net_profit", "صافي الربح", "Net Profit", False, "revenue"),
        ("assets", "إجمالي الأصول", "Total Assets", False, "assets"),
        # liabilities judged like a cost: increase = more leverage = worse
        ("liabilities", "إجمالي الالتزامات", "Total Liabilities", True, "assets"),
        ("equity", "حقوق الملكية", "Equity", False, "assets"),
    ]

    rows = []
    # period labels aligned to each row's history window (oldest → latest)
    plabels = [str(x).strip() for x in (result.get("period_labels") or [])]
    for concept, ar, en, is_cost, base_key in items:
        vals = series(concept)
        if len(vals) < 2:
            continue
        curr, prev = vals[-1], vals[-2]
        base_vals = series(base_key)
        if len(base_vals) < 2 or prev == 0:
            continue
        base_curr, base_prev = base_vals[-1], base_vals[-2]
        if not base_curr or not base_prev:
            continue

        change = curr - prev
        change_pct = change / abs(prev) * 100
        pct_curr = curr / base_curr * 100
        pct_prev = prev / base_prev * 100

        if is_cost:
            direction = "down" if change < 0 else ("up" if change > 0 else None)
        else:
            direction = "up" if change > 0 else ("down" if change < 0 else None)
        # judgment: up is good for non-costs, down is good for costs
        color = None
        if direction:
            good = (direction == "down") if is_cost else (direction == "up")
            color = "good" if good else "bad"

        def fmt(v: float) -> str:
            return f"({abs(v):,.0f})" if v < 0 else f"{v:,.0f}"

        # annual growth points (up to the last 6 periods): value per year +
        # YoY change vs the previous year — drives the report's growth table
        window = [round(v, 2) for v in vals[-6:]]
        if len(plabels) >= len(window):
            pt_labels = plabels[-len(window):]
        else:
            pt_labels = [(("الفترة ") if lang == "ar" else "Period ")
                         + str(i + 1) for i in range(len(window))]
        points = []
        for k, v in enumerate(window):
            growth = None
            if k > 0 and window[k - 1]:
                g = (v - window[k - 1]) / abs(window[k - 1]) * 100
                growth = (("+" if g >= 0 else "") + f"{g:.1f}%")
            points.append({"label": pt_labels[k], "value": fmt(v),
                           "raw": v, "growth": growth})

        # next-year forecast: the MEAN of this row's historical YoY rates
        # applied to its latest value — «متوسط النمو التاريخي». None when no
        # rate is computable (zero base year) or the latest value is zero.
        rates = [(window[k] - window[k - 1]) / abs(window[k - 1])
                 for k in range(1, len(window)) if window[k - 1]]
        fc = None
        if rates and window[-1] != 0:
            avg = sum(rates) / len(rates)
            nxt = window[-1] * (1.0 + avg)
            fc = {"value": fmt(nxt),
                  "growth": (("+" if avg >= 0 else "") + f"{avg * 100:.1f}%"),
                  "raw": round(nxt, 2)}

        rows.append({
            "key": concept,
            "label": ar if lang == "ar" else en,
            "is_cost": is_cost,
            # which statement the row belongs to — the reports group the
            # table into visually-closed blocks (income / balance sheet)
            "stmt": "income" if base_key == "revenue" else "balance",
            "curr": fmt(curr),
            "prev": fmt(prev),
            "change": ("+" if change >= 0 else "") + f"{change:,.0f}",
            "change_pct": ("+" if change_pct >= 0 else "") + f"{change_pct:.1f}%",
            "pct_curr": f"{pct_curr:.1f}%",
            "pct_prev": f"{pct_prev:.1f}%",
            # numeric mirrors for the UI heatmap colour intensity and the
            # Excel mini period-comparison column chart
            "curr_val": round(curr, 2), "prev_val": round(prev, 2),
            "change_pct_val": round(change_pct, 2),
            "pct_curr_val": round(pct_curr, 2),
            "color": color,
            # full history (up to the last 6 periods) for the UI sparkline
            "history": window,
            # annual growth points for the report's growth table
            "points": points,
            # next-year forecast (mean historical growth) — rendered as the
            # growth table's extra column when the table itself renders
            "forecast": fc,
        })

    # column headers adapt to the number of available periods
    n_periods = max((len(r.get("history") or []) for r in rows), default=0)

    if len(rows) < 2:
        return None

    multi = n_periods > 2
    if lang == "ar":
        columns = ["البند", "الفترة الحالية", "الفترة السابقة",
                   "التغير بالقيمة", "التغير بالنسبة", "% من الإيراد", "% سابق"]
        title = "تحليل المقارنة (أفقي وعمودي)"
        note = ("الأفقي: التغير بالقيمة والنسبة بين الفترتين · "
                "العمودي: كل بند كنسبة من إيراد فترته (الأصول للميزانية). "
                "الأخضر = تحسن، الأحمر = تراجع.")
        if multi:
            note += f" · الخط الزمني المصغر يغطي آخر {n_periods} فترات."
    else:
        columns = ["Item", "Current", "Prior", "Change", "Change %",
                   "% of Revenue", "% prior"]
        title = "Comparative Analysis (Horizontal & Vertical)"
        note = ("Horizontal: value & percent change between periods · "
                "Vertical: each item as % of its period's revenue "
                "(assets for the balance sheet). Green = improved, red = declined.")
        if multi:
            note += f" Sparkline covers the last {n_periods} periods."

    comp = {
        "title": title,
        "columns": columns,
        "rows": rows,
        "note": note,
        "periods": n_periods,
    }
    # annual growth table: year columns (oldest → latest) for the report
    growth_title = ("مقارنة النمو السنوي (القيمة ونسبة التغير عن العام السابق)"
                    if lang == "ar"
                    else "Annual Growth Comparison (value and YoY change)")
    longest = max(rows, key=lambda r: len(r.get("points") or []),
                  default=None)
    # the growth table earns its place from THREE periods on: with two the
    # curr/prev table above already shows the single transition
    if longest and len(longest.get("points") or []) >= 3:
        comp["years"] = [p["label"] for p in longest["points"]]
        comp["growth_title"] = growth_title
        # forecast column header: the period AFTER the last one — bump the
        # trailing number («2024» → «2025», «عام 2024» → «عام 2025»,
        # «الفترة 3» → «الفترة 4»); no trailing number → a plain label
        last_label = comp["years"][-1]
        m = re.search(r"(\d+)\s*$", str(last_label))
        if m:
            comp["forecast_label"] = (str(last_label)[:m.start()]
                                      + str(int(m.group(1)) + 1))
        else:
            comp["forecast_label"] = "توقع" if lang == "ar" else "Forecast"
        comp["growth_note"] = (
            "التوقع = آخر قيمة × (1 + متوسط النمو السنوي التاريخي) — رقم تقديري وليس وعدًا."
            if lang == "ar" else
            "Forecast = latest value × (1 + mean historical YoY growth) — an estimate, not a promise."
        )
    return comp


def build_working_capital_quality(result: dict, lang: str = "ar") -> dict | None:
    """Working-capital (earnings) quality indicator — مؤشر جودة رأس المال
    العامل: compares the file's STATED operating cash flow (cf_operating —
    «صافي التدفق النقدي من الأنشطة التشغيلية» as the file itself declares
    it) with net profit, period by period.

    A conversion ratio below 1.0 means profit is piling up in receivables &
    inventory rather than cash — انخفاض جودة الأرباح (earnings quality
    erosion); ≥ 1.0 means profit is cash-backed. Verdict per period:
    "ok" (≥ 0.8), "watch" (0.5–0.8), "bad" (< 0.5) — thresholds treat
    0.8× as the minimum healthy conversion. Returns None when the file
    states no operating cash flow (a composed/derived one would measure
    the platform's own assumption, not the company's earnings quality —
    the indicator must read what the company DECLARED).
    """
    metrics = result.get("metrics") or {}
    cf = _series_raw(metrics, "cf_operating")
    net = net_profit_series(result)
    n = min(len(cf), len(net))
    if n < 1:
        return None
    plabels = [str(x).strip() for x in (result.get("period_labels") or [])]

    def fmt(v: float) -> str:
        return f"({abs(v):,.0f})" if v < 0 else f"{v:,.0f}"

    rows = []
    ratios: list[float] = []
    for i in range(n):
        if not net[i]:            # zero/negative-denominator guard: the
            continue              # ratio is meaningless without profit
        ratio = cf[i] / net[i]
        ratios.append(ratio)
        verdict = "ok" if ratio >= 0.8 else ("watch" if ratio >= 0.5 else "bad")
        rows.append({
            "period": plabels[i] if i < len(plabels)
            else (("الفترة " if lang == "ar" else "Period ") + str(i + 1)),
            "net_profit": fmt(net[i]),
            "cf_operating": fmt(cf[i]),
            "ratio": f"{ratio * 100:.0f}%",
            "ratio_val": round(ratio, 2),
            "verdict": verdict,
        })
    if not rows:
        return None
    avg = sum(ratios) / len(ratios)
    low = min(ratios) < 0.8
    worst = min(rows, key=lambda r: r["ratio_val"])
    if lang == "ar":
        VERDICT = {"ok": "مستوفٍ ✓", "watch": "للمراقبة ≈", "bad": "ضعيف ✗"}
        if low:
            opinion = (f"جودة الأرباح منخفضة: أدنى تحويل نقدي «{worst['period']}» "
                       f"{worst['ratio']} — الأرباح تتراكم في الذمم والمخزون "
                       "لا في النقد؛ راجع التحصيل ودورة رأس المال العامل.")
        else:
            opinion = ("جودة أرباح جيدة: التدفق التشغيلي يغطي صافي الربح "
                       "في كل الفترات — الأرباح مدعومة بالنقد.")
        title = "مؤشر جودة رأس المال العامل"
        what = ("يقارن صافي التدفق النقدي التشغيلي المُعلن بصافي الربح لكل "
                "فترة: نسبة التحويل النقدي للأرباح.")
        why = ("ربحٌ لا يتحول إلى نقد يعني أن الأرباح محتقنة في الذمم "
               "والمخزون — إشارة مبكرة على تآكل جودة الأرباح قبل ظهوره "
               "في السيولة.")
        note = ("المنهجية: التدفق التشغيلي المُعلن ÷ صافي الربح — الحكم: "
                "مستوفٍ ≥ 80% · مراقبة 50–80% · ضعيف < 50%.")
    else:
        VERDICT = {"ok": "Healthy ✓", "watch": "Watch ≈", "bad": "Weak ✗"}
        if low:
            opinion = (f"Earnings quality is eroding: lowest cash conversion "
                       f"«{worst['period']}» at {worst['ratio']} — profit is "
                       "piling up in receivables & inventory, not cash.")
        else:
            opinion = ("Healthy earnings quality: operating cash flow covers "
                       "net profit in every period — profit is cash-backed.")
        title = "Working-Capital Quality Indicator"
        what = ("Compares the STATED operating cash flow with net profit per "
                "period: the cash-conversion ratio of earnings.")
        why = ("Profit that never converts to cash is trapped in receivables "
               "and inventory — an early signal of earnings-quality erosion.")
        note = ("Method: stated operating cash flow ÷ net profit — Healthy ≥ "
                "80% · Watch 50–80% · Weak < 50%.")
    return {
        "title": title, "what": what, "why": why, "opinion": opinion,
        "note": note, "rows": rows, "avg": round(avg, 2),
        "low": low, "worst": worst,
    }


def build_consistency_checks(result: dict, lang: str = "ar") -> list[dict]:
    """Statement consistency checks like the reference report's صفحة التحقق.

    Rules (only checked when the needed concepts exist in raw metrics):
    - revenue >= gross profit, gross profit >= operating income (approx:
      gross - opex >= 0 when both known)
    - assets = liabilities + equity (±5% tolerance)
    - gross/net margins are coherent (net <= gross)
    Returns [{label, ok, detail}] — missing concepts are skipped silently.
    """
    metrics = result.get("metrics") or {}

    def latest(concept: str) -> float | None:
        vals = metrics.get(concept) or []
        nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return nums[-1] if nums else None

    rev, cogs = latest("revenue"), latest("cogs")
    opex, net = latest("opex"), latest("net_profit")
    assets = latest("assets")
    liab, eq = latest("liabilities"), latest("equity")
    gross = (result.get("kpis") or {}).get("gross_profit", {}).get("value") \
        if isinstance((result.get("kpis") or {}).get("gross_profit"), dict) else None
    if gross is None and rev is not None and cogs is not None:
        gross = rev - cogs  # derive from detail rows when no KPI exists

    checks: list[dict] = []

    if lang == "ar":
        L = {
            "rev_ge_gross": ("الإيرادات ≥ الربح الإجمالي", "الإيرادات {rev:,.0f} والربح الإجمالي {gross:,.0f}"),
            "opex_ok": ("الربح الإجمالي ≥ الدخل التشغيلي", "بعد مصاريف تشغيل {opex:,.0f}"),
            "bs_eq": ("الأصول = الالتزامات + حقوق الملكية", "أصول {assets:,.0f} مقابل {sum:,.0f} (فرق {diff:,.0f})"),
            "margin_coherent": ("هامش صافي الربح ≤ الهامش الإجمالي", "صافي {net:,.1f}% مقابل إجمالي {gross:,.1f}%"),
        }
    else:
        L = {
            "rev_ge_gross": ("Revenue ≥ Gross profit", "Revenue {rev:,.0f} vs gross {gross:,.0f}"),
            "opex_ok": ("Gross profit ≥ Operating income", "after opex {opex:,.0f}"),
            "bs_eq": ("Assets = Liabilities + Equity", "Assets {assets:,.0f} vs {sum:,.0f} (diff {diff:,.0f})"),
            "margin_coherent": ("Net margin ≤ Gross margin", "net {net:,.1f}% vs gross {gross:,.1f}%"),
        }

    def add(key: str, ok: bool, **kw) -> None:
        label, detail_tmpl = L[key]
        checks.append({"label": label, "ok": ok, "detail": detail_tmpl.format(**kw)})

    if rev is not None and gross is not None and rev != 0:
        add("rev_ge_gross", rev >= gross, rev=rev, gross=gross)
    if gross is not None and opex is not None:
        add("opex_ok", gross - opex >= 0, opex=opex)
    if assets is not None and liab is not None and eq is not None and assets != 0:
        s = liab + eq
        diff = abs(assets - s)
        ok = diff / abs(assets) <= 0.05
        add("bs_eq", ok, assets=assets, sum=s, diff=assets - s)
    nm, gm = _ratio_value(result, "net_margin"), _ratio_value(result, "gross_margin")
    if nm is not None and gm is not None:
        add("margin_coherent", nm <= gm, net=nm, gross=gm)

    return checks
