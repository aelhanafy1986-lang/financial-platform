import { useEffect, useState } from "react";
import type { AdvicePayload, Lang } from "./types";

type Comp = NonNullable<AdvicePayload["yearly_comparison"]>;
type Row = Comp["rows"][number];

const T = {
  title: { ar: "النمو بين الفترتين", en: "Growth between periods" },
  flat: { ar: "مستقر", en: "flat" },
};

/** The horizontal-analysis headline set: revenue, costs, profits. */
const GROWTH_KEYS = new Set([
  "revenue",
  "cogs",
  "gross_profit",
  "opex",
  "net_profit",
]);

/** Shown whenever at least two periods exist: compares the LAST two
 *  periods (the horizontal-analysis pair), e.g. 2023 → 2024. */
export function GrowthStrip({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    setRows([]);
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => r.json())
      .then((d: AdvicePayload) => {
        const comp = d.yearly_comparison ?? null;
        if (!comp?.rows?.length || (comp.periods ?? 2) < 2) {
          setRows([]);
          return;
        }
        setRows(comp.rows.filter((r) => GROWTH_KEYS.has(r.key)));
      })
      .catch(() => setRows([]));
  }, [analysisId, lang]);

  if (rows.length === 0) return null;

  return (
    <section className="panel growth-strip" id="sec-growth">
      <h3>{T.title[lang]}</h3>
      <div className="growth-cards">
        {rows.map((r) => {
          const v = r.change_pct_val ?? 0;
          const flat = Math.abs(v) < 0.05;
          const up = v > 0;
          // cost-aware colouring comes from the backend verdict
          const cls = flat ? "flat" : r.color === "good" ? "good" : "bad";
          const arrow = flat ? "◄►" : up ? "▲" : "▼";
          return (
            <div className={`growth-card ${cls}`} key={r.key}>
              <span className="growth-label">{r.label}</span>
              <span className={`growth-pct ${cls}`}>
                <span className="growth-arrow">{arrow}</span>
                {flat ? T.flat[lang] : `${r.change_pct}`}
              </span>
              <span className="growth-delta">{r.change}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
