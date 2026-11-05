import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
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
import type { AnalysisFull, Lang } from "./types";
import { Sparkline } from "./Sparkline";

export interface ComparePayload {
  base: { id: number; filename: string };
  target: { id: number; filename: string };
  kpis: Record<string, CompareRow>;
  ratios: Record<string, CompareRow>;
  series: Record<string, CompareSeries>;
  /** Sales-kind comparison block (ride-along from /api/compare). */
  sales?: SalesCompare | null;
}

export interface SalesCompare {
  rows: Record<string, CompareRow>;
  regions: Record<string, CompareRow>;
  shared_months: string[];
  base_total?: number | null;
  target_total?: number | null;
  base: { regions: number; months: number };
  target: { regions: number; months: number };
}

export interface CompareRow {
  ar: string;
  en: string;
  base: number;
  target: number;
  change_pct: number;
  /** Judgment-based colour: 'good' | 'bad' | null (flat). */
  verdict?: "good" | "bad" | null;
  /** Base-side series + target's last value, for the UI sparkline. */
  history?: number[];
}

export interface CompareSeries {
  ar: string;
  en: string;
  base_values: number[];
  target_values: number[];
  change_pct: number;
  verdict?: "good" | "bad" | null;
}

const BASE_COLOR = "#94a3b8";
const TARGET_COLOR = "#0f766e";

const T = {
  compare_title: { ar: "مقارنة", en: "Comparison" },
  baseline: { ar: "المرجع", en: "Baseline" },
  comparison: { ar: "المقارن", en: "Comparison" },
  item: { ar: "البند", en: "Item" },
  base_col: { ar: "المرجع", en: "Baseline" },
  target_col: { ar: "المقارن", en: "Comparison" },
  change_col: { ar: "التغير", en: "Change" },
  kpis: { ar: "المؤشرات الرئيسية", en: "Key Indicators" },
  ratios: { ar: "النسب المالية", en: "Financial Ratios" },
  series: { ar: "الرسوم البيانية التحليلية", en: "Analytical Charts" },
  download: { ar: "تحميل تقرير المقارنة PDF", en: "Download Comparison PDF" },
  nothing: {
    ar: "لا توجد بنود مشتركة للمقارنة بين التحليلين",
    en: "No shared items to compare between these analyses",
  },
  pt: { ar: "نقطة", en: "pt" },
  legend: { ar: "دليل الألوان", en: "Color guide" },
  improved: { ar: "تحسّن", en: "Improved" },
  declined: { ar: "تراجع", en: "Declined" },
  flat: { ar: "مستقر", en: "Flat" },
  heat: { ar: "شدة اللون = حجم التغير", en: "Colour depth = change size" },
  // summary strip + extra charts (user request 2026-10-12: more indicators,
  // more charts and more comparisons on the compare screen)
  sumTitle: { ar: "ملخص المقارنة", en: "Comparison summary" },
  deltas: { ar: "حجم التغيرات (٪)", en: "Change magnitudes (%)" },
  winners: { ar: "الأفضل في كل بند", en: "Best-in-item wins" },
  radarTitle: { ar: "رادار النسب (أفقي: المرجع · عمودي: المقارن)", en: "Ratio radar (grey: baseline · teal: comparison)" },
  winsBase: { ar: "يتقدم المرجع", en: "Baseline leads" },
  winsTarget: { ar: "يتميّز المقارن", en: "Comparison leads" },
  absVal: { ar: "القيم المطلقة", en: "Absolute values" },
  improvedN: { ar: "تحسّن", en: "improved" },
  declinedN: { ar: "تراجع", en: "declined" },
  flatN: { ar: "مستقر", en: "flat" },
  // sales comparison headers (block rendered when the payload carries `sales`)
  salesKpis: { ar: "مؤشرات المبيعات", en: "Sales indicators" },
  salesRegions: { ar: "المناطق المشتركة", en: "Shared regions" },
  salesNote: {
    ar: "شهر مشترك: {m}",
    en: "Shared months: {m}",
  },
  salesNoCommon: {
    ar: "لا توجد مناطق مشتركة بين ملفّي المبيعات — المقارنة على مستوى الإجماليات فقط",
    en: "No shared regions between the two sales files — totals only",
  },
};

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
}

/** Arrow + class per row: direction from the sign, colour from the verdict. */
function arrow(changePct: number, verdict?: "good" | "bad" | null) {
  if (Math.abs(changePct) <= 0.05) return { ch: "◄►", cls: "flat" };
  const good = verdict === "good";
  if (changePct > 0) return { ch: "▲", cls: good ? "up-good" : "up-bad" };
  return { ch: "▼", cls: good ? "down-good" : "down-bad" };
}

/** Heatmap cell: green/red intensity scaled by |change %| (full at ±25%). */
function heatCell(changePct: number, verdict?: "good" | "bad" | null) {
  const t = Math.min(Math.abs(changePct) / 25, 1);
  const alpha = (0.06 + 0.3 * t).toFixed(3);
  const base = verdict === "bad" ? "220, 38, 38" : "5, 150, 105";
  return { backgroundColor: `rgba(${base}, ${alpha})` };
}

function CompareLegend({ lang }: { lang: Lang }) {
  return (
    <div className="yc-legend" aria-hidden="true">
      <span className="yc-leg-item">
        <i className="yc-swatch good" /> ▲ {T.improved[lang]}
      </span>
      <span className="yc-leg-item">
        <i className="yc-swatch bad" /> ▼ {T.declined[lang]}
      </span>
      <span className="yc-leg-item">
        <i className="yc-swatch flat" /> ◄► {T.flat[lang]}
      </span>
      <span className="yc-leg-heat">
        <i className="yc-gradient" /> {T.heat[lang]}
      </span>
    </div>
  );
}

interface Props {
  payload: ComparePayload;
  lang: Lang;
  t: Record<string, { ar: string; en: string }>;
}

export default function Compare({ payload, lang, t }: Props) {
  const labels = useMemo(() => {
    const out: Record<string, string> = {};
    Object.entries(T).forEach(([k, v]) => (out[k] = v[lang]));
    return out;
  }, [lang]);

  const hasAnything =
    Object.keys(payload.kpis).length +
      Object.keys(payload.ratios).length +
      Object.keys(payload.series).length >
    0;
  const sales = payload.sales;
  const hasSales = !!sales &&
    (Object.keys(sales.rows).length + Object.keys(sales.regions).length > 0);

  /** Sales-vs-sales comparison renderer — the financial-concept compare
   *  shows nothing for two sales files, which read as the empty state; this
   *  block renders their real indicators instead (fix 2026-10-12). */
  const renderSales = () => {
    if (!sales || !hasSales) return null;
    const renderRowTable = (
      title: string,
      rows: Record<string, CompareRow>,
      asPercent: boolean,
    ) => {
      if (!Object.keys(rows).length) return null;
      return renderTable(title, rows, asPercent);
    };
    const monthsLabel = sales.shared_months.length
      ? T.salesNote[lang].replace("{m}", sales.shared_months.join(" · "))
      : T.salesNoCommon[lang];
    return (
      <>
        <div className="cmp-sales-meta">
          <span>{`(${sales.base.regions}/${sales.target.regions})`}</span>
          <span>{monthsLabel}</span>
        </div>
        {renderRowTable(T.salesKpis[lang], sales.rows, false)}
        {renderRowTable(T.salesRegions[lang], sales.regions, false)}
      </>
    );
  };

  /* ---------- added comparisons (2026-10-12) ---------- */

  const allRows = useMemo(
    () => [...Object.values(payload.kpis), ...Object.values(payload.ratios)],
    [payload.kpis, payload.ratios],
  );
  const counts = useMemo(() => {
    const improved = allRows.filter((r) => r.verdict === "good").length;
    const declined = allRows.filter((r) => r.verdict === "bad").length;
    return { improved, declined, flat: allRows.length - improved - declined };
  }, [allRows]);

  // headline KPI bars: baseline vs comparison for the biggest absolute items
  const headline = useMemo(() => {
    const pick = Object.values(payload.kpis)
      .slice(0, 4)
      .map((r) => ({
        name: r[lang],
        base: Math.abs(r.base),
        target: Math.abs(r.target),
      }));
    return pick;
  }, [payload.kpis, lang]);

  // change-magnitude bar chart, sorted by |change %| desc
  const deltaBars = useMemo(
    () =>
      allRows
        .slice()
        .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
        .slice(0, 8)
        .map((r) => ({
          name: r[lang],
          change: r.change_pct,
          verdict: r.verdict ?? null,
        })),
    [allRows, lang],
  );

  // ratio radar: normalized per-ratio scale (max across the pair = 100)
  const ratioRadar = useMemo(() => {
    const rows = Object.values(payload.ratios);
    if (rows.length < 3) return [];
    return rows.map((r) => {
      const mx = Math.max(Math.abs(r.base), Math.abs(r.target)) || 1;
      return {
        ratio: r[lang],
        base: Math.round((Math.abs(r.base) / mx) * 100),
        target: Math.round((Math.abs(r.target) / mx) * 100),
      };
    });
  }, [payload.ratios, lang]);

  // best-in-item wins: which side «wins» each judged row (verdict colour
  // already says who improved — count improvement direction per side)
  const wins = useMemo(() => {
    let base = 0, target = 0;
    for (const r of allRows) {
      if (r.verdict === "good") {
        // improvement direction tells whose value moved favourably
        if (r.target >= r.base) target++; else base++;
      } else if (r.verdict === "bad") {
        if (r.target <= r.base) base++; else target++;
      }
    }
    return { base, target };
  }, [allRows]);

  const deltaColor = (v: "good" | "bad" | null) =>
    v === "bad" ? "#dc2626" : v === "good" ? "#059669" : "#94a3b8";

  const renderSummary = () => (
    <section className="panel cmp-summary">
      <h3>{labels.sumTitle}</h3>
      <div className="cmp-summary-grid">
        <div className="cmp-sum-card">
          <strong>{allRows.length}</strong>
          <span>{labels.item}</span>
        </div>
        <div className="cmp-sum-card good">
          <strong>{counts.improved}</strong>
          <span>▲ {labels.improvedN}</span>
        </div>
        <div className="cmp-sum-card bad">
          <strong>{counts.declined}</strong>
          <span>▼ {labels.declinedN}</span>
        </div>
        <div className="cmp-sum-card">
          <strong>{counts.flat}</strong>
          <span>◄► {labels.flatN}</span>
        </div>
        <div className="cmp-sum-card base">
          <strong>{wins.base}</strong>
          <span>{labels.winsBase}</span>
        </div>
        <div className="cmp-sum-card target">
          <strong>{wins.target}</strong>
          <span>{labels.winsTarget}</span>
        </div>
      </div>
    </section>
  );

  const renderExtraCharts = () => (
    <>
      {headline.length > 0 && (
        <section className="panel">
          <h3>{labels.absVal}</h3>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={headline}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={72} tickFormatter={(v: number) => fmt(v)} />
                <Tooltip formatter={(v: number) => fmt(v)} />
                <Legend />
                <Bar name={labels.base_col} dataKey="base" fill={BASE_COLOR} radius={[4, 4, 0, 0]} />
                <Bar name={labels.target_col} dataKey="target" fill={TARGET_COLOR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {deltaBars.length > 0 && (
        <section className="panel">
          <h3>{labels.deltas}</h3>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={Math.max(220, deltaBars.length * 34 + 60)}>
              <BarChart data={deltaBars} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number) => `${v}%`} />
                <Bar dataKey="change" radius={[4, 4, 0, 0]}>
                  {deltaBars.map((d, i) => (
                    <Cell key={i} fill={deltaColor(d.verdict)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {ratioRadar.length >= 3 && (
        <section className="panel">
          <h3>{labels.radarTitle}</h3>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={320}>
              <RadarChart data={ratioRadar} outerRadius="72%">
                <PolarGrid />
                <PolarAngleAxis dataKey="ratio" tick={{ fontSize: 11 }} />
                <PolarRadiusAxis tick={{ fontSize: 10 }} domain={[0, 100]} />
                <Tooltip formatter={(v: number) => `${v}%`} />
                <Legend />
                <Radar name={labels.base_col} dataKey="base" stroke={BASE_COLOR} fill={BASE_COLOR} fillOpacity={0.25} />
                <Radar name={labels.target_col} dataKey="target" stroke={TARGET_COLOR} fill={TARGET_COLOR} fillOpacity={0.3} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </>
  );

  const renderTable = (
    title: string,
    rows: Record<string, CompareRow>,
    asPercent: boolean
  ) => {
    if (!Object.keys(rows).length) return null;
    return (
      <section className="panel">
        <h3>{title}</h3>
        <CompareLegend lang={lang} />
        <table className="cmp-table">
          <thead>
            <tr>
              <th>{labels.item}</th>
              <th>{labels.base_col}</th>
              <th>{labels.target_col}</th>
              <th>{labels.change_col}</th>
            </tr>
          </thead>
          <tbody>
            {Object.values(rows).map((row) => {
              const a = arrow(row.change_pct, row.verdict);
              const change = asPercent
                ? `${row.target - row.base >= 0 ? "+" : ""}${(row.target - row.base).toFixed(1)} ${labels.pt}`
                : `${row.change_pct >= 0 ? "+" : ""}${row.change_pct}%`;
              const cls =
                row.verdict === "good" ? "good" : row.verdict === "bad" ? "bad" : "flat";
              const sparkColor =
                row.verdict === "bad" ? "#dc2626" : row.verdict === "good" ? "#059669" : "#64748b";
              return (
                <tr key={row.en}>
                  <td>
                    <span className={`yc-arrow ${a.cls}`}>{a.ch}</span>
                    {row[lang]}
                    {(row.history?.length ?? 0) >= 2 && (
                      <Sparkline values={row.history!} color={sparkColor} lang={lang} />
                    )}
                  </td>
                  <td className="num">{fmt(row.base)}</td>
                  <td className="num">{fmt(row.target)}</td>
                  <td className={`num strong ${cls}`} style={heatCell(row.change_pct, row.verdict)}>
                    {change}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    );
  };

  return (
    <div className="compare-page compare-page-wide">
      <header className="analysis-header">
        <div>
          <h2>{labels.compare_title}</h2>
          <span className="meta">
            {labels.baseline}: {payload.base.filename} ⇄ {labels.comparison}: {payload.target.filename}
          </span>
        </div>
        <a
          className="pdf-btn"
          href={`/api/compare/${payload.base.id}/${payload.target.id}/report?lang=${lang}`}
          target="_blank"
          rel="noreferrer"
        >
          📄 {labels.download}
        </a>
      </header>

      {!hasAnything && !hasSales && (
        <div className="placeholder">{labels.nothing}</div>
      )}

      {(hasAnything || hasSales) && renderSales()}
      {(hasAnything || hasSales) && renderSummary()}

      {Object.keys(payload.kpis).length > 0 && renderTable(labels.kpis, payload.kpis, false)}
      {Object.keys(payload.ratios).length > 0 && renderTable(labels.ratios, payload.ratios, true)}

      {hasAnything && renderExtraCharts()}

      {Object.keys(payload.series).length > 0 && (
        <section className="panel">
          <h3>{labels.series}</h3>
          <div className="charts">
            {Object.entries(payload.series).map(([key, s]) => {
              const n = Math.max(s.base_values.length, s.target_values.length);
              const data = Array.from({ length: n }, (_, i) => ({
                idx: i + 1,
                base: s.base_values[i] ?? null,
                target: s.target_values[i] ?? null,
              }));
              return (
                <div className="chart-box" key={key}>
                  <span className="chart-title">
                    {s[lang]} · {s.change_pct >= 0 ? "+" : ""}
                    {s.change_pct}%
                  </span>
                  <ResponsiveContainer width="100%" height={190}>
                    {data.some((d) => d.base !== null) && data.some((d) => d.target !== null) ? (
                      <LineChart data={data}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                        <XAxis dataKey="idx" tick={{ fontSize: 11 }} />
                        <YAxis
                          tick={{ fontSize: 11 }}
                          width={64}
                          tickFormatter={(v: number) => fmt(v)}
                        />
                        <Tooltip formatter={(v: number) => fmt(v)} />
                        <Legend />
                        <Line
                          name={labels.base_col}
                          type="monotone"
                          dataKey="base"
                          stroke={BASE_COLOR}
                          strokeWidth={2}
                          dot={false}
                          connectNulls
                        />
                        <Line
                          name={labels.target_col}
                          type="monotone"
                          dataKey="target"
                          stroke={TARGET_COLOR}
                          strokeWidth={2.5}
                          dot
                          connectNulls
                        />
                      </LineChart>
                    ) : (
                      <BarChart data={data}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                        <XAxis dataKey="idx" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} width={64} tickFormatter={(v: number) => fmt(v)} />
                        <Tooltip formatter={(v: number) => fmt(v)} />
                        <Legend />
                        <Bar name={labels.base_col} dataKey="base" fill={BASE_COLOR} radius={[4, 4, 0, 0]} />
                        <Bar name={labels.target_col} dataKey="target" fill={TARGET_COLOR} radius={[4, 4, 0, 0]} />
                      </BarChart>
                    )}
                  </ResponsiveContainer>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
