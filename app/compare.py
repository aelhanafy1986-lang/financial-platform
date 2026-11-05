"""Comparison engine: side-by-side comparison of two analyses with deltas.

Given two stored analysis results (older "base" and newer "target"), produces:
  - kpis   : per-concept rows {ar, en, base, target, change_pct}
  - ratios : same shape for financial ratios
  - series : per-concept {base_values, target_values} for dual charts

Deltas are computed on the *latest* value of each concept on each side.
Concepts missing on either side are skipped (never guessed), and division by
zero / None is guarded.
"""

from __future__ import annotations

# Concepts/ratios where an INCREASE is bad (costs & leverage) — every other
# concept reads as improved when it rises (revenue, profit, assets, cash,
# margins, returns, liquidity...).
_LOWER_IS_BETTER = {
    "cogs", "opex", "liabilities",
    "debt_ratio", "debt_to_equity",
}


def _verdict(concept: str, change_pct: float) -> str | None:
    """Judgment-based colour verdict: 'good' | 'bad' | None (flat)."""
    if abs(change_pct) <= 0.05:
        return None
    good = (change_pct < 0) if concept in _LOWER_IS_BETTER else (change_pct > 0)
    return "good" if good else "bad"


def _pct_change(base: float, target: float) -> float | None:
    if base is None or target is None or base == 0:
        return None
    return round((target - base) / abs(base) * 100, 1)


def _latest_value(entry: dict) -> float | None:
    """Latest value of a KPI/ratio entry: {'value': x} -> x."""
    value = entry.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _latest_series_value(series_entry: dict) -> float | None:
    values = series_entry.get("values") or []
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return nums[-1] if nums else None


def _build_rows(base_map: dict, target_map: dict, base_series: dict | None = None,
                target_series: dict | None = None) -> dict:
    """Generic per-concept delta rows over two {'concept': entry} maps.

    When the matching series are supplied, each row also carries ``history``:
    the base analysis's series followed by the target's last value — the
    timeline the sparkline draws in the UI.
    """
    base_series = base_series or {}
    target_series = target_series or {}
    rows = {}
    for concept, target_entry in target_map.items():
        base_entry = base_map.get(concept)
        if not base_entry:
            continue
        target_value = _latest_value(target_entry)
        base_value = _latest_value(base_entry)
        change = _pct_change(base_value, target_value)
        if change is None:
            continue

        history: list[float] = []
        base_hist = _series_numbers((base_series.get(concept) or {}).get("values"))
        target_hist = _series_numbers((target_series.get(concept) or {}).get("values"))
        if len(base_hist) >= 2:
            history = base_hist[-5:] + target_hist[-1:]
            history = history[-6:]

        rows[concept] = {
            "ar": target_entry.get("ar") or base_entry.get("ar") or concept,
            "en": target_entry.get("en") or base_entry.get("en") or concept,
            "base": base_value,
            "target": target_value,
            "change_pct": change,
            "verdict": _verdict(concept, change),
            "history": [round(v, 2) for v in history],
        }
    return rows


def _series_numbers(values) -> list[float]:
    if not isinstance(values, list):
        return []
    return [float(v) for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def compare_results(base_result: dict, target_result: dict) -> dict:
    """Compare two analysis-result dicts, returning kpis/ratios/series deltas."""
    base_series_map = base_result.get("series") or {}
    target_series_map = target_result.get("series") or {}
    kpis = _build_rows(
        base_result.get("kpis") or {}, target_result.get("kpis") or {},
        base_series_map, target_series_map,
    )
    ratios = _build_rows(
        base_result.get("ratios") or {}, target_result.get("ratios") or {},
    )

    series = {}
    for concept, target_entry in target_series_map.items():
        base_entry = base_series_map.get(concept)
        if not base_entry:
            continue
        base_values = list(base_entry.get("values") or [])
        target_values = list(target_entry.get("values") or [])
        change = _pct_change(
            _latest_series_value(base_entry), _latest_series_value(target_entry)
        )
        if change is None:
            continue
        series[concept] = {
            "ar": target_entry.get("ar") or base_entry.get("ar") or concept,
            "en": target_entry.get("en") or base_entry.get("en") or concept,
            "base_values": base_values,
            "target_values": target_values,
            "change_pct": change,
            "verdict": _verdict(concept, change),
        }

    return {"kpis": kpis, "ratios": ratios, "series": series}


def _display_name(row) -> str:
    """User-defined analysis name if set, otherwise the stored filename."""
    return getattr(row, "display_name", None) or row.filename


def compare_sales(base_result: dict, target_result: dict) -> dict | None:
    """Side-by-side SALES analysis: two sales-kind analyses compare through
    their sales_detection payloads (regions / reps / monthly trend) — the
    financial concept compare returns nothing for them, which read as «لا
    توجد بنود مشتركة». Returns a ``sales`` block or None when either side
    carries no sales data."""
    base_sales = base_result.get("sales_analysis") if base_result.get("kind") == "sales" else None
    target_sales = target_result.get("sales_analysis") if target_result.get("kind") == "sales" else None
    if not isinstance(base_sales, dict) or not isinstance(target_sales, dict):
        return None

    rows = {}
    # concept -> {ar, en, base, target, change_pct, verdict}
    for key, ar, en, lower in (
        ("total_sales", "إجمالي المبيعات", "Total sales", False),
        ("total_transactions", "عدد العمليات", "Transactions", False),
        ("new_customers", "العملاء الجدد", "New customers", False),
    ):
        b, t = base_sales.get(key), target_sales.get(key)
        if isinstance(b, (int, float)) and isinstance(t, (int, float)) and b:
            ch = _pct_change(float(b), float(t))
            if ch is not None:
                rows[key] = {"ar": ar, "en": en, "base": float(b), "target": float(t),
                             "change_pct": ch, "verdict": _verdict(key, ch)}

    months_b = set(base_sales.get("months") or [])
    months_t = set(target_sales.get("months") or [])
    shared_months = sorted(months_b & months_t)

    regions = {}
    base_regions = {r.get("region"): r for r in (base_sales.get("regions") or [])
                    if isinstance(r, dict) and r.get("region")}
    target_regions = {r.get("region"): r for r in (target_sales.get("regions") or [])
                      if isinstance(r, dict) and r.get("region")}
    for region, br in base_regions.items():
        tr = target_regions.get(region)
        if not tr:
            continue
        b, t = br.get("sales"), tr.get("sales")
        if isinstance(b, (int, float)) and isinstance(t, (int, float)) and b:
            ch = _pct_change(float(b), float(t))
            if ch is not None:
                regions[region] = {"ar": region, "en": region,
                                   "base": float(b), "target": float(t),
                                   "change_pct": ch, "verdict": _verdict("total_sales", ch)}

    return {
        "rows": rows,
        "regions": regions,
        "shared_months": shared_months,
        "base_total": base_sales.get("total_sales"),
        "target_total": target_sales.get("total_sales"),
        "base": {"regions": len(base_regions), "months": len(months_b)},
        "target": {"regions": len(target_regions), "months": len(months_t)},
    }


# The headline metrics every multi-company sheet reports side by side:
# revenue and net profit (absolute) + gross margin (percent ratio).
_GROUP_METRICS = [
    ("kpis", "revenue"),
    ("kpis", "net_profit"),
    ("ratios", "gross_margin"),
]


def compare_group(rows) -> dict:
    """Side-by-side (revenue / margin / net profit) across N companies.

    Every company contributes a column per metric when it has that metric
    (companies missing one are simply narrower in that column — never
    guessed). Returns {"companies": [{id, name, values}], "metrics": [...]}.
    """
    companies = []
    for row in rows:
        import json

        result = json.loads(row.result_json)
        values: dict[str, float | None] = {}
        for source, key in _GROUP_METRICS:
            entry = (result.get(source) or {}).get(key)
            value = entry.get("value") if isinstance(entry, dict) else None
            values[key] = (
                float(value)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else None
            )
        companies.append({
            "id": row.id,
            "name": _display_name(row),
            "values": values,
        })
    return {
        "companies": companies,
        "metrics": [
            {"key": key, "source": source} for source, key in _GROUP_METRICS
        ],
    }


def compare_analyses(base_row, target_row) -> dict:
    """Compare two Analysis DB rows; returns meta + delta payload. When
    either side is a sales-kind analysis, a ``sales`` block rides along and
    the UI renders the sales comparison instead of the «لا بنود مشتركة»
    empty state."""
    import json

    base_result = json.loads(base_row.result_json)
    target_result = json.loads(target_row.result_json)
    sales = None
    if base_result.get("kind") == "sales" or target_result.get("kind") == "sales":
        sales = compare_sales(base_result, target_result)
    return {
        "base": {"id": base_row.id, "filename": _display_name(base_row)},
        "target": {"id": target_row.id, "filename": _display_name(target_row)},
        **compare_results(base_result, target_result),
        **({"sales": sales} if sales else {}),
    }
