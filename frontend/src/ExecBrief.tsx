import { useEffect, useState } from "react";
import type { AdvicePayload, Lang } from "./types";
import { Glyph } from "./Glyph";

const T = {
  title: { ar: "📋 الملخص التنفيذي", en: "📋 Executive Summary" },
  about: { ar: "نبذة عن الشركة ونشاطها", en: "About the company & activity" },
  activity: { ar: "نوع النشاط", en: "Activity" },
  size: { ar: "حجم الشركة", en: "Company size" },
  pattern: { ar: "نمط التشغيل", en: "Operating pattern" },
  results: { ar: "ملخص النتائج", en: "Results summary" },
  strengths: { ar: "نقاط القوة", en: "Strengths" },
  weaknesses: { ar: "نقاط الضعف", en: "Weaknesses" },
  fmt: { ar: "القيمة", en: "Value" },
};

function fmtNum(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

/** Parse the brief's formatted values ("4,663,364" / "38.9%") for display. */
export function ExecBrief({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  const [brief, setBrief] = useState<AdvicePayload["brief"]>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    setBrief(null);
    setWarnings([]);
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => r.json())
      .then((d: AdvicePayload) => {
        setBrief(d.brief ?? null);
        setWarnings(d.data_warnings ?? []);
      })
      .catch(() => {});
  }, [analysisId, lang]);

  if (!brief && warnings.length === 0) return null;
  const company = brief?.company ?? {};

  return (
    <section className="panel exec-brief">
      {warnings.length > 0 && (
        <div className="data-warnings" role="alert">
          {warnings.map((w) => (
            <div className="data-warning" key={w}>
              <Glyph name="warning" size={12} /> {w}
            </div>
          ))}
        </div>
      )}
      <h3>{T.title[lang]}</h3>

      <div className="exec-about">
        <div className="exec-about-head">🏢 {T.about[lang]}</div>
        <div className="exec-about-grid">
          {company.activity && (
            <div className="exec-about-row">
              <span className="exec-k">{T.activity[lang]}</span>
              <span className="exec-v">{company.activity}</span>
            </div>
          )}
          {company.size && (
            <div className="exec-about-row">
              <span className="exec-k">{T.size[lang]}</span>
              <span className="exec-v">{company.size}</span>
            </div>
          )}
          {company.pattern && (
            <div className="exec-about-row">
              <span className="exec-k">{T.pattern[lang]}</span>
              <span className="exec-v">{company.pattern}</span>
            </div>
          )}
          {company.activity_fit && (
            <div className="exec-about-row">
              <span className="exec-k">{company.activity_fit.title}</span>
              <span className={`exec-v fit-${company.activity_fit.verdict}`}>
                {company.activity_fit.turnover_txt}
                {" · "}
                {company.activity_fit.verdict_label}
              </span>
            </div>
          )}
        </div>
      </div>

      {(brief?.results?.length ?? 0) > 0 && (
        <div className="exec-results">
          <div className="exec-sub">{T.results[lang]}</div>
          <div className="exec-chips">
            {brief!.results!.map((r) => (
              <div className={`exec-chip ${r.negative ? "neg" : ""}`} key={r.label}>
                <span className="exec-chip-l">{r.label}</span>
                <strong>{r.value}</strong>
              </div>
            ))}
          </div>
        </div>
      )}

      {((brief?.strengths?.length ?? 0) > 0 || (brief?.weaknesses?.length ?? 0) > 0) && (
        <div className="exec-sw">
          <div className="exec-col strengths">
            <div className="exec-col-head pos"><Glyph name="check" size={11} /> {T.strengths[lang]}</div>
            <ul>
              {brief!.strengths!.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
          <div className="exec-col weaknesses">
            <div className="exec-col-head warn">! {T.weaknesses[lang]}</div>
            <ul>
              {brief!.weaknesses!.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {brief?.verdict && (
        <div className="exec-verdict">
          <strong>{brief.verdict}</strong>
          {brief.paragraph && <p>{brief.paragraph}</p>}
        </div>
      )}
    </section>
  );
}
