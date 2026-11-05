import { useEffect, useState } from "react";
import type { Lang } from "./types";

const T = {
  title: { ar: "🎯 النسب مقابل المعايير المرجعية", en: "🎯 Ratios vs Reference Benchmarks" },
  ours: { ar: "النسبة المحققة (نسبة لمعيارها)", en: "Achieved ratio (× its benchmark)" },
  note: {
    ar: "المرساة = 1.00 · فوقها تحقيق للمعيار وتحتها قصور — المراسي وفق المنهجية (نسبة التداول 2.0، تغطية الفوائد 3.0×، تحصيل ≤ 90 يومًا…) · مستوفٍ · قريب · غير مستوفٍ",
    en: "Anchor = 1.00 · above means the benchmark is met, below means short of it — anchors per the adopted methodology (current ratio 2.0, interest coverage 3.0×, collection ≤ 90 days…) · Aligned · Near · Off",
  },
  empty: { ar: "لا توجد نسب قابلة للمقارنة بمعايير مرجعية", en: "No ratios with reference benchmarks" },
};

interface Bullet {
  key: string;
  label: string;
  value: number;
  norm: number;
  verdict: string;
}

const VERDICT_COLOR: Record<string, string> = {
  good: "#059669",
  ok: "#f59e0b",
  bad: "#dc2626",
};

export function BenchmarkAlignment({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  const [bullets, setBullets] = useState<Bullet[] | null>(null);

  useEffect(() => {
    setBullets(null);
    fetch(`/api/analyses/${analysisId}/dashboard?lang=${lang}`)
      .then((r) => r.json())
      .then((d) => setBullets(d.bullets || []))
      .catch(() => setBullets([]));
  }, [analysisId, lang]);

  if (bullets === null) return <div className="dash-section skeleton" />;
  if (bullets.length === 0) return null;

  return (
    <div className="dash-section" id="sec-benchmarks-inner">
      <h3>{T.title[lang]}</h3>
      <div className="bench-list">
        {bullets.map((b) => {
          const color = VERDICT_COLOR[b.verdict] || "#0070C0";
          const pct = Math.max(0, Math.min(100, (b.norm / 2) * 100));
          return (
            <div className="bench-row" key={b.key}>
              <span className="bench-label">{b.label}</span>
              <div className="bench-track">
                <div className="bench-fill" style={{ width: `${pct}%`, background: color }} />
                {/* anchor = 1.00 sits at the middle of the 0..2 scale */}
                <div className="bench-anchor" />
              </div>
              <span className="bench-value" style={{ color }}>
                {b.norm.toFixed(2)}×
              </span>
            </div>
          );
        })}
      </div>
      <div className="bench-legend">
        <span>
          <span className="dash-swatch" style={{ background: "#0070C0" }} /> {T.ours[lang]}
        </span>
        <span className="bench-note">{T.note[lang]}</span>
      </div>
      {bullets.length === 0 && <div className="placeholder">{T.empty[lang]}</div>}
    </div>
  );
}

export default BenchmarkAlignment;
