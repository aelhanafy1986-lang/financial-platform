import { Fragment, useEffect, useState } from "react";
import type { AdvicePayload, Lang } from "./types";
import { Sparkline } from "./Sparkline";

type Comp = NonNullable<AdvicePayload["yearly_comparison"]>;
type Row = Comp["rows"][number];

const T = {
  title: { ar: "📊 تحليل المقارنة (أفقي وعمودي)", en: "📊 Comparative Analysis" },
  legend: { ar: "دليل الألوان", en: "Color guide" },
  improved: { ar: "تحسّن", en: "Improved" },
  declined: { ar: "تراجع", en: "Declined" },
  flat: { ar: "مستقر", en: "Flat" },
  heat: { ar: "شدة اللون = حجم التغير", en: "Colour depth = change size" },
  bands: {
    income: { ar: "قائمة الدخل", en: "Income Statement" },
    balance: { ar: "قائمة المركز المالي", en: "Statement of Financial Position" },
  } as Record<string, { ar: string; en: string }>,
};

/** Arrow + verdict class per row (cost-aware: a falling cost is an up-arrow). */
function arrow(r: Row): { ch: string; cls: string } | null {
  const v = r.change_pct_val ?? 0;
  if (Math.abs(v) < 0.05) return { ch: "◄►", cls: "flat" };
  const good = r.color === "good";
  if (v > 0) return { ch: "▲", cls: good ? "up-good" : "up-bad" };
  return { ch: "▼", cls: good ? "down-good" : "down-bad" };
}

/** Heatmap background: green/red intensity scaled by |change %| (capped at 25%). */
function heat(r: Row, el: HTMLElement, key: "change" | "pct" | "v") {
  const v = Math.abs(r.change_pct_val ?? 0);
  const t = Math.min(v / 25, 1); // 0 → none, 1 → full at ±25%
  const alpha = (0.06 + 0.3 * t).toFixed(3);
  const base = r.color === "bad" ? "220, 38, 38" : "5, 150, 105";
  if (key === "change") {
    el.style.backgroundColor = `rgba(${base}, ${alpha})`;
  } else {
    // vertical % column: neutral teal heat by size, independent of verdict
    const pv = Math.abs(r.pct_curr_val ?? 0);
    const tt = Math.min(pv / 100, 1);
    el.style.backgroundColor = `rgba(15, 118, 110, ${(0.03 + 0.14 * tt).toFixed(3)})`;
  }
}

export function YearlyComparisonTable({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  const [comp, setComp] = useState<AdvicePayload["yearly_comparison"]>(null);

  useEffect(() => {
    setComp(null);
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => r.json())
      .then((d: AdvicePayload) => setComp(d.yearly_comparison ?? null))
      .catch(() => {});
  }, [analysisId, lang]);

  if (!comp?.rows?.length) return null;
  const multi = (comp.periods ?? 2) > 2;

  const hasHeat = comp.rows.some(
    (r) => r.change_pct_val !== undefined || r.pct_curr_val !== undefined,
  );

  return (
    <section className="panel yearly-comparison">
      <h3>{comp.title || T.title[lang]}</h3>

      {hasHeat && (
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
      )}

      <div className="yc-table-wrap">
        <table className="yc-table">
          <thead>
            <tr>
              {comp.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comp.rows.map((r, i) => {
              // visual closure: a full-width band opens each statement's
              // block (income statement, then balance sheet)
              const stmt = r.stmt ?? "income";
              const band = i === 0 || (comp.rows[i - 1].stmt ?? "income") !== stmt
                ? T.bands[stmt]?.[lang] : null;
              const a = arrow(r);
              const sparkColor =
                r.color === "bad" ? "#dc2626" : r.color === "good" ? "#059669" : "#64748b";
              return (
                <Fragment key={r.key}>
                {band && (
                  <tr className="yc-band">
                    <td colSpan={comp.columns.length}>{band}</td>
                  </tr>
                )}
                <tr>
                  <td className="yc-label">
                    {a && <span className={`yc-arrow ${a.cls}`}>{a.ch}</span>}
                    {r.label}
                    {multi && (r.history?.length ?? 0) >= 2 && (
                      <Sparkline values={r.history!} color={sparkColor} lang={lang} />
                    )}
                  </td>
                  <td className="num">{r.curr}</td>
                  <td className="num muted">{r.prev}</td>
                  <td
                    className={`num strong ${r.color ?? ""}`}
                    ref={(el) => el && heat(r, el, "change")}
                  >
                    {r.change}
                  </td>
                  <td
                    className={`num strong ${r.color ?? ""}`}
                    ref={(el) => el && heat(r, el, "pct")}
                  >
                    {r.change_pct}
                  </td>
                  <td
                    className="num"
                    ref={(el) => el && heat(r, el, "v")}
                  >
                    {r.pct_curr}
                  </td>
                  <td className="num muted">{r.pct_prev}</td>
                </tr>
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {comp.note && <div className="yc-note">{comp.note}</div>}
    </section>
  );
}
