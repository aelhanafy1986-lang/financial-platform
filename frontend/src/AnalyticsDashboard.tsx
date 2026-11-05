import { useEffect, useState } from "react";
import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HealthRadar, Lang } from "./types";

const T = {
  title: { ar: "📊 لوحة المؤشرات التحليلية", en: "📊 Analytics Dashboard" },
  health: { ar: "مؤشر الصحة المالية", en: "Financial health" },
  expenses: { ar: "توزيع المصروفات", en: "Expense mix" },
  expensesCenter: { ar: "المصروفات", en: "Expenses" },
  cost: { ar: "بنية الإيراد: التكلفة مقابل النتيجة", en: "Revenue composition: cost vs result" },
  trendForecast: { ar: "الاتجاه والتوقع", en: "Trend & forecast" },
  forecast: { ar: "توقع", en: "Forecast" },
  noData: { ar: "لا تتوفر بيانات كافية للوحة التحليلية", en: "Not enough data for the dashboard" },
};

interface DashPayload {
  score: number | null;
  grade_label: string;
  expenses: [string, number][];
  bullets: { key: string; label: string; value: number; norm: number; verdict: string }[];
  trends: { concept: string; values: number[]; label: string }[];
  cost_parts: [string, number][];
  /** Revenue trend + linear-regression projection — the deck's trend_line. */
  revenue_trend?: {
    label: string;
    values: number[];
    projections: { value: number }[];
    period_labels: string[] | null;
  } | null;
  /** Financial-health radar: one polygon per period (0-100 per dimension). */
  health?: HealthRadar | null;
}

/** Polygon colors, first period → last: purple/gold like the reference. */
const RADAR_COLORS = ["#7c3aed", "#FFC000", "#0070C0", "#EE6C4D", "#0ea5e9", "#6A9E1F"];

/** مؤشر الصحة المالية — five 0-100 dimensions, one polygon per period. */
function HealthRadarCard({ health, lang }: { health: HealthRadar; lang: Lang }) {
  const rows = health.radar.map((d) => ({
    dim: lang === "ar" ? d.ar : d.en,
    // null = no data on this axis (e.g. the first period has no prior to
    // grow from) — connectNulls bridges the polygon across the hole
    ...Object.fromEntries(health.periods.map((p) => [p, d.values[p] ?? null])),
  }));
  return (
    <div className="dash-card health-card">
      <div className="dash-donut-title">{T.health[lang]}</div>
      <div className="health-chart">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={rows} outerRadius="72%">
            <PolarGrid stroke="#E2E8F0" />
            <PolarAngleAxis
              dataKey="dim"
              tick={{ fontSize: 12, fill: "#334155", fontWeight: 600 }}
            />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 100]}
              tick={{ fontSize: 9, fill: "#94a3b8" }}
              axisLine={false}
            />
            {health.periods.map((p, i) => (
              <Radar
                key={p}
                name={p}
                dataKey={p}
                stroke={RADAR_COLORS[i % RADAR_COLORS.length]}
                fill={RADAR_COLORS[i % RADAR_COLORS.length]}
                fillOpacity={0.22}
                strokeWidth={2}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      </div>
      <div className="dash-legend">
        {health.periods.map((p, i) => (
          <span className="dash-legend-item" key={p}>
            <span
              className="dash-swatch"
              style={{ background: RADAR_COLORS[i % RADAR_COLORS.length] }}
            />
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}

const PALETTE = ["#052F61", "#0070C0", "#EE6C4D", "#6A9E1F", "#FFC000", "#7c3aed", "#0ea5e9"];

function fmt(v: number): string {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${(v / 1_000_000).toFixed(a < 10_000_000 ? 2 : 1)}M`;
  if (a >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toFixed(0);
}

/** CSS donut: conic gradient ring + centered total. */
function Donut({ parts, center, title, lang }: { parts: [string, number][]; center: string; title: string; lang: Lang }) {
  const total = parts.reduce((s, [, v]) => s + v, 0) || 1;
  let acc = 0;
  const stops = parts.map(([, v], i) => {
    const from = (acc / total) * 360;
    acc += v;
    const to = (acc / total) * 360;
    return `${PALETTE[i % PALETTE.length]} ${from}deg ${to}deg`;
  });
  return (
    <div className="dash-donut-wrap">
      <div className="dash-donut-title">{title}</div>
      <div
        className="dash-donut"
        style={{ background: `conic-gradient(${stops.join(", ")})` }}
      >
        <div className="dash-donut-hole">
          <span className="dash-donut-center">{center}</span>
          <strong>{fmt(total)}</strong>
        </div>
      </div>
      <div className="dash-legend">
        {parts.map(([label, v], i) => (
          <span className="dash-legend-item" key={label + i}>
            <span className="dash-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
            {label} · {fmt(v)}
          </span>
        ))}
      </div>
    </div>
  );
}

/** One 100% horizontal composition bar with segments + legend. */
function CostStack({ parts, title }: { parts: [string, number][]; title: string }) {
  const total = parts.reduce((s, [, v]) => s + v, 0) || 1;
  return (
    <div className="dash-cost">
      <div className="dash-donut-title">{title}</div>
      <div className="dash-stack">
        {parts.map(([label, v], i) => (
          <div
            key={label + i}
            className="dash-seg"
            style={{
              width: `${(v / total) * 100}%`,
              background: PALETTE[i % PALETTE.length],
            }}
            title={`${label} · ${fmt(v)}`}
          >
            {(v / total) * 100 >= 12 ? `${Math.round((v / total) * 100)}%` : ""}
          </div>
        ))}
      </div>
      <div className="dash-legend">
        {parts.map(([label, v], i) => (
          <span className="dash-legend-item" key={label + i}>
            <span className="dash-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
            {label} · {fmt(v)}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Chart rows: actual series + a gold dashed projection segment that
 *  connects from the LAST actual point (the deck's trend_line layout). */
function trendRows(
  rt: NonNullable<DashPayload["revenue_trend"]>,
  lang: Lang
): { x: string; actual: number | null; proj: number | null }[] {
  const labels = rt.period_labels || [];
  const rows: { x: string; actual: number | null; proj: number | null }[] = [];
  rt.values.forEach((v, i) => {
    rows.push({
      x: labels[i] || `P${i + 1}`,
      actual: v,
      proj: i === rt.values.length - 1 ? v : null,
    });
  });
  rt.projections.forEach((p, k) => {
    rows.push({ x: `${T.forecast[lang]} ${k + 1}`, actual: null, proj: p.value });
  });
  return rows;
}

function TrendCard({
  rt,
  lang,
}: {
  rt: NonNullable<DashPayload["revenue_trend"]>;
  lang: Lang;
}) {
  const rows = trendRows(rt, lang);
  // few periods: force every x tick (recharts' auto thinning hides P1);
  // many periods: keep the default auto thinning to avoid crowding
  const xInterval = rows.length <= 9 ? (0 as const) : undefined;
  const label = (v: unknown): string =>
    v === null || v === undefined || v === "" ? "" : fmt(Number(v));
  return (
    <div className="dash-card dash-card-wide">
      <div className="dash-donut-title">
        {rt.label} · {T.trendForecast[lang]}
      </div>
      <div className="dash-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 16, right: 18, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="#E2E8F0" vertical={false} />
            <XAxis
              dataKey="x"
              interval={xInterval}
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickLine={false}
              axisLine={{ stroke: "#E2E8F0" }}
            />
            <YAxis hide domain={["auto", "auto"]} />
            <Tooltip formatter={(v) => (typeof v === "number" ? fmt(v) : String(v))} />
            <Line
              type="monotone"
              dataKey="actual"
              name={rt.label}
              stroke="#052F61"
              strokeWidth={2.4}
              dot={{ r: 4, fill: "#052F61" }}
              connectNulls={false}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="actual"
                formatter={label}
                position="top"
                style={{ fontSize: 10, fontWeight: 700, fill: "#052F61" }}
              />
            </Line>
            <Line
              type="monotone"
              dataKey="proj"
              name={T.forecast[lang]}
              stroke="#FFC000"
              strokeWidth={2.4}
              strokeDasharray="6 4"
              dot={{ r: 3, fill: "#FFC000" }}
              connectNulls
              isAnimationActive={false}
            >
              <LabelList
                dataKey="proj"
                formatter={label}
                position="top"
                style={{ fontSize: 10, fontWeight: 700, fill: "#B45309" }}
              />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="dash-legend">
        <span className="dash-legend-item">
          <span className="dash-swatch" style={{ background: "#052F61" }} />
          {rt.label}
        </span>
        <span className="dash-legend-item">
          <span className="dash-swatch" style={{ background: "#FFC000" }} />
          {T.forecast[lang]}
        </span>
      </div>
    </div>
  );
}

export function AnalyticsDashboard({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  const [data, setData] = useState<DashPayload | null>(null);

  useEffect(() => {
    setData(null);
    fetch(`/api/analyses/${analysisId}/dashboard?lang=${lang}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, [analysisId, lang]);

  if (!data) return <div className="dash-section skeleton" />;
  const hasDonut = data.expenses && data.expenses.length >= 2;
  const hasCost = data.cost_parts && data.cost_parts.length >= 2;
  const rt = data.revenue_trend;
  const hasTrend =
    !!rt && rt.values.length >= 2 && (rt.projections?.length ?? 0) >= 1;
  const hasHealth = !!data.health && data.health.radar.length > 0;
  // the score gauge is rendered by the «التقييم المالي» section, so the
  // board hides entirely when none of ITS cards have data
  if (!hasDonut && !hasCost && !hasTrend && !hasHealth) return null;

  return (
    <div className="dash-section">
      <h3>{T.title[lang]}</h3>
      <div className="dash-grid">
        {/* the 0-100 score gauge lives in «التقييم المالي» alone — showing
            it here too duplicated the same figure twice on one page */}
        {hasHealth && data.health && <HealthRadarCard health={data.health} lang={lang} />}
        {hasDonut && (
          <div className="dash-card">
            <Donut parts={data.expenses} center={T.expensesCenter[lang]} title={T.expenses[lang]} lang={lang} />
          </div>
        )}
        {hasCost && (
          <div className="dash-card dash-card-wide">
            <CostStack parts={data.cost_parts} title={T.cost[lang]} />
          </div>
        )}
        {hasTrend && rt && <TrendCard rt={rt} lang={lang} />}
      </div>
      {!hasDonut && !hasCost && !hasHealth && (
        <div className="placeholder">{T.noData[lang]}</div>
      )}
    </div>
  );
}

export default AnalyticsDashboard;
