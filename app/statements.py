"""Full financial statements from a trial balance.

Builds the four standard statements plus notes:
  1. Income statement (قائمة الدخل) — classified per IFRS 18 categories
     (operating / investing / financing / income taxes) with the defined
     subtotals Operating Profit and Profit before Financing and Income
     Taxes, in preparation for IFRS 18 becoming mandatory on 1 Jan 2027.
  2. Statement of financial position (قائمة المركز المالي)
  3. Cash flow statement by activity (قائمة التدفقات النقدية)
  4. Statement of changes in equity (قائمة التغير في حقوق الملكية)
  5. Notes to the financial statements (إيضاحات الميزانية)

Bilingual labels ride along so reports/UI need no extra mapping.
"""

from __future__ import annotations

import re

from .analyzer import NUM_RE

ACCOUNT_RULES: list[tuple[str, list[str]]] = [
    ("accumulated_depr", [
        "مجمع اهلاك", "مجمع إهلاك", "مجمع استهلاك", "مجمع الاهلاك", "مجمع الإهلاك",
        "accumulated depreciation", "accum. depreciation",
    ]),
    ("cogs", [
        "تكلفة المبيعات", "تكلفة البضاعة", "تكلفة البضاعه", "تكلفة الايرادات",
        "تكلفة الإيرادات", "تكلفة الايراد", "تكلفة الإيراد", "تكلفة التشغيل",
        "cost of goods", "cost of sales", "cost of revenue",
    ]),
    ("revenue", [
        "ايرادات", "إيرادات", "إيراد", "مبيعات", "ايراد",
        "revenue", "sales", "service income",
    ]),
    # Accrued liabilities MUST be checked before opex: 'رواتب مستحقة' /
    # 'حقوق عاملين مستحقة' / 'مصروفات مستحقة حكوميه' are liabilities (LT22 in
    # real charts of accounts) even though they contain expense words.
    ("payables", [
        "مستحقة", "مستحق", "مستحقات",
    ]),
    ("opex", [
        "مصاريف", "مصروفات", "رواتب", "اجارات", "إيجارات", "ايجار", "إيجار",
        "كهرباء", "مياه", "اتصالات", "دعاية", "إعلان", "اعلان", "صيانة",
        "عمولات", "شحن", "نقل", "تأمين", "تامين", "م تشغيل", "م ع",
        "تشغيلي", "إداري", "اداري", "ضيافة", "قرطاسية", "مكتبية",
        "تشغيل ", "تشغيل-", "راتب", "عاملين", "بنزين", "دبابات", "فطور",
        "مخالفات", "فروق أسعار", "تذاكر",
        "expenses", "salaries", "rent", "utilities", "marketing", "advertis",
        "insurance", "sales and marketing", "general and administrative",
        "research and development", "research & development",
    ]),
    ("equity", [
        "رأس المال", "راس المال", "حقوق ملكية", "الأرباح المبقاة", "احتياطي",
        "capital", "equity", "retained", "reserve",
    ]),
    ("loans", [
        "قروض", "قرض", "سحب على المكشوف", "loan", "borrowing",
    ]),
    ("payables", [
        "دائنون", "الموردون", "أوراق دفع", "اوراق دفع", "موردين", "مورد",
        "مستحقات", "جاري ", "جاري", "اطراف ذات علاقة", "أطراف ذات علاقة",
        "حقوق عاملين", "payable", "suppliers",
    ]),
    ("cash", [
        "نقدية", "النقد", "الصندوق", "صندوق", "البنك", "البنوك", "بنك ",
        "بنك", "cash", "bank",
    ]),
    ("receivables", [
        "مدينون", "العملاء", "أوراق قبض", "اوراق قبض", "عهدة", "عهد",
        "سلف عاملين", "سلفة", "سلف ", "receivable", "customers",
    ]),
    ("inventory", [
        "مخزون", "مخزونات", "بضاعة", "inventory", "stock",
    ]),
    ("fixed_assets", [
        "أصول ثابتة", "اصول ثابتة", "أثاث", "سيارة", "سيارات", "آلات",
        "الات و", "الالات", "معدات",        "أراضي", "مبان", "عدد وأدوات", "عدد والأدوات",
        "عدد و اعدة", "حاسب", "لوحات", "برامج محاسبية", "موجودات",
        "fixed asset", "furniture", "vehicles", "machinery", "land",
        "building", "equipment",
    ]),
]

DEPRECIATION_PATTERNS = ["استهلاك", "إهلاك", "اهلاك", "depreciation"]
CAPITAL_PATTERNS = ["رأس المال", "راس المال", "capital"]
RESERVE_PATTERNS = ["احتياطي", "reserve"]
RETAINED_PATTERNS = ["مبقاة", "retained"]

# ---- IFRS 18 (effective 1 Jan 2027) income-statement categories ----------
# Revenue/cogs/opex are the operating category by construction; these
# patterns pull the other categories out of the generic opex/other pools.
# VAT and accrued items are balance-sheet matters, never income-tax expense.
IFRS18_VAT_PATTERNS = ["قيمة مضافة", "ض.ق.م", "vat"]
IFRS18_TAX_PATTERNS = [
    "زكاة", "ضريبة الدخل", "ضرائب الدخل", "ضريبة دخل", "ضرائب دخل",
    "income tax", "zakat",
]
IFRS18_INVESTING_PATTERNS = [
    "فوائد ودائع", "فوايد ودائع", "فائدة ودائع", "عوائد ودائع", "عائد ودائع",
    "عوائد استثمار", "عائد استثمار", "أرباح استثمار", "ارباح استثمار",
    "أرباح محافظ", "حصص الشركات", "حصة الشركات", "أرباح بيع أصول",
    "مكاسب", "dividend", "investment income", "gain on", "share of profit",
]
IFRS18_FINANCING_PATTERNS = [
    "فوائد", "فوايد", "فائدة", "مصاريف تمويل", "تكاليف تمويل",
    "مصاريف تمويلية", "مصروفات تمويلية", "تكاليف استدانة",
    "interest", "finance cost", "borrowing",
]


def _classify_ifrs18(label: str) -> str | None:
    """IFRS 18 category bucket for an income-statement item, or None.

    Only called for accounts the generic classifier put in 'opex' or
    'other', so named buckets (payables, equity, cash, ...) are never
    overridden. Priority: taxes > investing > financing (matches the
    IFRS 18 face order and keeps 'فوائد ودائع' (deposit returns) in the
    investing category while generic interest lands in financing).
    """
    low = label.lower().strip()
    if any(p in low for p in IFRS18_VAT_PATTERNS):
        return None
    if any(p in low for p in IFRS18_TAX_PATTERNS):
        return "tax_expense"
    if any(p in low for p in IFRS18_INVESTING_PATTERNS):
        return "investment_income"
    if any(p in low for p in IFRS18_FINANCING_PATTERNS):
        return "finance_cost"
    return None

BUCKET_LABELS = {
    "accumulated_depr": {"ar": "مجمع الإهلاك", "en": "Accumulated Depreciation"},
    "revenue": {"ar": "الإيرادات", "en": "Revenue"},
    "cogs": {"ar": "تكلفة المبيعات", "en": "Cost of Sales"},
    "opex": {"ar": "المصاريف التشغيلية", "en": "Operating Expenses"},
    "finance_cost": {"ar": "مصاريف التمويل", "en": "Finance Costs"},
    "investment_income": {"ar": "عوائد الاستثمار", "en": "Investment Income"},
    "tax_expense": {"ar": "الزكاة وضريبة الدخل", "en": "Zakat & Income Tax"},
    "cash": {"ar": "النقدية والبنوك", "en": "Cash & Banks"},
    "receivables": {"ar": "المدينون", "en": "Receivables"},
    "inventory": {"ar": "المخزون", "en": "Inventory"},
    "fixed_assets": {"ar": "الأصول الثابتة", "en": "Fixed Assets"},
    "payables": {"ar": "الدائنون", "en": "Payables"},
    "loans": {"ar": "القروض", "en": "Loans"},
    "equity": {"ar": "حقوق الملكية", "en": "Equity"},
    "other": {"ar": "بنود أخرى", "en": "Other"},
    "other_liab": {"ar": "بنود أخرى (دائنة)", "en": "Other (credit)"},
}

BS_ASSETS = ["cash", "receivables", "inventory", "fixed_assets", "other"]
BS_LIAB = ["payables", "loans"]
# Accumulated depreciation is a contra-asset (credit balance) — handled apart.
CONTRA_ASSET = "accumulated_depr"
# 'other' sits on the asset side of the BS, so it nets debit-minus-credit;
# a net-credit 'other' shows as a negative asset and keeps the identity.
DEBIT_NATURE = {"cash", "receivables", "inventory", "fixed_assets", "other", "cogs", "opex",
                "finance_cost", "tax_expense"}


def _classify(account: str) -> str:
    low = account.lower().strip()
    # Deferred (unearned) revenue CONTAINS a revenue word but is a LIABILTY
    # — booking it as income overstated revenue and broke the statements.
    if any(p in low for p in ("مؤجل", "مؤجلة", "unearned revenue",
                              "deferred revenue")):
        return "payables"
    for bucket, patterns in ACCOUNT_RULES:
        for pattern in patterns:
            if pattern in low:
                return bucket
    return "other"


def _to_number(value) -> float:
    """Parse a cell into a number, handling accounting notation:
    parentheses = negative, currency symbols/commas/spaces ignored,
    dashes used for empty cells = 0."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    negative = False
    # accounting parentheses: (1,250) -> -1250
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    # a lone dash (em/en/hyphen) means an empty balance
    if re.fullmatch(r"[\u2013\u2014\u2212-]+", text):
        return 0.0
    match = NUM_RE.search(text)
    if not match:
        return 0.0
    value = float(match.group(0).replace(",", ""))
    return -value if negative else value


SECTION_CODE_RE = re.compile(r"\b[A-Z]{1,3}\d{1,6}\b")
# Account-code token anywhere in the row (AT1104010001, LT2202, XT620116...).
CODE_RE = re.compile(r"\b([A-Za-z]{1,3}\d{2,})\b")
# Standard chart-of-account section prefixes (assets AT, liabilities LT,
# revenue RT, costs MT/CT, expenses XT) — leaf rows keep these prefixes.
KEEP_PREFIXES = ("AT", "LT", "RT", "MT", "CT", "XT")


def _has_section_code(texts: list) -> bool:
    """True when any cell carries a short section code (AT11, LT2202, MT5102…)
    whose prefix is NOT one of the standard leaf prefixes.

    Chart-of-account section header/total rows repeat their children's
    totals; leaf accounts always carry longer codes (AT1104010001) which do
    NOT match (no word boundary mid-number).
    """
    for t in texts:
        match = SECTION_CODE_RE.search(t)
        if match and not match.group(0).startswith(KEEP_PREFIXES):
            return True
    return False


def _looks_like_total(label: str) -> bool:
    """Section/grand total markers. Deliberately excludes the bare word
    'جمع'/'sum': 'مجمع اهلاك' (accumulated depreciation) contains 'جمع' and
    must never be treated as a total row."""
    low = label.lower().strip()
    return any(
        w in low
        for w in (
            "مجموع", "إجمالي", "الاجمالي", "اجمالي", "فرق",
            "total", "balance check", "difference",
        )
    )


def _pick_label(row, skip_idx: set[int]) -> str:
    """Best account-name cell among non-amount columns.

    Real TBs often carry a code column next to the name column; prefer the
    Arabic/longest text cell and demote pure codes like 'AT1104010001'.
    """
    best_score: tuple = None
    best: str = ""
    for i, c in enumerate(row):
        if i in skip_idx:
            continue
        text = str(c or "").strip()
        if not text or text in {"__________________", "-", "—"}:
            continue
        has_arabic = any("\u0600" <= ch <= "\u06ff" for ch in text)
        is_code = bool(re.fullmatch(r"[A-Za-z]{1,6}[\dA-Za-z\-]*", text)) and any(
            ch.isdigit() for ch in text
        )
        score = ((2 if has_arabic else 0) - (5 if is_code else 0), len(text))
        if best_score is None or score > best_score:
            best_score, best = score, text
    return best


def _find_debit_credit_cols(tb_rows: list) -> tuple[int, int] | None:
    """Locate debit/credit columns from a header row (مدين / دائن).

    Real trial balances carry extra columns (account code, name, balance,
    budget...) — reading the header is the only exact way to pick the right
    two. Exact cell match first (a data row like 'المدينون' must never match),
    then substring as a last resort.
    """
    for pass_substring in (False, True):
        for row in tb_rows[:10]:
            cells = [str(c or "").strip().lower() for c in row]
            d_idx = c_idx = None
            for i, cell in enumerate(cells):
                if pass_substring:
                    hit_d = "مدين" in cell and "مدينون" not in cell or "debit" in cell
                    hit_c = "دائن" in cell or "credit" in cell
                else:
                    hit_d = cell in {"مدين", "debit", "مديون"}
                    hit_c = cell in {"دائن", "credit", "دائنة"}
                if hit_d and d_idx is None:
                    d_idx = i
                if hit_c and c_idx is None:
                    c_idx = i
            if pass_substring and (d_idx == 0 or c_idx == 0):
                # amount columns never sit first; a match at index 0 is an
                # account name like 'الدائنون - الموردون', not a header cell
                d_idx = c_idx = None
                continue
            if d_idx is not None and c_idx is not None and d_idx != c_idx:
                return d_idx, c_idx
    return None


def _row_code(row) -> str:
    """First account-code-looking token in the row ('' when none)."""
    for cell in row:
        m = CODE_RE.search(str(cell or ""))
        if m:
            return m.group(1).upper()
    return ""


def _is_depreciation(account: str) -> bool:
    low = account.lower()
    return any(p in low for p in DEPRECIATION_PATTERNS)


def _lines(rows: list[dict]) -> list[dict]:
    return [
        {"account": r["account"], "amount": round(r["net"], 2),
         "depreciation": r.get("depreciation", False)}
        for r in rows
    ]


def build_statements(tb_rows: list[list], standard: str = "ifrs") -> dict:
    """Build the full statements from a trial balance.

    ``standard`` selects the accounting framework shown in statement titles:
    "ifrs" (المعايير الدولية للتقارير المالية) or "socpa" (الهيئة السعودية
    للمراجعين والمحاسبين — المعايير السعودية). It only affects presentation
    (titles/disclosure note), not the arithmetic.

    Real trial balances are hierarchical: detail (leaf) accounts plus main /
    sub / aggregate rows that repeat their children's totals. Only detail
    rows may be summed, so build_statements runs two passes:

      1. collect every amount-bearing row that is not explicitly marked as a
         total ("إجمالي", section codes, ...),
      2. structurally drop aggregate rows: a row whose account code is a
         strict prefix of other rows' codes AND whose amounts either equal a
         child's amounts (grouped total) or equal the sum of its children
         (section total). Detail accounts whose code merely *looks* like a
         prefix (XT6201160001 under XT62011600010) survive because their
         amounts do not match.

    Debit-nature buckets net = debit - credit; credit-nature = credit - debit.
    """
    cols = _find_debit_credit_cols(tb_rows)

    # ---------------- pass 1: candidate rows ----------------
    candidates: list[dict] = []
    marker_skipped = 0
    aggregate_labels: list[str] = []

    for row in tb_rows:
        cells = [c for c in row if c is not None and str(c).strip() != ""]
        if len(cells) < 2:
            continue
        if cols is not None:
            d_idx, c_idx = cols
            if d_idx >= len(row) or c_idx >= len(row):
                continue
            texts = [
                str(c or "").strip()
                for i, c in enumerate(row)
                if i not in (d_idx, c_idx) and str(c or "").strip()
                and str(c).strip() not in {"__________________", "-", "—"}
            ]
            # a total/subtotal row may carry its marker in ANY text cell;
            # section header/total rows carry a short section code.
            if any(_looks_like_total(t) for t in texts) or _has_section_code(texts):
                marker_skipped += 1
                if texts:
                    aggregate_labels.append(texts[0][:60])
                continue
            label = _pick_label(row, {d_idx, c_idx})
            if not label:
                continue
            debit = _to_number(row[d_idx])
            credit = abs(_to_number(row[c_idx]))
        else:
            # No header row: positional read — the first two numeric columns
            # are debit then credit ([account, debit, credit] convention).
            # Ranking by magnitude would misread [name, 0, 1_000_000] (a
            # credit row) as a 1M debit.
            numbers_probe = [
                i for i, c in enumerate(row)
                if c is not None and NUM_RE.search(str(c)) and "%" not in str(c)
            ]
            label = _pick_label(row, set(numbers_probe))
            if not label or _looks_like_total(label):
                if label:
                    marker_skipped += 1
                    aggregate_labels.append(label[:60])
                continue
            if len(numbers_probe) >= 2:
                d_i, c_i = numbers_probe[0], numbers_probe[1]
                debit = _to_number(row[d_i])
                credit = abs(_to_number(row[c_i]))
            elif numbers_probe:
                # single balance column: positive = debit, negative = credit
                value = _to_number(row[numbers_probe[0]])
                debit, credit = (value, 0.0) if value >= 0 else (0.0, -value)
            else:
                continue
            debit, credit = abs(debit), abs(credit)

        if debit == 0.0 and credit == 0.0:
            continue
        candidates.append({
            "account": label,
            "code": _row_code(row),
            "debit": debit,
            "credit": credit,
        })

    # ---------------- pass 2: structural hierarchy filter ----------------
    # Deepest codes first so intermediate aggregates are flagged before
    # their parents sum the remaining detail rows.
    ordered = sorted(candidates, key=lambda c: len(c["code"]), reverse=True)
    for cand in ordered:
        code = cand["code"]
        if not code:
            continue
        children = [
            c for c in candidates
            if c is not cand and c["code"].startswith(code)
            and len(c["code"]) > len(code) and not c.get("aggregate")
        ]
        if not children:
            continue
        same_amounts = any(
            (round(c["debit"], 2), round(c["credit"], 2))
            == (round(cand["debit"], 2), round(cand["credit"], 2))
            for c in children
        )
        sums_match = (
            abs(cand["debit"] - sum(c["debit"] for c in children))
            <= max(1.0, 0.02 * cand["debit"])
            and abs(cand["credit"] - sum(c["credit"] for c in children))
            <= max(1.0, 0.02 * cand["credit"])
        )
        if same_amounts or sums_match:
            cand["aggregate"] = True
            aggregate_labels.append(cand["account"][:60])

    detail_rows = [c for c in candidates if not c.get("aggregate")]
    code_levels: dict[str, int] = {}
    for c in detail_rows:
        if c["code"]:
            key = str(len(c["code"]))
            code_levels[key] = code_levels.get(key, 0) + 1
    hierarchy = {
        "detail_rows": len(detail_rows),
        "aggregate_rows": marker_skipped + len(candidates) - len(detail_rows),
        "aggregate_labels": aggregate_labels[:15],
        "code_levels": dict(sorted(code_levels.items())),
    }

    buckets: dict[str, list[dict]] = {}
    total_debit = total_credit = 0.0
    for cand in detail_rows:
        label = cand["account"]
        debit = cand["debit"]
        credit = cand["credit"]
        total_debit += debit
        total_credit += credit

        bucket = _classify(label)
        if bucket in ("opex", "other", "loans", "cash"):
            # IFRS 18: pull income-statement items out of the generic pools
            # and out of interest-flavoured balances the generic rules
            # swallowed (e.g. «فوائد قروض» is finance cost, not the loan).
            bucket = _classify_ifrs18(label) or bucket
        if bucket == CONTRA_ASSET:
            # credit balance with its own bucket (net = credit - debit)
            net = credit - debit
        else:
            net = debit - credit if bucket in DEBIT_NATURE else credit - debit
        buckets.setdefault(bucket, []).append({
            "account": label,
            "debit": debit,
            "credit": credit,
            "net": net,
            "depreciation": bucket == "opex" and _is_depreciation(label),
        })

    def _amount(bucket: str) -> float:
        """Signed bucket total.

        Each row's net is already stored with the correct side (debit-nature
        buckets debit-positive, credit-nature buckets credit-positive), so
        the plain sum preserves the accounting identity: when the trial
        balance balances, assets = liabilities + equity (incl. net profit)
        holds by pure arithmetic.
        """
        rows = buckets.get(bucket, [])
        if not rows:
            return 0.0
        return sum(r["net"] for r in rows)

    # ================= 1. Income statement (IFRS 18) =================
    revenue = _amount("revenue")
    cogs = _amount("cogs")
    opex_rows = buckets.get("opex", [])
    opex = _amount("opex")
    depr_total = sum(r["net"] for r in opex_rows if r.get("depreciation"))
    gross = revenue - cogs
    # IFRS 18 (effective 1 Jan 2027): the five categories and the defined
    # subtotals. Operating = gross − opex; the investing/financing/tax
    # categories adjust it to net profit. Without such items the face
    # reduces to the classic five-line statement (net = gross − opex).
    investment_income = _amount("investment_income")
    finance_cost = _amount("finance_cost")
    tax_expense = _amount("tax_expense")
    operating = gross - opex
    before_fin_tax = operating + investment_income - finance_cost
    net = before_fin_tax - tax_expense

    income_lines = [
        {"ar": "الإيرادات", "en": "Revenue", "amount": round(revenue, 2),
         "category": "operating"},
        {"ar": "تكلفة المبيعات", "en": "Cost of Sales", "amount": round(-cogs, 2),
         "category": "operating"},
        {"ar": "الربح الإجمالي", "en": "Gross Profit", "amount": round(gross, 2),
         "bold": True, "category": "operating"},
        {"ar": "المصاريف التشغيلية", "en": "Operating Expenses", "amount": round(-opex, 2),
         "category": "operating"},
        {"ar": "الربح التشغيلي", "en": "Operating Profit", "amount": round(operating, 2),
         "bold": True, "category": "operating"},
    ]
    if investment_income:
        income_lines.append({
            "ar": "عوائد الاستثمار", "en": "Investment Income",
            "amount": round(investment_income, 2), "category": "investing",
        })
    if finance_cost:
        income_lines.append({
            "ar": "مصاريف التمويل", "en": "Finance Costs",
            "amount": round(-finance_cost, 2), "category": "financing",
        })
    if investment_income or finance_cost:
        income_lines.append({
            "ar": "الربح قبل التمويل والضرائب",
            "en": "Profit before Financing and Income Taxes",
            "amount": round(before_fin_tax, 2), "bold": True,
            "category": "financing",
        })
    if tax_expense:
        income_lines.append({
            "ar": "الزكاة وضريبة الدخل", "en": "Zakat and Income Tax",
            "amount": round(-tax_expense, 2), "category": "taxes",
        })
    # an honest face: a NEGATIVE net is a loss — the label must say so,
    # no statement may read «صافي الربح» beside −935,317.
    income_lines.append({
        "ar": ("صافي الربح" if net >= 0 else "صافي الخسارة"),
        "en": ("Net Profit" if net >= 0 else "Net Loss"),
        "amount": round(net, 2), "bold": True,
        "is_loss": net < 0,
    })

    income_statement = {
        "lines": income_lines,
        "totals": {
            "revenue": round(revenue, 2),
            "gross_profit": round(gross, 2),
            "opex": round(opex, 2),
            "operating_profit": round(operating, 2),
            "net_profit": round(net, 2),
            **({"investment_income": round(investment_income, 2)} if investment_income else {}),
            **({"finance_cost": round(finance_cost, 2)} if finance_cost else {}),
            **({"tax_expense": round(tax_expense, 2)} if tax_expense else {}),
            **({"profit_before_financing_taxes": round(before_fin_tax, 2)}
               if (investment_income or finance_cost) else {}),
        },
        "ifrs18": {
            "applied": bool(investment_income or finance_cost or tax_expense),
            "categories": ["operating", "investing", "financing", "taxes"],
            "note": {
                "ar": "صُنّفت بنود قائمة الدخل وفق فئات IFRS 18 (تشغيلية/استثمارية/تمويلية/ضرائب) "
                      "وأُبرز الربح التشغيلي والربح قبل التمويل والضرائب — إعدادًا لسريانه إلزاميًا من 1 يناير 2027",
                "en": "Income statement items are classified per IFRS 18 categories "
                      "(operating/investing/financing/taxes) with the defined subtotals "
                      "Operating profit and Profit before financing and income taxes — "
                      "in preparation for IFRS 18 becoming mandatory on 1 January 2027",
            },
        },
        "detail": {
            "revenue": _lines(buckets.get("revenue", [])),
            "cogs": _lines(buckets.get("cogs", [])),
            "opex": _lines(opex_rows),
            **({"investment_income": _lines(buckets["investment_income"])} if buckets.get("investment_income") else {}),
            **({"finance_cost": _lines(buckets["finance_cost"])} if buckets.get("finance_cost") else {}),
            **({"tax_expense": _lines(buckets["tax_expense"])} if buckets.get("tax_expense") else {}),
        },
    }

    # ================= 2. Statement of financial position =================
    assets = {b: round(_amount(b), 2) for b in BS_ASSETS}
    liab = {b: round(_amount(b), 2) for b in BS_LIAB}
    # Unclassified accounts ('other') split by balance side: debit balances
    # stay under Other Assets, credit balances move to Other Liabilities —
    # a named-supplier credit account must not show as a negative asset.
    other_rows = buckets.get("other", [])
    other_pos = round(sum(r["net"] for r in other_rows if r["net"] > 0), 2)
    other_neg = round(sum(r["net"] for r in other_rows if r["net"] < 0), 2)
    assets["other"] = other_pos
    liab["other"] = round(-other_neg, 2)
    # Accumulated depreciation (its own contra-asset bucket) reduces fixed
    # assets on the face of the BS. When the TB has no such account, fall
    # back to the opex depreciation rows (dep expense) for the deduction.
    accum_depr = round(_amount(CONTRA_ASSET), 2)
    # Only the accumulated-depreciation (contra-asset) balance reduces fixed
    # assets on the BS face. Falling back to the depreciation EXPENSE here
    # would double-count it (it already reduced net profit) and break the
    # balance-sheet identity.
    if accum_depr:
        assets["fixed_assets"] = round(assets["fixed_assets"] - accum_depr, 2)
    total_assets = round(sum(assets.values()), 2)
    total_liab = round(sum(liab.values()), 2)

    # ================= 4. Equity (needed before BS totals) =================
    eq_rows = buckets.get("equity", [])
    capital = sum(r["net"] for r in eq_rows if any(p in r["account"].lower() for p in CAPITAL_PATTERNS))
    reserves = sum(r["net"] for r in eq_rows if any(p in r["account"].lower() for p in RESERVE_PATTERNS))
    retained = sum(
        r["net"] for r in eq_rows
        if any(p in r["account"].lower() for p in RETAINED_PATTERNS)
        and not any(p in r["account"].lower() for p in CAPITAL_PATTERNS)
    )
    opening_equity = round(capital + reserves + retained, 2)
    total_equity = round(opening_equity + net, 2)

    equity_statement = {
        "lines": [
            {"ar": "رأس المال المدفوع", "en": "Paid-in capital", "amount": round(capital, 2)},
            {"ar": "الاحتياطيات", "en": "Reserves", "amount": round(reserves, 2)},
            {"ar": "الأرباح المبقاة (أرصدة افتتاحية)", "en": "Retained earnings (opening)", "amount": round(retained, 2)},
            {"ar": ("صافي ربح الفترة" if net >= 0 else "صافي خسارة الفترة"),
             "en": "Net profit for the period", "amount": round(net, 2),
             "bold": True, "is_loss": net < 0},
        ],
        "total": total_equity,
    }

    liab_equity_total = round(total_liab + total_equity, 2)

    balance_sheet = {
        "assets": {
            "lines": [
                {**BUCKET_LABELS[b], "amount": assets[b]}
                for b in BS_ASSETS if assets[b]
            ],
            "detail": {
                b: _lines([r for r in buckets.get(b, []) if b != "other" or r["net"] > 0])
                for b in BS_ASSETS if buckets.get(b)
            },
            "total": total_assets,
        },
        "liabilities_equity": {
            "lines": [
                {**(BUCKET_LABELS["other_liab"] if b == "other" else BUCKET_LABELS[b]),
                 "amount": liab[b]}
                for b in BS_LIAB if liab[b]
            ] + [
                {"ar": "حقوق الملكية", "en": "Equity",
                 "amount": total_equity, "bold": True},
            ],
            "detail": {
                b: _lines([r for r in buckets.get(b, []) if b != "other" or r["net"] < 0])
                for b in BS_LIAB if buckets.get(b)
            },
            "total": liab_equity_total,
        },
        "balanced": abs(total_assets - liab_equity_total) < 0.01,
        "difference": round(total_assets - liab_equity_total, 2),
    }

    # ================= 3. Cash flow statement =================
    # Depreciation is non-cash: add the expense back once. Working-capital
    # changes use the BS amounts AFTER the accumulated-depreciation deduction.
    depr_addback = round(depr_total, 2)
    operating_lines = [
        {"ar": "صافي الربح", "en": "Net profit", "amount": round(net, 2)},
        {"ar": "إضافة: الإهلاك (مصروف غير نقدي)", "en": "Add: depreciation (non-cash)",
         "amount": depr_addback},
        {"ar": "التغير في المدينون", "en": "Change in receivables",
         "amount": round(-assets["receivables"], 2)},
        {"ar": "التغير في المخزون", "en": "Change in inventory",
         "amount": round(-assets["inventory"], 2)},
        {"ar": "التغير في الدائنون", "en": "Change in payables",
         "amount": round(liab["payables"], 2)},
    ]
    operating_total = round(
        net + depr_addback - assets["receivables"] - assets["inventory"] + liab["payables"], 2
    )
    # investing uses the gross fixed-asset cost (the TB figure), not the net
    # of accumulated depreciation, since the depreciation add-back already
    # neutralises the non-cash part in operating activities.
    gross_fixed = round(assets["fixed_assets"] + accum_depr, 2)
    investing_total = round(-gross_fixed, 2)
    financing_total = round(liab["loans"] + capital + reserves + retained, 2)
    # A single-period TB carries closing balances, not movements: accumulated
    # depreciation, unclassified accounts and opening balances surface as a
    # residual. Disclose it explicitly so the statement ties to cash.
    other_adjustment = round(
        assets["cash"] - (operating_total + investing_total + financing_total), 2
    )
    if abs(other_adjustment) >= 0.01:
        operating_lines.append({
            "ar": "تسوية: بنود أخرى وأرصدة افتتاحية",
            "en": "Other items & opening balances adjustment",
            "amount": other_adjustment,
        })
        operating_total = round(operating_total + other_adjustment, 2)
    net_change = round(operating_total + investing_total + financing_total, 2)
    cash_balance = round(assets["cash"], 2)

    cash_flow = {
        "operating": {
            "label": {"ar": "التدفقات من الأنشطة التشغيلية", "en": "Cash flows from operating activities"},
            "lines": operating_lines,
            "total": operating_total,
        },
        "investing": {
            "label": {"ar": "التدفقات من الأنشطة الاستثمارية", "en": "Cash flows from investing activities"},
            "lines": [
                {"ar": "شراء أصول ثابتة", "en": "Purchase of fixed assets",
                 "amount": investing_total},
            ],
            "total": investing_total,
        },
        "financing": {
            "label": {"ar": "التدفقات من الأنشطة التمويلية", "en": "Cash flows from financing activities"},
            "lines": [
                {"ar": "صافي القروض", "en": "Net loans", "amount": round(liab["loans"], 2)},
                {"ar": "حقوق الملكية (رأس مال واحتياطيات)", "en": "Equity (capital & reserves)",
                 "amount": round(capital + reserves + retained, 2)},
            ],
            "total": financing_total,
        },
        "net_change_label": {"ar": "صافي التغير في النقدية", "en": "Net change in cash"},
        "net_change": net_change,
        "cash_balance": cash_balance,
        "reconciles": abs(net_change - cash_balance) < 0.01,
    }

    # ================= 5. Notes to the financial statements =================
    detail_notes = []
    note_specs = [
        ("cash", "النقدية والبنوك", "Cash & banks"),
        ("receivables", "المدينون", "Receivables"),
        ("inventory", "المخزون", "Inventory"),
        ("fixed_assets", "الأصول الثابتة", "Fixed Assets"),
        ("payables", "الدائنون", "Payables"),
        ("loans", "القروض", "Loans"),
        ("revenue", "الإيرادات", "Revenue"),
        ("cogs", "تكلفة المبيعات", "Cost of Sales"),
        ("opex", "المصاريف التشغيلية", "Operating Expenses"),
        ("finance_cost", "مصاريف التمويل", "Finance Costs"),
        ("investment_income", "عوائد الاستثمار", "Investment Income"),
        ("tax_expense", "الزكاة وضريبة الدخل", "Zakat & Income Tax"),
        ("equity", "حقوق الملكية", "Equity"),
    ]
    for i, (bucket, ar, en) in enumerate(note_specs, 3):
        rows = buckets.get(bucket)
        if not rows:
            continue
        detail_notes.append({
            "no": i,
            "ar": ar,
            "en": en,
            "lines": _lines(rows),
        })

    notes = [
        {
            "no": 1,
            "ar": "أساس الإعداد",
            "en": "Basis of preparation",
            "text_ar": "أُعدت هذه القوائم من ميزان المراجعة المرفق وفق أساس الاستحقاق، وصُنفت الحسابات آلياً إلى بنود القوائم.",
            "text_en": "These statements were prepared from the attached trial balance on the accrual basis; accounts were classified automatically.",
        },
        {
            "no": 2,
            "ar": "تصنيف بنود قائمة الدخل وفق IFRS 18",
            "en": "Income statement classification per IFRS 18",
            "text_ar": "صُنّفت بنود قائمة الدخل إلى فئات IFRS 18 (تشغيلية/استثمارية/تمويلية/ضرائب) "
                       "وأُبرز الربح التشغيلي والربح قبل التمويل والضرائب، إعدادًا لسريان IFRS 18 إلزاميًا من 1 يناير 2027.",
            "text_en": "Income statement items are classified into the IFRS 18 categories "
                       "(operating/investing/financing/taxes) with the defined subtotals, in "
                       "preparation for IFRS 18 becoming mandatory on 1 January 2027.",
        },
        *detail_notes,
        {
            "no": len(detail_notes) + 3,
            "ar": "فحوص التوازن",
            "en": "Balance checks",
            "text_ar": (
                f"ميزان المراجعة: مدين {total_debit:,.2f} / دائن {total_credit:,.2f} "
                + ("متوازن ✓" if abs(total_debit - total_credit) < 0.01 else "غير متوازن ⚠")
                + f" — المركز المالي: أصول {total_assets:,.2f} مقابل التزامات وحقوق ملكية {liab_equity_total:,.2f} "
                + ("متوازن ✓" if balance_sheet["balanced"] else "غير متوازن ⚠")
            ),
            "text_en": (
                f"Trial balance: Dr {total_debit:,.2f} / Cr {total_credit:,.2f} "
                + ("balanced ✓" if abs(total_debit - total_credit) < 0.01 else "UNBALANCED ⚠")
                + f" — Financial position: assets {total_assets:,.2f} vs liabilities+equity {liab_equity_total:,.2f} "
                + ("balanced ✓" if balance_sheet["balanced"] else "UNBALANCED ⚠")
            ),
        },
    ]

    std_name = {
        "ifrs": {"ar": "وفق المعايير الدولية للتقارير المالية (IFRS)",
                 "en": "In accordance with IFRS"},
        "socpa": {"ar": "وفق معايير الهيئة السعودية للمراجعين والمحاسبين (SOCPA)",
                  "en": "In accordance with SOCPA standards"},
    }.get(standard if standard in ("ifrs", "socpa") else "ifrs")

    return {
        "standard": std_name,
        "trial_balance": {
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "balanced": abs(total_debit - total_credit) < 0.01,
            "hierarchy": hierarchy,
            "accounts": [
                {"account": r["account"], "debit": r["debit"], "credit": r["credit"]}
                for rows in buckets.values() for r in rows
            ],
        },
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
        "equity_statement": equity_statement,
        "notes": notes,
    }


def metrics_from_statements(statements: dict) -> dict[str, list[float]]:
    """Derive raw metrics from built statements so KPIs/ratios work on TB uploads."""
    isx = statements["income_statement"]["totals"]
    bs = statements["balance_sheet"]
    cf = statements["cash_flow"]
    assets_total = bs["assets"]["total"]
    liab_total = sum(
        ln["amount"] for ln in bs["liabilities_equity"]["lines"]
        if not ln.get("bold")
    )
    equity_total = statements["equity_statement"]["total"]
    cash = cf["cash_balance"]

    out = {
        "revenue": [isx["revenue"]],
        "cogs": [abs(next(ln["amount"] for ln in statements["income_statement"]["lines"]
                          if ln["en"] == "Cost of Sales"))],
        "gross_profit": [isx["gross_profit"]],
        "opex": [isx["opex"]],
        "net_profit": [isx["net_profit"]],
        "assets": [assets_total],
        "liabilities": [round(liab_total, 2)],
        "equity": [equity_total],
        "cash": [cash],
    }
    # IFRS 18 category items flow through so the KPI/audit derivations use
    # the full chain net = operating + investing − financing − taxes.
    for key in ("investment_income", "finance_cost", "tax_expense"):
        if key in isx:
            out[key] = [isx[key]]
    # Activity/liquidity balances from the built balance sheet: receivables
    # and inventory (turnover ratios) and the current-asset pool (current &
    # quick ratios). Missing buckets are simply absent — never guessed.
    bs_lines = {ln["en"]: ln["amount"] for ln in bs["assets"].get("lines", [])}
    for key, label in (("receivables", "Receivables"), ("inventory", "Inventory")):
        if label in bs_lines:
            out[key] = [bs_lines[label]]
    # Payables balance (working-capital cycle: payables turnover / DPO).
    liab_lines = {ln["en"]: ln["amount"] for ln in bs["liabilities_equity"].get("lines", [])}
    if "Payables" in liab_lines:
        out["payables"] = [liab_lines["Payables"]]
    if "cash" in out:
        current_pool = [out["cash"][0]]
        for key in ("receivables", "inventory"):
            if key in out:
                current_pool.append(out[key][0])
        out["current_assets"] = [round(sum(current_pool), 2)]
    return out


# =====================================================================
# Statements derived from multi-period captured metrics (United-style) -----
# =====================================================================
_PERIOD_NAME_AR = ("الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة")
_PERIOD_NAME_EN = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth")


def build_statements_from_metrics(metrics: dict,
                                  period_labels: list | None = None) -> dict | None:
    """Derive statements-shaped faces from multi-period metric series.

    Comparison files without a trial balance (the United-style capture:
    one metric value per year column) have no ``statements_json``, so the
    Excel workbook's statements sheet is skipped entirely. This builder
    reconstructs the SAME faces ``build_statements`` produces — income
    statement, statement of financial position, simplified cash flow — for
    EVERY period, composed from the metric series exactly as the platform
    defines them (expenses are positive magnitudes after sign normalisation;
    net follows the IFRS 18 chain).

    Requires at least two period values on the income-statement spine
    (revenue + cogs); single-period analyses keep the old behaviour. The
    derived dict carries ``"derived_from_metrics": True`` so callers can
    label it honestly (no trial balance, no notes/equity statement).
    Returns None when the capture cannot support a statement.
    """
    def series(concept: str) -> list[float]:
        vals = metrics.get(concept) or []
        return [float(v) for v in vals
                if isinstance(v, (int, float)) and not isinstance(v, bool)]

    rev_s = series("revenue")
    cogs_s = series("cogs")
    net_s = series("net_profit")
    if len(rev_s) < 2 or len(cogs_s) < 2:
        return None

    n = max(len(rev_s), len(cogs_s))
    # Balance-sheet and cash-flow-totals series END-ALIGN to the period grid:
    # a balance sheet / cash-flow statement carrying FEWER columns than the
    # income statement (US-GAAP: income 2023-2025, balance sheet 2024-2025)
    # has its LATEST value belong to the LATEST period — index-by-i would
    # miss it entirely and misread early values as late ones. Income-
    # statement spine concepts (revenue, cogs, opex…) stay LEFT-aligned: a
    # truncated series there means LATER periods are missing, never earlier
    # ones.
    balance_keys = {"cash", "inventory", "receivables", "payables",
                    "current_assets", "current_liabilities",
                    "assets", "liabilities", "equity",
                    "cf_operating", "cf_investing", "cf_financing",
                    "cf_other", "cf_net_change", "cf_cash_end"}
    periods: list[dict] = []
    for i in range(n):
        def val(concept: str) -> float | None:
            s = series(concept)
            if not s:
                return None
            if concept in balance_keys:
                k = i + len(s) - n
                return s[k] if 0 <= k < len(s) else None
            return s[i] if i < len(s) else None

        revenue = val("revenue")
        cogs = val("cogs")
        if revenue is None or cogs is None:
            continue  # an incomplete period is skipped, never guessed
        opex = val("opex")
        investment_income = val("investment_income")
        finance_cost = val("finance_cost")
        tax_expense = val("tax_expense")
        gross = revenue - cogs
        operating = gross - (opex or 0.0)
        before_fin_tax = operating + (investment_income or 0.0) - (finance_cost or 0.0)
        net = before_fin_tax - (tax_expense or 0.0)
        # a STATED bottom line outranks the chain for its period: OCR
        # misreads of the opex/tax/finance detail rows must not overwrite
        # the statement's own «ربح السنة» value (net_profit is an income-
        # statement spine concept — left-aligned like revenue/cogs)
        if i < len(net_s) and net_s[i] != 0.0:
            net = net_s[i]
        periods.append({
            "revenue": round(revenue, 2),
            "cogs": round(cogs, 2),
            "opex": opex,
            "investment_income": investment_income,
            "finance_cost": finance_cost,
            "tax_expense": tax_expense,
            "gross": round(gross, 2),
            "operating": round(operating, 2),
            "before_fin_tax": round(before_fin_tax, 2),
            "net": round(net, 2),
            "cash": val("cash"),
            "inventory": val("inventory"),
            "receivables": val("receivables"),
            "payables": val("payables"),
            "current_assets": val("current_assets"),
            "current_liabilities": val("current_liabilities"),
            "assets": val("assets"),
            "liabilities": val("liabilities"),
            "equity": val("equity"),
            "cf_operating": val("cf_operating"),
            "cf_investing": val("cf_investing"),
            "cf_financing": val("cf_financing"),
            "cf_other": val("cf_other"),
            "cf_net_change": val("cf_net_change"),
            "cf_cash_end": val("cf_cash_end"),
        })

    if len(periods) < 2:
        return None

    def fmt_period(i: int) -> dict:
        raw = ""
        if period_labels and i < len(period_labels):
            raw = str(period_labels[i]).strip()
        if raw:
            return {"ar": raw, "en": raw}
        ar = f"الفترة {_PERIOD_NAME_AR[i]}" if i < len(_PERIOD_NAME_AR) else f"الفترة {i + 1}"
        en = f"{_PERIOD_NAME_EN[i]} period" if i < len(_PERIOD_NAME_EN) else f"Period {i + 1}"
        return {"ar": ar, "en": en}

    def income_face(p: dict) -> list[dict]:
        lines = [
            {"ar": "الإيرادات", "en": "Revenue", "amount": p["revenue"],
             "category": "operating"},
            {"ar": "تكلفة المبيعات", "en": "Cost of Sales",
             "amount": round(-p["cogs"], 2), "category": "operating"},
            {"ar": "الربح الإجمالي", "en": "Gross Profit",
             "amount": p["gross"], "bold": True, "category": "operating"},
        ]
        if p["opex"] is not None:
            lines.append({"ar": "المصاريف التشغيلية", "en": "Operating Expenses",
                          "amount": round(-p["opex"], 2), "category": "operating"})
        lines.append({"ar": "الربح التشغيلي", "en": "Operating Profit",
                      "amount": p["operating"], "bold": True, "category": "operating"})
        if p["investment_income"]:
            lines.append({"ar": "عوائد الاستثمار", "en": "Investment Income",
                          "amount": round(p["investment_income"], 2),
                          "category": "investing"})
        if p["finance_cost"]:
            lines.append({"ar": "مصاريف التمويل", "en": "Finance Costs",
                          "amount": round(-p["finance_cost"], 2),
                          "category": "financing"})
        if p["investment_income"] or p["finance_cost"]:
            lines.append({"ar": "الربح قبل التمويل والضرائب",
                          "en": "Profit before Financing and Income Taxes",
                          "amount": p["before_fin_tax"], "bold": True,
                          "category": "financing"})
        if p["tax_expense"]:
            lines.append({"ar": "الزكاة وضريبة الدخل", "en": "Zakat and Income Tax",
                          "amount": round(-p["tax_expense"], 2), "category": "taxes"})
        lines.append({"ar": ("صافي الربح" if p["net"] >= 0
                             else "صافي الخسارة"),
                      "en": "Net Profit",
                      "amount": p["net"], "bold": True,
                      "is_loss": p["net"] < 0})
        return lines

    def bs_face(p: dict) -> dict:
        assets = {k: p[k] for k in ("cash", "receivables", "inventory")
                  if p[k] is not None}
        if p["assets"] is not None:
            named_assets = sum(assets.values())
            fixed = p["assets"] - named_assets
            if fixed > 0:
                assets["fixed_assets"] = round(fixed, 2)
            # when the named pool OVERSHOOTS the stated total, the stated
            # total is the corrupt read (an OCR truncation) — the named
            # components are the real captures and stand alone; fabricating
            # an «other» line from the discrepancy doubled the error.
        liab = {k: p[k] for k in ("payables",) if p[k] is not None}
        if p["liabilities"] is not None:
            named_liab = sum(liab.values())
            rest = p["liabilities"] - named_liab
            if rest > 0.005:
                liab["loans"] = round(rest, 2)  # long-term / other financing
            elif rest < -0.005:
                liab["other_liab"] = round(-rest, 2)
        equity = p["equity"]
        if equity is None:
            if p["assets"] is not None and p["liabilities"] is not None:
                equity = p["assets"] - p["liabilities"]
            else:
                eq_named = (p["current_assets"] or 0.0) - (p["current_liabilities"] or 0.0)
                equity = eq_named if eq_named else None
        liab_list = [
            {**BUCKET_LABELS["other_liab" if k == "other_liab" else k],
             "amount": round(v, 2)}
            for k, v in liab.items() if v
        ]
        if equity is not None:
            liab_list.append({"ar": "حقوق الملكية", "en": "Equity",
                              "amount": round(equity, 2), "bold": True})
        total_assets = round(sum(assets.values()), 2) if assets else None
        liab_eq_total = round(sum(ln["amount"] for ln in liab_list), 2) if liab_list else None
        return {
            "assets": {
                "lines": [{**BUCKET_LABELS[k], "amount": round(v, 2)}
                          for k, v in assets.items() if v],
                **({"total": total_assets} if total_assets is not None else {}),
            },
            "liabilities_equity": {
                "lines": liab_list,
                **({"total": liab_eq_total} if liab_eq_total is not None else {}),
            },
            **({"balanced": abs(total_assets - liab_eq_total) < 0.01,
                "difference": round(total_assets - liab_eq_total, 2)}
               if total_assets is not None and liab_eq_total is not None else {}),
        }

    def cash_face(p: dict, prev: dict | None) -> dict:
        """Statement of cash flows. The file's own STATED activity totals
        («Net cash from operations / investing / financing», captured as
        cf_operating/cf_investing/cf_financing) win when present — one line
        per activity, carrying the file's figure verbatim. Only files that
        don't state them fall back to the balance-delta composition (real
        working-capital deltas with a previous period; settled-in-cash zeros
        without one)."""
        def stated(concept: str, ar: str, en: str,
                   block_ar: str | None = None, block_en: str | None = None):
            v = p.get(concept)
            if v is None:
                return None
            return {
                # per-file honesty: the face marks the stated source
                # (the file's own figure, not a derived composition)
                "lines": [{"ar": f"{ar} (حسب الملف)",
                           "en": f"{en} (per file)",
                           "amount": round(v, 2)}],
                "total": round(v, 2),
                # the activity-heading exporters (Excel/PDF) print — keep the
                # block self-describing like the three activity blocks
                **({"label": {"ar": block_ar, "en": block_en}}
                   if block_ar and block_en else {}),
            }

        op_stated = stated("cf_operating",
                           "صافي التدفق من الأنشطة التشغيلية",
                           "Net cash from operating activities")
        inv_stated = stated("cf_investing",
                            "صافي التدفق من الأنشطة الاستثمارية",
                            "Net cash from investing activities")
        fin_stated = stated("cf_financing",
                            "صافي التدفق من الأنشطة التمويلية",
                            "Net cash from financing activities")
        # FX / other effects on cash («Effect of foreign exchange rates on
        # cash») — without them the stated activities never explain the
        # actual cash movement (US-GAAP statements carry this line precisely
        # to close that gap).
        other_stated = stated("cf_other",
                              "أثر العملات والبنود الأخرى على النقدية",
                              "Foreign-exchange and other effects",
                              "أثر العملات والبنود الأخرى",
                              "Foreign-exchange and other effects")
        other_total = other_stated["total"] if other_stated else 0.0

        operating_lines = [{"ar": ("صافي الربح" if p["net"] >= 0
                                   else "صافي الخسارة"),
                            "en": "Net profit",
                            "amount": p["net"]}]
        wc = 0.0
        if op_stated is None and prev is not None:
            for k, ar, en in (("receivables", "التغير في المدينون", "Change in receivables"),
                              ("inventory", "التغير في المخزون", "Change in inventory")):
                if p[k] is not None and prev[k] is not None:
                    delta = round(p[k] - prev[k], 2)
                    operating_lines.append({"ar": ar, "en": en, "amount": -delta})
                    wc += -delta
            if p["payables"] is not None and prev["payables"] is not None:
                delta = round(p["payables"] - prev["payables"], 2)
                operating_lines.append({"ar": "التغير في الدائنون",
                                        "en": "Change in payables", "amount": delta})
                wc += delta
        if op_stated is not None:
            operating_block = op_stated
            operating_total = op_stated["total"]
        else:
            operating_total = round(p["net"] + wc, 2)
            operating_block = {
                "lines": operating_lines,
                "total": operating_total,
            }
        investing_total = None
        financing_total = None
        # the closing-cash line shown on the face: the cash-flow statement's
        # OWN «Cash and cash equivalents, end of period» when the file states
        # it — the balance-sheet cash line is often WIDER («Total cash, cash
        # equivalents, and short-term investments») and never ties to the
        # statement's walk
        cash_balance = p["cf_cash_end"] \
            if p.get("cf_cash_end") is not None else p["cash"]
        blocks = [{
            "label": {"ar": "التدفقات من الأنشطة التشغيلية",
                      "en": "Cash flows from operating activities"},
            **operating_block,
        }]
        if prev is not None:
            investing_total = 0.0
            financing_total = 0.0
        if inv_stated is not None:
            investing_total = inv_stated["total"]
            investing_block = inv_stated
        else:
            investing_block = {"lines": [], "total": investing_total or 0.0}
        if fin_stated is not None:
            financing_total = fin_stated["total"]
            financing_block = fin_stated
        else:
            financing_block = {"lines": [], "total": financing_total or 0.0}
        blocks.extend([
            {"label": {"ar": "التدفقات من الأنشطة الاستثمارية",
                       "en": "Cash flows from investing activities"},
             **investing_block},
            {"label": {"ar": "التدفقات من الأنشطة التمويلية",
                       "en": "Cash flows from financing activities"},
             **financing_block},
        ])
        net_change = round(operating_total
                           + (investing_total or 0.0)
                           + (financing_total or 0.0)
                           + other_total, 2)
        # does the face explain the ACTUAL cash movement? The check is
        # meaningful only for the file's OWN stated face: a fully derived
        # composition (net profit + working-capital deltas, zeros for
        # investing/financing) never claims to explain the whole cash walk,
        # so a failed tie there is construction noise, not an «unbalanced»
        # verdict. Priority: the file's stated «Net change in cash» line,
        # then the CF closing-cash walk, then the balance-sheet cash delta
        # — a proxy whenever the BS cash line carries short-term
        # investments beyond the CF statement's scope.
        reconciles = None
        if any(p.get(k) is not None for k in
               ("cf_operating", "cf_investing", "cf_financing",
                "cf_other")):
            stated_net = p.get("cf_net_change")
            if stated_net is not None:
                reconciles = abs(net_change
                                 - round(stated_net, 2)) < 0.01
            elif p.get("cf_cash_end") is not None and prev is not None \
                    and prev.get("cf_cash_end") is not None:
                reconciles = abs(net_change
                                 - round(p["cf_cash_end"]
                                         - prev["cf_cash_end"], 2)) < 0.01
            elif p.get("cf_cash_end") is None and cash_balance is not None \
                    and prev is not None and prev.get("cash") is not None:
                reconciles = abs(net_change
                                 - round(cash_balance - prev["cash"], 2)) < 0.01
        return {
            "operating": blocks[0],
            "investing": blocks[1],
            "financing": blocks[2],
            **({"other": other_stated} if other_stated else {}),
            "net_change_label": {"ar": "صافي التغير في النقدية",
                                 "en": "Net change in cash"},
            "net_change": net_change,
            **({"cash_balance": round(cash_balance, 2)}
               if cash_balance is not None else {}),
            **({"reconciles": reconciles} if reconciles is not None else {}),
        }

    periods_out = []
    for i, p in enumerate(periods):
        prev = periods[i - 1] if i > 0 else None
        periods_out.append({
            "label": fmt_period(i),
            "income_statement": {
                "lines": income_face(p),
                "totals": {
                    "revenue": p["revenue"],
                    "cogs": p["cogs"],
                    "gross_profit": p["gross"],
                    "operating_profit": p["operating"],
                    "net_profit": p["net"],
                    **({"opex": round(p["opex"], 2)} if p["opex"] is not None else {}),
                    **({"investment_income": round(p["investment_income"], 2)}
                       if p["investment_income"] else {}),
                    **({"finance_cost": round(p["finance_cost"], 2)}
                       if p["finance_cost"] else {}),
                    **({"tax_expense": round(p["tax_expense"], 2)}
                       if p["tax_expense"] else {}),
                    **({"profit_before_financing_taxes": p["before_fin_tax"]}
                       if (p["investment_income"] or p["finance_cost"]) else {}),
                },
            },
            "balance_sheet": bs_face(p),
            "cash_flow": cash_face(p, prev),
            **{k: p[k] for k in ("cash", "receivables", "inventory", "payables",
                                 "current_assets", "current_liabilities",
                                 "assets", "liabilities", "equity",
                                 # the file's OWN stated activity figures —
                                 # the comparative grid reads them to show
                                 # each activity's net flow per period
                                 "cf_operating", "cf_investing",
                                 "cf_financing", "cf_other",
                                 "cf_net_change", "cf_cash_end")},
        })

    return {
        "derived_from_metrics": True,
        "period_labels": [fmt_period(i) for i in range(len(periods))],
        "periods": periods_out,
    }


# Comparative-grid row specs: (totals/balance key, ar, en, bold).
# Income keys read the per-period totals (positive magnitudes for costs,
# exactly as captured); the rest read the per-period balance snapshot.
_DERIVED_GRID_ROWS = (
    ("revenue", "الإيرادات", "Revenue", False),
    ("cogs", "تكلفة المبيعات", "Cost of Sales", False),
    ("gross_profit", "الربح الإجمالي", "Gross Profit", True),
    ("opex", "المصاريف التشغيلية", "Operating Expenses", False),
    ("operating_profit", "الربح التشغيلي", "Operating Profit", True),
    ("investment_income", "عوائد الاستثمار", "Investment Income", False),
    ("finance_cost", "مصاريف التمويل", "Finance Costs", False),
    ("profit_before_financing_taxes", "الربح قبل التمويل والضرائب",
     "Profit before Financing and Income Taxes", True),
    ("tax_expense", "الزكاة وضريبة الدخل", "Zakat and Income Tax", False),
    ("net_profit", "صافي الربح", "Net Profit", True),
    # net cash flow per activity — each activity's evolution across periods,
    # straight from the per-period cash-flow faces (stated figures win;
    # the composed operating line — net profit ± working-capital deltas —
    # is always real; composed investing/financing zeros stay OFF the grid:
    # they mean «nothing captured», and a wall of 0.0 would invent history)
    ("cf_operating", "صافي التدفق من الأنشطة التشغيلية",
     "Net cash from operating activities", True),
    ("cf_investing", "صافي التدفق من الأنشطة الاستثمارية",
     "Net cash from investing activities", True),
    ("cf_financing", "صافي التدفق من الأنشطة التمويلية",
     "Net cash from financing activities", True),
    ("cash", "النقدية والبنوك", "Cash & Banks", False),
    ("receivables", "المدينون", "Receivables", False),
    ("inventory", "المخزون", "Inventory", False),
    ("payables", "الدائنون", "Payables", False),
    ("current_assets", "الأصول المتداولة", "Current Assets", False),
    ("current_liabilities", "الالتزامات المتداولة", "Current Liabilities", False),
    ("assets", "إجمالي الأصول", "Total Assets", True),
    ("liabilities", "إجمالي الالتزامات", "Total Liabilities", False),
    ("equity", "حقوق الملكية", "Equity", True),
)
_IS_TOTALS_KEYS = frozenset(
    ("revenue", "cogs", "gross_profit", "opex", "operating_profit",
     "investment_income", "finance_cost", "profit_before_financing_taxes",
     "tax_expense", "net_profit")
)

# cash-flow grid rows read the per-period cash-flow faces' activity totals
_CF_GRID_KEYS = {"cf_operating": "operating", "cf_investing": "investing",
                 "cf_financing": "financing"}


def _derived_tb_stub(bs: dict) -> dict:
    """Honest TB-like verdict for a metrics-derived face: it owns no trial
    balance, so «balanced» reports the BS-face identity (assets vs L+E)
    instead of a constant True that could mask a gap in the file's own
    numbers. When neither total exists there is nothing to check — the
    pre-existing neutral-True behaviour is kept."""
    assets_total = (bs.get("assets") or {}).get("total")
    le_total = (bs.get("liabilities_equity") or {}).get("total")
    if assets_total is None or le_total is None:
        return {"balanced": True,
                "total_debit": assets_total, "total_credit": assets_total}
    balanced = abs(round(assets_total, 2) - round(le_total, 2)) < 0.01
    return {
        "balanced": balanced,
        "total_debit": assets_total,
        **({"total_credit": le_total} if not balanced else {}),
    }


def extend_derived_statements_for_export(st: dict) -> dict:
    """Give a metrics-derived statements dict the REAL-statements surface so
    the PDF/PPTX reports can render their statements section from it.

    The Excel export renders the derived shape natively (per-period faces +
    the comparative grid); the documents need a single face — so the LATEST
    period becomes the face, the previous period rides along as the honest
    «مقارنة بالفترة السابقة» evidence, and a TB-like accounts block is
    composed from the captured concepts so report.py's balance note works.
    Reports keep their existing ``if statements:`` gates untouched.
    """
    periods = st.get("periods") or []
    if not periods:
        return st
    last = periods[-1]
    prev = periods[-2] if len(periods) > 1 else None
    isx = last.get("income_statement") or {}
    lines_out = []
    prev_totals = (prev or {}).get("income_statement", {}).get("totals") or {}
    for ln in isx.get("lines") or []:
        out = dict(ln)
        en = str(ln.get("en") or "")
        prev_amount = None
        for pkey, pval in (("Revenue", "revenue"), ("Cost of Sales", "cogs"),
                           ("Operating Expenses", "opex"),
                           ("Investment Income", "investment_income"),
                           ("Finance Costs", "finance_cost"),
                           ("Zakat and Income Tax", "tax_expense")):
            if en == pkey and prev_totals.get(pval) is not None:
                sign = -1.0 if pval in ("cogs", "opex", "finance_cost", "tax_expense") \
                    else 1.0
                prev_amount = round(sign * prev_totals[pval], 2)
        if prev_amount is None and en in ("Gross Profit", "Operating Profit",
                                          "Net Profit"):
            pk = {"Gross Profit": "gross_profit", "Operating Profit": "operating_profit",
                  "Net Profit": "net_profit"}[en]
            if prev_totals.get(pk) is not None:
                prev_amount = round(prev_totals[pk], 2)
        if prev_amount is not None:
            out["prev"] = prev_amount
        lines_out.append(out)
    return {
        **st,
        "income_statement": {
            "lines": lines_out,
            "totals": isx.get("totals") or {},
        },
        "balance_sheet": last.get("balance_sheet") or {},
        "cash_flow": last.get("cash_flow") or {},
        "trial_balance": {
            "accounts": [],
            **_derived_tb_stub(last.get("balance_sheet") or {}),
        },
        "equity_statement": {
            "lines": [],
            "total": next((ln.get("amount") for ln in
                           ((last.get("balance_sheet") or {})
                            .get("liabilities_equity", {}).get("lines") or [])
                           if str(ln.get("en")) == "Equity"), None),
        },
    }


def _derived_comparative_grid(st: dict, lang: str):
    """Comparative grid over ALL derived periods: one row per concept,
    one column per period (headers = the file's own period labels).
    Returns (headers, rows, bold_row_indices); rows lacking any value
    are omitted — nothing is invented."""
    periods = st.get("periods") or []
    if len(periods) < 2:
        return [], [], set()
    labels = st.get("period_labels") or []
    headers = [
        (labels[i] or {}).get(lang) or (labels[i] or {}).get("en")
        or f"P{i + 1}" for i in range(len(periods))
    ]
    rows: list[list] = []
    bold: set[int] = set()
    for key, ar, en, is_bold in _DERIVED_GRID_ROWS:
        vals = []
        for p in periods:
            if key in _IS_TOTALS_KEYS:
                v = p["income_statement"]["totals"].get(key)
            elif key in _CF_GRID_KEYS:
                if p.get(key) is not None:
                    v = p.get(key)    # the file's OWN stated activity figure
                elif key == "cf_operating":
                    # composed operating line is always real arithmetic
                    # (net profit ± working-capital deltas)
                    v = ((p.get("cash_flow") or {}).get("operating")
                         or {}).get("total")
                else:
                    v = None          # nothing captured — never invent 0.0
            else:
                v = p.get(key)
            vals.append(round(v, 2) if isinstance(v, (int, float))
                        and not isinstance(v, bool) else None)
        if not any(v is not None for v in vals):
            continue  # concept absent from this capture entirely
        label = {"ar": ar, "en": en}
        rows.append([label.get(lang) or en] + vals)
        if is_bold:
            bold.add(len(rows) - 1)
    return headers, rows, bold
