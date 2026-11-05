"""Analysis quality gate — المدقق المركزي لجودة التحليل.

أساس المنصة: المستخدم يرفع ملفًا ويحصل على تحليل ذكي وسريع **صحيح**. كل نتيجة
تحليل (رفع جديد أو إعادة تحليل) تمر على ``run_quality_gate()`` قبل أن تقترب
من قاعدة البيانات. البوابة تجسّد كل صنف خطأ رصدناه في ملفات حقيقية كقاعدة
صريحة مُختبَرة:

  قاتل (يمنع الحفظ — يُترجم لخطأ 422 في طبقة الـAPI):
    C3 GROSS_GT_REVENUE   الربح الإجمالي أكبر من الإيراد — مستحيل رياضيًا
                          (هامش > 100%، عَرَض أعطاب الإشارة غير المعالجة)
    C4 NET_GT_REVENUE     صافي الربح أكبر من الإيراد بلا مصاريف تُشتق منها
    C5 NONPOS_REVENUE     إيراد ≤ 0 بعد معالجة الإشارات — استخراج فاسد
    C7 NO_METRICS         لم يُستخرج أي مؤشر مالي قابل للاستخدام

  يُصلَّح تلقائيًا في المكان (يُسجَّل، غير قاتل):
    R1 WHOLESALE_NEG      سلسلة كاملة مخزّنة سالبة (اصطلاح عمود مصروفات
                          الشامل) → قيم مطلقة، ويشمل الإيراد والأصول والنقدية
    R2 GROSS_INCOHERENT   الإجمالي ≠ الإيراد − التكلفة → يُشتق من جديد
    R3 NET_INCOHERENT     الصافي ≠ الإجمالي − المصاريف (عند توفرها) → يُشتق

  تحذير (يُحفَظ التحليل مع شارة في الواجهة):
    W1 YEARLIKE_REVENUE   الإيراد يساوي رقم سنة (1900–2100) — تسريب خلية
                          ملاحظات نصية (حالة «عام 2024 بقيمة …»)
    W2 DEEP_LOSS_MARGIN   هامش صافٍ أدنى من −500% — مريب لكنه ممكن
    W3 NO_REVENUE         لا يوجد إيراد بين المؤشرات (ملف ميزانية فقط؟)
    W4 BS_IDENTITY_GAP    هوية الميزانية مختلة: الأصول ≠ الالتزامات +
                          حقوق الملكية بفرق يتجاوز 2% من الأصول — أرقام
                          مشكوكة تُحفظ بتحذير بدل قبولها صامتة

  فحص القوائم المالية (يُستدعى من مسار إرفاق القوائم):
    validate_statements() يرفض ميزانية غير متوازنة أو قائمة دخل غير مترابطة
    (الإجمالي ≠ الإيراد − التكلفة، أو الصافي ≠ الإجمالي − المصاريف).

سجل الفحص يُخزَّن مع النتيجة في ``result["audit"]`` فتعرضه الواجهة كشارة:
أخضر «مدقق» عند سلامة كاملة، كهرماني بعدد التحذيرات، أحمر عند أخطاء صفوف قديمة.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .analyzer import recompute_result

# Concepts that are positive by nature in this platform's convention; a
# WHOLESALE-negative series (every value < 0) is an expense-column sign
# convention leaking through and is flipped to absolute magnitudes.
_POSITIVE_BY_NATURE = ("revenue", "cogs", "opex", "assets", "cash")

_YEAR_LIKE = re.compile(r"^(?:19|20)\d{2}(?:\.0+)?$")
_TOL_FRACTION = 0.005  # 0.5% coherence tolerance on derived quantities
_DEEP_LOSS = -500.0    # net-margin percent below which we warn
# Balance-sheet identity (الأصول = الالتزامات + حقوق الملكية): a gap larger
# than this fraction of total assets means the extracted balance sheet does
# not hold together — the figures are suspect and are warned about (W4),
# not silently accepted.
_BS_GAP_FRACTION = 0.02  # 2% of total assets


def _nums(values) -> list[float]:
    if not isinstance(values, list):
        return []
    return [
        float(v) for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]


def _last(metrics: dict, concept: str) -> float | None:
    vals = _nums(metrics.get(concept))
    return vals[-1] if vals else None


def check_balance_sheet_identity(result: dict) -> dict | None:
    """Balance-sheet identity check (الأصول = الالتزامات + حقوق الملكية).

    Runs on the LAST captured period of the three totals (balance-sheet
    concepts are end-aligned in the statements builder, so the latest value
    is the current balance sheet). The gap is measured relative to total
    assets — the identity's own scale: assets that do not equal their
    financing within 2% mean the extraction mixed rows from different
    statements and the figures are suspect.

    Returns ``{"gap", "gap_pct", "assets", "liabilities", "equity"}``
    when all three totals exist AND the gap breaches the threshold, else
    None (missing sides are the W3 no-revenue / partial-capture cases, not
    a broken identity — nothing to assert without both sides).
    """
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return None
    assets = _last(metrics, "assets")
    liabilities = _last(metrics, "liabilities")
    equity = _last(metrics, "equity")
    if assets is None or liabilities is None or equity is None:
        return None
    if assets <= 0:
        return None
    gap = assets - (liabilities + equity)
    gap_pct = abs(gap) / assets * 100
    if gap_pct <= _BS_GAP_FRACTION * 100:
        return None
    return {
        "gap": round(gap, 2),
        "gap_pct": round(gap_pct, 2),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
    }


def _issue(code: str, severity: str, ar: str, en: str) -> dict:
    return {"code": code, "severity": severity, "ar": ar, "en": en}


def _tol(*magnitudes: float | None) -> float:
    m = max((abs(x) for x in magnitudes if x is not None), default=0.0)
    return max(1.0, m * _TOL_FRACTION)


def _refresh(result: dict) -> None:
    """Rebuild kpis/ratios/series/forecast from the (repaired) metrics while
    keeping every metadata key (period_labels, _sheet, data_quality, …)."""
    rebuilt = recompute_result(result)
    result.clear()
    result.update(rebuilt)


def _ensure_metrics(result: dict) -> dict | None:
    """Guarantee a usable metrics block; back-derive one from kpis when the
    metrics block was never stored (legacy rows)."""
    metrics = result.get("metrics")
    if isinstance(metrics, dict) and any(_nums(v) for v in metrics.values()):
        return metrics
    kpis = result.get("kpis") or {}
    derived = {
        concept: [kpi["value"]]
        for concept, kpi in kpis.items()
        if isinstance(kpi, dict)
        and isinstance(kpi.get("value"), (int, float))
        and not isinstance(kpi["value"], bool)
    }
    if derived:
        result["metrics"] = derived
        return derived
    return None


def _repair_series(metrics: dict, concept: str, apply: bool = True) -> int:
    """Flip a wholesale-negative series to absolute values. Returns the
    number of flipped values (0 when the series is not wholesale-negative).

    With ``apply=False`` (check-only mode) nothing is mutated; the return
    value is the number of values that WOULD be flipped.
    """
    values = metrics.get(concept)
    nums = _nums(values)
    if not nums or not all(v < 0 for v in nums):
        return 0
    if not apply:
        return len(nums)
    metrics[concept] = [
        abs(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
        for v in values
    ]
    return len(nums)


def _rederive_net_chain(metrics: dict, apply: bool = True) -> int:
    """IFRS 18 net-profit coherence: net = gross − opex + investment_income
    − finance_cost − tax_expense, over whichever category series are present
    (statements-built metrics carry them). Falls back to the plain
    gross − opex derivation when no category component exists.
    Returns the number of repaired (or, in check-only mode, mismatched)
    values."""
    signed = (
        ("gross_profit", 1.0),
        ("opex", -1.0),
        ("investment_income", 1.0),
        ("finance_cost", -1.0),
        ("tax_expense", -1.0),
    )
    present = {c: _nums(metrics.get(c)) for c, _ in signed}
    # the chain needs its TOP: when gross_profit was never captured the
    # components are a partial read (tax/opex rows seen without the gross
    # line — mixed regions of one sheet) and summing the present ones
    # treats the missing top as zero: «net = −opex − tax». That derived
    # value must never overwrite the face's own stated bottom line, which
    # may legitimately carry deductions below the tax line the generic
    # chain cannot see (branch-manager %, executive %) — تعاليم «الراشد
    # January-2026» multi-company workbook. (The gross−opex fallback below
    # already no-ops without gross; this guard closes the tax-present
    # branch that silently skipped the missing top.)
    if not present["gross_profit"]:
        return 0
    if not any(present[c] for c in ("investment_income", "finance_cost", "tax_expense")):
        return _rederive_series(metrics, "net_profit", "gross_profit", "opex", apply=apply)

    current = _nums(metrics.get("net_profit")) or []
    lengths = {len(v) for v in present.values() if v}
    partial = len(lengths) != 1
    if len(lengths) == 1:
        n = lengths.pop()
        expected = [
            round(sum(sign * present[c][i] for c, sign in signed if present[c]), 2)
            for i in range(n)
        ]
    else:
        # partial capture: validate the KPI-level (latest) values only
        partial = True
        expected = [
            round(sum(sign * present[c][-1] for c, sign in signed if present[c]), 2)
        ]
        current = current[-1:]
    if not expected:
        return 0
    tol = _tol(*[v[-1] for v in present.values() if v], expected[-1],
               current[-1] if current else None)
    if len(current) == len(expected) and all(
        abs(c - e) <= tol for c, e in zip(current, expected)
    ):
        return 0
    if not apply:
        if len(current) != len(expected):
            return len(expected)
        return sum(1 for c, e in zip(current, expected) if abs(c - e) > tol)
    # a PARTIAL chain (components captured with different period counts,
    # typical of OCR detail rows) must not collapse a multi-period STATED
    # bottom line to a single derived value — the statement's own series
    # outranks a chain assembled from noisy component rows
    if partial and len(_nums(metrics.get("net_profit")) or []) > 1:
        return 0
    # a stated multi-point bottom line whose HEAD reconciles with the main
    # chain (stated[0] == gross − opex) is the face's own allocation chain:
    # the face continues below the tax line with rows the generic chain
    # cannot see (branch-manager %, executive %) — collapsing it to the
    # single-point derived value would ERASE those real deductions
    # (الراشد January-2026 multi-company reports)
    if len(current) >= 2 and len(expected) == 1:
        gp_vals = _nums(metrics.get("gross_profit"))
        ox_vals = _nums(metrics.get("opex"))
        if gp_vals and ox_vals:
            head = gp_vals[0] - ox_vals[0]
            if abs(current[0] - head) <= _tol(gp_vals[0], ox_vals[0],
                                              head, current[0]):
                return 0
    metrics["net_profit"] = expected
    return len(expected)


def _rederive_series(metrics: dict, target: str, a: str, b: str,
                     apply: bool = True) -> int:
    """Rebuild ``target = a - b`` per period when the stored series
    contradicts the derivation. Returns the number of repaired values.

    With ``apply=False`` (check-only mode) the incoherence is only counted,
    never written.
    """
    a_vals, b_vals = _nums(metrics.get(a)), _nums(metrics.get(b))
    if not a_vals or not b_vals:
        return 0
    # fabricating a missing basis is not a «repair»: when the subtracted
    # side is a zero-singleton (concept absent from the capture, e.g. an
    # OCR file with no legible cost rows) deriving target = a − 0 would
    # rename one concept into another (revenue → «net_profit») and poison
    # every downstream read. Leave the capture untouched instead.
    if b_vals == [0.0] or (len(b_vals) == 1 and b_vals[0] == 0.0):
        return 0
    if len(a_vals) != len(b_vals):
        # period counts disagree (partial extraction) — repair the KPI only
        a_vals, b_vals = a_vals[-1:], b_vals[-1:]
    expected = [round(x - y, 2) for x, y in zip(a_vals, b_vals)]
    current = _nums(metrics.get(target)) or []
    tol = _tol(a_vals[-1], b_vals[-1])
    if len(current) == len(expected) and all(
        abs(c - e) <= tol for c, e in zip(current, expected)
    ):
        return 0
    if not apply:
        return len(expected)
    metrics[target] = expected
    return len(expected)


def validate_statements(cand: dict) -> list[str]:
    """Deep validation of a built-statements candidate (arabic reasons).

    Returns a list of problems; empty list = statements are coherent and
    safe to attach. Checks the trial balance AND the built statements:
    the balance sheet must balance, and the income statement must tie
    (gross = revenue − cogs, net = gross − opex).
    """
    problems: list[str] = []
    if not isinstance(cand, dict):
        return ["بنية القوائم غير صالحة"]

    tb = cand.get("trial_balance") or {}
    if not tb.get("balanced"):
        problems.append("ميزان المراجعة غير متوازن")

    bs = cand.get("balance_sheet") or {}
    if bs and not bs.get("balanced"):
        diff = bs.get("difference")
        problems.append(
            f"الميزانية العمومية غير متوازنة (فرق {diff})"
            if diff is not None
            else "الميزانية العمومية غير متوازنة"
        )

    isx = cand.get("income_statement") or {}

    def _val(block: dict, key: str) -> float | None:
        """Read a flat key, falling back to the nested ``totals`` block that
        build_statements produces (so the tie checks actually run on built
        statements, not only on flat candidates)."""
        v = block.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            v = (block.get("totals") or {}).get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    revenue, cogs = _val(isx, "revenue"), _val(isx, "cogs")
    gross, opex = _val(isx, "gross_profit"), _val(isx, "opex")
    net = _val(isx, "net_profit")
    if revenue is not None and cogs is not None and gross is not None:
        if abs(gross - (revenue - cogs)) > _tol(revenue, cogs):
            problems.append("قائمة الدخل غير مترابطة: الربح الإجمالي ≠ الإيراد − التكلفة")
    if gross is not None and opex is not None and net is not None:
        # IFRS 18 chain: net = gross − opex + investing − financing − taxes
        inv, fin, tax = _val(isx, "investment_income"), _val(isx, "finance_cost"), _val(isx, "tax_expense")
        expected_net = gross - opex + (inv or 0.0) - (fin or 0.0) - (tax or 0.0)
        if abs(net - expected_net) > _tol(gross, opex):
            problems.append(
                "قائمة الدخل غير مترابطة: صافي الربح ≠ الربح التشغيلي ± فئات IFRS 18"
                if (inv or fin or tax)
                else "قائمة الدخل غير مترابطة: صافي الربح ≠ الإجمالي − المصاريف"
            )
    operating = _val(isx, "operating_profit")
    if operating is not None and gross is not None:
        if abs(operating - (gross - (opex or 0.0))) > _tol(gross, opex):
            problems.append("الربح التشغيلي ≠ الإجمالي − المصاريف التشغيلية")
    return problems


def _suspect_ocr_value(value: float) -> bool:
    """Digit-pattern verdicts that almost never appear in a REAL statement:
    zigzag groups (4,9,4,9,4,9...) come from OCR reading a right-aligned
    amount boxwise, tiny odd remainders (163, 274) are truncated tails of
    swallowed groups — amounts ending in a non-round digit run through
    real ledgers constantly. Used ONLY for the OCR-flagged warning."""
    d = [int(c) for c in str(int(abs(value)))]
    if len(d) >= 4 and len(set(d)) == 2:
        # a,b,a,b,... zigzag over the whole digit run
        if all(d[i] == d[i % 2] for i in range(len(d))):
            return True
    if 100 <= abs(value) <= 999 and abs(value) % 2 == 1:
        return True
    return False


# A per-period series (balance-sheet/P&L concept) should carry one reading
# per period — more than this many non-zero values means OCR rows from
# several different lines were misattributed to the concept (the scanned
# al-Marāʾī balance yields a 14-value «cash» soup) and EVERY value in it
# is then doubtful.
_SUSPECT_MAX_READINGS = 6


def flag_suspect_ocr_numbers(result: dict) -> int:
    """Warn when OCR-sourced numbers carry read-corruption patterns.

    Two classes, both OCR-only:
    - digit-pattern corruption (``_suspect_ocr_value``: zigzag runs, odd
      3-digit remainders),
    - concept-level misattribution: a concept series carrying more
      non-zero readings than any plausible period count (rows collapsed
      into the wrong concept by the scanned-grid parser).
    Sets ``result["ocr_confidence"] = {"suspect", "suspect_concepts"}``
    and appends a W3 warning to ``result["audit"]["warnings"]`` when the
    audit record already exists (a second gate pass after a reanalysis).
    Returns the number of suspect values found.
    """
    if not result.get("_ocr_used"):
        return 0
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return 0
    suspect: list[str] = []
    for concept, series in metrics.items():
        if not isinstance(series, list):
            continue
        nums = [
            v for v in series
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0
        ]
        if len(nums) > _SUSPECT_MAX_READINGS:
            # misattributed rows: the concept cannot honestly carry this
            # many readings — treat the whole series as doubtful
            if concept not in suspect:
                suspect.append(concept)
            continue
        for v in nums:
            if _suspect_ocr_value(v):
                if concept not in suspect:
                    suspect.append(concept)
                break
    result["ocr_confidence"] = {
        "suspect": bool(suspect),
        "suspect_concepts": suspect,
    }
    if suspect:
        from .hygiene import _AR_NAMES, _EN_NAMES
        names_ar = " و".join(_AR_NAMES.get(c, c) for c in suspect)
        names_en = " & ".join(_EN_NAMES.get(c, c) for c in suspect)
        warning = _issue(
            "W3", "warning",
            f"قُرئت الأرقام ضوئيًا (OCR) وقد تحتوي قيمًا مشكوكًا فيها في: {names_ar} "
            "— راجع الأرقام أو ارفع نسخة نصية/Excel",
            f"Numbers were OCR-read and may carry suspect values in: {names_en} "
            "— review the figures or upload a text/Excel copy",
        )
        audit = result.get("audit")
        if isinstance(audit, dict):
            audit.setdefault("warnings", []).append(warning)
            audit["ok"] = False
    return len(suspect)


def run_quality_gate(result: dict, apply_repairs: bool = True) -> dict:
    """Validate + repair an analysis result IN PLACE, before persistence.

    With ``apply_repairs=False`` the gate runs in **check-only** mode: the
    same rules are evaluated against the values exactly as stored, would-be
    repairs (R1/R2/R3) are reported as warnings instead of being applied,
    and the stored record is tagged ``"mode": "check_only"``. This backs the
    audit backfill for legacy rows whose historical figures must not change.

    Returns a gate report:
      {"ok": no errors, "fatal": bool, "messages": [ar error messages],
       "warnings": count, "repairs": count}

    ``result["audit"]`` carries the full bilingual issue log for the UI badge.
    Fatal results must NOT be persisted — the API layer turns them into 422.
    """
    issues: list[dict] = []
    repairs: list[dict] = []

    metrics = _ensure_metrics(result)
    if metrics is not None and "kpis" not in result:
        # self-sufficiency: validate legacy/partial results too — kpis and
        # ratios are rebuilt from the metrics block when they were never
        # computed (or were stripped upstream)
        _refresh(result)
        metrics = result["metrics"]
    if metrics is None:
        issues.append(_issue(
            "C7", "error",
            "لم يُستخرج أي مؤشر مالي قابل للاستخدام من الملف — تحقق من أن الملف يحتوي أرقامًا مالية فعلية",
            "No usable financial indicators were extracted — make sure the file contains real financial figures",
        ))
        report = {
            "ok": False, "fatal": True,
            "messages": [i["ar"] for i in issues if i["severity"] == "error"],
            "warnings": 0, "repairs": 0,
        }
        result["audit"] = {
            "ok": False, "errors": issues, "warnings": [], "repairs": [],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            **({"mode": "check_only"} if not apply_repairs else {}),
        }
        return report

    # ---- R1: wholesale-negative series (expense-column convention) --------
    flipped = 0
    flipped_concepts = []
    for concept in _POSITIVE_BY_NATURE:
        n = _repair_series(metrics, concept, apply=apply_repairs)
        if n:
            flipped += n
            flipped_concepts.append(concept)
            if apply_repairs:
                repairs.append(_issue(
                    "R1", "repair",
                    f"سلسلة «{concept}» كانت مخزّنة سالبة بالكامل (اصطلاح عمود مصروفات) — قُلبت لقيم مطلقة ({n} قيمة)",
                    f"The {concept} series was stored entirely negative (expense-column convention) — flipped to absolute values ({n} values)",
                ))
            else:
                issues.append(_issue(
                    "R1", "warning",
                    f"سلسلة «{concept}» مخزّنة سالبة بالكامل (اصطلاح عمود مصروفات) — رُصدت في الفحص دون تعديل الأرقام ({n} قيمة)",
                    f"The {concept} series is stored entirely negative (expense-column convention) — flagged without modifying the figures ({n} values)",
                ))
    if flipped:
        _refresh(result)
        metrics = result["metrics"]

    # ---- R2: gross profit coherence ---------------------------------------
    # re-derivation repairs a STORED gross_profit; synthesizing the top of
    # the P&L when the capture never saw it (then chaining net off that
    # synthesized top in R3) is a double derivation that erases stated
    # figures — compute_ratios already derives the margin from
    # revenue − cogs for display without mutating anything.
    if _nums(metrics.get("gross_profit")) and _rederive_series(
            metrics, "gross_profit", "revenue", "cogs",
            apply=apply_repairs):
        if apply_repairs:
            repairs.append(_issue(
                "R2", "repair",
                "الربح الإجمالي لم يكن مساويًا للإيراد − التكلفة — أُعيد اشتقاقه",
                "Gross profit did not equal revenue − cost of sales — re-derived",
            ))
            _refresh(result)
            metrics = result["metrics"]
        else:
            issues.append(_issue(
                "R2", "warning",
                "الربح الإجمالي لا يساوي الإيراد − التكلفة كما هو مخزّن — رُصد دون إعادة اشتقاق",
                "Stored gross profit does not equal revenue − cost of sales — flagged without re-derivation",
            ))

    # ---- R3: net profit coherence (IFRS 18 chain when category items exist) -
    if _rederive_net_chain(metrics, apply=apply_repairs):
        if apply_repairs:
            repairs.append(_issue(
                "R3", "repair",
                "صافي الربح لم يكن مساويًا للإجمالي − المصاريف التشغيلية — أُعيد اشتقاقه",
                "Net profit did not equal gross profit − operating expenses — re-derived",
            ))
            _refresh(result)
            metrics = result["metrics"]
        else:
            issues.append(_issue(
                "R3", "warning",
                "صافي الربح لا يساوي الإجمالي − المصاريف التشغيلية كما هو مخزّن — رُصد دون إعادة اشتقاق",
                "Stored net profit does not equal gross profit − operating expenses — flagged without re-derivation",
            ))

    # ---- Fatal + warning checks on the (repaired) values -------------------
    revenue = _last(metrics, "revenue")
    gross = _last(metrics, "gross_profit")
    net = _last(metrics, "net_profit")
    opex = _last(metrics, "opex")
    cogs = _last(metrics, "cogs")

    if revenue is None:
        issues.append(_issue(
            "W3", "warning",
            "لم يُستخرج إيراد من الملف — قد يكون ملف ميزانية فقط أو بلا قائمة دخل",
            "No revenue was extracted — the file may be balance-sheet only",
        ))
    else:
        if revenue <= 0:
            issues.append(_issue(
                "C5", "error",
                f"الإيراد المستخرج غير موجب ({revenue}) — استخراج فاسد رُفض حفظه",
                f"Extracted revenue is not positive ({revenue}) — corrupt extraction rejected",
            ))
        elif _YEAR_LIKE.match(f"{revenue}"):
            issues.append(_issue(
                "W1", "warning",
                "الإيراد يساوي رقم سنة (مثل 2024) — يُرجى التأكد من عدم التقاط خلية ملاحظات نصية بدل رقم",
                "Revenue equals a calendar year — please verify a note cell was not parsed as the figure",
            ))
        elif gross is not None and gross > revenue + _tol(revenue):
            issues.append(_issue(
                "C3", "error",
                f"الربح الإجمالي ({gross:,.2f}) أكبر من الإيراد ({revenue:,.2f}) — مستحيل رياضيًا (هامش يتجاوز 100%)",
                f"Gross profit ({gross:,.2f}) exceeds revenue ({revenue:,.2f}) — mathematically impossible (margin over 100%)",
            ))
        elif (
            net is not None
            and net > revenue + _tol(revenue)
            and (opex is None or cogs is None)
        ):
            issues.append(_issue(
                "C4", "error",
                f"صافي الربح ({net:,.2f}) أكبر من الإيراد ({revenue:,.2f}) بلا مصاريف تُشتق منها — نتائج مختلطة رُفضت",
                f"Net profit ({net:,.2f}) exceeds revenue ({revenue:,.2f}) with no expenses to derive from — rejected",
            ))
        elif net is not None and revenue > 0:
            margin = net / revenue * 100
            if margin < _DEEP_LOSS:
                issues.append(_issue(
                    "W2", "warning",
                    f"هامش الربح الصافي مأزوم جدًا ({margin:,.1f}%) — تأكد من صحة الأعمدة المستخرجة",
                    f"Net margin is extremely deep ({margin:,.1f}%) — verify the extracted columns",
                ))

    # ---- W4: balance-sheet identity (الأصول = الالتزامات + حقوق الملكية) ---
    # checked on the FINAL repaired values: after R1-R3 the stored totals
    # are as coherent as they will ever be — a remaining identity gap is
    # extraction noise (rows mixed from different statements), warned
    # about, never silently accepted
    bs_gap = check_balance_sheet_identity(result)
    if bs_gap:
        issues.append(_issue(
            "W4", "warning",
            f"قائمة المركز المالي غير متوازنة: الأصول ({bs_gap['assets']:,.0f}) ≠ "
            f"الالتزامات + حقوق الملكية ({bs_gap['liabilities'] + bs_gap['equity']:,.0f}) "
            f"بفرق {bs_gap['gap']:,.0f} ({bs_gap['gap_pct']:.1f}%) — الأرقام مشكوك فيها، راجع الملف أو أعد الرفع",
            f"Balance sheet does not balance: assets ({bs_gap['assets']:,.0f}) ≠ "
            f"liabilities + equity ({bs_gap['liabilities'] + bs_gap['equity']:,.0f}) "
            f"— gap {bs_gap['gap']:,.0f} ({bs_gap['gap_pct']:.1f}%); the figures are suspect, review the file",
        ))

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    result["audit"] = {
        "ok": not errors and not warnings,
        "errors": errors,
        "warnings": warnings,
        "repairs": repairs,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **({"mode": "check_only"} if not apply_repairs else {}),
    }
    # OCR read-confidence: flag suspect digit patterns BEFORE returning so
    # the W3 warning counts in the UI badge immediately
    flag_suspect_ocr_numbers(result)
    final_warnings = (result.get("audit") or {}).get("warnings") or []
    return {
        "ok": not errors,
        "fatal": bool(errors),
        "messages": [i["ar"] for i in errors],
        "warnings": len(final_warnings),
        "repairs": len(repairs),
    }
