"""Financial analysis engine.

Extracts key performance indicators, financial ratios, trends and a simple
linear-regression forecast from generic tabular/textual content produced by
the parsers.

Values are read from the numeric cells to the RIGHT of a recognised label.
Summary/computed rows (مجمل الربح، الربح الإجمالي، الإجمالي، ...مجموع) are
excluded from raw metric capture — they are re-derived in compute_kpis — so
single-column P&L sheets keep their true numbers instead of percentages.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone

# leading/trailing digit-group fragments glued to OCR-noise letter runs:
# «19 575585 ا» → 575585 (the letter tail would truncate NUM_RE to 19)
# — used to HEAL cells from the OCR path (never text-layer extractions)
_FRAG_DIGITS_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:[ ,]\d{3})+)(?![\d.])")
# a pure digit token, optionally with thousands commas («1872», «575585», «2,225»)
_DIGIT_TOKEN_RE = re.compile(r"^\d+(?:,\d{3})*$")


def _heal_glued_digits(value: str) -> str:
    """Return `value` with swallowed-comma digit groups rejoined.

    OCR splits an amount across boxes with a space: the classifier's
    NUM_RE then reads the FIRST fragment only («1872» of «1872 2 2 58»).
    Two passes:
    1. proper thousand-groupings split by stray spaces («19 575 585»),
       even with non-Arabic labels riding along;
    2. a cell made ONLY of digit tokens whose fragments total 6-14
       digits is one amount — join it («1872 2 2 58»→18722258,
       «19 575585»→19575585). Anything with letters riding along
       (dates: «31 ديسمبر 2023») or out of range stays untouched.
    Latin digits only.
    """
    if not value or not any("0" <= c <= "9" for c in value):
        return value
    if any("\u0600" <= c <= "\u06FF" for c in value):
        return value
    total = sum(
        len(m.group(1).replace(" ", "").replace(",", ""))
        for m in _FRAG_DIGITS_RE.finditer(value)
    )
    if 6 <= total <= 14:
        value = _FRAG_DIGITS_RE.sub(
            lambda m: m.group(1).replace(" ", "").replace(",", ""), value
        )
    # pass 2: ragged fragments — only when the cell is pure digit tokens
    tokens = value.split()
    if len(tokens) >= 2 and all(_DIGIT_TOKEN_RE.fullmatch(t) for t in tokens):
        total = sum(len(t.replace(",", "")) for t in tokens)
        if 6 <= total <= 14:
            return "".join(t.replace(",", "") for t in tokens)
    return value


NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# Period labels (years, quarters, months) used as column headers in financial
# statements. Captured per column so the report banner can show the REAL
# periods analysed (e.g. "2023 - 2024") instead of just counting columns.
_PERIOD_RE = re.compile(
    r"^(?:(?:19|20)\d{2})"                      # 2023
    r"|(?:Q[1-4])"                              # Q1..Q4
    r"|(?:الربع\s*(?:الأول|الثاني|الثالث|الرابع|[1-4]))"  # الربع الأول / الربع 3
    r"|(?:H[12])"                               # H1/H2
    r"|(?:يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*$",
    re.IGNORECASE,
)


def _normalize_period_labels(labels: list[str]) -> list[str]:
    """Dedupe and order a header sequence chronologically (oldest → latest).

    Merged header cells repeat a year twice («2025, 2025, 2024, 2024»), and
    US-GAAP layouts run years NEWEST-first — the year-sorted metric series
    need clean ascending labels to line up with them.
    """
    out: list[str] = []
    for lb in labels:
        if not out or lb != out[-1]:
            out.append(lb)
    if out and all(re.fullmatch(r"(?:19|20)\d{2}", lb) for lb in out):
        return [str(y) for y in sorted({int(lb) for lb in out})]
    seen: set[str] = set()
    return [lb for lb in out if not (lb in seen or seen.add(lb))]


def _extract_period_labels(tables: list) -> list[str]:
    """Collect period column headers (years/quarters/months) from tables.

    Looks at each table's first rows (headers) for year/quarter/month tokens;
    returns the longest consistent header sequence found (oldest → latest).
    """
    best: list[str] = []
    for table in tables:
        rows = table.get("rows") or []
        if not rows:
            continue
        for row in rows[:6]:  # headers live in the top rows — Word tables
            # carry lead-in rows («(In millions)» / blanks) ABOVE the real
            # header, so the scan must reach the same depth _year_columns uses
            labels = [
                str(c).strip()
                for c in row
                if isinstance(c, str) and _PERIOD_RE.fullmatch(str(c).strip())
            ]
            if not labels:
                # «عام 2024 (ريال)» / «FY2024» — years embedded in header text
                labels = []
                for c in row:
                    m = _YEAR_RE.search(str(c or ""))
                    if m:
                        labels.append(m.group(0))
            labels = _normalize_period_labels(labels)
            # keep sequences of >= 2 period labels (a single year could be
            # a document title, not a column header)
            if len(labels) >= 2 and len(labels) > len(best):
                best = labels
    return best[:12]

# Summary / aggregate rows: their numbers are derived from the detail rows
# (or are ratios like margins), so they must never be captured as raw values.
# opex is matched first so "إجمالي المصروفات" classifies as opex and is then
# allowed through via the _HAS_OWN_LABEL exception (its own natural title).
_SUMMARY_PATTERNS = [
    "مجمل", "مجمل الربح", "الربح الإجمالي", "ربح إجمالي",
    "الربح الخام", "gross profit",
    "هامش", "margin",
    "إجمالي", "اجمالي", "مجموع", "الجمع", "total",
    "صافي", "الخسارة", "خسارة", "loss", "الربح", "النتيجة",
]

# Arabic and English labels for the concepts we try to recognise.
# Insertion order matters: more specific concepts (cost of sales) must be
# checked before generic ones (sales/revenue) because labels like
# "تكلفة المبيعات" contain generic words.
KEYWORDS = {
    # Statement-of-cash-flows STATED activity totals («Net cash from
    # operations 136,162 / investing (72,599) / financing (51,699)») — the
    # file's own cash-flow section. MUST precede 'cash': the labels contain
    # the word «cash» and would otherwise pollute the cash-balance series.
    "cf_operating": ["net cash from operations", "net cash provided by operating", "net cash used in operating", "cash flows from operating activities", "صافي التدفق النقدي من الأنشطة التشغيلية", "التدفقات النقدية من الأنشطة التشغيلية", "صافي النقدية من الأنشطة التشغيلية", "صافي التدفق النقدي التشغيلي",
             # OCR scanned faces word the CF totals «الناتج عن الانشطة…» —
             # without these the totals fall through to the generic cash
             # keyword («النقد» lives inside «النقدي»)
             "الناتج عن الانشطة التشغيلية", "الناتج عن الأنشطة التشغيلية"],
    "cf_investing": ["net cash from investing", "net cash provided by investing", "net cash used in investing", "cash flows from investing activities", "صافي التدفق النقدي من الأنشطة الاستثمارية", "التدفقات النقدية من الأنشطة الاستثمارية", "التدفقات النقدية من الأنشطة الاستثمائية", "صافي التدفق النقدي الاستثماري",
             "الناتج عن الانشطة الاستثمارية", "الناتج عن الأنشطة الاستثمارية"],
    "cf_financing": ["net cash from financing", "net cash provided by financing", "net cash used in financing", "cash flows from financing activities", "صافي التدفق النقدي من الأنشطة التمويلية", "التدفقات النقدية من الأنشطة التمويلية", "صافي التدفق النقدي التمويلي",
             "الناتج عن الانشطة التمويلية", "الناتج عن الأنشطة التمويلية"],
    "cf_other": ["effect of foreign exchange", "foreign exchange effect", "exchange rate effect", "effect of exchange rate", "أثر العملات", "فروق العملات", "أثر فروق العملات"],
    # the cash-flow statement's OWN reconciliation anchors: the stated
    # «Net change in cash and cash equivalents» line and the «Cash and cash
    # equivalents, end of period» closing balance. They MUST precede 'cash'
    # (their labels contain the word «cash») and are NOT balance concepts —
    # the file's cash-flow face ties to these, while the balance-sheet cash
    # line is often WIDER («Total cash, cash equivalents, and short-term
    # investments») and can never close the statement's own walk.
    "cf_net_change": ["net change in cash", "change in cash and cash equivalents", "net increase (decrease) in cash", "net increase in cash", "net decrease in cash", "صافي التغير في النقدية", "التغير في النقدية", "التغير في النقد وما في حكمه", "صافي الزيادة في النقد", "صافي النقص في النقد"],
    "cf_cash_end": ["cash and cash equivalents, end of period", "cash and cash equivalents at end of period", "cash at end of the period", "cash at end of period", "closing cash and cash equivalents", "closing cash", "نقدية وما في حكمها في نهاية الفترة", "النقدية في نهاية الفترة", "النقد وما في حكمه في نهاية الفترة", "النقدية بنهاية الفترة"],
    "cogs": ["cogs", "cost of goods", "cost of sales", "cost of revenue", "تكلفة المبيعات", "تكلفة البضاعة", "تكلفة الإيرادات", "تكلفة الإيراد", "تكلفة البضاعة المباعة",
             # OCR variants: the article ال is often dropped/mis-decoded on
             # scanned faces («تكلفة إيرادات 9», «9- تكلفة الايرادات») —
             # without these the row falls through to the generic revenue
             # keyword and prices the COGS value as revenue!
             "تكلفة إيرادات", "تكلفة ايرادات", "تكلفة الايرادات", "تكلفة ايراد"],
    # finance/tax BEFORE opex: «مصاريف الفوائد البنكية» and «الزكاة المقدرة»
    # must not sink into the generic expense pool (IFRS 18 categories).
    "finance_cost": ["مصاريف الفوائد", "فوائد بنكية", "فوائد القروض", "مصاريف التمويل", "مصاريف تمويلية", "finance cost", "interest expense"],
    # non-operating income BEFORE opex: US-GAAP statements carry the P&L
    # bridge line «Other income (expense), net» — without it the IFRS 18
    # chain (net = operating ± other − tax) never ties for English reports
    "investment_income": ["other income", "non-operating income", "غير تشغيلي", "عوائد الاستثمار", "دخل الاستثمار", "إيرادات الاستثمار", "investment income"],
    "tax_expense": ["زكاة", "ضريبة الدخل", "الضرائب", "ضريبة", "tax expense", "income tax"],
    "opex": ["operating expenses", "opex", "المصاريف التشغيلية", "مصاريف التشغيل", "النفقات التشغيلية", "إجمالي المصروفات", "اجمالي المصروفات", "المصروفات", "المصاريف", "مصاريف", "مصاريف بيعية", "مصاريف توزيعية", "مصاريف إدارية", "مصاريف عمومية", "مصاريف الاستهلاك", "مصاريف استهلاك", "selling expenses", "administrative expenses", "general expenses", "depreciation expense", "sales and marketing", "general and administrative", "research and development", "research & development",
             # OCR variants: scanned faces print the operating expenses
             # without ال («مصروفات عمومية وإدارية») and the depreciation
             # line bare («استهلاك ممتلكات، آلات ومعدات») — the compound
             # forms (never the bare «مصروفات») keep the notes' titles out
             "مصروفات عمومية", "مصروفات إدارية", "مصروفات ادارية",
             "مصروفات بيعية", "مصروفات توزيعية",
             "استهلاك ممتلكات", "استهلاك آلات", "استهلاك أصول", "استهلاك اصول"],
    "revenue": ["revenue", "sales", "total revenue", "الإيرادات", "الإيراد", "المبيعات", "إيرادات", "ايرادات", "ايراد"],
    # Working-capital balances from plain (non-TB) balance sheets — the
    # comparative-statement shape («ذمم مدينة (عملاء)»). TB headers «مدين /
    # دائن» never match these multi-char words, and TB tables skip them
    # entirely (the statements builder owns those buckets).
    "receivables": ["ذمم مدينة", "مدينون", "أوراق قبض", "المدينون", "receivables", "accounts receivable"],
    "payables": ["ذمم دائنة", "دائنون", "موردون", "أوراق دفع", "payables", "accounts payable"],
    "equity": ["equity", "shareholders equity", "حقوق الملكية", "حقوق المساهمين", "جاري الشركاء", "جاري الشريك", "حساب جاري"],
    "current_assets": ["current assets", "الأصول المتداولة", "أصول متداولة"],
    "current_liabilities": ["current liabilities", "الالتزامات المتداولة", "التزامات متداولة"],
    "inventory": ["inventory", "المخزون", "المخزونات", "مخزون"],
    "liabilities": ["total liabilities", "liabilities", "إجمالي الالتزامات", "الخصوم", "الالتزامات", "التمويل من", "تمويل"],
    "assets": ["total assets", "assets", "إجمالي الأصول", "الأصول", "الموجودات"],
    "cash": ["cash", "النقد", "النقدية", "النقد وما يعادله", "نقد وما في حكمه", "نقدية وما في حكمها"],
    "net_profit": ["net profit", "net income", "صافي الربح", "صافي الأرباح", "صافي الدخل", "صافي الخسارة", "الخسارة الصافية", "ربح السنة", "خسارة السنة", "الربح", "ربح الفترة", "الربح الصافي"],
}

# Lines whose stated value is trustworthy as-is (a real profit/loss line in
# a text paragraph or a bare statement) — captured directly, never filtered.
_TRUSTED_EXACT = {"net profit", "net income", "صافي الربح", "صافي الأرباح", "صافي الدخل", "الخسارة", "صافي الخسارة"}

# STATED bottom-line titles on a statement face («الربح», «صافي الربح»,
# «ربح الفترة») — trusted as net_profit even though the summary filter
# flags them: when the face carries post-profit allocation rows (tax,
# branch-manager %, executive %) the derived chain (gross − opex − tax)
# can never reproduce the true bottom line, and the stated row is the
# ground truth. Intermediate/computed titles (مجمل الربح، الربح التشغيلي،
# الإجمالي) stay filtered.
_STATED_NET_LABELS = {"net profit", "net income", "net loss", "صافي الربح",
                      "صافي الأرباح", "صافي الدخل", "صافي الخسارة",
                      "الخسارة الصافية", "الربح الصافي", "ربح السنة",
                      "ربح الفترة", "خسارة السنة", "الربح", "الخسارة"}

# Detail-only concepts (revenue/cogs/opex/equity...) vs concepts whose own
# natural title IS a summary word (e.g. 'إجمالي المصروفات' for opex, or
# 'إجمالي الأصول' for assets) — these pass the summary filter. Comparative
# statements title their bottom lines exactly this way: «إجمالي المبيعات»,
# «صافي الربح (Net Income)», «إجمالي حقوق الملكية», «إجمالي الأصول المتداولة».
_HAS_OWN_LABEL = {"assets", "liabilities", "cash", "opex", "cogs",
                  "revenue", "equity", "current_assets", "current_liabilities",
                  # the cash-flow totals' own natural title IS «صافي التدفق…» /
                  # «Net cash…» — never filtered as a computed line
                  "cf_operating", "cf_investing", "cf_financing", "cf_other",
                  # «صافي التغير في النقدية» / «Net change in cash…» IS the
                  # natural row title of the CF reconciliation anchor
                  "cf_net_change", "cf_cash_end"}


def _is_summary_row(label: str, concept: str, from_text: bool = False) -> bool:
    """True when a row's title is a derived/aggregate line whose numbers must
    not be captured raw (margins, totals, computed profit lines).

    Detail concepts (revenue, cogs, opex, equity...) are skipped whenever the
    label matches a summary pattern; balance-sheet concepts keep their own
    titles (e.g. 'إجمالي الأصول' is the natural row name for total assets).

    In free text (no table), a line titled exactly like a net-profit line IS
    the value ("Net Profit 640,000") — trusted there.
    """
    if concept in _HAS_OWN_LABEL:
        return False
    stripped = label.lower().strip().rstrip(":").strip()
    if from_text and stripped in _TRUSTED_EXACT:
        return False
    low = f" {stripped} "
    return any(p in low for p in _SUMMARY_PATTERNS)


_RATIO_ARTIFACT_RE = re.compile(r"-?\d{0,2}\.\d{6,}")


def _to_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # cached FORMULA values arrive as floats too (openpyxl data_only:
        # «=C6/C5» → -0.6413145167662294 stored in the «الإيراد» row) — a
        # per-row RATIO with a long decimal tail, never a financial amount
        if isinstance(value, float) and _RATIO_ARTIFACT_RE.fullmatch(repr(value)):
            return None
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # a broken FORMULA cell pasted as text (a per-row RATIO with its =
    # swallowed: «=C6/C5» → "0.6413145167662294" or "-.641…") is a
    # percentage artefact in [-1, 1], never an amount (amounts here are
    # 4-digit-plus in these sheets) — reading it as a value produced
    # phantom series entries like -0.64 next to 762,284.99
    if re.fullmatch(r"-?\.\d+", text) or _RATIO_ARTIFACT_RE.fullmatch(text):
        return None
    # OCR cells carry space-split digit-group fragments that the regex
    # below would read as a tiny leading number («1872 2 2 58» → 1872) —
    # rejoin them first (pure-Latin-digit guard inside; dates with Arabic
    # words are untouched)
    text = _heal_glued_digits(text)
    match = NUM_RE.search(text)
    if not match:
        return None
    try:
        num = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    # accounting parentheses: «(15,000)» is NEGATIVE 15,000 — an explicit
    # «(+15,000)» stays positive. A fragment like «(4,901» (Word/PDF tables
    # split the closing paren into the NEXT cell) is negative too.
    if "(" in text and ")" in text and not re.search(r"\(\s*\+", text):
        num = -abs(num)
    elif text.startswith("(") and ")" not in text:
        num = -abs(num)
    return num


# Labels that must NEVER be captured as a concept value: deferred (unearned)
# revenue is a liability, «sales of investments» is an investing cash-flow
# line, and «income BEFORE income taxes» is a pre-tax SUBTOTAL (reading it as
# tax expense or net profit broke every tie check on US-GAAP statements).
_CLASSIFY_EXCLUDE = ("unearned revenue", "deferred revenue", "الإيرادات المؤجلة",
                     "ايرادات مؤجلة", "إيرادات مؤجلة", "sales of investments",
                     "before income taxes", "before income tax",
                     "الدخل قبل الضريبة", "قبل الزكاة والضريبة", "قبل الضريبة")


# concept-scoped label exclusions: rows whose title CONTAINS a concept's
# keyword but belongs to another statement. The scanned al-Marāʾī report
# floods «cash» with the cash-flow statement's own lines (hedging fair-
# value movements, «acquired net of cash», activity subtotals) and the
# attribution section («ربح السنة العائد إلى…») — none of these is the
# balance-sheet cash or the period net profit.
_CONCEPT_EXCLUDE: dict[str, tuple] = {
    "cash": (
        "التدفقات النقدية", "تحوطات", "الحركة في القيمة", "المستحوذ",
        "الأنشطة", "التغير في النقد", "نهاية الفترة", "بداية الفترة",
        "cash flow", "hedg", "acquisition", "change in cash",
        "end of the period", "end of period", "beginning",
    ),
    "net_profit": (
        "العائد إلى", "attributable",
        # «الربح التشغيلي / Operating profit» is an INTERMEDIATE line — the
        # generic «الربح» keyword would otherwise claim it as the bottom line
        "التشغيلي", "التشغيلية", "operating",
        # «مجمل الربح / Gross profit» is equally intermediate: the generic
        # «الربح» keyword claims it (OCR faces print it bare, no ال) and the
        # gross subtotal priced itself as the bottom line
        "مجمل", "gross",
    ),
    "tax_expense": (
        # «احتساب الضريبة:» heads the income-tax NOTE — its companion cell
        # is the squashed date 312025, priced as the tax provision
        "احتساب الضريبة",
    ),
}


def _ns(text: str) -> str:
    """Space-free form for label matching.

    Windows OCR splits Arabic words across boxes («الاير ادات» for
    «الايرادات») — spaced substring matching misses the concept entirely
    and the row's numbers are lost. Comparing BOTH sides space-free is a
    strict superset of spaced containment (Excel/text-layer labels keep
    matching exactly as before) and heals the OCR split."""
    return text.lower().replace(" ", "")


def _classify_row(label: str, skip: frozenset = frozenset()) -> str | None:
    # OCR wraps loss words in parens on the face («(خسارة) السنة», «(الخسارة)
    # قبل الضريبة») — the parens are pure punctuation but glue themselves
    # into the keyword («خسارة السنة») and kill the match. Drop them before
    # normalizing; keyword semantics never live inside parens.
    low = label.lower().replace("(", " ").replace(")", " ").strip()
    ns = _ns(low)
    if any(_ns(p) in ns for p in _CLASSIFY_EXCLUDE):
        return None
    # balance-sheet and cash-flow income-TAX lines («Short-term income
    # taxes», «Deferred income taxes», the CF «Income taxes» change) are
    # not the P&L provision — only «(Provision for) income tax expense»
    # rows feed tax_expense
    if low.startswith(("short-term income taxes", "long-term income taxes",
                       "deferred income taxes", "income taxes")):
        return None
    # statement TITLES are not data rows: «قائمة الربح أو الخسارة للسنة
    # المنتهية في 31/12/2025» carries the generic «الربح» keyword AND the
    # squashed date «312025» passes _money_like — pricing a date as the
    # net profit. A face's title never carries row-level values.
    if low.startswith(("قائمة", "statement")):
        return None
    # note HEADINGS carry a leading number+dash («10- مصروفات عمومية
    # وادارية», «9- تكلفة الايرادات») and their companion cell is the
    # squashed date — a note title is never a data row
    if re.match(r"^\s*\d+\s*[-/]", low):
        return None
    for concept, words in KEYWORDS.items():
        if concept in skip:
            continue  # statement-scope filter: this face never carries it
        if any(_ns(w) in ns for w in words):
            if any(_ns(x) in ns for x in _CONCEPT_EXCLUDE.get(concept, ())):
                continue  # keyword hit but the row belongs elsewhere
            return concept
    return None


def _looks_total(label: str) -> bool:
    """True when a row label is a STATED total line («إجمالي المصروفات»,
    «مجموع الأصول», «Total Expenses») — such rows win over detail rows of
    the same concept in messy sheets carrying both."""
    low = str(label or "").lower()
    return any(p in low for p in ("إجمالي", "اجمالي", "مجموع", "total"))


_YEAR_RE = re.compile(r"(19|20)\d{2}")
_CHANGE_WORDS = ("تغير", "الفرق", "change", "variation")
# a totals COLUMN («الإجمالي» under the periods) is a cross-period aggregate:
# reading it as a period would make _latest() report the grand total
_TOTAL_WORDS = ("إجمالي", "اجمالي", "مجموع", "total")


def _year_columns(rows: list) -> dict[int, int]:
    """Value-column → year, from HEADER cells like «عام 2024 (ريال)».

    Only text cells in header rows qualify — a row with ANY numeric value is
    a data row (the number 4,820,000 contains the digit-run «2000»!), and a
    numeric cell is a balance, never a year label."""
    out: dict[int, int] = {}
    for row in rows[:6]:
        if any(isinstance(c, (int, float)) and not isinstance(c, bool)
               for c in row):
            continue  # a data row — years may not be read out of numbers
        for j, cell in enumerate(row):
            if j == 0 or isinstance(cell, (int, float)):
                continue
            # the cell's digit runs must be year-sized: a GLUED date like
            # «312023» (31/12/2023 read as one token) contains «2023» but is
            # a date, not a column header — trusting it planted a false
            # year column that broke per-year bucketing below. A separated
            # date header «31/12/2024» keeps its runs ≤4 and stays valid.
            if max((len(run) for run in re.findall(r"\d+", str(cell or ""))),
                   default=0) > 5:
                continue
            m = _YEAR_RE.search(str(cell or ""))
            if m:
                out.setdefault(j, int(m.group(0)))
    return out


_TB_BLOCK_HEADER_RE = re.compile(r"اسم\s*الحساب")


def _strip_embedded_tb_blocks(rows: list) -> list:
    """Income-statement sheets that append an ACCOUNTS export below the
    face (the report's own detail: «اسم الحساب | الرصيد» pairs of coded
    rows RT410…/CT510…/MT…) — those columns are a PARTIAL, unbalanced
    account dump, not statement periods: values from the header row down
    would flood the face's concepts with a second (wrong) series.

    Cut the sheet at its LAST block header row; the face above keeps the
    statement lines only. When several blocks stack (two account columns
    side by side), the first header row starts the dump — cutting there
    is correct because the face NEVER continues below its own signature
    row (المدير المالي / المدير العام).
    """
    cut = None
    for i, row in enumerate(rows):
        for cell in row or []:
            t = str(cell or "")
            if _TB_BLOCK_HEADER_RE.search(t):
                cut = i
                break
        if cut is not None:
            break
    return rows[:cut] if cut else rows


def _change_columns(rows: list, year_cols: dict[int, int] | None = None) -> set[int]:
    """Columns carrying a DERIVED value in a comparative statement — deltas
    («التغير / نسبة التغير / Δ») and, in MULTI-period tables, cross-period
    totals («الإجمالي / المجموع / Total»). Those are never period balances
    and must not pollute the captured series (they are usually the LAST
    column, which _latest would otherwise read as the current value — the
    totals-column grand total).

    The totals-column rule applies ONLY when year columns exist: in a
    single-period statement («البيان | الفرعي | الإجمالي») the الإجمالي
    column IS the authoritative value column, never an aggregate to drop."""
    multi = bool(year_cols)
    bad: set[int] = set()
    for row in rows[:6]:
        for j, cell in enumerate(row):
            if j == 0 or isinstance(cell, (int, float)):
                continue
            low = str(cell or "").strip().lower()
            if any(w in low for w in _CHANGE_WORDS):
                bad.add(j)
            elif multi and any(w in low for w in _TOTAL_WORDS) and not _YEAR_RE.search(low):
                bad.add(j)  # «الإجمالي» — but «إجمالي عام 2024» stays a period
    return bad


def _is_tb_table(rows: list, force: bool = False) -> bool:
    """Trial-balance table: a short «مدين / دائن» header pair. ``force``
    (analysis_mode=force_trial_balance from the upload screen) pins every
    table to the trial-balance reading so debit/credit columns always
    extract."""
    if force:
        return True
    for row in rows[:4]:
        texts = [str(c or "").strip() for c in row]
        if (any("مدين" in t and len(t) <= 6 for t in texts)
                and any("دائن" in t and len(t) <= 6 for t in texts)):
            return True
    return False


# Balance-sheet concepts: a cash-flow statement carries these row NAMES only
# as WORKING-CAPITAL CHANGES (Δ) — never balances — so they must not be
# captured from a cash-flow table at all.
_BALANCE_CONCEPTS = {"receivables", "payables", "inventory", "cash",
                     "current_assets", "current_liabilities",
                     "assets", "liabilities", "equity"}

# Income-statement-face concepts: rows carrying these labels on a BALANCE
# SHEET page are assets/liabilities wearing expense words — «مصاريف مدفوعة
# مقدما طويلة الأجل» is a prepaid ASSET (it was captured as opex and the
# derived income statement showed the balance-sheet figure as operating
# expenses), «موجودات ضريبية مؤجلة» fed tax_expense, and «تكلفة تمويل،
# صافي» (a P&L line) fed liabilities through the «تمويل» keyword. Scoping
# per statement face kills the whole class of cross-statement pollution.
_INCOME_CONCEPTS = {"revenue", "cogs", "opex", "finance_cost",
                    "investment_income", "tax_expense", "net_profit"}

_BALANCE_TITLE_WORDS = ("المركز المالي", "الموقع المالي", "المركز المالى",
                        "financial position", "balance sheet",
                        "statement of financial")
_INCOME_TITLE_WORDS = ("الربح أو الخسارة", "الربح او الخسارة", "قائمة الدخل",
                       "الدخل الشامل", "income statement",
                       "profit or loss", "profit and loss",
                       "statement of operations", "comprehensive income")


def _table_scope(rows: list) -> str:
    """"income" | "balance" | "mixed" | "none" from the table's statement
    TITLES (a scanned face prints «قائمة المركز المالي الموحدة» as its
    first rows). FULL-table scan: one Excel sheet carrying BOTH statements
    (their titles stacked mid-table) is "mixed" and stays unrestricted —
    scoping it by its first title would blind the second face's rows."""
    income = balance = False
    for row in rows:
        for cell in row:
            t = str(cell or "").strip().lower()
            if not t:
                continue
            if not income and any(w in t for w in _INCOME_TITLE_WORDS):
                income = True
            elif not balance and any(w in t for w in _BALANCE_TITLE_WORDS):
                balance = True
        if income and balance:
            return "mixed"
    if income:
        return "income"
    if balance:
        return "balance"
    return "none"

_CF_ACTIVITY_WORDS = ("operating activities", "investing activities",
                      "financing activities", "cash from operations",
                      "cash used in operations",
                      "cash provided by operations", "investing", "financing",
                      "الأنشطة التشغيلية", "الأنشطة الاستثمارية",
                      "الأنشطة الاستثمائية", "الأنشطة التمويلية",
                      # OCR sheds the hamza on scanned faces
                      # («الانشطة التشغيلية»)
                      "الانشطة التشغيلية", "الانشطة الاستثمارية",
                      "الانشطة الاستثمائية", "الانشطة التمويلية")


def _is_cash_flow_table(rows: list) -> bool:
    """Cash-flow statement: a «Net income» anchor row PLUS an activities
    section («Operating / Investing / Financing activities»). The working-
    capital lines of such a table are DELTAS («Accounts receivable (10,581)»
    is a change, not a balance) — reading them as balances produced nonsense
    statements (negative receivables, an «unbalanced» balance sheet)."""
    hit_net = False
    hit_act = False
    for row in rows[:40]:
        for cell in row:
            t = str(cell or "").strip().lower()
            if not t:
                continue
            if ("net income" in t or "صافي الربح" in t
                    or "صافي الدخل" in t or "ربح السنة" in t
                    or "خسارة السنة" in t or "الخسارة" in t
                    or "net loss" in t):
                hit_net = True
            if any(w in t for w in _CF_ACTIVITY_WORDS):
                hit_act = True
            if hit_net and hit_act:
                return True
    # a statement TITLED cash flow IS a cash-flow statement — the OCR of
    # scanned Arabic statements reads «ربح السنة» (not «صافي الربح») as the
    # anchor and mangles the activities wording, so the title decides
    for row in rows[:6]:
        for cell in row:
            t = str(cell or "").strip().lower()
            if ("التدفقات النقدية" in t or "قائمة التدفقات" in t
                    or "cash flow" in t):
                return True
    return False


def _is_equity_change_table(rows: list) -> bool:
    """Statement of changes in EQUITY: its rows carry one value per equity
    COMPONENT (retained earnings, NCI, total…) — a «ربح السنة» row there is
    that profit sliced per component, never a period series. Capturing it
    multiplied the net_profit series with component/total magnitudes."""
    for row in rows[:8]:
        for cell in row:
            t = str(cell or "").strip().lower()
            if ("التغيرات في حقوق الملكية" in t
                    or "changes in equity" in t):
                return True
    # scanned faces shed the TITLE from the table itself (it stays on the
    # cover page) — the beginning-balance row beside the equity COMPONENT
    # columns («رأس المال أرباح مبقاة مجموع حقوق الملكية») identifies the
    # statement just as surely
    has_balance_row = has_component = False
    for row in rows[:8]:
        for cell in row:
            t = str(cell or "").strip().lower()
            if "الرصيد في بداية الفترة" in t:
                has_balance_row = True
            if ("أرباح مبقاة" in t or "حقوق الملكية" in t
                    or "retained earnings" in t):
                has_component = True
            if has_balance_row and has_component:
                return True
    return False


def _extract_metrics(tables: list, texts: list, tb_hint: bool = False) -> dict:
    """Return {concept: [values]} found in tables and text lines.

    ``tb_hint`` comes from the upload screen's «تفسير ميزان مراجعة» mode:
    every table is forced onto the debit/credit reading so the extraction
    never walks the automatic concept path for this upload.

    Series are ordered OLDEST→NEWEST (the platform's «latest = last column"
    convention): when a table carries YEAR headers, each row's values are
    re-ordered by year ascending — a US-GAAP statement laid out 2025 | 2024
    | 2023 must not read its oldest year as the latest.
    """
    found: dict[str, list[float]] = {}

    def add(concept: str, value: float) -> None:
        found.setdefault(concept, []).append(value)

    # stated TOTAL rows collected across ALL tables — a total in ANY table
    # beats detail-row captures of the same concept from EVERY table (the
    # cash-flow statement's «Other long-term assets» line must not overwrite
    # the balance sheet's «Total assets» series)
    global_total_captures: dict[str, list[tuple[str, list[float]]]] = {}

    for table in tables:
        rows = table.get("rows") or []
        if not rows:
            continue
        # an income-statement sheet with an embedded ACCOUNTS dump (its own
        # «اسم الحساب | الرصيد» block below the face) — the dump is not part
        # of the statement; reading it flooded the concepts with a second,
        # wrong series (the multi-company January-2026 reports)
        if not _is_tb_table(rows):
            rows = _strip_embedded_tb_blocks(rows)
            if not rows:
                continue
        change_cols = _change_columns(rows)
        year_cols = _year_columns(rows)
        # a totals column is an aggregate only in multi-period tables —
        # year_cols must be known first
        change_cols |= _change_columns(rows, year_cols)
        tb_table = _is_tb_table(rows, force=tb_hint)
        cf_table = _is_cash_flow_table(rows)
        eq_table = _is_equity_change_table(rows)
        # statement-face scoping (scanned multi-statement reports): a table
        # TITLED as one face only captures that face's concepts — the BS
        # page's expense-labelled ASSETS and the P&L page's financing word
        # must not feed each other's concepts. Unidentified or MIXED tables
        # (one sheet, both statements; generic Excel sheets) stay free.
        scope = _table_scope(rows)
        income_table = scope == "income" and not cf_table and not eq_table
        bs_table = scope == "balance" and not cf_table and not eq_table
        if income_table:
            row_skip: frozenset = _BALANCE_CONCEPTS
        elif bs_table:
            row_skip = frozenset(_INCOME_CONCEPTS)
        elif cf_table:
            row_skip = frozenset(_BALANCE_CONCEPTS | _INCOME_CONCEPTS
                                 - {"net_profit"})
        else:
            row_skip = frozenset()
        # OCR tables without usable year headers: the grid emits amounts from
        # the label side outward — the NEWEST period in both layout
        # conventions (English newest-leftmost, Arabic newest-nearest-the-
        # labels). The platform reads «latest = last», so flip each row's
        # values to oldest-first (the year-header sort below still wins when
        # the header cells were actually read).
        ocr_flip = str(table.get("name") or "").endswith("_ocr")
        # P&L expense concepts (opex / finance_cost / tax_expense) in a
        # comparative statement with year headers must SUM per period —
        # several detail rows (بيعية/إدارية/استهلاك...) otherwise interleave
        # [2024, 2025, 2024, 2025, ...] and the «latest» read breaks.
        agg_cols: dict[str, dict[int, list]] = {}
        # bucket per column: [signed_sum, abs_sum, prev_sign, mixed] — the
        # SIGNED sum is the contract (parenthesised expense rows sum
        # negative); when OCR drops the parens on SOME rows of the same
        # face (بيع reads (2,789,745), عمومية reads 469,022) the signs mix
        # and only the magnitude sum is meaningful for that column
        agg_total_values: dict[str, list[float]] = {}
        # per-concept row captures: messy sheets often carry DETAIL rows AND a
        # stated TOTAL row for the same concept (رأس المال + إجمالي حقوق
        # الملكية) — the stated total must win, the details must not pollute
        # the series with mixed component/total magnitudes.
        concept_rows: dict[str, list[tuple[str, list[float]]]] = {}
        for row in rows:
            row = [("" if c is None else c) for c in row]
            for i, cell in enumerate(row):
                concept = _classify_row(str(cell), row_skip)
                if not concept:
                    continue
                label = str(cell)
                # summary/computed lines (مجمل الربح، الإجمالي، هامش ...) are
                # re-derived later from detail rows — never captured raw.
                # A STATED bottom line (الربح / صافي الربح) is the exception:
                # post-profit allocation rows make the derived chain diverge
                # from the face's own bottom line, so the stated row wins.
                if (_is_summary_row(label, concept)
                        and not (concept == "net_profit"
                                 and _ns(label.lower()
                                         .replace("(", " ")
                                         .replace(")", " ").strip()) in
                                 {_ns(s) for s in _STATED_NET_LABELS})):
                    continue
                # SECTION subtotals are NOT the statement total: «صافي الأصول
                # غير المتداولة» is not total assets; current liabilities and
                # the combined «الالتزامات وحقوق الملكية» line are not total
                # liabilities either.
                if concept == "assets" and "غير المتداولة" in label:
                    continue
                if concept == "liabilities" and ("المتداولة" in label or "حقوق" in label):
                    continue
                # the combined closing line «إجمالي الالتزامات وحقوق الملكية»
                # / «Total liabilities and stockholders' equity» IS total
                # assets — it must not double into equity
                if concept == "equity" and ("الالتزامات" in label
                                            or "liabilities" in label.lower()):
                    continue
                # trial balances own their buckets via the statements builder
                # — generic capture would read the debit/credit columns as
                # two periods and zero out the balances
                if tb_table and concept in ("receivables", "payables"):
                    continue
                # cash-flow tables carry the balance-sheet NAMES only as
                # change lines (Δ receivables / Δ payables / beginning-
                # ending cash) — never balances; capturing them polluted the
                # balance-sheet series with deltas and broke the statements
                if cf_table and concept in _BALANCE_CONCEPTS:
                    continue
                # «ربح السنة» inside the equity statement is profit sliced
                # per equity component — not a period series; the equity
                # COMPONENT columns are the same trap for equity, and the
                # merged component header («رأس المال أرباح مبقاة مجموع
                # حقوق الملكية») carries the squashed date — both faces
                # already state these series correctly
                if (eq_table and not cf_table
                        and concept in ("net_profit", "equity")):
                    continue
                # multi-year statement rows: capture every number to the right
                captured = 0
                last_captured_col: int | None = None
                gap = 0  # consecutive valueless cells since the last capture
                row_values: list[float] = []
                row_jv: list[tuple[int, float]] = []  # (column, value)
                # a ZERO followed by a real figure on the SAME row is the
                # empty side of a two-column layout (OCR tables emit the
                # empty debit/credit slot as an explicit «0») — informationless
                # either way, so it never becomes a period
                later_nonzero = any(
                    (_to_number(c) or 0.0) != 0
                    for c in row[i + 1:i + 13]
                    if isinstance(c, str) and "%" not in c
                    and len(c.strip()) <= 30
                )
                for j, candidate in enumerate(row[i + 1:], start=i + 1):
                    if captured >= 12:
                        break
                    # a run of ≥3 valueless cells after a captured value is
                    # the blank gutter BEFORE a side table (the sales-by-
                    # stream block printed beside a restaurant income
                    # statement): its figures are stream components, not
                    # periods of THIS row — stop reading here. A currency
                    # marker («$» prefix columns in US-style exports) resets
                    # the run: it belongs to the NEXT value, not a new block.
                    if last_captured_col is not None:
                        ct = str(candidate or "").strip()
                        if ct in {"$", "€", "£", "﷼", "ر.س", "ريال", "USD", "SAR"}:
                            gap = 0
                            continue
                        gap += 1
                        if gap >= 3:
                            break
                    if j in change_cols:
                        continue  # a «التغير» column is derived, never a period
                    cand_text = str(candidate)
                    # skip percentage cells and long NOTE cells — a sentence
                    # like «عام 2024 بقيمة 219448.98» is not a value cell
                    if "%" in cand_text or len(cand_text.strip()) > 30:
                        continue
                    # a MIXED cell like «الإجمالي 3000» / «total 3000» is a
                    # derived aggregate — never a period value (a pure number
                    # in a totals COLUMN still passes; the row resolution below
                    # and the header rules own column semantics)
                    if (any(w in cand_text for w in ("إجمالي", "اجمالي", "مجموع", "total"))
                            and not cand_text.replace(",", "").replace(".", "")
                                .replace("-", "").replace("+", "").strip().isdigit()):
                        continue
                    value = _to_number(candidate)
                    if value is None:
                        continue
                    # a trailing ZERO after a captured figure is the empty
                    # side of a trial-balance row (مدين 400000 / دائن 0) —
                    # never a second period that erases the balance.
                    # A LEADING zero on a TB row is the SAME artefact on the
                    # other side (دائن 0 / مدين — explicit «0» cells are how
                    # accounting exports fill the empty column); treating it
                    # as a period made the real figure the SECOND period.
                    if value == 0 and (captured > 0 or tb_table
                                       or later_nonzero):
                        continue
                    captured += 1
                    last_captured_col = j
                    gap = 0
                    if (concept in ("opex", "finance_cost", "tax_expense")
                            and not tb_table
                            and (j in year_cols or ocr_flip)):
                        # route the value into its YEAR bucket (summed below);
                        # a STATED total row carries its own series verbatim
                        if _looks_total(label):
                            agg_total_values.setdefault(concept, []).append(value)
                        else:
                            b = agg_cols.setdefault(concept, {}).setdefault(
                                j, [0.0, 0.0, 0, False])
                            b[0] += value
                            b[1] += abs(value)
                            s = (1 if value > 0 else -1) if value else 0
                            if s:
                                if b[2] and s != b[2]:
                                    b[3] = True
                                b[2] = s
                        continue
                    row_values.append(value)
                    row_jv.append((j, value))
                if row_values:
                    # scattered-fragment guard: an OCR total row can shed
                    # digit fragments into far columns («إجمالي الموجودات»
                    # emitting «15» beside the real 36,194,015) — a row with
                    # 3+ values loses the ones under 1% of its own max
                    if len(row_values) >= 3:
                        vmax = max(abs(v) for v in row_values)
                        row_values = [v for v in row_values
                                      if abs(v) >= 0.01 * vmax]
                    # year headers present: re-order the row's values oldest
                    # → newest so the whole series follows the platform's
                    # latest-last convention regardless of layout direction
                    if (year_cols and row_jv
                            and all(j in year_cols for j, _ in row_jv)):
                        row_jv.sort(key=lambda p: year_cols[p[0]])
                        row_values = [v for _, v in row_jv]
                    elif (ocr_flip and len(row_values) >= 2
                          and not all(j in year_cols for j, _ in row_jv)):
                        row_values = row_values[::-1]
                    concept_rows.setdefault(concept, []).append((label, row_values))
        # resolve row captures: when a concept has BOTH detail rows and a
        # stated total row in the same table, a stated total row wins —
        # the LAST one when the sheet stacks statement faces, otherwise the
        # one carrying the LARGEST magnitude: a side table of revenue
        # STREAMS (كاش/سائقين/طبخ beside the face's own total row) must not
        # bury the total under its components (the multi-company January-
        # 2026 reports read each stream as its own period)
        for concept, captures in concept_rows.items():
            if len(captures) > 1:
                totals = [(lbl, vals) for lbl, vals in captures
                          if _looks_total(lbl)]
                if concept == "net_profit" and not any(
                        _looks_total(lbl) for lbl, _ in captures):
                    # stated net rows form a CHAIN (الربح → الربح بعد الضريبة
                    # → صافي الربح): the LAST row is the face's bottom line
                    captures = captures[-1:]
                elif totals:
                    captures = [totals[-1]]
            if captures and _looks_total(captures[-1][0]) and len(captures) == 1:
                global_total_captures.setdefault(concept, []).append(captures[-1])
            for _lbl, vals in captures:
                for v in vals:
                    add(concept, v)
        # emit per-column expense sums in chronological (year) order when the
        # columns are year-headed, else physical (column) order — unless a
        # stated total row exists for the concept (it wins)
        for concept, cols in agg_cols.items():
            if concept in agg_total_values:
                continue
            if cols and all(j in year_cols for j in cols):
                ordered = sorted(cols, key=lambda j: year_cols[j])
            elif ocr_flip and not all(j in year_cols for j in cols):
                # OCR grid columns run newest-first (see ocr_flip above)
                ordered = sorted(cols, reverse=True)
            else:
                ordered = sorted(cols)
            for j in ordered:
                b = cols[j]
                add(concept, round(b[1] if b[3] else b[0], 2))
        for concept, vals in agg_total_values.items():
            for v in vals:
                add(concept, v)

    # GLOBAL totals-wins: a stated total row from ANY table replaces the
    # concept's whole series — lookalike rows from other statements (a cash-
    # flow «Other long-term assets» investing line) must not overwrite the
    # balance sheet's «Total assets» as the latest value.
    for concept, tcs in global_total_captures.items():
        if found.get(concept):
            found[concept] = [v for _lbl, vals in tcs for v in vals]

    # The same statement line is often RESTATED in several statements of one
    # document (income + comprehensive income + cash flow + equity statement
    # all repeat «Net income») — the identical block would multiply the
    # series (12 points for 3 years) and break every trend/growth read.
    for concept, vals in found.items():
        if len(vals) >= 4:
            n = len(vals)
            for p in range(2, n // 2 + 1):
                if n % p == 0 and vals[:p] * (n // p) == vals:
                    found[concept] = vals[:p]
                    break

    for text in texts:
        for line in text.splitlines():
            if "__TABLE__" in line:
                continue
            words = line.split()
            i = 0
            while i < len(words):
                concept = _classify_row(words[i])
                consumed = 1
                if concept is None and i + 1 < len(words):
                    # multi-word labels: "Net Profit", "صافي الربح", ...
                    concept = _classify_row(words[i] + " " + words[i + 1])
                    if concept:
                        consumed = 2
                if concept is None and i + 2 < len(words):
                    # three-word labels: "Cost of Sales", "تكلفة المبيعات"...
                    concept = _classify_row(" ".join(words[i: i + 3]))
                    if concept:
                        consumed = 3
                if concept and not _is_summary_row(" ".join(words[i:i + consumed]), concept, from_text=True):
                    tail = " ".join(words[i + consumed: i + consumed + 3])
                    if "%" not in tail:
                        value = _to_number(tail)
                        if value is not None:
                            add(concept, value)
                i += consumed

    return found


def _latest(metrics: dict, concept: str) -> float | None:
    values = metrics.get(concept) or []
    return values[-1] if values else None


def compute_kpis(metrics: dict) -> dict:
    """KPI cards: latest absolute figures.

    The profit line is derived from the captured detail concepts and carries
    its true sign (net loss keeps the negative value). The reported concept
    name reflects reality: net_profit for profit, net_loss for a loss.
    """
    kpis = {}
    labels = {
        "revenue": {"en": "Revenue", "ar": "الإيرادات"},
        "net_profit": {"en": "Net Profit", "ar": "صافي الربح"},
        "assets": {"en": "Total Assets", "ar": "إجمالي الأصول"},
        "cash": {"en": "Cash", "ar": "النقدية"},
    }
    # a STATED bottom line outranks the derived chain: detail-row noise
    # (OCR misreads of opex/tax/finance rows) must not overwrite the
    # statement's own «ربح السنة» series. The chain still wins for
    # statements-built metrics — the quality gate repairs the stated series
    # to the chain BEFORE kpis are rebuilt when they truly disagree.
    stated_np = [v for v in (metrics.get("net_profit") or [])
                 if isinstance(v, (int, float)) and not isinstance(v, bool)]
    stated_net = (stated_np[-1]
                  if stated_np and any(v != 0 for v in stated_np) else None)
    revenue = _latest(metrics, "revenue")
    cogs = _latest(metrics, "cogs")
    opex = _latest(metrics, "opex")
    # a ZERO-ONLY series is an empty/noisy capture (OCR singletons), never a
    # cost basis — deriving gross = revenue − 0 would rename revenue into
    # «net profit» and poison every KPI (same contract as the audit
    # re-derivation guard)
    cogs_series = [v for v in (metrics.get("cogs") or [])
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if cogs is not None and cogs_series and all(v == 0 for v in cogs_series):
        cogs = None

    gross = None
    if revenue is not None and cogs is not None:
        gross = revenue - cogs
    elif _latest(metrics, "gross_profit") is not None:
        gross = _latest(metrics, "gross_profit")

    # IFRS 18 chain: operating result adjusted by the investing/financing/
    # tax categories when such items were captured (statements-built metrics):
    # net = gross − opex + investment_income − finance_cost − tax_expense.
    inv = _latest(metrics, "investment_income")
    fin = _latest(metrics, "finance_cost")
    tax = _latest(metrics, "tax_expense")
    net = stated_net
    if net is not None:
        pass  # the stated bottom line wins
    elif gross is not None and (opex is not None or inv is not None
                              or fin is not None or tax is not None):
        # derived from detail rows (the manual-edit contract: net follows
        # whenever a component value is corrected) — with per-period expense
        # aggregation this reproduces the stated bottom line exactly
        net = (gross - (opex or 0.0)) + (inv or 0.0) - (fin or 0.0) - (tax or 0.0)
    elif gross is not None:
        net = gross  # no expense row captured: gross IS the result
    else:
        net = _latest(metrics, "net_profit")
        # a zero-only captured series is noise, not a stated bottom line
        np_series = [v for v in (metrics.get("net_profit") or [])
                     if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if net is not None and np_series and all(v == 0 for v in np_series):
            net = None

    for concept, lab in labels.items():
        if concept == "net_profit":
            value = net
        else:
            value = _latest(metrics, concept)
        if value is not None:
            entry = {"value": value, **lab}
            if concept == "net_profit" and value < 0:
                entry = {"value": value, "en": "Net Loss", "ar": "صافي الخسارة"}
            kpis[concept] = entry
    return kpis


def compute_ratios(metrics: dict) -> dict:
    """Financial ratios, each as {'value', 'en', 'ar'} or omitted if not computable."""
    ratios: dict[str, dict] = {}

    def put(key: str, value: float | None, en: str | None = None, ar: str | None = None) -> None:
        # التسميات من المصدر الموحد ratio_labels — التعابير الحرفية المرسلة
        # تُقبل كتجاوز اختياري للنسب غير المدرجة هناك فقط.
        from .ratio_labels import RATIO_LABELS
        label = RATIO_LABELS.get(key) or {"en": en or key, "ar": ar or en or key}
        if value is not None:
            ratios[key] = {
                "value": round(value, 2),
                "en": label["en"],
                "ar": label["ar"],
            }

    revenue = _latest(metrics, "revenue")
    gross = _latest(metrics, "gross_profit")
    cogs = _latest(metrics, "cogs")
    net = _latest(metrics, "net_profit")
    opex = _latest(metrics, "opex")
    assets = _latest(metrics, "assets")
    cash = _latest(metrics, "cash")
    liabilities = _latest(metrics, "liabilities")
    equity = _latest(metrics, "equity")
    fin = _latest(metrics, "finance_cost")
    tax = _latest(metrics, "tax_expense")
    inv_income = _latest(metrics, "investment_income")

    # Losses/profits: net derived from detail rows when no explicit net line
    # was captured (summary rows are excluded from raw capture) — the SAME
    # IFRS 18 chain as compute_kpis: operating − financing − taxes + investing.
    if net is None:
        gross_d = revenue - cogs if (revenue is not None and cogs is not None) else gross
        if gross_d is not None and (opex is not None or fin is not None
                                    or tax is not None or inv_income is not None):
            net = ((gross_d or 0.0) - (opex or 0.0)) + (inv_income or 0.0) \
                - (fin or 0.0) - (tax or 0.0)
        elif gross_d is not None:
            net = gross_d

    if revenue:
        if gross is None and cogs is not None:
            gross = revenue - cogs
        if gross is not None and revenue != 0:
            put("gross_margin", gross / revenue * 100, "Gross Margin %", "هامش الربح الإجمالي %")
        if net is not None and revenue != 0:
            put("net_margin", net / revenue * 100, "Net Margin %", "هامش صافي الربح %")

    if assets:
        if liabilities is not None and assets != 0:
            put("debt_ratio", liabilities / assets * 100, "Debt Ratio %", "نسبة الالتزامات %")
            if equity is not None and equity != 0:
                put("debt_to_equity", liabilities / equity, "Debt to Equity", "الالتزامات إلى حقوق الملكية")

    current_assets = _latest(metrics, "current_assets")
    current_liabilities = _latest(metrics, "current_liabilities")
    inventory = _latest(metrics, "inventory")
    if current_assets:
        # the liquidity tests divide by CURRENT liabilities — total
        # liabilities only as a fallback when no current split was captured
        short_term = current_liabilities if current_liabilities is not None else liabilities
        if short_term is not None and short_term != 0:
            put("current_ratio", current_assets / short_term, "Current Ratio", "نسبة التداول")
            quick_basis = current_assets - (inventory or 0)
            if quick_basis > 0:
                put("quick_ratio", quick_basis / short_term, "Quick Ratio", "النسبة السريعة")
    if assets and assets != 0:
        if net is not None:
            put("roa", net / assets * 100, "Return on Assets %", "العائد على الأصول %")
    if equity and equity != 0:
        if net is not None:
            put("roe", net / equity * 100, "Return on Equity %", "العائد على حقوق الملكية %")
    if assets and assets != 0 and revenue:
        put("asset_turnover", revenue / assets, "Asset Turnover", "معدل دوران الأصول")

    # Interest coverage (ratio-explain reference set: EBIT / interest paid).
    # Finance costs are pulled out of generic expenses when the statements
    # are built from a trial balance; file-based analyses fall back to the
    # explicit capture below. Only a positive (debit-side) burden counts:
    # a credit balance means interest income leaking in, not a burden.
    finance_cost = _latest(metrics, "finance_cost")
    interest = _latest(metrics, "interest")
    if finance_cost is not None:
        interest_burden = finance_cost if finance_cost > 0 else None
    elif interest is not None:
        interest_burden = interest if interest > 0 else None
    else:
        interest_burden = None
    if interest_burden:
        ebit = net + interest_burden if net is not None else None
        if ebit is not None:
            put("interest_coverage", ebit / interest_burden,
                "Interest Coverage (x)", "تغطية الفوائد (x)")

    # Activity ratios (analysis methodology): receivables turnover,
    # collection period (days) and inventory turnover — computed only from
    # real statement balances; absent buckets never produce a guess.
    receivables = _latest(metrics, "receivables")
    inventory = _latest(metrics, "inventory")
    if receivables is not None and receivables > 0 and revenue:
        put("receivables_turnover", revenue / receivables,
            "Receivables Turnover (x)", "دوران المدينين (x)")
        put("receivable_days", receivables * 365 / revenue,
            "Collection Period (days)", "فترة التحصيل (يوم)")
    if inventory is not None and inventory > 0 and cogs:
        put("inventory_turnover", cogs / inventory,
            "Inventory Turnover (x)", "دوران المخزون (x)")
        put("inventory_days", inventory * 365 / cogs,
            "Inventory Holding Period (days)", "فترة بقاء المخزون (يوم)")

    # Payables side of the working-capital cycle: payables turnover and
    # payment period (DPO), then the composite cash conversion cycle
    # CCC = collection days + inventory days − payment days. Only real
    # statement balances count — absent buckets never produce a guess.
    payables = _latest(metrics, "payables")
    if payables is not None and payables > 0 and cogs:
        put("payables_turnover", cogs / payables,
            "Payables Turnover (x)", "دوران الدائنين (x)")
        put("days_payable", payables * 365 / cogs,
            "Payment Period (days)", "فترة السداد (يوم)")
    dso = ratios.get("receivable_days", {}).get("value")
    dio = ratios.get("inventory_days", {}).get("value")
    dpo = ratios.get("days_payable", {}).get("value")
    if dso is not None and dio is not None and dpo is not None:
        put("cash_conversion_cycle", dso + dio - dpo,
            "Cash Conversion Cycle (days)", "دورة التحول النقدي (يوم)")

    # ---- دليل النسب الموسّع (توثيق الصور المرجعية عياض الله المراجح) ----
    # ratios computable from ALREADY-captured statement buckets only: no
    # market prices, share counts or cash-flow detail required — absent
    # buckets never produce a guess, matching the module's honesty rule.

    # رأس المال العامل: المتداولة − المتداولة الالتزامات (قيمة نقديّة، ولست نسبة)
    wc = None
    if current_assets is not None and current_liabilities is not None:
        wc = current_assets - current_liabilities
        put("working_capital", wc, "Working Capital", "رأس المال العامل")

    # EBIT: الربح التشغيلي — إيراد − تكلفة − مصاريف تشغيلية (بدون فوائد/ضرائب)
    # أُستخرَج من سلسلة IFRS 18 عند غياب سطر مسمى
    ebit = None
    if revenue is not None and (cogs is not None or opex is not None):
        ebit = revenue - (cogs or 0.0) - (opex or 0.0)
    elif gross is not None and opex is not None:
        ebit = gross - opex
    if ebit is not None and revenue:
        put("operating_margin", ebit / revenue * 100,
            "Operating Margin %", "هامش الربح التشغيلي %")

    # رأس المال المستثمر (IC): الالتزامات + حقوق الملكية — محايد النقدية الدائنة:
    # رخصة ال F22 يقيس العائد على كل المموّل من الغير + الملكية
    invested_capital = None
    if liabilities is not None and equity is not None:
        invested_capital = liabilities + equity
    elif assets is not None:
        invested_capital = assets

    if invested_capital and invested_capital != 0 and ebit is not None:
        put("roce", ebit / invested_capital * 100,
            "Return on Capital Employed %", "العائد على رأس المال المستخدم %")
        # NOPAT = EBIT × (1 − معدل الضريبة الفعلي من القوائم نفسها)
        ebt = ebit + (fin or 0.0)
        tax_rate = (tax / ebt) if (tax is not None and ebt > 0) else None
        nopat = ebit * (1 - min(max(tax_rate or 0.0, 0.0), 1.0))
        put("roic", nopat / invested_capital * 100,
            "Return on Invested Capital %", "العائد على رأس المال المستثمر %")

    # هيكل التمويل والسيولة
    if equity is not None and assets and assets != 0:
        put("equity_ratio", equity / assets * 100,
            "Equity Ratio %", "نسبة الملكية %")
    if cash is not None and current_liabilities and current_liabilities != 0:
        put("cash_ratio", cash / current_liabilities,
            "Cash Ratio", "نسبة النقدية إلى الالتزامات المتداولة")
    if current_assets is not None and assets and assets != 0:
        put("current_assets_share", current_assets / assets * 100,
            "Current Assets / Total Assets %", "نسبة الأصول المتداولة إلى إجمالي الأصول %")

    # ---- نسب التدفقات النقدية (الدليل المرجعي 81/82/83/87) --------------
    # computed ONLY from real cash-flow totals the parser already captures;
    # detail-dependent ratios (capex/dividends/share counts → sufficiency,
    # FCF conversion, per-share) stay absent rather than guessed.
    ocf = _latest(metrics, "cf_operating")
    if ocf is not None:
        if revenue and revenue != 0:
            put("ocf_margin", ocf / revenue * 100,
                "Operating Cash Flow / Sales %", "التدفق النقدي التشغيلي إلى المبيعات %")
        if liabilities and liabilities != 0:
            put("ocf_to_debt", ocf / liabilities,
                "Operating Cash Flow / Total Debt", "التدفق النقدي التشغيلي إلى إجمالي الدين")
        if current_liabilities and current_liabilities != 0:
            put("ocf_liquidity", ocf / current_liabilities,
                "OCF Coverage of Current Liabilities", "تغطية التدفق النقدي للالتزامات المتداولة")
        if net and net != 0:
            put("earnings_quality", ocf / net,
                "Cash Flow Quality of Earnings", "جودة الأرباح (التشغيلي ÷ صافي الربح)")

    return ratios


def compute_series(metrics: dict) -> dict:
    """Time series for charting: any multi-value concept."""
    series = {}
    labels = {
        "revenue": {"en": "Revenue", "ar": "الإيرادات"},
        "assets": {"en": "Total Assets", "ar": "إجمالي الأصول"},
        "liabilities": {"en": "Liabilities", "ar": "الالتزامات"},
        "cash": {"en": "Cash", "ar": "النقدية"},
        "cogs": {"en": "Cost of Sales", "ar": "تكلفة المبيعات"},
        "opex": {"en": "Operating Expenses", "ar": "المصاريف التشغيلية"},
        "receivables": {"en": "Receivables", "ar": "المدينون"},
        "payables": {"en": "Payables", "ar": "الدائنون"},
        "inventory": {"en": "Inventory", "ar": "المخزون"},
        "equity": {"en": "Equity", "ar": "حقوق الملكية"},
        "finance_cost": {"en": "Finance Costs", "ar": "مصاريف التمويل"},
        "tax_expense": {"en": "Zakat & Taxes", "ar": "الزكاة والضرائب"},
    }
    for concept, lab in labels.items():
        values = metrics.get(concept) or []
        if len(values) >= 2:
            series[concept] = {"values": values[:12], **lab}
    return series


def compute_activity_series(metrics: dict) -> dict:
    """Per-period activity ratios for the Excel charts sheet: the collection
    period (days), inventory turnover (x), the payment period (days) and the
    cash conversion cycle CCC = DSO + DIO − DPO — period by period, the same
    formulas compute_ratios applies to the latest period, applied across
    every captured period (a period missing its inputs yields None there;
    a ratio with no qualifying period at all is omitted)."""
    receivables = [abs(v) for v in metrics.get("receivables") or []]
    revenue = [abs(v) for v in metrics.get("revenue") or []]
    inventory = [abs(v) for v in metrics.get("inventory") or []]
    cogs = [abs(v) for v in metrics.get("cogs") or []]
    payables = [abs(v) for v in metrics.get("payables") or []]
    n = max(len(receivables), len(revenue), len(inventory), len(cogs),
            len(payables))

    dso: list[float | None] = []
    inv_turn: list[float | None] = []
    dpo: list[float | None] = []
    ccc: list[float | None] = []
    for i in range(n):
        if i < len(receivables) and i < len(revenue) \
                and receivables[i] > 0 and revenue[i] > 0:
            dso.append(round(receivables[i] * 365 / revenue[i], 2))
        else:
            dso.append(None)
        if i < len(inventory) and i < len(cogs) \
                and inventory[i] > 0 and cogs[i] > 0:
            inv_turn.append(round(cogs[i] / inventory[i], 2))
        else:
            inv_turn.append(None)
        if i < len(payables) and i < len(cogs) \
                and payables[i] > 0 and cogs[i] > 0:
            dpo.append(round(payables[i] * 365 / cogs[i], 2))
        else:
            dpo.append(None)
        # CCC needs all three legs of the working-capital cycle for THAT
        # period — a missing leg leaves a hole instead of a partial cycle
        if dso[-1] is not None and inv_turn[-1] is not None and dpo[-1] is not None:
            dio = round(inventory[i] * 365 / cogs[i], 2)
            ccc.append(round(dso[-1] + dio - dpo[-1], 2))
        else:
            ccc.append(None)

    out: dict = {}
    if any(v is not None for v in dso):
        out["receivable_days"] = {
            "en": "Collection Period (days)", "ar": "فترة التحصيل (يوم)",
            "values": dso,
        }
    if any(v is not None for v in inv_turn):
        out["inventory_turnover"] = {
            "en": "Inventory Turnover (x)", "ar": "دوران المخزون (x)",
            "values": inv_turn,
        }
    if any(v is not None for v in dpo):
        out["days_payable"] = {
            "en": "Payment Period (days)", "ar": "فترة السداد (يوم)",
            "values": dpo,
        }
    if any(v is not None for v in ccc):
        out["cash_conversion_cycle"] = {
            "en": "Cash Conversion Cycle (days)", "ar": "دورة التحول النقدي (يوم)",
            "values": ccc,
        }
    return out


def forecast(series: dict) -> list:
    """One-step linear-regression forecast per series, as percent change."""
    out = []
    for concept, s in series.items():
        values = s["values"]
        n = len(values)
        if n < 2:
            continue
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(values) / n
        denom = sum((x - mean_x) ** 2 for x in xs)
        if denom == 0:
            continue
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
        if mean_y == 0:
            continue
        change = slope / abs(mean_y) * 100
        out.append({
            "concept": concept,
            "en": s["en"],
            "ar": s["ar"],
            "change_pct": round(change, 1),
            "trend": "up" if change > 1 else ("down" if change < -1 else "flat"),
        })
    return out


def _normalise_expense_signs(metrics: dict) -> None:
    """Normalise expense-sign conventions for cogs/opex.

    Income-statement sheets often list تكلفة البضاعة المباعة as a NEGATIVE
    (expense convention). The platform derives gross = revenue - cogs, which
    assumes costs as positive magnitudes — so a wholesale-negative cogs/opex
    series is flipped to absolute values here, once, before any derivation.
    Mixed-sign series are left for the data-hygiene pass (it warns + fixes).
    """
    for concept in ("cogs", "opex", "finance_cost", "tax_expense"):
        values = metrics.get(concept)
        if not values:
            continue
        nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if nums and all(v < 0 for v in nums):
            metrics[concept] = [
                abs(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                for v in values
            ]


# ---------------------------------------------------------------------------
# Confused-concept review: rows the classifier could NOT name but that LOOK
# like a known concept (OCR-mangled labels) — surfaced to the user so the
# concept can be fixed by hand BEFORE the analysis is accepted, with the
# ratios recomputing instantly on every correction.
# ---------------------------------------------------------------------------

# Concept keys a manual correction may assign to: the classifier's own
# vocabulary plus the derived concept result_to_metrics can back-derive.
EDITABLE_CONCEPTS = frozenset(KEYWORDS) | {"gross_profit"}

# fuzzy-match floor: OCR mangling swaps a few characters («تكلغة» for
# «تكلفة», «Revemue» for «Revenue») — below ~0.72 the resemblance is noise.
_FUZZ_MIN = 0.72

# a glued date whose day digits (and an optional single month digit) sit
# before a real year — OCR eats «/» and may drop the month entirely:
# «312025» = «31/12/2025» (31 + 2025), «1012025» = «10/1/2025»
_SQUASHED_DATE_RE = re.compile(r"^(3[01]|[12]\d)\d?(19|20)\d{2}$")
_NUM_TOKEN_RE = re.compile(r"[-+]?\d[\d.,]*")


def _is_squashed_date_number(value) -> bool:
    """True for an OCR-glued date that reads as a bare number.

    Scanned Arabic statements print the header date «31/12/2025» as bare
    312025 in table cells — it passes every numeric filter, and a review
    card whose row is a SECTION HEADER («الأنشطة التشغيلية») collects it
    as the section's values. Accepting that card in the UI prices
    +312,025 into the target concept (a «%» concept then multiplies it
    ×100 ≈ +31,202,500) and poisons the very series the card was meant to
    repair. A date-like 6–7 digit glue (day 1..31 head + 19xx/20xx year
    tail) is therefore dropped from review-card values only; real
    amounts this size are not day/year-shaped («200202» = stock
    200,202 — head «20» + tail «2202», not a year — kept).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if v <= -10000:  # negative glued dates aren't a thing
        n = str(int(-v))
    else:
        if v < 100000:
            return False
        n = str(int(v))
    return bool(_SQUASHED_DATE_RE.fullmatch(n))


def _fuzzy_concept_candidates(label: str, limit: int = 3) -> list[str]:
    """Concept keys whose keywords closely resemble an UNCLASSIFIED label."""
    ns = _ns(str(label or ""))
    if len(ns) < 4:
        return []
    scored: list[tuple[float, str]] = []
    for concept, words in KEYWORDS.items():
        best = 0.0
        for w in words:
            nw = _ns(w)
            if len(nw) < 4:
                continue
            r = difflib.SequenceMatcher(None, ns, nw).ratio()
            if r > best:
                best = r
        if best >= _FUZZ_MIN:
            scored.append((best, concept))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, c in scored[:limit]]


def build_concept_review(tables: list, texts: list, limit: int = 24) -> list[dict]:
    """Rows/text lines whose label resembles a known concept but was NOT
    classified — the OCR-mangled names whose values the analysis silently
    lost. Each item carries a stable ``rid`` the correction endpoint keys
    on, the values read off that row, and the closest concept candidates."""
    items: list[dict] = []
    seen: set[str] = set()

    def add(label: str, values: list, source: str) -> None:
        t = " ".join(str(label or "").split())
        if not t or t in seen or len(items) >= limit:
            return
        if _classify_row(t):
            return  # classified fine — nothing to correct here
        candidates = _fuzzy_concept_candidates(t)
        if not candidates:
            return
        seen.add(t)
        items.append({
            "rid": f"r{len(items)}",
            "label": t[:160],
            "values": [round(float(v), 2) for v in values[:12]
                       if v is not None and not _is_squashed_date_number(v)],
            "candidates": candidates,
            "source": source,
        })

    for table in tables or []:
        rows = table.get("rows") or []
        figure_cols = set(_year_columns(rows))
        for row in rows:
            cells = [("" if c is None else str(c)) for c in (row or [])]
            # the label is the first non-numeric cell; the values are the
            # numeric cells of the detected period columns (fallback: every
            # numeric cell after the label)
            label_idx = next((i for i, c in enumerate(cells)
                              if c.strip() and _to_number(c) is None), None)
            if label_idx is None or label_idx + 1 >= len(cells):
                continue
            vals = []
            for i in range(label_idx + 1, len(cells)):
                n = _to_number(cells[i])
                if n is not None and (not figure_cols or i in figure_cols):
                    vals.append(n)
            add(cells[label_idx], vals, "table")

    for line in texts or []:
        t = " ".join(str(line or "").split())
        if not t or "__TABLE__" in t:
            continue
        vals = [n for n in (_to_number(tok)
                            for tok in _NUM_TOKEN_RE.findall(t))
                if n is not None]
        if not vals:
            continue
        add(_NUM_TOKEN_RE.sub(" ", t).strip(" -:،,"), vals, "text")
    return items


def table_has_financials(table: dict) -> bool:
    """True when a parsed table carries recognisable financial rows — a
    labelled concept with at least one numeric value to its right. Used to
    detect workbooks that hold one statement per sheet (multi-company files)."""
    for row in table.get("rows") or []:
        row = [("" if c is None else c) for c in row]
        for i, cell in enumerate(row):
            concept = _classify_row(str(cell))
            if not concept or _is_summary_row(str(cell), concept):
                continue
            for candidate in row[i + 1:]:
                if _to_number(candidate) is not None:
                    return True
    return False


def table_has_revenue(table: dict) -> bool:
    """True when the table carries its own revenue/sales row WITH a value —
    i.e. the sheet is a self-contained income statement. A balance-sheet
    sheet has assets/liabilities but no revenue row; a period continuation
    of another sheet does not repeat the label with a value either."""
    for row in table.get("rows") or []:
        row = [("" if c is None else c) for c in row]
        for i, cell in enumerate(row):
            if _classify_row(str(cell)) != "revenue":
                continue
            if _is_summary_row(str(cell), "revenue"):
                continue
            if any(_to_number(c) is not None for c in row[i + 1:]):
                return True
    return False


def analyze(tables: list, texts: list, mode: str = "auto") -> dict:
    # analysis_mode routing from the upload screen: «force_trial_balance»
    # tells the extractor to prefer debit/credit column reading over the
    # automatic concept matching (helps trial-balance exports whose labels
    # confuse the concept classifier); other modes are read as auto.
    tb_hint = mode == "force_trial_balance"
    metrics = _extract_metrics(tables, texts, tb_hint=tb_hint)
    _normalise_expense_signs(metrics)
    series = compute_series(metrics)
    result = {
        "kpis": compute_kpis(metrics),
        "ratios": compute_ratios(metrics),
        "series": series,
        "forecast": forecast(series),
        # the TRUE captured metrics ride with the result — deriving them back
        # from kpis+series loses balance-sheet buckets (current_assets,
        # receivables, payables…) and with them the liquidity/CCC ratios
        "metrics": metrics,
        "tables_found": len(tables),
        "texts_found": sum(len(t.splitlines()) for t in texts),
        "analysed_at": datetime.now(timezone.utc).isoformat(),
        "period_labels": _extract_period_labels(tables),
    }
    if tb_hint:
        result["analysis_mode"] = "force_trial_balance"
    # OCR/labels the classifier mangled — the user's review list; correcting
    # one of these via PATCH injects the row's values under the right concept
    # and recomputes the ratios immediately.
    review_items = build_concept_review(tables, texts)
    if review_items:
        result["concept_review"] = {"items": review_items}
    return result


def texts_overview(texts: list, limit: int = 40) -> list:
    return [t for t in texts if "__TABLE__" not in t][:limit]


def texts_sample(texts: list, limit: int = 24, max_len: int = 160) -> list[str]:
    """The extracted text lines worth SHOWING the user — prose documents
    (a scanned report with no financial indicators) keep their reading
    sample on the result so the platform can present the document instead
    of a blank. Empty lines and table markers are dropped; long lines are
    capped (they are a sample, not a transcript)."""
    out: list[str] = []
    for line in texts:
        t = " ".join(str(line or "").split())
        if not t or "__TABLE__" in t:
            continue
        out.append(t[:max_len])
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Rebuilding an analysis result from (possibly user-edited) raw values
# ---------------------------------------------------------------------------

RESULT_META = {
    "revenue": {"en": "Revenue", "ar": "الإيرادات"},
    "net_profit": {"en": "Net Profit", "ar": "صافي الربح"},
    "gross_profit": {"en": "Gross Profit", "ar": "الربح الإجمالي"},
    "assets": {"en": "Total Assets", "ar": "إجمالي الأصول"},
    "liabilities": {"en": "Liabilities", "ar": "الالتزامات"},
    "equity": {"en": "Equity", "ar": "حقوق الملكية"},
    "cash": {"en": "Cash", "ar": "النقدية"},
    "cogs": {"en": "Cost of Sales", "ar": "تكلفة المبيعات"},
    "opex": {"en": "Operating Expenses", "ar": "المصاريف التشغيلية"},
}


def result_to_metrics(result: dict) -> dict[str, list[float]]:
    """Recover {concept: [values]} from a stored analysis result.

    KPIs and series are both derived from the same raw values; the KPI is
    simply the latest value of its concept. Prefer the explicit ``metrics``
    block when present, otherwise reconstruct it from kpis + series.
    """
    stored = result.get("metrics")
    if isinstance(stored, dict) and stored:
        metrics: dict[str, list[float]] = {}
        for concept, values in stored.items():
            nums = [float(v) for v in (values or [])
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums:
                metrics[concept] = nums
        if metrics:
            return metrics

    metrics = {}
    for concept, kpi in (result.get("kpis") or {}).items():
        value = kpi.get("value") if isinstance(kpi, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics.setdefault(concept, []).append(float(value))
    for concept, s in (result.get("series") or {}).items():
        nums = [float(v) for v in (s.get("values") or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if nums:
            existing = metrics.get(concept)
            if existing and existing[-1] == nums[-1]:
                metrics[concept] = existing[:-1] + nums
            else:
                metrics[concept] = nums

    # Ratios may derive from concepts that never made it into kpis/series
    # (e.g. gross margin from cogs, net margin from opex, debt ratio from
    # liabilities). Back-derive their raw values so recomputation keeps
    # those ratios instead of silently dropping them.
    ratios = result.get("ratios") or {}

    def _ratio_value(key: str) -> float | None:
        entry = ratios.get(key)
        value = entry.get("value") if isinstance(entry, dict) else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    revenue = (metrics.get("revenue") or [None])[-1]
    if revenue:
        gross_margin = _ratio_value("gross_margin")
        if gross_margin is not None and not metrics.get("gross_profit") and not metrics.get("cogs"):
            metrics["gross_profit"] = [round(revenue * gross_margin / 100, 2)]
            metrics["cogs"] = [round(revenue - metrics["gross_profit"][0], 2)]
        net_margin = _ratio_value("net_margin")
        if net_margin is not None and not metrics.get("net_profit") and not metrics.get("opex"):
            metrics["net_profit"] = [round(revenue * net_margin / 100, 2)]
        elif net_margin is not None and not metrics.get("opex"):
            # net margin known but opex missing: back-derive opex from
            # gross - net so the recompute chain stays consistent.
            net = (metrics.get("net_profit") or [None])[-1]
            gross_d = (metrics.get("gross_profit") or [None])[-1]
            if net is not None and gross_d is not None:
                metrics["opex"] = [round(gross_d - net, 2)]

    assets = (metrics.get("assets") or [None])[-1]
    if assets:
        debt_ratio = _ratio_value("debt_ratio")
        if debt_ratio is not None and not metrics.get("liabilities"):
            metrics["liabilities"] = [round(assets * debt_ratio / 100, 2)]
        debt_to_equity = _ratio_value("debt_to_equity")
        liabilities = (metrics.get("liabilities") or [None])[-1]
        if (
            debt_to_equity not in (None, 0)
            and liabilities
            and not metrics.get("equity")
        ):
            metrics["equity"] = [round(liabilities / debt_to_equity, 2)]

    return metrics


def recompute_result(result: dict) -> dict:
    """Recompute ratios/series/forecast from raw values, keeping metadata.

    The stored ``metrics`` block is updated so future recomputations chain
    correctly. tables_found / texts_found / analysed_at are preserved.
    """
    metrics = result_to_metrics(result)
    series = compute_series(metrics)
    recomputed = {
        "kpis": compute_kpis(metrics),
        "ratios": compute_ratios(metrics),
        "series": series,
        "forecast": forecast(series),
        "tables_found": result.get("tables_found", 0),
        "texts_found": result.get("texts_found", 0),
        "analysed_at": result.get("analysed_at"),
        "metrics": metrics,
    }
    # keep the original column-header periods across recomputations
    if isinstance(result.get("period_labels"), list) and result["period_labels"]:
        recomputed["period_labels"] = [str(x) for x in result["period_labels"]]
    if isinstance(result.get("original_metrics"), dict) and result["original_metrics"]:
        recomputed["original_metrics"] = result["original_metrics"]
    if result.get("edited_at"):
        recomputed["edited_at"] = result["edited_at"]
    # metadata that must survive every recomputation: data-quality log,
    # quality-gate audit record, the split-workbook sheet binding, the
    # OCR-extraction flag (the audit's suspect-numbers warning reads it),
    # and the extracted-text sample (prose documents — a scanned file with
    # no financial indicators is kept as a document analysis, and the UI
    # shows WHAT was read instead of nothing).
    for key in ("data_quality", "audit", "_sheet", "_ocr_used",
                "_file_kind", "_analysis_mode",
                "texts_sample", "concept_labels", "concept_fixes",
                "concept_review"):
        if key in result:
            recomputed[key] = result[key]
    # the user's corrected concept names ride on top of every recompute
    _apply_concept_labels(recomputed)
    return recomputed


def _apply_concept_labels(result: dict) -> None:
    """Stamp user-corrected concept names onto the kpi/series display
    entries — a confused concept the user renamed (``concept_labels``)
    keeps its corrected name through every recomputation chain."""
    labels = result.get("concept_labels") or {}
    if not isinstance(labels, dict) or not labels:
        return
    for block in ("kpis", "series"):
        for key, entry in (result.get(block) or {}).items():
            lab = labels.get(key)
            if lab and isinstance(entry, dict):
                entry["ar"] = lab
                entry["en"] = lab


def to_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
