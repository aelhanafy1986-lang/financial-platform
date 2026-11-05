"""Recommendations engine: forward-looking advice, risk solutions, and a
numeric forecast horizon derived from the stored analysis values.

Everything here is derived from raw values (metrics) and computed ratios, so
it stays consistent with manual value edits.
"""

from __future__ import annotations

from .analyzer import forecast as linear_forecast
from .ratio_explain import build_consistency_checks, build_ratio_insights

# Bilingual advice entries: each advice carries severity, ar/en text, and an
# optional solutions list shown when results deteriorate (or look risky).
ADVICE_LIBRARY: list[dict] = [
    {
        "key": "gross_margin",
        "severity": "critical",  # when below threshold
        "metric": ("ratio", "gross_margin"),
        "bad_when": "below",
        "thresholds": {"warn": 25.0, "critical": 15.0},
        "ar": "هامش الربح الإجمالي منخفض — تكلفة المبيعات تلتهم جزءاً كبيراً من الإيراد",
        "en": "Gross margin is low — cost of sales consumes a large share of revenue",
        "solutions_ar": [
            "أعد التفاوض على أسعار الموردين أو ابحث عن بدائل أقل تكلفة",
            "ارفع أسعار البيع تدريجياً على المنتجات الأقل ربحية",
            "قلّل الهدر وعيّن نسبة فاقد مستهدفة لكل خط إنتاج",
        ],
        "solutions_en": [
            "Renegotiate supplier prices or source cheaper alternatives",
            "Raise prices gradually on low-margin products",
            "Cut waste and set a target shrinkage rate per product line",
        ],
    },
    {
        "key": "net_margin",
        "severity": "critical",
        "metric": ("ratio", "net_margin"),
        "bad_when": "below",
        "thresholds": {"warn": 8.0, "critical": 3.0},
        "ar": "هامش صافي الربح ضعيف — الربحية النهائية تحت الضغط",
        "en": "Net margin is weak — final profitability under pressure",
        "solutions_ar": [
            "راجع المصاريف التشغيلية بنداً بنداً واجعل خفضها هدفًا ربع سنويًا",
            "أوقف المنتجات/الفروع الخاسرة أو أعِد تسعيرها",
            "زد الإيراد عالي الهامش (خدمات، بيع إضافي) دون رفع التكلفة",
        ],
        "solutions_en": [
            "Review operating expenses line by line; make cuts a quarterly goal",
            "Stop or re-price loss-making products/branches",
            "Grow high-margin revenue (services, upselling) without cost",
        ],
    },
    {
        "key": "debt_ratio",
        "severity": "critical",
        "metric": ("ratio", "debt_ratio"),
        "bad_when": "above",
        "thresholds": {"warn": 60.0, "critical": 80.0},
        "ar": "نسبة الالتزامات مرتفعة — مخاطر مالية على السيولة والملاءة",
        "en": "Debt ratio is high — liquidity and solvency risk",
        "solutions_ar": [
            "أعد جدولة القروذ قصيرة الأجل إلى آجال أطول",
            "قلّل النفقات الرأسمالية غير الضرورية هذا العام",
            "فكّر في ضخ حقوق ملكية أو تحويل جزء من الأرباح لتقوية الهيكل التمويلي",
        ],
        "solutions_en": [
            "Refinance short-term loans to longer maturities",
            "Postpone non-essential capex this year",
            "Inject equity or retain profits to strengthen the capital structure",
        ],
    },
    {
        "key": "cash",
        "severity": "critical",
        "metric": ("kpi_vs_revenue", "cash"),
        "bad_when": "below",
        "thresholds": {"warn": 0.05, "critical": 0.02},
        "ar": "النقدية منخفضة مقارنة بحجم النشاط — خطر أزمة سيولة",
        "en": "Cash is low relative to activity — liquidity crunch risk",
        "solutions_ar": [
            "اعمل توقعاً نقدياً أسبوعياً لـ 13 أسبوعاً مقدماً",
            "شدّ التحصيل: خصم للسداد المبكر وحدود ائتمان لكل عميل",
            "أجّل المشتريات غير الحرجة وحوّل فوائض الأصول إلى نقد",
        ],
        "solutions_en": [
            "Run a 13-week rolling cash forecast",
            "Tighten collections: early-payment discounts and per-customer limits",
            "Defer non-critical purchases and monetise idle assets",
        ],
    },
    # ---- positive reinforcement entries (info severity) ---------------------
    {
        "key": "gross_margin_good",
        "severity": "info",
        "metric": ("ratio", "gross_margin"),
        "bad_when": "below",
        "thresholds": {"good": 35.0},
        "ar": "هامش الربح الإجمالي قوي — حافظ على سياسة التسعير ومراقبة التكلفة",
        "en": "Healthy gross margin — keep pricing and cost discipline",
        "solutions_ar": [],
        "solutions_en": [],
    },
    {
        "key": "net_margin_good",
        "severity": "info",
        "metric": ("ratio", "net_margin"),
        "bad_when": "below",
        "thresholds": {"good": 15.0},
        "ar": "ربحية صافية ممتازة — فرصة للاستثمار في النمو",
        "en": "Excellent net profitability — consider investing in growth",
        "solutions_ar": [],
        "solutions_en": [],
    },
    {
        "key": "debt_ratio_good",
        "severity": "info",
        "metric": ("ratio", "debt_ratio"),
        "bad_when": "above",
        "thresholds": {"good": 40.0},
        "ar": "هيكل تمويلي متوازن — القدرة على الاقتراض متاحة عند الحاجة",
        "en": "Balanced financing structure — borrowing headroom available",
        "solutions_ar": [],
        "solutions_en": [],
    },
]


def _ratio_value(result: dict, key: str) -> float | None:
    entry = (result.get("ratios") or {}).get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _kpi_value(result: dict, key: str) -> float | None:
    entry = (result.get("kpis") or {}).get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _latest_metric(result: dict, key: str) -> float | None:
    values = [v for v in ((result.get("metrics") or {}).get(key) or [])
              if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return values[-1] if values else None


def _cost_cut_solutions(result: dict, net_margin: float) -> tuple[list[str], list[str]]:
    """Quantified cost-reduction lines computed from the entity's OWN figures.

    Loss case → an explicit recovery plan: the total cost cut that returns
    the business to break-even, the revenue growth alternative at the same
    cost ratio, the per-1%-of-COGS margin effect and the opex-cut coverage
    of the loss. Weak-but-positive case → the milder 1%-of-COGS line only.
    Figures the file does not carry are skipped — never guessed.
    """
    revenue = _kpi_value(result, "revenue")
    if not revenue:
        return [], []
    cogs = _latest_metric(result, "cogs")
    opex = _latest_metric(result, "opex")
    net = _kpi_value(result, "net_profit")
    if net is None and net_margin is not None:
        net = revenue * net_margin / 100
    ar: list[str] = []
    en: list[str] = []

    loss = -net if (net is not None and net < 0) else None
    if loss:
        ar.append(
            f"نقطة التعادل: خفض إجمالي في التكاليف بنحو {loss:,.0f} "
            f"({loss / revenue * 100:.1f}% من الإيراد) يعيد النشاط للتعادل عند مستوى الأداء الحالي")
        en.append(
            f"Break-even: a total cost cut of ~{loss:,.0f} "
            f"({loss / revenue * 100:.1f}% of revenue) returns the business to break-even at current volumes")
        if cogs and cogs > 0 and opex is not None and opex > 0:
            gm = max((revenue - cogs) / revenue, 0.0)
            if gm > 0:
                be_rev = opex / gm
                ar.append(
                    f"أو زيادة الإيراد بنحو {be_rev - revenue:,.0f} "
                    f"({(be_rev - revenue) / revenue * 100:+.1f}%) عند نفس نسبة التكلفة وبقاء المصاريف كما هي")
                en.append(
                    f"Or grow revenue by ~{be_rev - revenue:,.0f} "
                    f"({(be_rev - revenue) / revenue * 100:+.1f}%) at the same cost ratio with expenses held flat")
        if opex and opex > 0:
            ar.append(
                f"خفض المصاريف التشغيلية 10% (≈ {opex * 0.10:,.0f}) يغطي "
                f"{opex * 0.10 / loss * 100:.0f}% من الخسارة الحالية")
            en.append(
                f"A 10% operating-expense cut (≈ {opex * 0.10:,.0f}) covers "
                f"{opex * 0.10 / loss * 100:.0f}% of the current loss")
    if cogs and cogs > 0:
        pts = cogs / revenue  # 1% of cogs as margin points = cogs/revenue
        if loss:
            ar.append(f"كل خفض 1% في تكلفة المبيعات (≈ {cogs / 100:,.0f}) "
                      f"يرفع هامش صافي الربح {pts:.2f} نقطة مئوية")
            en.append(f"Every 1% cut in cost of sales (≈ {cogs / 100:,.0f}) "
                      f"lifts the net margin by {pts:.2f} percentage points")
        else:
            ar.append(f"كل خفض 1% في تكلفة المبيعات (≈ {cogs / 100:,.0f}) "
                      f"يضيف {pts:.2f} نقطة لهامش صافي الربح")
            en.append(f"Every 1% cut in cost of sales (≈ {cogs / 100:,.0f}) "
                      f"adds {pts:.2f} points to the net margin")
    return ar, en


def _augment_cost_advice(advice: list[dict], result: dict) -> None:
    """Attach the quantified cost-reduction plan to the weak/loss net-margin
    advice entry (dynamic lines first, two generic lines kept after)."""
    entry = next((a for a in advice
                  if a["key"] == "net_margin" and a["severity"] != "info"), None)
    if entry is None or not isinstance(entry.get("value"), (int, float)):
        return
    value = entry["value"]
    dyn_ar, dyn_en = _cost_cut_solutions(result, value)
    if not dyn_ar:
        return
    entry["solutions_ar"] = dyn_ar + entry["solutions_ar"][:2]
    entry["solutions_en"] = dyn_en + entry["solutions_en"][:2]
    if value < 0:
        entry["ar"] = (f"خسارة صافية ({value:.2f}% من الإيراد) — "
                       "خطة استعادة الربحية مطلوبة")
        entry["en"] = (f"Net loss ({value:.2f}% of revenue) — "
                       "a profitability recovery plan is required")


def _evaluate(result: dict) -> list[dict]:
    """Turn the advice library into concrete, data-driven advice entries."""
    out: list[dict] = []
    for item in ADVICE_LIBRARY:
        kind, key = item["metric"]
        thresholds = item["thresholds"]
        bad_when = item.get("bad_when", "below")

        def _grade(v: float) -> tuple[str | None, bool]:
            """Return (severity, triggered) for a value vs thresholds."""
            if "good" in thresholds:
                ok = v >= thresholds["good"] if bad_when == "below" else v <= thresholds["good"]
                return ("info", True) if ok else (None, False)
            if bad_when == "below":
                critical, warn = v < thresholds["critical"], v < thresholds["warn"]
            else:
                critical, warn = v > thresholds["critical"], v > thresholds["warn"]
            if critical:
                return "critical", True
            if warn:
                return "warning", True
            return None, False

        if kind == "ratio":
            value = _ratio_value(result, key)
            if value is None:
                continue
            severity, ok = _grade(value)
        else:  # kpi_vs_revenue
            value = _kpi_value(result, key)
            revenue = _kpi_value(result, "revenue")
            if value is None or not revenue:
                continue
            severity, ok = _grade(value / revenue)

        if not ok:
            continue
        out.append({
            "key": item["key"],
            "severity": severity or "info",
            "value": value if kind == "ratio" else round(value / revenue * 100, 2),
            "ar": item["ar"],
            "en": item["en"],
            "solutions_ar": item.get("solutions_ar", []),
            "solutions_en": item.get("solutions_en", []),
        })
    return out


def _forecast_horizon(result: dict, periods: int = 2) -> list[dict]:
    """Numeric forecast per series: linear projection for the next periods."""
    from .analyzer import RESULT_META

    out = []
    for concept, s in (result.get("series") or {}).items():
        values = [v for v in (s.get("values") or [])
                  if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(values) < 2:
            continue  # two periods already give an exact linear trend
        n = len(values)
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(values) / n
        denom = sum((x - mean_x) ** 2 for x in xs)
        if denom == 0 or mean_y == 0:
            continue
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom

        projections = []
        last = values[-1]
        for i in range(1, periods + 1):
            projected = values[-1] + slope * i
            change = (projected - last) / abs(last) * 100 if last else 0.0
            projections.append({
                "period": n + i,
                "value": round(projected, 2),
                "change_pct": round(change, 1),
            })

        meta = RESULT_META.get(concept) or s
        out.append({
            "concept": concept,
            "en": s.get("en") or meta.get("en", concept),
            "ar": s.get("ar") or meta.get("ar", concept),
            "values": values,
            "projections": projections,
            "trend": "up" if slope > 0 else ("down" if slope < 0 else "flat"),
        })
    return out


def build_advisor(result: dict, lang: str = "ar") -> dict:
    """Full advisory payload: advice list + future projections + summary."""
    advice = _evaluate(result)
    _augment_cost_advice(advice, result)
    projections = _forecast_horizon(result)

    criticals = [a for a in advice if a["severity"] == "critical"]
    warnings = [a for a in advice if a["severity"] == "warning"]
    positives = [a for a in advice if a["severity"] == "info"]

    if lang == "ar":
        if criticals:
            headline = "وضع يتطلب تدخلاً عاجلاً — هناك مؤشرات حرجة"
        elif warnings:
            headline = "وضع مقبول مع نقاط تحت المراقبة"
        else:
            headline = "وضع مالي سليم حسب المؤشرات المتاحة"
    else:
        if criticals:
            headline = "Situation needs urgent action — critical indicators present"
        elif warnings:
            headline = "Acceptable with points to watch"
        else:
            headline = "Financially healthy per available indicators"

    return {
        "headline": headline,
        "advice": advice,
        "projections": projections,
        "summary": {
            "critical": len(criticals),
            "warning": len(warnings),
            "positive": len(positives),
        },
        "ratio_insights": build_ratio_insights(result, lang),
        "consistency_checks": build_consistency_checks(result, lang),
        "solutions": [
            s
            for a in criticals + warnings
            for s in (a["solutions_ar"] if lang == "ar" else a["solutions_en"])
        ][:8],
    }
