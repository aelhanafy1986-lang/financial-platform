import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line,
  LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Glyph } from "./Glyph";
import type { Lang } from "./types";

/** Sales-operations analysis view (بيانات المبيعات — مناطق/مناديب/أشهر).
 *  Rendered instead of the financial report when the uploaded file is
 *  a sales grid (kind === "sales"). Visual executive dashboard: KPI
 *  cards with trend badges, trend/region/rep charts, achievement bars,
 *  forecast gauge and AI insights. */

export interface SalesAnalysis {
  generated_at?: string;
  total_sales: number;
  total_transactions: number;
  new_customers: number;
  avg_ticket_overall?: number | null;
  months: string[];
  monthly: { month: string; sales: number; transactions: number; new_customers: number; growth: number | null }[];
  regions: { region: string; sales: number; transactions: number; avg_ticket: number | null; growth: number | null; best_rep: string | null; share_pct: number | null }[];
  reps: { rep: string; region: string; sales: number; transactions: number; avg_ticket: number | null; new_customers: number; growth: number | null; target?: number | null; achievement_pct?: number | null }[];
  products?: { product: string; sales: number; units: number; transactions: number; avg_ticket: number | null; share_pct: number | null; top_month: string | null }[];
  peak_month: { month: string; sales: number } | null;
  low_month: { month: string; sales: number } | null;
  strengths: string[];
  weaknesses: string[];
  reps_target_note?: string | null;
  forecast_next_month: { sales: number | null; growth: number | null; method?: string };
  recommendations: { ar: string; en: string }[];
  by_region_months?: Record<string, Record<string, { sales: number; transactions: number; new_customers: number }>>;
  by_rep_months?: Record<string, Record<string, { sales: number; transactions: number; new_customers: number }>>;
}

const SHOP_TALK = { ar: "ريال", en: "SAR" } as const;

const PALETTE = ["#2563eb", "#8b5cf6", "#06b6d4", "#f59e0b", "#ec4899", "#10b981", "#f43f5e"];

const fmt = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { maximumFractionDigits: 0 });

/* compact axis numbers: 1958400 → 1.96M, 758100 → 758K */
const fmtAxis = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`
  : n >= 1_000 ? `${(n / 1_000).toFixed(0)}K` : `${n}`;

const GrowthBadge = ({ g, size = "sm" }: { g: number | null | undefined; size?: "sm" | "lg" }) => {
  if (g == null) return <span className="sa-badge sa-badge-flat">—</span>;
  const up = g >= 0;
  const v = Math.round(Math.abs(g) * 10) / 10; // 36.693…% → 36.7%
  return (
    <span className={`sa-badge ${up ? "sa-badge-up" : "sa-badge-down"} ${size === "lg" ? "sa-badge-lg" : ""}`}>
      {up ? "▲" : "▼"} {v}%
    </span>
  );
};

/* horizontal share bar for regions */
const ShareBar = ({ pct, i }: { pct: number | null; i: number }) => (
  <div className="sa-sharebar">
    <div className="sa-sharebar-fill" style={{ width: `${pct ?? 0}%`, background: PALETTE[i % PALETTE.length] }} />
  </div>
);

/* mini delta badge used inside the period comparison table */
const DeltaPct = ({ v }: { v: number | null }) => {
  if (v == null) return <span className="sa-delta sa-delta-flat">—</span>;
  const up = v >= 0;
  return (
    <span className={`sa-delta ${up ? "sa-delta-up" : "sa-delta-down"}`}>
      {up ? "▲" : "▼"} {Math.round(Math.abs(v) * 10) / 10}%
    </span>
  );
};

/* radial gauge for target achievement (pure CSS conic-gradient) */
export function AchievementGauge({ pct, size = 64 }: { pct: number; size?: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  const color = pct >= 100 ? "#10b981" : pct >= 80 ? "#f59e0b" : "#f43f5e";
  return (
    <div
      className="sa-gauge"
      style={{
        width: size, height: size,
        background: `conic-gradient(${color} ${clamped * 3.6}deg, rgba(148,163,184,.25) 0deg)`,
      }}
      title={`${pct}%`}
    >
      <div className="sa-gauge-hole" style={{ width: size * 0.72, height: size * 0.72 }}>
        <strong style={{ color }}>{Math.round(pct)}%</strong>
      </div>
    </div>
  );
}

type Filter = { type: "region"; value: string } | { type: "rep"; value: string } | null;

export function SalesAnalysisPanel({ data, lang }: { data: SalesAnalysis; lang: Lang }) {
  const [repSort, setRepSort] = useState<"sales" | "growth" | "newc">("sales");
  const [filter, setFilter] = useState<null | { type: "region" | "rep"; value: string }>(null);
  /* user-configurable slowdown threshold (2–4 consecutive declining months) */
  const [threshold, setThreshold] = useState(3);
  const ar = lang === "ar";
  const unit = ar ? SHOP_TALK.ar : SHOP_TALK.en;

  /* ===== interactive filter: dataset recomputed per region/rep =========="*/
  const drill = useMemo(() => {
    if (!filter) return null;
    const matrix = filter.type === "region"
      ? (data.by_region_months?.[filter.value] ?? {})
      : (data.by_rep_months?.[filter.value] ?? {});
    /* order follows the report's month sequence (fills missing as zero) */
    const monthly = data.monthly.map((m) => {
      const slot = matrix[m.month];
      return {
        month: m.month,
        sales: slot?.sales ?? 0,
        transactions: slot?.transactions ?? 0,
        new_customers: slot?.new_customers ?? 0,
        growth: null as number | null,
      };
    });
    /* month-over-month growth within the selection */
    for (let i = 0; i < monthly.length; i++) {
      monthly[i].growth =
        i > 0 && monthly[i - 1].sales > 0
          ? Math.round(((monthly[i].sales - monthly[i - 1].sales) / monthly[i - 1].sales) * 1000) / 10
          : null;
    }
    const totalSales = monthly.reduce((s, m) => s + m.sales, 0);
    const totalTxns = monthly.reduce((s, m) => s + m.transactions, 0);
    const totalNewc = monthly.reduce((s, m) => s + m.new_customers, 0);
    const peak = monthly.reduce<null | (typeof monthly)[number]>(
      (a, m) => (!a || m.sales > a.sales ? m : a), null);
    const low = monthly.reduce<null | (typeof monthly)[number]>(
      (a, m) => (!a || m.sales < a.sales ? m : a), null);
    const overall =
      monthly.length >= 2 && monthly[0].sales > 0
        ? ((monthly[monthly.length - 1].sales - monthly[0].sales) / monthly[0].sales) * 100
        : null;
    /* period comparison within the selection */
    const half = Math.min(3, Math.floor(monthly.length / 2));
    const cmp = monthly.length >= 4 && half >= 1 ? (() => {
      const A = monthly.slice(0, half), B = monthly.slice(-half);
      const sum = (rows: typeof A, k: "sales" | "transactions" | "new_customers") =>
        rows.reduce((s, r) => s + (r[k] || 0), 0);
      const d = (a: number, b: number) => (a > 0 ? Math.round(((b - a) / a) * 1000) / 10 : null);
      return {
        aMonths: A.map((m) => m.month), bMonths: B.map((m) => m.month),
        rows: [
          { label: ar ? "المبيعات" : "Sales", unit, a: sum(A, "sales"), b: sum(B, "sales"), delta: d(sum(A, "sales"), sum(B, "sales")) },
          { label: ar ? "العمليات" : "Transactions", unit: "", a: sum(A, "transactions"), b: sum(B, "transactions"), delta: d(sum(A, "transactions"), sum(B, "transactions")) },
          { label: ar ? "متوسط العملية" : "Avg. ticket", unit, a: sum(A, "transactions") ? Math.round(sum(A, "sales") / sum(A, "transactions")) : null, b: sum(B, "transactions") ? Math.round(sum(B, "sales") / sum(B, "transactions")) : null, delta: sum(A, "transactions") && sum(B, "transactions") ? d(sum(A, "sales") / sum(A, "transactions"), sum(B, "sales") / sum(B, "transactions")) : null },
          { label: ar ? "عملاء جدد" : "New customers", unit: "", a: sum(A, "new_customers"), b: sum(B, "new_customers"), delta: d(sum(A, "new_customers"), sum(B, "new_customers")) },
        ],
        chart: [
          { label: ar ? "متوسط شهري" : "Monthly avg", a: Math.round(sum(A, "sales") / A.length), b: Math.round(sum(B, "sales") / B.length) },
          { label: ar ? "العمليات" : "Transactions", a: sum(A, "transactions"), b: sum(B, "transactions") },
          { label: ar ? "عملاء جدد" : "New customers", a: sum(A, "new_customers"), b: sum(B, "new_customers") },
        ],
      };
    })() : null;
    /* forecast within the selection (same weighted model as the backend) */
    const sales = monthly.map((m) => m.sales);
    let forecast: { sales: number | null; growth: number | null } = { sales: null, growth: null };
    if (sales.length >= 2) {
      const n = sales.length;
      let wsum = 0;
      for (let i = 0; i < n; i++) wsum += i + 1;
      let wm = 0;
      for (let i = 0; i < n; i++) wm += ((i + 1) / wsum) * sales[i];
      const value = Math.max(0, wm * 1.02);
      forecast = {
        sales: Math.round(value),
        growth: sales[n - 1] ? Math.round(((value - sales[n - 1]) / sales[n - 1]) * 1000) / 10 : null,
      };
    }
    return {
      monthly,
      total_sales: totalSales,
      total_transactions: totalTxns,
      new_customers: totalNewc,
      avg_ticket_overall: totalTxns ? Math.round(totalSales / totalTxns) : null,
      overall_growth: overall,
      peak, low,
      cmp,
      forecast,
      filter_label: filter.value,
    };
  }, [filter, data, ar, unit]);

  /* view: which monthly series the cards/charts render (global or filtered) */
  const view = drill
    ? {
        monthly: drill.monthly,
        peak: drill.peak,
        low: drill.low,
      }
    : {
        monthly: data.monthly,
        peak: data.peak_month,
        low: data.low_month,
      };

  const reps = useMemo(() => {
    /* when a region filter is active keep only that region's reps; when a
       rep filter is active keep only the selected rep's own row */
    let list = data.reps;
    if (filter?.type === "region") list = list.filter((r) => r.region.split(", ").includes(filter.value));
    else if (filter?.type === "rep") list = list.filter((r) => r.rep === filter.value);
    list = [...list];
    if (repSort === "growth") list.sort((a, b) => (b.growth ?? -99) - (a.growth ?? -99));
    else if (repSort === "newc") list.sort((a, b) => b.new_customers - a.new_customers);
    return list;
  }, [data.reps, repSort, filter]);

  /* monthly trend rows for charts — reflects the active filter */
  const trendRows = view.monthly.map((m) => ({
    ...m,
    label: m.month,
    sales: m.sales,
    growth: m.growth ?? undefined,
  }));
  const scopeNote = filter
    ? (ar ? `النطاق: ${filter.value}` : `Scope: ${filter.value}`)
    : null;

  /* first vs last month growth for the headline KPI */
  const overallGrowth =
    data.monthly.length >= 2 && data.monthly[0].sales > 0
      ? ((data.monthly[data.monthly.length - 1].sales - data.monthly[0].sales) / data.monthly[0].sales) * 100
      : null;

  /* ===== slowdown + surge detection on monthly growth ====================
     walks the month-over-month growth series backwards from the latest
     month; fires the slowdown alert once the consecutive-decline streak
     reaches the user's threshold, and a green surge alert after 3+
     consecutive increases. Both work on the filtered view too. */
  const momentum = useMemo(() => {
    const gs = view.monthly.map((m) => m.growth).filter((g): g is number => g != null);
    if (gs.length < 2) return { slowdown: null, surge: null };
    let streak = 0;
    for (let i = gs.length - 1; i > 0; i--) {
      if (gs[i] < gs[i - 1]) streak++;
      else break;
    }
    const slowdown = streak >= threshold
      ? { months: streak, from: gs[gs.length - 1 - streak], to: gs[gs.length - 1], negative: gs[gs.length - 1] < 0 }
      : null;
    let up = 0;
    for (let i = gs.length - 1; i > 0; i--) {
      if (gs[i] > gs[i - 1]) up++;
      else break;
    }
    /* surge is independent of the threshold: 3+ consecutive rises are the
       positive mirror of the default slowdown severity */
    const surge = up >= 3 && !(slowdown && streak >= up)
      ? { months: up, from: gs[gs.length - 1 - up], to: gs[gs.length - 1] }
      : null;
    return { slowdown, surge };
  }, [view.monthly, threshold]);
  const slowdown = momentum.slowdown;
  const surge = momentum.surge;

  /* ===== slowdown root-cause diagnosis ===================================
     When a slowdown fires, score each region/rep by its OWN growth-rate
     slide over the same window (sales can rise while growth decelerates,
     which is exactly the amber case) and name the steepest one, plus
     whether the slide came from fewer transactions or a smaller ticket. */
  const diagnosis = useMemo(() => {
    if (!slowdown) return null;
    const months = view.monthly.map((m) => m.month);
    const winLen = Math.min(slowdown.months + 1, months.length);
    const win = months.slice(months.length - winLen);

    type Candidate = { name: string; kind: "region" | "rep"; growthDrop: number; from: number; to: number; salesDeltaAbs: number };
    const candidates: Candidate[] = [];
    const scan = (
      matrix: Record<string, Record<string, { sales: number; transactions: number; new_customers: number }>> | undefined,
      kind: "region" | "rep",
    ) => {
      for (const [name, m] of Object.entries(matrix ?? {})) {
        /* entity's own MoM growth over the full month span, in report order */
        const es = months.map((mo) => m?.[mo]?.sales ?? 0);
        const gs: number[] = [];
        for (let i = 1; i < es.length; i++) gs.push(es[i - 1] > 0 ? Math.round(((es[i] - es[i - 1]) / es[i - 1]) * 1000) / 10 : 0);
        if (gs.length < slowdown.months) continue;
        let streak = 0;
        for (let i = gs.length - 1; i > 0; i--) {
          if (gs[i] < gs[i - 1]) streak++;
          else break;
        }
        if (streak < slowdown.months) continue;  /* not honouring the alert pattern */
        const activeWin = win.some((mo) => (m?.[mo]?.transactions ?? 0) > 0);
        if (!activeWin) continue;
        const from = gs[gs.length - 1 - streak];
        const to = gs[gs.length - 1];
        const firstWin = es[months.indexOf(win[0])];
        const lastWin = es[months.indexOf(win[win.length - 1])];
        candidates.push({ name, kind, growthDrop: Math.round((to - from) * 10) / 10, from, to, salesDeltaAbs: lastWin - firstWin });
      }
    };
    scan(data.by_region_months, "region");
    scan(data.by_rep_months, "rep");
    candidates.sort((a, b) => a.growthDrop - b.growthDrop);  /* steepest growth slide first */

    /* transaction-vs-ticket decomposition over the whole view window */
    const winRows = view.monthly.filter((m) => win.includes(m.month));
    const tA = winRows[0]?.transactions ?? 0, tB = winRows[winRows.length - 1]?.transactions ?? 0;
    const sA = winRows[0]?.sales ?? 0, sB = winRows[winRows.length - 1]?.sales ?? 0;
    const tickA = tA ? sA / tA : 0, tickB = tB ? sB / tB : 0;
    const tDrop = tA ? ((tB - tA) / tA) * 100 : 0;
    const tickDrop = tickA ? ((tickB - tickA) / tickA) * 100 : 0;
    const lever = Math.abs(tDrop) >= Math.abs(tickDrop)
      ? { key: "txns", drop: Math.round(tDrop * 10) / 10 }
      : { key: "ticket", drop: Math.round(tickDrop * 10) / 10 };

    const top = candidates[0] ?? null;
    return { top, lever, candidatesN: candidates.length, window: win };
  }, [slowdown, view.monthly, data.by_region_months, data.by_rep_months]);

  const hasTargets = reps.some((r) => r.achievement_pct != null);
  /* top-selling items: the payload is already ranked by sales — chart and
     table share the same top-N slice so the two stay aligned */
  const productsList = data.products ?? [];
  const topProducts = productsList.slice(0, 8);
  const lastGrowth = data.monthly.length ? data.monthly[data.monthly.length - 1].growth : null;

  /* ===== period comparison: first 3 months vs last 3 months ============
     needs at least 2 distinct months on each side; otherwise hidden. */
  const half = Math.min(3, Math.floor(data.monthly.length / 2));
  const compareReady = data.monthly.length >= 4 && half >= 1;
  const cmp = useMemo(() => {
    if (!compareReady) return null;
    const A = data.monthly.slice(0, half);
    const B = data.monthly.slice(-half);
    const sum = (rows: typeof A, k: "sales" | "transactions" | "new_customers") =>
      rows.reduce((s, r) => s + (r[k] || 0), 0);
    const newc = (rows: typeof A) => sum(rows, "new_customers");
    const sales = (rows: typeof A) => sum(rows, "sales");
    const txns = (rows: typeof A) => sum(rows, "transactions");
    const delta = (a: number, b: number) => (a > 0 ? ((b - a) / a) * 100 : null);
    return {
      aMonths: A.map((m) => m.month),
      bMonths: B.map((m) => m.month),
      rows: [
        {
          label: ar ? "المبيعات" : "Sales",
          unit,
          a: sales(A), b: sales(B), delta: delta(sales(A), sales(B)),
        },
        {
          label: ar ? "العمليات" : "Transactions",
          unit: "",
          a: txns(A), b: txns(B), delta: delta(txns(A), txns(B)),
        },
        {
          label: ar ? "متوسط العملية" : "Avg. ticket",
          unit,
          a: txns(A) ? Math.round(sales(A) / txns(A)) : null,
          b: txns(B) ? Math.round(sales(B) / txns(B)) : null,
          delta: txns(A) && txns(B) ? delta(sales(A) / txns(A), sales(B) / txns(B)) : null,
        },
        {
          label: ar ? "عملاء جدد" : "New customers",
          unit: "",
          a: newc(A), b: newc(B), delta: delta(newc(A), newc(B)),
        },
      ],
      chart: [
        {
          label: ar ? "متوسط شهري" : "Monthly avg",
          a: Math.round(sales(A) / A.length),
          b: Math.round(sales(B) / B.length),
        },
        {
          label: ar ? "العمليات" : "Transactions",
          a: txns(A), b: txns(B),
        },
        {
          label: ar ? "عملاء جدد" : "New customers",
          a: newc(A), b: newc(B),
        },
      ],
    };
  }, [data.monthly, compareReady, ar, unit, half]);

 /* shared forecast slot for the trend chart (global or filtered) */
  const forecastNow = drill
    ? drill.forecast
    : data.forecast_next_month;

  const alertChip = slowdown
    ? { label: ar ? `تباطؤ ${slowdown.months} أشهر` : `${slowdown.months}-month slowdown`, tint: slowdown.negative ? "sa-tint-red" : "sa-tint-amber2" }
    : surge
      ? { label: ar ? `تسارع ${surge.months} أشهر` : `${surge.months}-month surge`, tint: "sa-tint-green" }
      : null;

  const kpis = drill
    ? [
        {
          label: ar ? `إجمالي المبيعات — ${drill.filter_label}` : `Total sales — ${drill.filter_label}`,
          value: fmt(drill.total_sales), unit,
          icon: "💰", tint: alertChip ? alertChip.tint : "sa-tint-blue",
          iconFallback: alertChip?.label,
          foot: drill.overall_growth != null && <GrowthBadge g={drill.overall_growth} />,
          footText: ar ? "من أول شهر لآخر شهر" : "first → last month",
        },
        {
          label: ar ? "عدد العمليات" : "Transactions",
          value: fmt(drill.total_transactions),
          icon: "🧾", tint: "sa-tint-violet",
          foot: drill.monthly.length ? drill.monthly[drill.monthly.length - 1].growth != null && (
            <GrowthBadge g={drill.monthly[drill.monthly.length - 1].growth} />
          ) : false,
          footText: ar ? "آخر شهر" : "last month",
        },
        {
          label: ar ? "متوسط العملية" : "Avg. ticket",
          value: fmt(drill.avg_ticket_overall), unit,
          icon: "📊", tint: "sa-tint-cyan",
        },
        {
          label: ar ? "عملاء جدد" : "New customers",
          value: fmt(drill.new_customers),
          icon: "👥", tint: "sa-tint-amber",
        },
      ]
    : [
        {
          label: ar ? "إجمالي المبيعات" : "Total sales",
          value: fmt(data.total_sales), unit,
          icon: "💰", tint: alertChip ? alertChip.tint : "sa-tint-blue",
          iconFallback: alertChip?.label,
          foot: overallGrowth != null && (
            <GrowthBadge g={overallGrowth} />
          ),
          footText: ar ? "من أول شهر لآخر شهر" : "first → last month",
        },
        {
          label: ar ? "عدد العمليات" : "Transactions",
          value: fmt(data.total_transactions),
          icon: "🧾", tint: "sa-tint-violet",
          foot: lastGrowth != null && <GrowthBadge g={lastGrowth} />,
          footText: ar ? "آخر شهر" : "last month",
        },
        {
          label: ar ? "متوسط العملية" : "Avg. ticket",
          value: fmt(data.avg_ticket_overall), unit,
          icon: "📊", tint: "sa-tint-cyan",
        },
        {
          label: ar ? "عملاء جدد" : "New customers",
          value: fmt(data.new_customers),
          icon: "👥", tint: "sa-tint-amber",
        },
      ];

  const tooltipStyle: CSSProperties = {
    background: "rgba(15,23,42,.92)", border: "1px solid rgba(148,163,184,.3)",
    borderRadius: 10, color: "#e2e8f0", fontSize: 12, direction: ar ? "rtl" : "ltr",
  };

  return (
    <div className="sales-analysis" id="sec-sales">
      <div className="sa-banner sa-banner-v2">
        <div className="sa-banner-title">
          <strong><Glyph name="doc" size={13} /> {ar ? "داشبورد المبيعات" : "Sales dashboard"}</strong>
          <span>{ar
            ? "شبكة عمليات مبيعات (مناطق · مناديب · أشهر) — محللة كبانات عمليات وليست قوائم مالية."
            : "Sales operations grid (regions · reps · months) — analysed as operations data, not financial statements."}</span>
        </div>
      </div>

      {/* ===== interactive filter — region / rep drill-down ================= */}
      <div className="sa-filterbar">
        <span className="sa-filter-label">{ar ? "تصفية:" : "Filter:"}</span>
        <button
          className={`sa-chip-btn ${!filter ? "active" : ""}`}
          onClick={() => setFilter(null)}
        >
          {ar ? "الكل" : "All"}
        </button>
        <span className="sa-filter-group">
          {data.regions.map((r) => (
            <button
              key={r.region}
              className={`sa-chip-btn ${filter?.type === "region" && filter.value === r.region ? "active" : ""}`}
              onClick={() => setFilter({ type: "region", value: r.region })}
            >
              {r.region}
            </button>
          ))}
        </span>
        <span className="sa-filter-sep" />
        <span className="sa-filter-group">
          {data.reps.map((r) => (
            <button
              key={r.rep}
              className={`sa-chip-btn ${filter?.type === "rep" && filter.value === r.rep ? "active" : ""}`}
              onClick={() => setFilter({ type: "rep", value: r.rep })}
            >
              {r.rep}
            </button>
          ))}
        </span>
        {filter && (
          <button className="sa-chip-clear" onClick={() => setFilter(null)}>
            ✕ {ar ? "إلغاء التصفية" : "Clear filter"}
          </button>
        )}
      </div>

      {/* ===== headline KPI cards ================================= */}
      <div className="sa-kpis sa-kpis-v2">
        {kpis.map((k) => (
          <div className={`sa-kpi ${k.tint}`} key={k.label}>
            {k.iconFallback
              ? <div className="sa-kpi-icon sa-kpi-alert" title={k.iconFallback}><strong>{k.iconFallback}</strong></div>
              : <div className="sa-kpi-icon"><span aria-hidden>{k.icon}</span></div>}
            <small>{k.label}</small>
            <strong>{k.value}</strong>
            {k.unit && <em>{k.unit}</em>}
            {(k.foot || k.footText) && (
              <div className="sa-kpi-foot">
                {k.foot}
                {k.footText && <span>{k.footText}</span>}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ===== monthly trend (area) + transactions (bars) ========== */}
      <div className="sa-grid sa-grid-2">
        <section className="sa-card">
          <h3>{ar ? "📈 اتجاه المبيعات الشهري" : "📈 Monthly sales trend"}{scopeNote && <small className="sa-scope">{scopeNote}</small>}</h3>
          <div className="sa-chart sa-chart-tall">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendRows} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                <defs>
                  <linearGradient id="saFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2563eb" stopOpacity={0.55} />
                    <stop offset="100%" stopColor="#2563eb" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.25)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "currentColor" }} tickLine={false} axisLine={false} reversed={ar} />
                <YAxis tickFormatter={fmtAxis} tick={{ fontSize: 10, fill: "currentColor" }} tickLine={false} axisLine={false} width={46} orientation={ar ? "right" : "left"} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number | string) => [`${fmt(Number(v))} ${unit}`, ar ? "المبيعات" : "Sales"]} />
                <Area type="monotone" dataKey="sales" stroke="#2563eb" strokeWidth={2.5} fill="url(#saFill)" dot={{ r: 3.5, fill: "#2563eb" }} activeDot={{ r: 5 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {view.peak && view.low && (
            <p className="sa-note sa-note-inline">
              <span className="sa-pill sa-pill-peak">{ar ? "الذروة" : "Peak"}: {view.peak.month} · {fmt(view.peak.sales)}</span>
              <span className="sa-pill sa-pill-low">{ar ? "الأدنى" : "Low"}: {view.low.month} · {fmt(view.low.sales)}</span>
            </p>
          )}
          {slowdown && (
            <div className="sa-alert sa-alert-slowdown sa-alert-diag">
              <div className="sa-alert-main">
                <p className="sa-alert-head">
                  <span className="sa-alert-icon">⚠</span>
                  <span>
                    {ar ? (slowdown.negative
                      ? `تنبيه تباطؤ: النمو انخفض ${slowdown.months} أشهر متتالية — آخر شهر سالب (${slowdown.to}%). تحقق من المسببات قبل نهاية الشهر الحالي.`
                      : `تنبيه تباطؤ: النمو الآني تراجع ${slowdown.months} أشهر متتالية (${slowdown.from}% → ${slowdown.to}%). الاتجاه يحتاج تدخّلًا قبل أن يصبح سالبًا.`)
                      : (slowdown.negative
                        ? `Slowdown alert: growth fell ${slowdown.months} consecutive months — latest is negative (${slowdown.to}%). investigate before month-end.`
                        : `Slowdown alert: growth has declined ${slowdown.months} consecutive months (${slowdown.from}% → ${slowdown.to}%). Intervene before it turns negative.`)}
                  </span>
                </p>
                {diagnosis && (
                  <p className="sa-diagnosis">
                    <strong>{ar ? "التشخيص الأكثر ترجيحًا:" : "Likely cause:"} </strong>
                    {diagnosis.top
                      ? (ar
                        ? `${diagnosis.top.kind === "region" ? "منطقة" : "المندوب"} ${diagnosis.top.name} — نموه الشهري تراجع من ${diagnosis.top.from}% إلى ${diagnosis.top.to}% (أشدّ تراجع بين ${diagnosis.candidatesN} كيانًا نشطًا عبر ${diagnosis.window[0]} → ${diagnosis.window[diagnosis.window.length - 1]}). المحرّك الأكبر: ${diagnosis.lever.key === "txns" ? "عدد العمليات" : "متوسط قيمة العملية"} (${diagnosis.lever.drop}%). راجع حساباته/حملاته أولًا هذا الشهر.`
                        : `${diagnosis.top.kind === "region" ? "Region" : "Rep"} ${diagnosis.top.name} — monthly growth slid from ${diagnosis.top.from}% to ${diagnosis.top.to}% (steepest of ${diagnosis.candidatesN} active entities over ${diagnosis.window[0]} → ${diagnosis.window[diagnosis.window.length - 1]}). Main lever: ${diagnosis.lever.key === "txns" ? "transaction count" : "average ticket"} (${diagnosis.lever.drop}%). Review their accounts/campaigns first this month.`)
                      : (ar
                        ? "لا توجد منطقة أو مندوب واحد مسؤول واضح — الانخفاض موزّع، راجع العوامل العامة (الموسمية، الأسعار، الحملات)."
                        : "No single region or rep stands out — the decline is broad-based; review seasonality, pricing and campaigns.")}
                  </p>
                )}
              </div>
            </div>
          )}
          {surge && !slowdown && (
            <p className="sa-alert sa-alert-surge">
              <span className="sa-alert-icon">✦</span>
              <span>
                {ar
                  ? `نمو متسارع: النمو ارتفع ${surge.months} أشهر متتالية (${surge.from}% → ${surge.to}%). استثمر الزخم الحالي — وسّع ما ينجح ويحقق النمو.`
                  : `Accelerating growth: momentum has risen ${surge.months} consecutive months (${surge.from}% → ${surge.to}%). Ride the surge — scale what is working.`}
              </span>
            </p>
          )}
          <div className="sa-alert-ctrl">
            <span>{ar ? "عتبة تنبيه التباطؤ:" : "Slowdown threshold:"}</span>
            {[2, 3, 4].map((t) => (
              <button key={t} className={`sa-thc ${threshold === t ? "active" : ""}`} onClick={() => setThreshold(t)} aria-pressed={threshold === t}>
                {ar ? `${t} أشهر` : `${t} mo`}
              </button>
            ))}
          </div>
        </section>

        <section className="sa-card">
          <h3>{ar ? "🔄 العمليات والعملاء الجدد شهريًا" : "🔄 Transactions & new customers"}</h3>
          <div className="sa-chart sa-chart-tall">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendRows} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.25)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "currentColor" }} tickLine={false} axisLine={false} reversed={ar} />
                <YAxis tick={{ fontSize: 10, fill: "currentColor" }} tickLine={false} axisLine={false} width={40} orientation={ar ? "right" : "left"} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="transactions" stroke="#8b5cf6" strokeWidth={2.5}
                  name={ar ? "العمليات" : "Transactions"} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                <Line type="monotone" dataKey="new_customers" stroke="#f59e0b" strokeWidth={2.5}
                  name={ar ? "عملاء جدد" : "New customers"} dot={{ r: 3 }} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      {/* ===== period comparison: first 3 months vs last 3 months ===== */}
      {cmp && !filter && (
        <section className="sa-card sa-card-compare">
          <div className="sa-card-head">
            <h3>{ar ? "⏱️ مقارنة الفترات — أول 3 أشهر ضد آخر 3 أشهر" : "⏱️ Period comparison — first 3 vs last 3 months"}</h3>
            <span className="sa-compare-periods">
              <span className="sa-period a">{cmp.aMonths[0]} → {cmp.aMonths[cmp.aMonths.length - 1]}</span>
              <strong>{ar ? "ضد" : "vs"}</strong>
              <span className="sa-period b">{cmp.bMonths[0]} → {cmp.bMonths[cmp.bMonths.length - 1]}</span>
            </span>
          </div>
          <div className="sa-grid sa-grid-2 sa-grid-tight">
            <table className="sa-table sa-table-v2 sa-compare-table">
              <thead>
                <tr>
                  <th>{ar ? "المؤشر" : "Metric"}</th>
                  <th>{ar ? "الفترة الأولى (أ)" : "Period A"}</th>
                  <th>{ar ? "الفترة الأخيرة (ب)" : "Period B"}</th>
                  <th>{ar ? "التغير" : "Change"}</th>
                </tr>
              </thead>
              <tbody>
                {cmp.rows.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{row.a != null ? `${fmt(row.a)}${row.unit ? " " + row.unit : ""}` : "—"}</td>
                    <td><strong>{row.b != null ? `${fmt(row.b)}${row.unit ? " " + row.unit : ""}` : "—"}</strong></td>
                    <td><DeltaPct v={row.delta} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="sa-chart sa-chart-tall">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={cmp.chart} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.25)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "currentColor" }} tickLine={false} axisLine={false} reversed={ar} />
                  <YAxis tickFormatter={fmtAxis} tick={{ fontSize: 10, fill: "currentColor" }} tickLine={false} axisLine={false} width={46} orientation={ar ? "right" : "left"} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend
                    formatter={(v: string) => (v === "a" ? cmp.aMonths[0] : cmp.bMonths[0])}
                    wrapperStyle={{ fontSize: 11 }}
                  />
                  <Bar dataKey="a" fill="#94a3b8" radius={5} barSize={20} name="a" />
                  <Bar dataKey="b" fill="#2563eb" radius={5} barSize={20} name="b" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}
      <div className="sa-grid sa-grid-2">
        <section className="sa-card">
          <h3>{ar ? "🎯 توزيع المبيعات على المناطق" : "🎯 Sales share by region"}</h3>
          <div className="sa-chart sa-chart-tall">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data.regions} dataKey="sales" nameKey="region"
                  innerRadius="55%" outerRadius="85%" paddingAngle={3} stroke="none">
                  {data.regions.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                </Pie>
                <Tooltip contentStyle={tooltipStyle}
                  formatter={(v: number | string, name: unknown) => [`${fmt(Number(v))} ${unit}`, String(name)]} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="sa-card">
          <h3>{ar ? "🗺️ تحليل المناطق" : "🗺️ Regions"}</h3>
          <table className="sa-table sa-table-v2">
            <thead>
              <tr>
                <th>{ar ? "المنطقة" : "Region"}</th>
                <th>{ar ? "المبيعات" : "Sales"}</th>
                <th>{ar ? "النصيب" : "Share"}</th>
                <th>{ar ? "النمو" : "Growth"}</th>
                <th>{ar ? "أفضل مندوب" : "Best rep"}</th>
              </tr>
            </thead>
            <tbody>
              {data.regions.map((r, i) => (
                <tr key={r.region}>
                  <td><span className="sa-dot" style={{ background: PALETTE[i % PALETTE.length] }} />{r.region}</td>
                  <td>{fmt(r.sales)}</td>
                  <td>
                    <div className="sa-sharecell">
                      <ShareBar pct={r.share_pct} i={i} />
                      <span>{r.share_pct ?? "—"}%</span>
                    </div>
                  </td>
                  <td><GrowthBadge g={r.growth} /></td>
                  <td><span className="sa-chip">{r.best_rep ?? "—"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      {/* ===== products: top-selling items (only when the file carries
             a product/item column — honest absence otherwise) ========== */}
      {productsList.length > 0 && (
        <section className="sa-card">
          <div className="sa-card-head">
            <h3>{ar ? "🛍️ الأصناف الأكثر مبيعًا" : "🛍️ Top-selling products"}</h3>
            <small className="sa-scope">
              {ar ? `${productsList.length} صنفًا — مرتبة بالمبيعات` : `${productsList.length} items — ranked by sales`}
            </small>
          </div>
          <div className="sa-grid sa-grid-2 sa-grid-tight">
            <div className="sa-chart sa-chart-tall">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topProducts} layout="vertical" margin={{ top: 4, right: 12, left: 12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.25)" horizontal={false} />
                  <XAxis type="number" tickFormatter={fmtAxis} tick={{ fontSize: 10, fill: "currentColor" }} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="product" tick={{ fontSize: 11, fill: "currentColor" }} tickLine={false} axisLine={false} width={72} orientation={ar ? "right" : "left"} />
                  <Tooltip contentStyle={tooltipStyle}
                    formatter={(v: number | string) => [`${fmt(Number(v))} ${unit}`, ar ? "المبيعات" : "Sales"]} />
                  <Bar dataKey="sales" fill="#2563eb" radius={6} barSize={16} name={ar ? "المبيعات" : "Sales"} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <table className="sa-table sa-table-v2">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{ar ? "الصنف" : "Item"}</th>
                  <th>{ar ? "المبيعات" : "Sales"}</th>
                  <th>{ar ? "النصيب" : "Share"}</th>
                  <th>{ar ? "الكمّية" : "Qty"}</th>
                  <th>{ar ? "أفضل شهر" : "Top month"}</th>
                </tr>
              </thead>
              <tbody>
                {topProducts.map((p, i) => (
                  <tr key={p.product}>
                    <td>
                      <span className={`sa-rank ${i === 0 ? "sa-rank-1" : i === 1 ? "sa-rank-2" : i === 2 ? "sa-rank-3" : ""}`}>{i + 1}</span>
                    </td>
                    <td><strong>{p.product}</strong></td>
                    <td>{fmt(p.sales)}</td>
                    <td>
                      <div className="sa-sharecell">
                        <ShareBar pct={p.share_pct} i={i} />
                        <span>{p.share_pct ?? "—"}%</span>
                      </div>
                    </td>
                    <td>{fmt(p.transactions)}</td>
                    <td><span className="sa-chip">{p.top_month ?? "—"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ===== reps: ranking bars + sortable table ================= */}
      <section className="sa-card">
        <div className="sa-card-head">
          <h3>{ar ? "🏅 ترتيب المندوبين" : "🏅 Rep leaderboard"}</h3>
          <div className="sa-sort">
            {([["sales", ar ? "المبيعات" : "Sales"], ["growth", ar ? "النمو" : "Growth"], ["newc", ar ? "العملاء الجدد" : "New clients"]] as const).map(([k, l]) => (
              <button key={k} className={repSort === k ? "active" : ""} onClick={() => setRepSort(k)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="sa-grid sa-grid-2 sa-grid-tight">
          <div className="sa-chart sa-chart-tall">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={reps} layout="vertical" margin={{ top: 4, right: 12, left: 12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.25)" horizontal={false} />
                <XAxis type="number" tickFormatter={fmtAxis} tick={{ fontSize: 10, fill: "currentColor" }} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="rep" tick={{ fontSize: 11, fill: "currentColor" }} tickLine={false} axisLine={false} width={72} orientation={ar ? "right" : "left"} />
                <Tooltip contentStyle={tooltipStyle}
                  formatter={(v: number | string, n: unknown) => [fmt(Number(v)), String(n)]} />
                <Bar dataKey="sales" fill="#2563eb" radius={6} barSize={16} name={ar ? "المبيعات" : "Sales"} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="sa-table sa-table-v2">
            <thead>
              <tr>
                <th>#</th>
                <th>{ar ? "المندوب" : "Rep"}</th>
                <th>{ar ? "المبيعات" : "Sales"}</th>
                <th>{ar ? "النمو" : "Growth"}</th>
                {hasTargets && <th>{ar ? "🏆 الهدف" : "🏆 Target"}</th>}
              </tr>
            </thead>
            <tbody>
              {reps.map((r, i) => (
                <tr key={r.rep}>
                  <td>
                    <span className={`sa-rank ${i === 0 ? "sa-rank-1" : i === 1 ? "sa-rank-2" : i === 2 ? "sa-rank-3" : ""}`}>{i + 1}</span>
                  </td>
                  <td><strong>{r.rep}</strong><small className="sa-region">{r.region}</small></td>
                  <td>{fmt(r.sales)}</td>
                  <td><GrowthBadge g={r.growth} /></td>
                  {hasTargets && (
                    <td>{r.achievement_pct != null ? <AchievementGauge pct={r.achievement_pct} size={44} /> : "—"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.reps_target_note && <p className="sa-note">{data.reps_target_note}</p>}
      </section>

      {/* ===== forecast + strengths/weaknesses ===================== */}
      <div className="sa-grid sa-grid-2">
        <section className="sa-card sa-card-forecast">
          <h3>{ar ? "🔮 التنبؤ بالشهر القادم" : "🔮 Next-month forecast"}{scopeNote && <small className="sa-scope">{scopeNote}</small>}</h3>
          {forecastNow.sales != null ? (
            <div className="sa-forecast-v2">
              <div className="sa-forecast-big">
                <strong>{fmt(forecastNow.sales)}</strong>
                <em>{unit}</em>
              </div>
              <GrowthBadge g={forecastNow.growth} size="lg" />
              <small>{ar ? "تنبؤ خطي مرجّح على آخر الأشهر" : "Weighted linear projection of recent months"}</small>
            </div>
          ) : (
            <p>{ar ? "بيانات غير كافية للتنبؤ" : "Not enough data to forecast"}</p>
          )}
        </section>

        <section className="sa-card sa-card-forecast">
          <h3>{ar ? "🤖 توصيات ذكية" : "🤖 Smart recommendations"}</h3>
          <ul className="sa-recs sa-recs-v2">
            {data.recommendations.map((r, i) => (
              <li key={i}>{ar ? r.ar : r.en}</li>
            ))}
          </ul>
        </section>
      </div>

      {/* ===== strengths / weaknesses ============================== */}
      <div className="sa-grid sa-grid-2">
        <section className="sa-card sa-sw-strong">
          <h3>{ar ? "✅ نقاط القوة" : "✅ Strengths"}</h3>
          <ul>{data.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </section>
        <section className="sa-card sa-sw-weak">
          <h3>{ar ? "⚠️ نقاط الضعف" : "⚠️ Weaknesses"}</h3>
          <ul>{data.weaknesses.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </section>
      </div>
    </div>
  );
}
