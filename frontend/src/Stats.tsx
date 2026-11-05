import { useEffect, useState } from "react";
import type { Lang } from "./types";

export interface StatsPayload {
  total: number;
  analyses: {
    id: number;
    name: string;
    created_at: string;
    edited: boolean;
  }[];
  concepts: Record<
    string,
    {
      label: { ar?: string; en?: string; value?: number };
      label_en: string;
      first: { name: string; date: string; value: number };
      last: { name: string; date: string; value: number };
      change_pct: number | null;
      trend: "up" | "down" | "flat";
    }
  >;
}

const T = {
  title: { ar: "📊 لوحة الإحصاءات", en: "📊 Statistics" },
  close: { ar: "إخفاء", en: "Hide" },
  total: { ar: "تحليلات محفوظة", en: "saved analyses" },
  concept: { ar: "البند", en: "Concept" },
  oldest: { ar: "أقدم تحليل", en: "Oldest" },
  latest: { ar: "أحدث تحليل", en: "Latest" },
  change: { ar: "التغير بين التحليلات", en: "Change across analyses" },
  nothing: {
    ar: "لا توجد بيانات كافية للإحصاءات بعد",
    en: "Not enough data for statistics yet",
  },
  up: { ar: "صاعد ▲", en: "Up ▲" },
  down: { ar: "هابط ▼", en: "Down ▼" },
  flat: { ar: "مستقر ◄►", en: "Flat ◄►" },
};

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function Stats({ payload, lang }: { payload: StatsPayload; lang: Lang }) {
  const concepts = Object.values(payload.concepts).filter(
    (c) => c.first && c.last && c.first.name !== c.last.name
  );
  if (!concepts.length) {
    return <div className="placeholder">{T.nothing[lang]}</div>;
  }

  return (
    <section className="panel stats-panel">
      <h3>
        {T.title[lang]} — {payload.total} {T.total[lang]}
      </h3>
      <div className="stats-grid">
        {concepts.map((c, i) => (
          <div className="stat-card" key={c.label_en + i}>
            <h4>{lang === "ar" ? c.label?.ar ?? c.label_en : c.label_en}</h4>
            <div className="stat-values">
              <div>
                <small>{T.oldest[lang]}: </small>
                <span title={c.first.name}>{c.first.name}</span>
                {" · "}
                <span className="num">{fmt(c.first.value)}</span>
              </div>
              <div>
                <small>{T.latest[lang]}: </small>
                <span title={c.last.name}>{c.last.name}</span>
                {" · "}
                <span className="num">{fmt(c.last.value)}</span>
              </div>
              <div className={c.trend}>
                {T.change[lang]}:{" "}
                <span className="num">
                  {c.change_pct !== null && (c.change_pct > 0 ? "+" : "")}
                  {c.change_pct !== null ? c.change_pct + "%" : "—"}
                </span>{" "}
                {c.trend === "up" ? T.up[lang] : c.trend === "down" ? T.down[lang] : T.flat[lang]}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
