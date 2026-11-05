"""IFRS knowledge base — الركيزة المعيارية للمنصة.

المرجعية المعيارية للتحليل المالي وإعداد التقارير: المعايير الدولية لإعداد
التقارير المالية (IFRS) الصادرة عن مجلس معايير المحاسبة الدولية (IASB).

المنصة تستخدمها في ثلاثة أدوار:
  1. أساس الإعداد (basis of preparation) — يُطبع في PDF وPPTX وExcel:
     الاستحقاق، الاستمرارية، التكلفة التاريخية، تصنيف متداول/غير متداول.
  2. كشف الانطباق — يفحص مفاهيم التحليل وبنود القوائم ودفتر الأستاذ ليرفع
     المعايير التي «يلمسها» هذا الملف فعليًا (لا قوائم معايير عامة).
  3. إسناد النسب — كل نسبة مالية تحمل مرجعها المعياري في بطاقات التحليل
     (ما هي؟ / ما فائدتها؟ / الرأي / المرجع المعياري).

الهيكل العرضي للقوائم في المنصة (قائمة دخل، مركز مالي، تدفقات نقدية، تغير
في حقوق الملكية) يتبع IAS 1، مع إشارة صريحة إلى IFRS 18 («العرض والإفصاح في
القوائم المالية»، صدر أبريل 2024، يسري إلزاميًا من الفترات السنوية بدءًا من
1 يناير 2027 محل IAS 1).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# المكتبة المعيارية — كل معيار: الرمز + الاسم + خلاصة جوهرية بالعربية والإنجليزية
# ---------------------------------------------------------------------------

IFRS_LIBRARY: list[dict] = [
    {
        "code": "IAS 1",
        "ar": "عرض القوائم المالية",
        "en": "Presentation of Financial Statements",
        "gist_ar": "أساس عرض القوائم: أساس الاستحقاق والاستمرارية، التمييز بين البنود المتداولة وغير المتداولة، والبنية العامة لقائمة الدخل والمركز المالي.",
        "gist_en": "Basis of presentation: accrual basis, going concern, current/non-current classification, and the overall structure of the statements.",
    },
    {
        "code": "IAS 2",
        "ar": "المخزون",
        "en": "Inventories",
        "gist_ar": "قياس المخزون بأدنى التكلفة وصافي القيمة القابلة للتحقيق، وتحديد تكلفة المبيعات.",
        "gist_en": "Inventories measured at the lower of cost and net realisable value; drives cost of sales.",
    },
    {
        "code": "IAS 7",
        "ar": "قائمة التدفقات النقدية",
        "en": "Statement of Cash Flows",
        "gist_ar": "تصنيف الحركة النقدية إلى تشغيلية واستثمارية وتمويلية وربط صافي التغير برصيد النقدية.",
        "gist_en": "Classifies cash movements into operating, investing and financing, tying the net change to the cash balance.",
    },
    {
        "code": "IAS 8",
        "ar": "السياسات المحاسبية والتقديرات والأخطاء",
        "en": "Accounting Policies, Estimates and Errors",
        "gist_ar": "انتقاء السياسات المحاسبية والتعامل مع تغيّر التقديرات وتصحيح الأخطاء بأثر رجعي عند إعادة العرض.",
        "gist_en": "Selecting accounting policies, handling estimate changes and prior-period error corrections.",
    },
    {
        "code": "IAS 16",
        "ar": "الممتلكات والآلات والمعدات",
        "en": "Property, Plant and Equipment",
        "gist_ar": "الاعتراف بالأصول الثابتة بالتكلفة وخصم الإهلاك المنهجي على مدى عمرها الإنتاجي.",
        "gist_en": "PP&E carried at cost less systematic depreciation over useful life.",
    },
    {
        "code": "IAS 36",
        "ar": "انخفاض قيمة الأصول",
        "en": "Impairment of Assets",
        "gist_ar": "اختبار انخفاض القيمة عند وجود مؤشرات: القيمة الدفترية لا تتجاوز القيمة القابلة للاسترداد.",
        "gist_en": "Impairment testing when indicators exist; carrying amount must not exceed recoverable amount.",
    },
    {
        "code": "IAS 37",
        "ar": "المخصصات والالتزامات المحتملة",
        "en": "Provisions and Contingent Liabilities",
        "gist_ar": "الاعتراف بالمخصصات عند وجود التزام حالي واحتمال أكبر من التدفقات الخارجية وقياسها بأفضل تقدير.",
        "gist_en": "Recognise provisions for present obligations with probable outflows, at best estimate.",
    },
    {
        "code": "IAS 38",
        "ar": "الأصول غير الملموسة",
        "en": "Intangible Assets",
        "gist_ar": "الاعتراف بالأصول غير الملموسة عند قابلية التمييز والسيطرة على المنافع المستقبلية.",
        "gist_en": "Intangibles recognised when identifiable and control over future benefits is held.",
    },
    {
        "code": "IFRS 9",
        "ar": "الأدوات المالية",
        "en": "Financial Instruments",
        "gist_ar": "قياس المدينين والالتزامات المالية، وخسائر الائتمان المتوقعة (ECL) على الذمم المدينة.",
        "gist_en": "Measurement of receivables and financial liabilities, with expected credit losses (ECL) on receivables.",
    },
    {
        "code": "IFRS 13",
        "ar": "قياس القيمة العادلة",
        "en": "Fair Value Measurement",
        "gist_ar": "إطار قياس القيمة العادلة وتصنيفاتها الثلاث عند الحاجة للقياس العادل.",
        "gist_en": "Fair-value measurement framework and its three-level hierarchy.",
    },
    {
        "code": "IFRS 15",
        "ar": "الإيراد من العقود مع العملاء",
        "en": "Revenue from Contracts with Customers",
        "gist_ar": "الاعتراف بالإيراد عند انتقال السيطرة على السلع أو الخدمات للعميل بمبلغ المقابل المتوقع.",
        "gist_en": "Recognise revenue as control of goods or services transfers to the customer.",
    },
    {
        "code": "IFRS 16",
        "ar": "عقود الإيجار",
        "en": "Leases",
        "gist_ar": "الإيجار يُعرض بأصل حق استخدام والتزام إيجار، ويُحسب إهلاكه ومصروف فوائده.",
        "gist_en": "Leases presented as a right-of-use asset and lease liability, depreciated with interest expense.",
    },
    {
        "code": "IFRS 18",
        "ar": "العرض والإفصاح في القوائم المالية (يسري إلزاميًا من 2027 محل IAS 1)",
        "en": "Presentation and Disclosure in Financial Statements (mandatory from 2027, replacing IAS 1)",
        "gist_ar": "يجدد متطلبات العرض: تصنيفات ثابتة لقائمة الدخل وربط القوائم بالملاحظات — المنصة مهيأة للانتقال إليه.",
        "gist_en": "Redefines presentation: fixed income-statement categories and statement-note linkage — the platform is aligned for the transition.",
    },
]

# ---------------------------------------------------------------------------
# كشف الانطباق: أي معايير «يلمسها» هذا الملف فعليًا؟
# ---------------------------------------------------------------------------

# مفاهيم metrics → معيار + سبب الانطباق
_CONCEPT_TRIGGERS = {
    "revenue": ("IFRS 15", "رُصد بند إيرادات — الاعتراف بها يخضع لمعيار الإيراد IFRS 15",
                "A revenue line exists — recognition follows IFRS 15"),
    "cogs": ("IAS 2", "تكلفة المبيعات تُشتق من قياس المخزون وفق IAS 2",
             "Cost of sales derives from inventory measurement under IAS 2"),
    "cash": ("IAS 7", "رُصدت النقدية — حركتها تُعرض وفق قائمة التدفقات IAS 7",
             "Cash detected — its movement is presented under IAS 7"),
    "assets": ("IAS 16", "رُصدت الأصول — الثابتة منها تُقاس وفق IAS 16",
               "Assets detected — fixed assets are measured under IAS 16"),
    "liabilities": ("IAS 1", "الالتزامات مصنّفة متداولة/غير متداولة وفق IAS 1",
                    "Liabilities classified current/non-current under IAS 1"),
    "equity": ("IAS 1", "حقوق الملكية وعناصرها تُعرض وفق IAS 1",
               "Equity and its components presented under IAS 1"),
}

# مفاهيم مفصّلة من القوائم/الأستاذ → معيار + سبب
_DETAIL_TRIGGERS = {
    "receivables": ("IFRS 9", "رُصِدت ذمم مدينة — تُقاس بخسائر الائتمان المتوقعة وفق IFRS 9",
                    "Receivables detected — measured with expected credit losses under IFRS 9"),
    "inventory": ("IAS 2", "رُصِد مخزون — يُقاس بأدنى التكلفة وصافي القيمة القابلة للتحقيق وفق IAS 2",
                  "Inventory detected — lower of cost and NRV under IAS 2"),
    "fixed_assets": ("IAS 16", "رُصِدت أصول ثابتة — تُهلك منهجيًا وفق IAS 16",
                     "Fixed assets detected — systematically depreciated under IAS 16"),
    "loans": ("IFRS 9", "رُصِدت قروض — أدوات مالية تُقاس وفق IFRS 9",
              "Loans detected — financial instruments measured under IFRS 9"),
    "intangibles": ("IAS 38", "رُصِدت أصول غير ملموسة — وفق IAS 38",
                    "Intangible assets detected — under IAS 38"),
}

# كلمات مفتاحية في نص حسابات دفتر الأستاذ → معيار
_KEYWORD_TRIGGERS: list[tuple[tuple[str, ...], str, str, str]] = [
    (("إيجار", "ايجار", "rent", "lease"), "IFRS 16",
     "رُصِدت بنود إيجار — تُعرض بأصل حق استخدام والتزام إيجار وفق IFRS 16",
     "Lease items detected — right-of-use asset and lease liability under IFRS 16"),
    (("إهلاك", "اهلاك", "depreciat", "أصول ثابتة", "fixed asset"), "IAS 16",
     "رُصِدت أصول ثابتة/إهلاك — القياس والإهلاك وفق IAS 16",
     "Fixed assets/depreciation detected — measurement under IAS 16"),
    (("مخصص", "provision"), "IAS 37",
     "رُصِدت مخصصات — الاعتراف والقياس وفق IAS 37",
     "Provisions detected — recognition and measurement under IAS 37"),
    (("انخفاض قيمة", "impairment"), "IAS 36",
     "رُصِدت مؤشرات انخفاض قيمة — الاختبار وفق IAS 36",
     "Impairment indicators detected — testing under IAS 36"),
    (("غير ملموس", "intangible", "برمجيات", "software"), "IAS 38",
     "رُصِدت أصول غير ملموسة — الاعتراف والقياس وفق IAS 38",
     "Intangible assets detected — under IAS 38"),
    (("مدينون", "receivab", "ذمم"), "IFRS 9",
     "رُصِدت ذمم مدينة — خسائر الائتمان المتوقعة وفق IFRS 9",
     "Receivables detected — expected credit losses under IFRS 9"),
    (("مخزون", "inventory", "stock"), "IAS 2",
     "رُصِد مخزون — القياس وفق IAS 2",
     "Inventory detected — measured under IAS 2"),
]

_BY_CODE = {s["code"]: s for s in IFRS_LIBRARY}


def _iter_account_text(statements: dict | None):
    tb = ((statements or {}).get("trial_balance") or {}).get("accounts") or []
    for acc in tb:
        if isinstance(acc, dict):
            yield str(acc.get("account") or "")


def detect_applicable(result: dict, statements: dict | None = None) -> list[dict]:
    """المعايير التي يلمسها هذا التحليل فعليًا — مرتبة بترتيب المكتبة.

    Returns entries: {code, ar, en, gist_ar, gist_en, why_ar, why_en}.
    IAS 1 is always included: it is the presentation umbrella every
    analysis is built on (with the IFRS 18 transition note).
    """
    found: dict[str, list[tuple[str, str]]] = {"IAS 1": [
        ("كل بنود التحليل تُعرض وفق أساس العرض في IAS 1 (الاستحقاق والاستمرارية والتصنيف)",
         "All figures are presented on the IAS 1 basis (accrual, going concern, classification)"),
    ]}

    metrics = result.get("metrics") if isinstance(result, dict) else None
    if isinstance(metrics, dict):
        for concept, (code, why_ar, why_en) in _CONCEPT_TRIGGERS.items():
            values = metrics.get(concept)
            if isinstance(values, list) and any(
                isinstance(v, (int, float)) and not isinstance(v, bool) and v for v in values
            ):
                found.setdefault(code, []).append((why_ar, why_en))

    st = statements if isinstance(statements, dict) else None
    if st:
        bs = st.get("balance_sheet") or {}
        for side in ("assets", "liabilities_equity"):
            block = bs.get(side) or {}
            for key in list((block.get("detail") or {}).keys()):
                trig = _DETAIL_TRIGGERS.get(str(key))
                if trig:
                    found.setdefault(trig[0], []).append((trig[1], trig[2]))
        for text in _iter_account_text(st):
            low = text.lower()
            for needles, code, why_ar, why_en in _KEYWORD_TRIGGERS:
                if any(n in text or n in low for n in needles):
                    found.setdefault(code, []).append((why_ar, why_en))

    out: list[dict] = []
    for std in IFRS_LIBRARY:
        reasons = found.get(std["code"])
        if not reasons:
            continue
        why_ar = reasons[0][0]
        why_en = reasons[0][1]
        out.append({**std, "why_ar": why_ar, "why_en": why_en})
    return out


# ---------------------------------------------------------------------------
# إسناد النسب المالية إلى مراجعها المعيارية
# ---------------------------------------------------------------------------

RATIO_STANDARDS: dict[str, dict[str, str]] = {
    "gross_margin": {
        "code": "IAS 1 · IAS 2",
        "ar": "تكلفة المبيعات وفق قياس IAS 2 والعرض وفق IAS 1",
        "en": "Cost of sales per IAS 2, presentation per IAS 1",
    },
    "net_margin": {
        "code": "IAS 1",
        "ar": "بنود قائمة الدخل وترتيبها وفق IAS 1",
        "en": "Income-statement line items per IAS 1",
    },
    "debt_ratio": {
        "code": "IAS 1",
        "ar": "عرض الالتزامات وتصنيفها وفق IAS 1",
        "en": "Liability presentation per IAS 1",
    },
    "debt_to_equity": {
        "code": "IAS 1",
        "ar": "هيكل التمويل كما يعرضه IAS 1",
        "en": "Financing structure as presented by IAS 1",
    },
    "current_ratio": {
        "code": "IAS 1",
        "ar": "التمييز المتداول/غير المتداول أساس النسبة وفق IAS 1",
        "en": "Current/non-current split under IAS 1",
    },
    "quick_ratio": {
        "code": "IAS 1 · IAS 2",
        "ar": "يستبعد المخزون المُقاس وفق IAS 2",
        "en": "Excludes inventory measured under IAS 2",
    },
    "roa": {
        "code": "IAS 1 · IAS 16",
        "ar": "الأصول الثابتة مقياسها وفق IAS 16 والإجمالي وفق IAS 1",
        "en": "Fixed assets per IAS 16, totals per IAS 1",
    },
    "roe": {
        "code": "IAS 1",
        "ar": "حقوق الملكية كما تعرضها IAS 1",
        "en": "Equity as presented by IAS 1",
    },
    "asset_turnover": {
        "code": "IAS 1 · IAS 16",
        "ar": "كفاءة أصول مقياسها وفق IAS 16/IAS 1",
        "en": "Asset efficiency per IAS 16/IAS 1",
    },
    "interest_coverage": {
        "code": "IFRS 18 · IFRS 9",
        "ar": "مصاريف التمويل فئة تمويلية وفق IFRS 18 والفوائد وفق IFRS 9",
        "en": "Finance costs as the IFRS 18 financing category, interest per IFRS 9",
    },
    "receivables_turnover": {
        "code": "IFRS 9 · IAS 1",
        "ar": "المدينون أصول مالية وفق IFRS 9 والعرض وفق IAS 1",
        "en": "Receivables are financial assets per IFRS 9, presented per IAS 1",
    },
    "receivable_days": {
        "code": "IFRS 9 · IAS 1",
        "ar": "فترة التحصيل من أرصدة المدينين وفق IFRS 9/IAS 1",
        "en": "Collection period from IFRS 9/IAS 1 receivable balances",
    },
    "inventory_turnover": {
        "code": "IAS 2",
        "ar": "المخزون مقياسه وفق IAS 2 وتكلفة المبيعات من قائمة الدخل",
        "en": "Inventory measured per IAS 2, cost of sales from the income statement",
    },
    "inventory_days": {
        "code": "IAS 2",
        "ar": "فترة بقاء المخزون من أرصدة IAS 2 وتكلفة المبيعات",
        "en": "Inventory holding period from IAS 2 balances and cost of sales",
    },
    "payables_turnover": {
        "code": "IAS 1",
        "ar": "الدائنون التزامات متداولة تُعرض وفق IAS 1",
        "en": "Payables are current liabilities presented per IAS 1",
    },
    "days_payable": {
        "code": "IAS 1",
        "ar": "فترة السداد من أرصدة الدائنين وفق IAS 1",
        "en": "Payment period from IAS 1 payables balances",
    },
    "cash_conversion_cycle": {
        "code": "IAS 1 · IAS 2",
        "ar": "الدورة المجمعة من أرصدة المدينين (IFRS 9) والمخزون (IAS 2) والدائنين (IAS 1)",
        "en": "Composite cycle from receivables (IFRS 9), inventory (IAS 2) and payables (IAS 1)",
    },
}


def ratio_reference(key: str, lang: str = "ar") -> str | None:
    entry = RATIO_STANDARDS.get(key)
    if not entry:
        return None
    return f"{entry['code']} — {entry['ar'] if lang == 'ar' else entry['en']}"


# ---------------------------------------------------------------------------
# أساس الإعداد — يُطبع في التقارير الثلاثة
# ---------------------------------------------------------------------------

_BASIS = {
    "ar": (
        "أُعدّ هذا التحليل وتقاريره وفق المعايير الدولية لإعداد التقارير المالية (IFRS) "
        "الصادرة عن مجلس معايير المحاسبة الدولية (IASB): على أساس الاستحقاق وافتراض استمرارية "
        "النشاط، وبالقياس التاريخي للتكلفة، وببنية العرض المقررة في IAS 1 (تصنيف البنود "
        "متداولة/غير متداولة، وبنية قائمة الدخل وقائمة المركز المالي وقائمة التدفقات النقدية "
        "وفق IAS 7). وتُعرض النسب المالية بإسنادها إلى معاييرها، مع انتباه متطلبات IFRS 18 "
        "الجديد للعرض والإفصاح الساري إلزاميًا من 2027."
    ),
    "en": (
        "This analysis and its reports are prepared in accordance with International Financial "
        "Reporting Standards (IFRS) issued by the IASB: on the accrual basis, assuming going "
        "concern, at historical cost, with the presentation structure of IAS 1 (current/"
        "non-current classification, and the structure of the income statement, financial "
        "position and cash-flow statements per IAS 7). Ratios are attributed to their governing "
        "standards, mindful of the new IFRS 18 presentation requirements effective from 2027."
    ),
}


def basis_of_preparation(lang: str = "ar") -> str:
    return _BASIS.get(lang) or _BASIS["ar"]


def framework_note(result: dict, statements: dict | None = None, lang: str = "ar") -> dict:
    """الحزمة الكاملة للتقارير: أساس الإعداد + المعايير المنطبقة."""
    standards = detect_applicable(result, statements)
    if lang == "ar":
        items = [{"code": s["code"], "title": s["ar"], "why": s["why_ar"]} for s in standards]
    else:
        items = [{"code": s["code"], "title": s["en"], "why": s["why_en"]} for s in standards]
    return {"basis": basis_of_preparation(lang), "standards": items}
