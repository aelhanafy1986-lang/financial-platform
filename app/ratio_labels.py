"""التسميات الموحدة للنسب المالية — المصدر الوحيد في المشروع.

كل وحدة تعرض نسبًا (المحلل، بطاقات التحليل، Excel، PDF، PPTX، بيانات
الديمو) تأخذ نصوصها العربية والإنجليزية من هنا — لا قوائم نصية يدوية
مبعثرة، فلا ينحرف أي عرض عن بقية العروض مستقبلًا.

القاعدة: المفتاح ``key`` هو المعرف البرمجي للنسبة، والسلسلة ``ar``/``en``
هي نص العرض الأصلي كما اعتمدته المنصة (مع وحدتها الملتصقة: % أو (x)
أو (يوم)).
"""

from __future__ import annotations

RATIO_LABELS: dict[str, dict[str, str]] = {
    # الربحية
    "gross_margin": {"en": "Gross Margin %", "ar": "هامش الربح الإجمالي %"},
    "net_margin": {"en": "Net Margin %", "ar": "هامش صافي الربح %"},
    "operating_margin": {"en": "Operating Margin %", "ar": "هامش الربح التشغيلي %"},
    "roa": {"en": "Return on Assets %", "ar": "العائد على الأصول %"},
    "roe": {"en": "Return on Equity %", "ar": "العائد على حقوق الملكية %"},
    "roce": {"en": "Return on Capital Employed %", "ar": "العائد على رأس المال المستخدم %"},
    "roic": {"en": "Return on Invested Capital %", "ar": "العائد على رأس المال المستثمر %"},
    # الرفع والهيكل التمويلي
    "debt_ratio": {"en": "Debt Ratio %", "ar": "نسبة الالتزامات %"},
    "debt_to_equity": {"en": "Debt to Equity", "ar": "الالتزامات إلى حقوق الملكية"},
    "equity_ratio": {"en": "Equity Ratio %", "ar": "نسبة الملكية %"},
    "working_capital": {"en": "Working Capital", "ar": "رأس المال العامل"},
    # السيولة
    "current_ratio": {"en": "Current Ratio", "ar": "نسبة التداول"},
    "quick_ratio": {"en": "Quick Ratio", "ar": "النسبة السريعة"},
    "cash_ratio": {"en": "Cash Ratio", "ar": "نسبة النقدية إلى الالتزامات المتداولة"},
    "current_assets_share": {
        "en": "Current Assets / Total Assets %",
        "ar": "نسبة الأصول المتداولة إلى إجمالي الأصول %",
    },
    # النشاط ودورة رأس المال العامل
    "asset_turnover": {"en": "Asset Turnover", "ar": "معدل دوران الأصول"},
    "receivables_turnover": {"en": "Receivables Turnover (x)", "ar": "دوران المدينين (x)"},
    "receivable_days": {"en": "Collection Period (days)", "ar": "فترة التحصيل (يوم)"},
    "inventory_turnover": {"en": "Inventory Turnover (x)", "ar": "دوران المخزون (x)"},
    "inventory_days": {"en": "Inventory Holding Period (days)", "ar": "فترة بقاء المخزون (يوم)"},
    "payables_turnover": {"en": "Payables Turnover (x)", "ar": "دوران الدائنين (x)"},
    "days_payable": {"en": "Payment Period (days)", "ar": "فترة السداد (يوم)"},
    "cash_conversion_cycle": {
        "en": "Cash Conversion Cycle (days)",
        "ar": "دورة التحول النقدي (يوم)",
    },
    # التغطية
    "interest_coverage": {"en": "Interest Coverage (x)", "ar": "تغطية الفوائد (x)"},
    # التدفقات النقدية
    "ocf_margin": {
        "en": "Operating Cash Flow / Sales %",
        "ar": "التدفق النقدي التشغيلي إلى المبيعات %",
    },
    "ocf_to_debt": {
        "en": "Operating Cash Flow / Total Debt",
        "ar": "التدفق النقدي التشغيلي إلى إجمالي الدين",
    },
    "ocf_liquidity": {
        "en": "OCF Coverage of Current Liabilities",
        "ar": "تغطية التدفق النقدي للالتزامات المتداولة",
    },
    "earnings_quality": {
        "en": "Cash Flow Quality of Earnings",
        "ar": "جودة الأرباح (التشغيلي ÷ صافي الربح)",
    },
}


def ratio_label(key: str, lang: str = "ar") -> str | None:
    """تسمية العرض الموحدّة لنسبة (كر) — «لا شيء» عندما لا تعرف النسبة."""
    entry = RATIO_LABELS.get(key)
    if not entry:
        return None
    return entry.get(lang) or entry.get("en")
