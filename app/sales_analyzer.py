"""Sales-operations analyzer.

A sales file (شهر / منطقة / مندوب / عمليات / مبيعات) is NOT a financial
statement: it carries no revenue/cost/assets rows and the financial
analyzer misreads it. This module builds the proper sales analysis:

- per-region aggregates (sales, transactions, avg ticket, growth)
- per-rep aggregates (best rep per region, target achievement, new customers)
- monthly totals + growth trend, peak/low month detection
- strengths/weaknesses extraction + next-month forecast + AI-style
  recommendations

Output shape (JSON-serialisable):

    {
      "sales_analysis": {
        "total_sales": float,
        "total_transactions": int,
        "new_customers": int,
        "months": [...],               # chronological month labels
        "monthly": [{month, sales, transactions, growth}],   # trend
        "regions": [{region, sales, transactions, avg_ticket, growth,
                     best_rep, share_pct}],
        "reps": [{rep, region, sales, transactions, avg_ticket,
                  new_customers, growth}],
        "peak_month": {...}, "low_month": {...},
        "strengths": [...], "weaknesses": [...],
        "forecast_next_month": {sales, growth},
        "recommendations": [...],
      }
    }

``detect_sales_table`` is the router: it inspects parsed Excel/CSV rows
and returns the raw sales records when the table really is sales
operations data (headers = month/region/rep/transactions/sales...), or
None when the table is financial.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

MONTH_ORDER = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]
_MONTH_ALIASES = {
    "jan": 0, "feb": 1, "mar": 2, "apr": 3, "may": 4, "jun": 5,
    "jul": 6, "aug": 7, "sep": 8, "oct": 9, "nov": 10, "dec": 11,
}

# header tokens that identify a sales-operations table (Arabic + English).
# Date- column tokens («التاريخ») are month candidates too: invoice-grain
# sales files carry per-transaction dates, not month labels, and the
# month aggregation derives the month FROM the date.
_H_MONTH = ["الشهر", "الاشهر", "شهر", "التاريخ", "التواريخ", "date"]
_H_REGION = ["المنطقة", "منطقة", "المدينة", "region", "city"]
_H_REP = ["المندوب", "مندوب", "المندوبين", "مسؤول المبيعات", "مسؤول بيع", "اسم المندوب", "بائع", "البائع", "sales rep", "salesperson", "rep", "agent"]
_H_TXNS = ["عدد العمليات", "العمليات", "عمليات", "الكمية", "كمية", "transactions", "deals", "orders", "quantity", "qty"]
# «المبلغ» catches «المبلغ الإجمالي» (invoice total) — a sold-amount header
# the generic «مبيعات» tokens miss. Sales rep/amount tokens are listed so
# that «مسؤول المبيعات» (contains «المبيعات») only lands in rep — the rep
# group is checked FIRST in the header loop.
_H_SALES = ["إجمالي المبيعات", "المبيعات", "مبيعات", "المبلغ", "sales", "revenue", "amount"]
_H_NEWC = ["العملاء الجدد", "عملاء جدد", "new customers", "new clients"]
_H_TARGET = ["هدف", "الهدف", "target"]
# product / item column (المنتج / الصنف ...) for the top-products ranking
_H_PRODUCT = ["المنتج", "المنتجات", "الصنف", "الأصناف", "الأصنام", "صنف", "منتج", "product", "item", "sku"]

_MONTH_RE = re.compile(
    r"(يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|اغسطس|أغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر"
    r"|jan[a-z]*|feb[a-z]*|mar[a-z]*|apr[a-z]*|may|jun[a-z]*|jul[a-z]*|aug[a-z]*|sep[a-z]*|oct[a-z]*|nov[a-z]*|dec[a-z]*)",
    re.IGNORECASE,
)


def _norm(v) -> str:
    """Normalise a header cell for matching: strip, remove diacritics/art."""
    return re.sub(r"\s+", " ", str(v or "").strip()).lower()


def _match(header: str, tokens: list[str]) -> bool:
    h = _norm(header)
    return any(tok in h for tok in tokens)


def _month_index(label: str) -> int | None:
    s = _norm(label)
    # invoice-grain files carry ISO/plain DATES as the «month» column
    # (2026-01-01, 05/03/2026) — the aggregation month is the date's month
    # part. Full-match guards keep invoice numbers («INV-2026-1000»)
    # from being read as October.
    s2 = s.replace(" ", "")
    m = re.fullmatch(r"\d{4}[-/.](\d{1,2})(?:[-/.]\d{1,2})?", s2)
    if m:
        mi = int(m.group(1)) - 1
        if 0 <= mi <= 11:
            return mi
    m = re.fullmatch(r"\d{1,2}[-/.](\d{1,2})[-/.]\d{2,4}", s2)
    if m:
        mi = int(m.group(1)) - 1
        if 0 <= mi <= 11:
            return mi
    for i, m in enumerate(MONTH_ORDER):
        base = _norm(m)
        alt = _norm(m.replace("أ", "ا").replace("ى", "ي"))
        if s == base or s == alt or s.startswith(base) or s.startswith(alt):
            return i
    ls = s[:3]
    return _MONTH_ALIASES.get(ls)


def _num(v) -> float | None:
    """Parse a number that may arrive as «148,000» / «7.6%» / «3,520»."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if v is None:
        return None
    s = str(v).strip().replace("،", "").replace(",", "")
    if not s or s in {"—", "-", "–"}:
        return None
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return x / 100.0 if pct else x


def detect_sales_table(rows: list[list]) -> list[dict] | None:
    """Return sales records when ``rows`` IS sales-operations data.

    A row qualifies when it carries the *rep/region + numeric sales*
    signature (an actual sales grid) instead of financial statement
    concepts. Returns [(month, region, rep, txns, sales, newc), ...] or
    None.
    """
    if not rows or len(rows) < 3:
        return None
    header = rows[0]
    n = len(header)
    # «مسؤول المبيعات / اسم المندوب» contain the generic «مبيعات» token —
    # the rep group is evaluated BEFORE the sales group so the rep column
    # claims its own header instead of pricing the rep name as sales.
    order = (("rep", _H_REP), ("month", _H_MONTH), ("region", _H_REGION),
             ("txns", _H_TXNS), ("sales", _H_SALES), ("newc", _H_NEWC),
             ("product", _H_PRODUCT))
    idx = {}
    for i in range(n):
        h = _norm(header[i])
        if not h:
            continue
        for key, tokens in order + (("target", _H_TARGET),):
            if key in idx:
                continue
            if not _match(h, tokens):
                continue
            if key == "target" and "sales" in idx and idx["sales"] == i:
                continue  # the sales column is not a growth/target column
            idx[key] = i
            break
    # sales data needs: a month or region/rep dimension + numeric sales
    if "sales" not in idx or not ({"month", "region", "rep"} & set(idx)):
        return None
    cols = [idx.get(k) for k in ("month", "region", "rep", "txns", "sales", "newc")]
    records = []
    for row in rows[1:]:
        vals = list(row) + [None] * n
        sales = _num(vals[idx["sales"]])
        if sales is None or sales <= 0:
            continue
        month = str(vals[idx["month"]] or "").strip() if "month" in idx else ""
        region = str(vals[idx["region"]] or "").strip() if "region" in idx else ""
        rep = str(vals[idx["rep"]] or "").strip() if "rep" in idx else ""
        txns = _num(vals[idx["txns"]]) if "txns" in idx else None
        newc = _num(vals[idx["newc"]]) if "newc" in idx else None
        target = _num(vals[idx["target"]]) if "target" in idx else None
        records.append({
            "month": month, "region": region, "rep": rep,
            "txns": int(txns or 0), "sales": sales,
            "new_customers": int(newc or 0),
            "target": target,
            "product": (str(vals[idx["product"]] or "").strip()
                        if "product" in idx else ""),
        })
    # month labels must look like months, not like 2024/ «عام» columns
    mlabels = [r["month"] for r in records if r.get("month")]
    if len(mlabels) >= 3 and sum(1 for m in mlabels if _month_index(m) is not None) / len(mlabels) < 0.6:
        return None
    return records or None


def analyze_sales(records: list[dict]) -> dict:
    """Build the full sales analysis from detected sales records."""
    now = datetime.now(timezone.utc).isoformat()

    # normalized month slots
    for r in records:
        r["_mi"] = _month_index(r.get("month") or "")

    months = sorted({r["_mi"] for r in records if r["_mi"] is not None})
    ordered = [MONTH_ORDER[i] for i in months]

    # ---- monthly totals + growth --------------------------------------
    monthly = []
    for i, mi in enumerate(months):
        rec = [r for r in records if r["_mi"] == mi]
        sales = sum(r["sales"] for r in rec)
        txns = sum(r["txns"] for r in rec)
        growth = None
        if i > 0:
            prev = monthly[-1]["sales"]
            growth = (sales - prev) / prev * 100 if prev else None
        monthly.append({
            "month": ordered[i], "sales": round(sales, 2),
            "transactions": txns, "new_customers": sum(r["new_customers"] for r in rec),
            "growth": None if growth is None else round(growth, 1),
        })

    total_sales = sum(m["sales"] for m in monthly)
    total_txns = sum(m["transactions"] for m in monthly)
    total_newc = sum(m["new_customers"] for m in monthly)

    # ---- per region ----------------------------------------------------
    regions = []
    reg_keys = sorted({r.get("region") or "غير محدد" for r in records})
    for reg in reg_keys:
        rec = [r for r in records if (r.get("region") or "غير محدد") == reg]
        sales = sum(r["sales"] for r in rec)
        txns = sum(r["txns"] for r in rec)
        # region growth: last month vs first month on a per-month basis
        gs = _series_growth(rec, months)
        # best rep inside the region
        reps_here = sorted(
            {r.get("rep") or "غير محدد" for r in rec},
            key=lambda x: -sum(r["sales"] for r in rec if (r.get("rep") or "غير محدد") == x),
        )
        regions.append({
            "region": reg, "sales": round(sales, 2), "transactions": txns,
            "avg_ticket": round(sales / txns, 2) if txns else None,
            "growth": gs, "best_rep": reps_here[0] if reps_here else None,
            "share_pct": round(sales / total_sales * 100, 1) if total_sales else None,
        })
    regions.sort(key=lambda x: -x["sales"])

    # ---- per rep ---------------------------------------------------------
    has_targets = any(r.get("target") for r in records)
    reps = []
    rep_keys = sorted({(r.get("rep") or "غير محدد") for r in records})
    for rep in rep_keys:
        rec = [r for r in records if (r.get("rep") or "غير محدد") == rep]
        sales = sum(r["sales"] for r in rec)
        txns = sum(r["txns"] for r in rec)
        target = sum(r["target"] for r in rec if r.get("target")) if has_targets else None
        reps.append({
            "rep": rep, "sales": round(sales, 2), "transactions": txns,
            "avg_ticket": round(sales / txns, 2) if txns else None,
            "new_customers": sum(r["new_customers"] for r in rec),
            "growth": _series_growth(rec, months),
            "region": ", ".join(sorted({r.get("region") or "غير محدد" for r in rec})),
            "target": round(target, 2) if target else None,
            "achievement_pct": round(sales / target * 100, 1) if target else None,
        })
    reps.sort(key=lambda x: -x["sales"])

    # ---- per product (الأصناف الأكثر مبيعًا) -------------------------
    # only radiates when the file actually carries a product/item column;
    # grid files without it keep an empty list so panel & exports hide
    # the section (the honest-absence UI rule).
    pkeys = sorted({r["product"] for r in records if r.get("product")})
    products = []
    for p in pkeys:
        rec = [r for r in records if r.get("product") == p]
        ps = sum(r["sales"] for r in rec)
        pt = sum(r["txns"] for r in rec)
        # best month for this product (sales within months carrying rows)
        per_month: dict[int, float] = {}
        for r in rec:
            if r["_mi"] is not None:
                per_month[r["_mi"]] = per_month.get(r["_mi"], 0.0) + r["sales"]
        best_mi = max(per_month, key=per_month.get) if per_month else None
        products.append({
            "product": p, "sales": round(ps, 2),
            "units": len(rec),          # عدد صفوف/فواتير هذا الصنف
            "transactions": pt,         # مجموع عمود العمليات/الكمّية (دلالة العمود)
            "avg_ticket": round(ps / pt, 2) if pt else None,
            "share_pct": round(ps / total_sales * 100, 1) if total_sales else None,
            "top_month": MONTH_ORDER[best_mi] if best_mi is not None else None,
        })
    products.sort(key=lambda x: -x["sales"])
    if not has_targets:
        # honest label: achievement needs a target column in the file
        reps_target_note = "لم يُجد عمود أهداف («هدف») في الملف — نسبة تحقيق الأهداف تتطلب بيانات الأهداف"
    else:
        reps_target_note = None

    peak = max(monthly, key=lambda m: m["sales"]) if monthly else None
    low = min(monthly, key=lambda m: m["sales"]) if monthly else None

    strengths, weaknesses = _swot(monthly, regions, reps)
    forecast = _forecast(monthly)
    recs = _recommendations(monthly, regions, reps, peak, low, forecast)

    def _by_month(filter_key: str, pick: list) -> dict:
        """(month -> {sales, transactions, new_customers}) aggregates for a
        region or rep filter — the interactive dashboard's drill-down data.
        Months with NO rows for the subset are skipped (they merge as zero
        on the frontend, showing the real shape instead of a fake flat 0)."""
        agg: dict[int, dict] = {}
        for r in records:
            if (r.get(filter_key) or "غير محدد") not in pick:
                continue
            if r["_mi"] is None:
                continue
            slot = agg.setdefault(r["_mi"], {"sales": 0, "transactions": 0, "new_customers": 0})
            slot["sales"] += r["sales"]
            slot["transactions"] += r["txns"]
            slot["new_customers"] += r["new_customers"]
        return {MONTH_ORDER[mi]: slot for mi, slot in sorted(agg.items())}

    by_region_months = {reg: _by_month("region", [reg]) for reg in reg_keys}
    by_rep_months = {rep: _by_month("rep", [rep]) for rep in rep_keys}

    return {
        "generated_at": now,
        "total_sales": round(total_sales, 2),
        "total_transactions": total_txns,
        "new_customers": total_newc,
        "avg_ticket_overall": round(total_sales / total_txns, 2) if total_txns else None,
        "months": ordered,
        "monthly": monthly,
        "regions": regions,
        "reps": reps,
        "peak_month": peak, "low_month": low,
        "strengths": strengths, "weaknesses": weaknesses,
        "reps_target_note": reps_target_note,
        "forecast_next_month": forecast,
        "recommendations": recs,
        "by_region_months": by_region_months,
        "by_rep_months": by_rep_months,
        "products": products,
    }


def _series_growth(rec: list[dict], months: list[int]) -> float | None:
    """First → last month growth of a subset's monthly sales."""
    if len(months) < 2:
        return None
    s = []
    for mi in months:
        s.append(sum(r["sales"] for r in rec if r["_mi"] == mi))
    first, last = s[0], s[-1]
    if not first:
        return None
    return round((last - first) / first * 100, 1)


def slowdown_alert(sales: dict, threshold: int = 3) -> dict | None:
    """Mirror of the live sales panel's slowdown alert + root-cause
    diagnosis (SalesAnalysis.tsx «momentum» + «diagnosis» memos).

    Walks the monthly MoM growth series backwards; fires once the
    consecutive-decline streak reaches ``threshold`` months (the panel's
    default control value). The diagnosis then scores every region AND
    rep by its OWN growth-rate slide over the same window (sales can rise
    while growth decelerates — the amber case), names the steepest one,
    and decomposes whether the slide came from fewer transactions or a
    smaller average ticket. Returns None exactly when the live alert is
    hidden, so exports stay in lockstep with the on-screen behaviour.
    """
    monthly = sales.get("monthly") or []
    gs = [m["growth"] for m in monthly if m.get("growth") is not None]
    if len(gs) < 2:
        return None
    streak = 0
    for i in range(len(gs) - 1, 0, -1):
        if gs[i] < gs[i - 1]:
            streak += 1
        else:
            break
    if streak < threshold:
        return None
    slowdown = {
        "months": streak,
        "from": gs[len(gs) - 1 - streak],
        "to": gs[-1],
        "negative": gs[-1] < 0,
    }

    # root-cause candidates over the same month span, zero-filled per
    # entity (a subset absent from a month counts as 0 sales there —
    # identical to the frontend reading of the drill-down matrices)
    month_labels = [str(m["month"]) for m in monthly]
    win_len = min(slowdown["months"] + 1, len(month_labels))
    win = month_labels[len(month_labels) - win_len:]

    def _scan(matrix: dict | None, kind: str) -> list:
        cands = []
        for name, ent in (matrix or {}).items():
            ent = ent or {}
            es = [float((ent.get(mo) or {}).get("sales", 0)) for mo in month_labels]
            gse = []
            for i in range(1, len(es)):
                gse.append(round((es[i] - es[i - 1]) / es[i - 1] * 100, 1)
                           if es[i - 1] > 0 else 0.0)
            if len(gse) < slowdown["months"]:
                continue
            st = 0
            for i in range(len(gse) - 1, 0, -1):
                if gse[i] < gse[i - 1]:
                    st += 1
                else:
                    break
            if st < slowdown["months"]:  # not honouring the alert pattern
                continue
            if not any((ent.get(mo) or {}).get("transactions", 0) > 0 for mo in win):
                continue
            cands.append({
                "name": name, "kind": kind,
                "from": gse[len(gse) - 1 - st], "to": gse[-1],
                "drop": round(gse[-1] - gse[len(gse) - 1 - st], 1),
            })
        return cands

    candidates = _scan(sales.get("by_region_months"), "region") + \
        _scan(sales.get("by_rep_months"), "rep")
    candidates.sort(key=lambda c: c["drop"])   # steepest growth slide first

    # transaction-count vs average-ticket decomposition over the window
    win_rows = [m for m in monthly if str(m["month"]) in win]
    t_a = win_rows[0].get("transactions", 0)
    t_b = win_rows[-1].get("transactions", 0)
    s_a = win_rows[0].get("sales", 0)
    s_b = win_rows[-1].get("sales", 0)
    t_drop = (t_b - t_a) / t_a * 100 if t_a else 0.0
    k_drop = ((s_b / t_b - s_a / t_a) / (s_a / t_a) * 100
              if t_a and t_b and s_a else 0.0)
    lever = ({"key": "txns", "drop": round(t_drop, 1)}
             if abs(t_drop) >= abs(k_drop)
             else {"key": "ticket", "drop": round(k_drop, 1)})

    return {
        "slowdown": slowdown,
        "top": candidates[0] if candidates else None,
        "lever": lever,
        "candidates_n": len(candidates),
        "window": win,
        "threshold": threshold,
    }


def _swot(monthly, regions, reps) -> tuple[list, list]:
    strengths, weaknesses = [], []
    if monthly:
        gs = [m["growth"] for m in monthly if m["growth"] is not None]
        if gs:
            avg = sum(gs) / len(gs)
            if avg > 0:
                strengths.append(f"نمو شهري إجمالي إيجابي بمتوسط {avg:.1f}% شهريًا")
            else:
                weaknesses.append(f"متوسط النمو الشهري سالب ({avg:.1f}%) — الاتجاه العام تراجعي")
    if regions:
        top = regions[0]
        strengths.append(f"المنطقة الأقوى: {top['region']} بمبيعات {top['sales']:,.0f} ({top['share_pct']}% من الإجمالي)")
        if len(regions) > 1 and regions[-1]["share_pct"] is not None and regions[-1]["share_pct"] < 30:
            weak_region = regions[-1]
            weaknesses.append(
                f"المنطقة الأضعف: {weak_region['region']} بنصيب {weak_region['share_pct']}% فقط من المبيعات"
            )
    if reps:
        best = reps[0]
        strengths.append(f"أفضل مندوب: {best['rep']} ({best['region']}) بمبيعات {best['sales']:,.0f}")
        if len(reps) > 1 and best["sales"] > 2 * reps[-1]["sales"]:
            weaknesses.append(
                f"فجوة أداء كبيرة بين {best['rep']} و{reps[-1]['rep']} ({best['sales'] / max(1, reps[-1]['sales']):.1f}x)"
            )
    return strengths, weaknesses


def _forecast(monthly) -> dict:
    """Next-month forecast: weighted linear projection over the monthly series."""
    sales = [m["sales"] for m in monthly if m.get("sales") is not None]
    if len(sales) < 2:
        return {"sales": None, "growth": None, "method": "insufficient data"}
    n = len(sales)
    xs = list(range(n))
    wsum = sum(i + 1 for i in xs)
    w = [(i + 1) / wsum for i in xs]  # recent months weigh more
    wm = sum(w[i] * sales[i] for i in range(n))
    value = max(0.0, wm * 1.02)  # +2% momentum-headed projection
    growth = (value - sales[-1]) / sales[-1] * 100 if sales[-1] else None
    return {
        "sales": round(value, 2),
        "growth": None if growth is None else round(growth, 1),
        "method": "weighted linear projection (last months weigh heaviest, +2% momentum)",
    }


def _recommendations(monthly, regions, reps, peak, low, forecast) -> list[dict]:
    out: list[dict] = []
    if peak and low and peak["month"] != low["month"]:
        out.append({
            "ar": f"استثمر نجاح شهر الذروة ({peak['month']}) — كرّر الحملات والعروض التي كانت جارية حينها، وعوّض فجوة شهر الانخفاض ({low['month']}) بعروض موسمية مسبقة.",
            "en": f"Replicate the peak-month playbook ({peak['month']}) and plan seasonal offers ahead of the low month ({low['month']}).",
        })
    if regions and len(regions) > 1:
        weak = regions[-1]
        strong = regions[0]
        out.append({
            "ar": f"انقل ممارسات «{strong['region']}» (أفضل مندوب: {strong['best_rep']}) إلى «{weak['region']}» مع تدريب وفترة متابعة شهرية قابلة للقياس.",
            "en": f"Transfer best-practice from {strong['region']} to {weak['region']} with measurable monthly follow-up.",
        })
    if reps and len(reps) > 1:
        gap = reps[0]["sales"] / max(1, reps[-1]["sales"])
        if gap > 1.5:
            out.append({
                "ar": f"أعد توزيع الأهداف: أدنى مندوب ({reps[-1]['rep']}) يحتاج خطة مكثفة (زيارات أكبر / متابعة العملاء الجدد) للوصول إلى 60% من أداء الأفضل.",
                "en": f"Re-set targets for the lowest-performing rep ({reps[-1]['rep']}) toward 60% of the top rep's level.",
            })
    if forecast.get("growth") is not None and forecast["growth"] < 0:
        out.append({
            "ar": "التنبؤ للشهر القادم يشير إلى تراجع — جهّز حملة تفعيل (حوافز للمناطق المتعثرة) قبل نهاية الشهر الحالي.",
            "en": "Forecast shows a dip — prepare an activation campaign before month-end.",
        })
    elif forecast.get("growth") is not None:
        out.append({
            "ar": f"التنبؤ للشهر القادم إيجابي ({forecast['growth']:+.1f}%) — ثبّت الزخم بمتابعة برنامج العملاء الجدد أسبوعيًا.",
            "en": f"Next-month forecast is positive ({forecast['growth']:+.1f}%) — keep the momentum.",
        })
    return out
