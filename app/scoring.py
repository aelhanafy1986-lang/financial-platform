"""Financial Score (0-100) + future scenarios (optimistic/realistic/conservative).

Both are derived from a stored analysis result (kpis + ratios + series +
forecast), so they recompute automatically when the user edits values.

Score dimensions
----------------
- الربحية   profitability : net & gross margins            (35 pts)
- السيولة    liquidity    : cash relative to revenue/assets (20 pts)
- المديونية  leverage     : debt ratio / D/E                (25 pts)
- الكفاءة    efficiency   : opex share of revenue           (20 pts)

Missing dimensions are dropped and the remaining weights renormalised, so a
profit-and-loss-only file (like the shawarma report) still yields a fair score.
"""

from __future__ import annotations

def _latest(result: dict, key: str) -> float | None:
    kpi = (result.get("kpis") or {}).get(key)
    if isinstance(kpi, dict):
        v = kpi.get("value")
        if isinstance(v, (int, float)):
            return float(v)
    series = (result.get("series") or {}).get(key)
    if isinstance(series, dict):
        vals = [v for v in (series.get("values") or []) if isinstance(v, (int, float))]
        if vals:
            return float(vals[-1])
    return None


def _ratio(result: dict, key: str) -> float | None:
    entry = (result.get("ratios") or {}).get(key)
    if isinstance(entry, dict):
        v = entry.get("value")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Financial Score
# ---------------------------------------------------------------------------

def _profitability_points(result: dict) -> tuple[float, bool]:
    """Return (points out of 35, whether dimension is available)."""
    net_m = _ratio(result, "net_margin")
    gross_m = _ratio(result, "gross_margin")
    if net_m is None and gross_m is None:
        return 0.0, False
    pts = 0.0
    if net_m is not None:
        # 20 pts: 10%+ net margin full marks, negative margin -> 0
        pts += _clamp(net_m / 10 * 20, 0, 20)
    if gross_m is not None:
        # 15 pts: 40%+ gross margin full marks
        pts += _clamp(gross_m / 40 * 15, 0, 15)
    return _clamp(pts, 0, 35), True


def _liquidity_points(result: dict) -> tuple[float, bool]:
    cash = _latest(result, "cash")
    if cash is None:
        return 0.0, False
    assets = _latest(result, "assets")
    revenue = _latest(result, "revenue")
    # benchmark: cash >= 10% of assets, or >= 15% of monthly-ish proxy (rev/12)
    base = None
    if assets and assets > 0:
        base = assets * 0.10
    elif revenue and revenue > 0:
        base = revenue / 12 * 1.8
    if not base:
        return 0.0, False
    return _clamp(cash / base * 20, 0, 20), True


def _leverage_points(result: dict) -> tuple[float, bool]:
    debt = _ratio(result, "debt_ratio")
    de = _ratio(result, "debt_to_equity")
    if debt is None and de is None:
        return 0.0, False
    pts = 0.0
    if debt is not None:
        # 15 pts: <=30% debt full marks, >=80% zero
        pts += _clamp((80 - debt) / 50 * 15, 0, 15)
    if de is not None:
        # 10 pts: D/E <= 0.5 full marks, >= 2 zero
        pts += _clamp((2 - de) / 1.5 * 10, 0, 10)
    return _clamp(pts, 0, 25), True


def _efficiency_points(result: dict) -> tuple[float, bool]:
    revenue = _latest(result, "revenue")
    opex = _latest(result, "opex")
    if not revenue or opex is None:
        return 0.0, False
    share = opex / revenue * 100
    # 20 pts: opex <= 20% of revenue full marks, >= 70% zero
    return _clamp((70 - share) / 50 * 20, 0, 20), True


def compute_score(result: dict) -> dict:
    """Financial Score 0-100 with per-dimension breakdown and a verdict."""
    dims = []

    p_pts, p_ok = _profitability_points(result)
    if p_ok:
        dims.append({"key": "profitability", "ar": "الربحية", "en": "Profitability",
                     "weight": 35, "points": round(p_pts, 1)})

    l_pts, l_ok = _liquidity_points(result)
    if l_ok:
        dims.append({"key": "liquidity", "ar": "السيولة", "en": "Liquidity",
                     "weight": 20, "points": round(l_pts, 1)})

    d_pts, d_ok = _leverage_points(result)
    if d_ok:
        dims.append({"key": "leverage", "ar": "المديونية", "en": "Leverage",
                     "weight": 25, "points": round(d_pts, 1)})

    e_pts, e_ok = _efficiency_points(result)
    if e_ok:
        dims.append({"key": "efficiency", "ar": "الكفاءة", "en": "Efficiency",
                     "weight": 20, "points": round(e_pts, 1)})

    if not dims:
        return {"score": None, "grade": None, "dimensions": [],
                "ar": "لا تتوفر بيانات كافية للتقييم",
                "en": "Not enough data to compute a score"}

    total_weight = sum(d["weight"] for d in dims)
    score = round(sum(d["points"] for d in dims) / total_weight * 100, 1)
    score = _clamp(score)

    # A company losing money cannot grade "Fair" however strong its balance
    # sheet looks: cap the score while net margin is negative.
    net_m = _ratio(result, "net_margin")
    if net_m is not None and net_m < 0:
        score = min(score, 48.0)

    if score >= 80:
        grade = {"ar": "ممتاز", "en": "Excellent", "color": "#10b981"}
    elif score >= 65:
        grade = {"ar": "جيد جداً", "en": "Good", "color": "#22c55e"}
    elif score >= 50:
        grade = {"ar": "مقبول", "en": "Fair", "color": "#f59e0b"}
    elif score >= 35:
        grade = {"ar": "ضعيف", "en": "Weak", "color": "#f97316"}
    else:
        grade = {"ar": "حرج", "en": "Critical", "color": "#ef4444"}

    return {"score": score, "grade": grade, "dimensions": dims}


# ---------------------------------------------------------------------------
# Scenarios: optimistic / realistic / conservative
# ---------------------------------------------------------------------------

def _series_growth(revenue_series: list) -> tuple[float, float, int] | None:
    """(mean growth, volatility, n_observations) trusted from a series.

    Returns None when the series does not provide trustworthy growth info:
    no usable observations, or a single extreme one (a lone -90% "collapse"
    is almost always a sign error / bad extraction, not a trend).

    Sanitisation: only positive bases of meaningful size (>= 5% of the peak)
    produce observations, each observation is winsorised to [-90%, +200%],
    and the mean is clamped to [-60%, +60%].
    """
    nums = [v for v in revenue_series if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None
    peak = max((abs(v) for v in nums), default=0.0)
    floor = peak * 0.05
    obs = []
    for a, b in zip(nums, nums[1:]):
        if a <= 0 or a < floor or not isinstance(b, (int, float)):
            continue
        g = b / a - 1
        if g < -1.0:
            continue  # base→negative or base→(almost)zero: sign error, not growth
        obs.append(max(-0.9, min(2.0, g)))
    if not obs:
        return None
    if len(obs) == 1 and abs(obs[0]) > 0.5:
        return None  # single extreme observation — not a trend
    mean_g = max(-0.60, min(0.60, sum(obs) / len(obs)))
    var = sum((g - mean_g) ** 2 for g in obs) / len(obs)
    return mean_g, min(var ** 0.5, 0.35), len(obs)


def _fallback_signals(result: dict) -> tuple[float, float]:
    """Estimated (growth, volatility) when the revenue series is too short.

    Priority:
    1. Net-profit series trend (profit expanding/shrinking is a decent proxy).
    2. Net-margin level: strong margins support a modest growth assumption.
    3. Neutral default: ~4% growth, ~12% volatility — typical small-business
       band, so scenarios stay realistic instead of collapsing to 0/0.
    """
    net_series = ((result.get("series") or {}).get("net_profit") or {}).get("values") or []
    net_g = _series_growth(net_series)
    if net_g is not None:
        return net_g[0], max(net_g[1], 0.05)

    nm = _ratio(result, "net_margin")
    if nm is not None:
        if nm >= 15:
            return 0.08, 0.12
        if nm >= 8:
            return 0.05, 0.12
        if nm >= 0:
            return 0.02, 0.15
        # loss-making: do not assume growth; keep a mild contraction + volatility
        return -0.01, 0.18

    return 0.04, 0.12


def compute_scenarios(result: dict) -> dict | None:
    """Project revenue & net profit one period ahead under three scenarios.

    Realistic    = estimated trend growth (real data when available, else
                   derived from margin level / net-profit trend / a default)
    Optimistic   = realistic + upside swing (volatility or an estimating band)
    Conservative = realistic - downside swing (floors at -15% swing)

    The three scenarios are always distinct: even with zero observed growth
    the spread comes from the volatility band, never collapses to 0/0/0.
    """
    revenue_series = ((result.get("series") or {}).get("revenue") or {}).get("values") or []
    net = _latest(result, "net_profit")
    rev = _latest(result, "revenue")
    net_m = _ratio(result, "net_margin")
    gross_m = _ratio(result, "gross_margin")

    # current cost structure shares (of revenue)
    cogs = _latest(result, "cogs")
    opex = _latest(result, "opex")
    cogs_share = (cogs / rev) if (cogs is not None and rev) else None
    opex_share = (opex / rev) if (opex is not None and rev) else None

    if not rev:
        return None

    # growth estimate: real trend when the series allows it, otherwise
    # substitute signals (net-profit trend / margin level / default band).
    trusted = _series_growth(revenue_series)
    if trusted is not None:
        mean_g, std, n_obs = trusted
        if n_obs < 2:
            std = max(std, 0.06)  # single observation: volatility is meaningless
    else:
        mean_g, std = _fallback_signals(result)

    # net margin per scenario: base margin adjusted by growth swing.
    # A net margin is a fraction of revenue: it can never exceed ~100%, so
    # every path is clamped to [-5, +0.95]. Garbage extracted ratios (e.g.
    # 77,604%) must not flow into projections as multi-thousand margins.
    if net_m is not None:
        base_margin = max(-5.0, min(0.95, net_m / 100))
    elif cogs_share is not None or opex_share is not None:
        # already a fraction of revenue — do NOT divide by 100 again
        base_margin = max(-5.0, min(0.95, 1 - (cogs_share or 0) - (opex_share or 0)))
    elif gross_m is not None:
        base_margin = max(-5.0, min(0.95, gross_m / 100 * 0.6))  # gross→net haircut
    else:
        base_margin = 0.0

    scenarios = []
    for key, ar, en, delta in (
        ("optimistic", "متفائل", "Optimistic", +max(std, 0.04)),
        ("realistic", "واقعي", "Realistic", 0.0),
        ("conservative", "متحفظ", "Conservative", -max(std, 0.05)),
    ):
        g = mean_g + delta
        next_rev = rev * (1 + g)
        # margin improves slightly with growth (operating leverage), degrades
        # with decline; always a fraction of revenue, never above ~100%.
        margin = base_margin + (0.15 * g if g > 0 else 0.25 * g)
        margin = max(-5.0, min(0.95, margin))
        next_net = next_rev * margin
        scenarios.append({
            "key": key, "ar": ar, "en": en,
            "growth_pct": round(g * 100, 1),
            "revenue": round(next_rev, 2),
            "net": round(next_net, 2),
            "margin_pct": round(margin * 100, 2),
        })
    return {"scenarios": scenarios, "base_revenue": rev, "base_net": net}


# ---------------------------------------------------------------------------
# Financial-health radar (مؤشر الصحة المالية)
# ---------------------------------------------------------------------------

def _metric_lists(result: dict) -> dict[str, list[float | None]]:
    """Raw per-period metric values from result['metrics'], junk filtered."""
    metrics = result.get("metrics") or {}
    out: dict[str, list[float | None]] = {}
    for key, raw in metrics.items():
        if not isinstance(raw, list):
            continue
        out[key] = [float(v) if isinstance(v, (int, float)) else None for v in raw]
    return out


def _at(series: list[float | None], i: int) -> float | None:
    return series[i] if i < len(series) else None


# radar dimension order mirrors the reference report: السيولة · الربحية ·
# الكفاءة · النمو · المديونية (clockwise from the top vertex)
_RADAR_DIMS = (
    ("liquidity", "السيولة", "Liquidity"),
    ("profitability", "الربحية", "Profitability"),
    ("efficiency", "الكفاءة", "Efficiency"),
    ("growth", "النمو", "Growth"),
    ("leverage", "المديونية", "Leverage"),
)


def health_radar(result: dict) -> dict | None:
    """Per-period financial-health radar: five dimensions, 0-100 each, for
    EVERY captured period so the UI draws one polygon per period (like the
    reference report's 2023/2024 comparison).

    Derived from result['metrics'] raw per-period values (not just the
    latest), so it recomputes when the user edits stored values. Per-dimension
    scoring reuses compute_score's anchors normalised to 0-100:

    - الربحية   profitability : net margin (20/35 basis) + gross margin (15/35)
    - السيولة    liquidity    : cash vs 10% of assets (or rev/12*1.8 proxy)
    - المديونية  leverage     : debt ratio (15/25) + D/E (10/25)
    - الكفاءة   efficiency   : opex share of revenue
    - النمو     growth       : revenue change vs the prior period; the first
                               period has no prior → a hole on that axis.

    Dimensions with no scored period are dropped (mirrors compute_score).
    Returns None when there is no data to draw at all.
    """
    m = _metric_lists(result)
    revenue, net, gross = (m.get(k) or [] for k in ("revenue", "net_profit", "gross_profit"))
    cash, assets, liab = (m.get(k) or [] for k in ("cash", "assets", "liabilities"))
    equity, opex = (m.get(k) or [] for k in ("equity", "opex"))

    n = len(revenue)
    if n == 0:
        return None

    labels = [str(x).strip() for x in (result.get("period_labels") or [])]
    periods = [labels[i] if i < len(labels) and labels[i] else f"P{i + 1}"
               for i in range(n)]

    # values[dim_key] -> list of per-period 0-100 scores (None = no data)
    scored: dict[str, list[float | None]] = {
        key: [] for key, _ar, _en in _RADAR_DIMS
    }
    for i in range(n):
        rev = _at(revenue, i)

        # profitability (35-pt basis → 0-100)
        p: float | None = None
        if rev and rev > 0:
            pts = 0.0
            any_margin = False
            net_i = _at(net, i)
            gross_i = _at(gross, i)
            if net_i is not None:
                pts += _clamp((net_i / rev) * 100 / 10 * 20, 0, 20)
                any_margin = True
            if gross_i is not None:
                pts += _clamp((gross_i / rev) * 100 / 40 * 15, 0, 15)
                any_margin = True
            if any_margin:
                p = round(pts / 35 * 100, 1)
        scored["profitability"].append(p)

        # liquidity (20-pt basis → 0-100)
        l: float | None = None
        cash_i = _at(cash, i)
        if cash_i is not None and cash_i >= 0:
            assets_i = _at(assets, i)
            base = None
            if assets_i and assets_i > 0:
                base = assets_i * 0.10
            elif rev and rev > 0:
                base = rev / 12 * 1.8
            if base:
                l = round(_clamp(cash_i / base * 20, 0, 20) / 20 * 100, 1)
        scored["liquidity"].append(l)

        # leverage (25-pt basis → 0-100)
        d: float | None = None
        liab_i = _at(liab, i)
        if liab_i is not None and liab_i >= 0:
            pts = 0.0
            any_leg = False
            assets_i = _at(assets, i)
            equity_i = _at(equity, i)
            if assets_i and assets_i > 0:
                debt_pct = liab_i / assets_i * 100
                pts += _clamp((80 - debt_pct) / 50 * 15, 0, 15)
                any_leg = True
            if equity_i and equity_i > 0:
                de = liab_i / equity_i
                pts += _clamp((2 - de) / 1.5 * 10, 0, 10)
                any_leg = True
            if any_leg:
                d = round(pts / 25 * 100, 1)
        scored["leverage"].append(d)

        # efficiency (20-pt basis → 0-100)
        e: float | None = None
        opex_i = _at(opex, i)
        if opex_i is not None and rev and rev > 0:
            share = opex_i / rev * 100
            e = round(_clamp((70 - share) / 50 * 20, 0, 20) / 20 * 100, 1)
        scored["efficiency"].append(e)

        # growth: revenue change vs the prior period, 0% → 50, ±20% → 100/0
        g: float | None = None
        if i >= 1:
            prev = revenue[i - 1]
            if rev is not None and prev is not None and prev > 0:
                g = round(_clamp(50 + (rev / prev - 1) * 250, 0, 100), 1)
        scored["growth"].append(g)

    keep = [key for key, _ar, _en in _RADAR_DIMS
            if any(v is not None for v in scored[key])]
    if not keep:
        return None

    radar = []
    for key in keep:
        ar, en = next((ar, en) for k, ar, en in _RADAR_DIMS if k == key)
        radar.append({
            "key": key, "ar": ar, "en": en,
            "values": {periods[i]: scored[key][i] for i in range(n)},
        })
    return {"periods": periods, "radar": radar}
