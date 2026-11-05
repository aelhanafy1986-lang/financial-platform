import { useEffect, useRef, useState } from "react";
import type { AdvicePayload, Lang, RatioInsight, ConsistencyCheck } from "./types";
import { Glyph } from "./Glyph";

const T = {
  title: { ar: "📐 تحليل النسب المالية", en: "📐 Ratio Analysis" },
  consistency: { ar: "✅ التحقق من صحة الأرقام", en: "✅ Consistency checks" },
  quality: { ar: "فحوصات الجودة", en: "Quality checks" },
  what: { ar: "ما هي؟", en: "What is it?" },
  why: { ar: "ما فائدتها؟", en: "Why it matters" },
  opinion: { ar: "الرأي", en: "Verdict" },
};

function fmtVal(c: RatioInsight, lang: Lang): string {
  if (c.is_percent) return `${c.value.toFixed(2)}%`;
  if (c.is_days)
    return `${Math.round(c.value)} ${lang === "ar" ? "يوم" : "days"}`;
  return `${c.value.toFixed(2)}x`;
}

export function RatioInsights({
  analysisId,
  lang,
  focusQuality = 0,
  onQualityFocusDone,
}: {
  analysisId: number;
  lang: Lang;
  /** non-zero token (Date.now()) while a quality-badge click is waiting to land on this section; changes on every click so repeats re-trigger */
  focusQuality?: number;
  onQualityFocusDone?: () => void;
}) {
  const [insights, setInsights] = useState<RatioInsight[]>([]);
  const [checks, setChecks] = useState<ConsistencyCheck[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [hl, setHl] = useState(false);
  const hlTimer = useRef<number | null>(null);

  useEffect(() => {
    setInsights([]);
    setChecks([]);
    setLoaded(false);
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => r.json())
      .then((d: AdvicePayload) => {
        setInsights(d.ratio_insights ?? []);
        setChecks(d.consistency_checks ?? []);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [analysisId, lang]);

  // a click on the list's warning badge lands here: scroll the quality
  // checks into view and mark the violating (failing) items — the marker
  // holds ~12s, or until the user clicks anywhere (they took over)
  useEffect(() => {
    if (!focusQuality || !loaded) return;
    const target =
      document.getElementById("sec-quality-checks") ??
      document.getElementById("sec-ratio-insights");
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    setHl(true);
    const release = () => {
      setHl(false);
      onQualityFocusDone?.();
    };
    if (hlTimer.current) window.clearTimeout(hlTimer.current);
    hlTimer.current = window.setTimeout(release, 12000);
    const dismiss = () => release();
    window.addEventListener("pointerdown", dismiss, { once: true });
    return () => {
      if (hlTimer.current) window.clearTimeout(hlTimer.current);
      window.removeEventListener("pointerdown", dismiss);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusQuality, loaded]);

  if (insights.length === 0 && checks.length === 0) return null;

  return (
    <section className="panel ratio-insights">
      <h3>{T.title[lang]}</h3>

      {checks.length > 0 && (
        <div className={`consistency-box ${hl ? "quality-focus" : ""}`} id="sec-quality-checks">
          <div className="consistency-head">
            {T.consistency[lang]}
            {hl && <span className="quality-focus-hint"> — {T.quality[lang]}</span>}
          </div>
          <ul className="consistency-list">
            {checks.map((c) => (
              <li
                key={c.label}
                className={`${c.ok ? "ok" : "fail"} ${hl && !c.ok ? "chk-hl" : ""}`}
              >
                <span className="chk"><Glyph name={c.ok ? "check" : "cross"} size={10} /></span>
                <span className="chk-label">{c.label}</span>
                <span className="chk-detail">{c.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {insights.map((c) => (
        <div className={`ratio-card ${c.verdict}`} key={c.key}>
          <div className="ratio-card-head">
            <strong>{c.label}</strong>
            <span className="ratio-val">{fmtVal(c, lang)}</span>
          </div>
          <div className="ratio-row">
            <span className="ratio-q">{T.what[lang]}</span>
            <span>{c.what}</span>
          </div>
          <div className="ratio-row">
            <span className="ratio-q">{T.why[lang]}</span>
            <span>{c.why}</span>
          </div>
          <div className="ratio-row opinion">
            <span className="ratio-q">{T.opinion[lang]}</span>
            <span>{c.opinion}</span>
          </div>
        </div>
      ))}
    </section>
  );
}
