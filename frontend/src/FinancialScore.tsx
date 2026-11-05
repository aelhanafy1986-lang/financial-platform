import { useEffect, useState } from "react";
import type { AdvicePayload, Lang, Scenario } from "./types";

const T = {
  title: { ar: "🎯 التقييم المالي", en: "🎯 Financial Score" },
  of100: { ar: "من 100", en: "of 100" },
  dims: { ar: "أبعاد التقييم", en: "Score dimensions" },
  scenarios: { ar: "🔮 السيناريوهات المستقبلية", en: "🔮 Future scenarios" },
  nextRev: { ar: "الإيراد المتوقع", en: "Projected revenue" },
  nextNet: { ar: "صافي الربح المتوقع", en: "Projected net" },
  growth: { ar: "النمو", en: "Growth" },
  noData: { ar: "لا تتوفر بيانات كافية للتقييم", en: "Not enough data to score" },
};

/** Conic-gradient ring gauge for the 0-100 score. */
function ScoreRing({ score, color }: { score: number; color: string }) {
  const deg = Math.max(0, Math.min(100, score)) * 3.6;
  return (
    <div
      className="score-ring"
      style={{
        background: `conic-gradient(${color} ${deg}deg, var(--ring-track, #e5e7eb) ${deg}deg)`,
      }}
    >
      <div className="score-ring-hole">
        <strong>{Math.round(score)}</strong>
        <span>{T.of100.en === "of 100" ? "/100" : "/100"}</span>
      </div>
    </div>
  );
}

function ScenarioCard({ s, lang }: { s: Scenario; lang: Lang }) {
  const cls = s.key === "optimistic" ? "opt" : s.key === "conservative" ? "cons" : "real";
  const fmt = (v: number) =>
    new Intl.NumberFormat(lang === "ar" ? "ar-EG" : "en-US", {
      maximumFractionDigits: 0,
    }).format(v);
  return (
    <div className={`scenario-card ${cls}`}>
      <div className="scenario-name">{lang === "ar" ? s.ar : s.en}</div>
      <div className="scenario-growth">
        {s.growth_pct >= 0 ? "▲" : "▼"} {Math.abs(s.growth_pct)}% {T.growth[lang]}
      </div>
      <div className="scenario-row">
        <span>{T.nextRev[lang]}</span>
        <strong>{fmt(s.revenue)}</strong>
      </div>
      <div className="scenario-row">
        <span>{T.nextNet[lang]}</span>
        <strong className={s.net < 0 ? "neg" : "pos"}>{fmt(s.net)}</strong>
      </div>
    </div>
  );
}

export function FinancialScore({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  const [data, setData] = useState<AdvicePayload | null>(null);

  useEffect(() => {
    setData(null);
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, [analysisId, lang]);

  const score = data?.score;
  const scenarios = data?.scenarios?.scenarios;

  if (!data) return <div className="score-section skeleton" />;
  if (!score || score.score === null) {
    return (
      <div className="score-section">
        <h3>{T.title[lang]}</h3>
        <div className="placeholder">{T.noData[lang]}</div>
      </div>
    );
  }

  return (
    <div className="score-section">
      <h3>{T.title[lang]}</h3>
      <div className="score-main">
        <ScoreRing score={score.score} color={score.grade?.color ?? "#22c55e"} />
        <div className="score-grade" style={{ color: score.grade?.color }}>
          {lang === "ar" ? score.grade?.ar : score.grade?.en}
        </div>
        <div className="score-dims">
          {score.dimensions.map((d) => (
            <div className="score-dim" key={d.key}>
              <span className="dim-name">{lang === "ar" ? d.ar : d.en}</span>
              <div className="dim-bar">
                <div
                  className="dim-fill"
                  style={{ width: `${(d.points / d.weight) * 100}%` }}
                />
              </div>
              <span className="dim-pts">
                {Math.round(d.points)}/{d.weight}
              </span>
            </div>
          ))}
        </div>
      </div>

      {scenarios && scenarios.length > 0 && (
        <>
          <h4>{T.scenarios[lang]}</h4>
          <div className="scenarios-grid">
            {scenarios.map((s) => (
              <ScenarioCard key={s.key} s={s} lang={lang} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default FinancialScore;
