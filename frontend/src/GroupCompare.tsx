import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Lang } from "./types";

export interface GroupCompany {
  id: number;
  name: string;
  /** revenue / net_profit / gross_margin — null when the company lacks it */
  values: Record<string, number | null>;
}

export interface GroupComparePayload {
  companies: GroupCompany[];
  metrics: { key: string; source: string }[];
}

const T = {
  title: { ar: "مقارنة الشركات جنبًا إلى جنب", en: "Companies side by side" },
  subtitle: {
    ar: "الإيراد · الهامش الإجمالي · صافي الربح",
    en: "Revenue · Gross margin · Net profit",
  },
  company: { ar: "الشركة", en: "Company" },
  revenue: { ar: "الإيراد", en: "Revenue" },
  net_profit: { ar: "صافي الربح", en: "Net profit" },
  gross_margin: { ar: "الهامش الإجمالي %", en: "Gross margin %" },
  dash: { ar: "— غير متوفر", en: "— n/a" },
};

const PALETTE = ["#0f766e", "#7c3aed", "#2563eb", "#059669", "#d97706", "#1e3a5f", "#dc2626"];

/** best-in-column marker: highest value per metric (losses never win) */
function bestIn(metric: string, companies: GroupCompany[]): number | null {
  let best: number | null = null;
  for (const c of companies) {
    const v = c.values[metric];
    if (typeof v === "number" && (best === null || v > best)) best = v;
  }
  return best;
}

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
}

export default function GroupCompare({ payload, lang }: { payload: GroupComparePayload; lang: Lang }) {
  const labels = useMemo(
    () => Object.fromEntries(Object.entries(T).map(([k, v]) => [k, v[lang]])),
    [lang]
  ) as Record<keyof typeof T, string>;

  const metrics = payload.metrics.map((m) => m.key);
  const companies = payload.companies;

  const chartData = metrics.map((m) => {
    const row: Record<string, string | number | null> = { metric: labels[m as keyof typeof T] ?? m };
    for (const c of companies) row[`${c.id}`] = c.values[m];
    return row;
  });

  return (
    <>
      <header className="analysis-header">
        <div>
          <h2>{labels.title}</h2>
          <span className="meta">
            {companies.map((c) => c.name).join(" · ")}
            {" — "}
            {labels.subtitle}
          </span>
        </div>
      </header>

      <section className="panel">
        <h3>{labels.company}</h3>
        <table className="cmp-table group-cmp">
          <thead>
            <tr>
              <th>{labels.company}</th>
              {metrics.map((m) => (
                <th key={m}>{labels[m as keyof typeof T] ?? m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {companies.map((c, i) => (
              <tr key={c.id}>
                <td>
                  <span className="grp-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
                  {c.name}
                </td>
                {metrics.map((m) => {
                  const v = c.values[m];
                  const isBest = typeof v === "number" && v === bestIn(m, companies) && companies.length > 1;
                  return (
                    <td key={m} className={`num ${isBest ? "strong best" : ""}`}>
                      {typeof v === "number" ? fmt(v) : labels.dash}
                      {isBest && " ★"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h3>{labels.subtitle}</h3>
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
              <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
              <YAxis
                tick={{ fontSize: 11 }}
                width={72}
                tickFormatter={(v: number) => fmt(v)}
              />
              <Tooltip formatter={(v: number) => fmt(v)} />
              <Legend />
              {companies.map((c, i) => (
                <Bar
                  key={c.id}
                  name={c.name}
                  dataKey={`${c.id}`}
                  fill={PALETTE[i % PALETTE.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </>
  );
}
