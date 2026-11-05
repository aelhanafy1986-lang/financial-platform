import { useEffect, useRef, useState } from "react";
import type { Lang } from "./types";

const SECTIONS = [
  { id: "sec-home", ar: "النظرة العامة", en: "Overview" },
  { id: "sec-exec-brief", ar: "الملخص التنفيذي", en: "Executive brief" },
  { id: "sec-statements", ar: "القوائم المالية", en: "Statements" },
  { id: "sec-kpis", ar: "المؤشرات الرئيسية", en: "Key indicators" },
  { id: "sec-ratios", ar: "النسب المالية", en: "Financial ratios" },
  { id: "sec-benchmarks", ar: "النسب مقابل المعايير", en: "Ratios vs benchmarks" },
  { id: "sec-ratio-insights", ar: "تحليل النسب", en: "Ratio insights" },
  { id: "sec-comparison", ar: "المقارنة السنوية", en: "Yearly comparison" },
  { id: "sec-trends", ar: "الرسوم البيانية التحليلية", en: "Analytical Charts" },
  { id: "sec-dashboard", ar: "لوحة المؤشرات التحليلية", en: "Analytics dashboard" },
  { id: "sec-score", ar: "التقييم المالي", en: "Financial score" },
  { id: "sec-forecast", ar: "التنبؤات", en: "Forecast" },
  { id: "sec-advisor", ar: "التوصيات", en: "Recommendations" },
  { id: "sec-review", ar: "مراجعة المفاهيم", en: "Concept review" },
  { id: "sec-notes", ar: "الملاحظات", en: "Notes" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

/* Pastel-tile icon set in the spirit of the reference sidebar: a rounded
   square tile per section with a small white glyph, cycling through a
   fixed pastel gradient palette (blue, purple, teal, pink, orange, red,
   violet, indigo, sky, emerald). */
const ICON_TILES: Record<SectionId, { from: string; to: string; icon: JSX.Element }> = {
  "sec-home": {
    from: "#0f766e", to: "#2dd4bf",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path
          d="M4 11.2 12 4.5l8 6.7M6.5 10v9h11v-9"
          stroke="#fff"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  "sec-exec-brief": {
    from: "#6366f1", to: "#8b5cf6",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <rect x="5" y="4" width="14" height="16" rx="2.5" stroke="#fff" strokeWidth="1.8" />
        <path d="M8.5 9h7M8.5 12.5h7M8.5 16h4" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
  "sec-statements": {
    from: "#0ea5e9", to: "#60a5fa",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M6 3.5h8.5L19 8v12.5H6z" stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M14 3.5V8h5" stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M9 17v-3.5M12 17v-6M15 17v-2" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
  "sec-kpis": {
    from: "#0ea5e9", to: "#38bdf8",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <rect x="4" y="12" width="4" height="8" rx="1.2" fill="#fff" />
        <rect x="10" y="7" width="4" height="13" rx="1.2" fill="#fff" opacity="0.85" />
        <rect x="16" y="4" width="4" height="16" rx="1.2" fill="#fff" opacity="0.7" />
      </svg>
    ),
  },
  "sec-ratios": {
    from: "#14b8a6", to: "#2dd4bf",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="7.5" stroke="#fff" strokeWidth="1.8" />
        <path d="M12 12V4.5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
        <path d="M12 12l5.5 3.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" opacity="0.85" />
      </svg>
    ),
  },
  "sec-benchmarks": {
    from: "#ef4444", to: "#f97316",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M4 20h16" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <rect x="6" y="12" width="3.4" height="8" rx="1" fill="#fff" />
        <rect x="11.3" y="7" width="3.4" height="13" rx="1" fill="#fff" opacity="0.85" />
        <path d="M4.5 6.5h6M18.5 6.5h-6" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity="0.9" />
        <path d="M12 6.5c0-1.6 1.4-2.6 3-2.6s3 1 3 2.6-1.4 2.4-3 2.4-3-.8-3-2.4z" fill="#fff" opacity="0.9" />
      </svg>
    ),
  },
  "sec-ratio-insights": {
    from: "#8b5cf6", to: "#a78bfa",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M4 19l4.5-6 3.5 3 4-7 4 4.5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20" cy="13.5" r="1.6" fill="#fff" />
      </svg>
    ),
  },
  "sec-comparison": {
    from: "#ec4899", to: "#f472b6",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M7 4v16M17 4v16" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M4.5 8.5L9.5 5M19.5 15.5l-5 3.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="12" cy="12" r="1.5" fill="#fff" />
      </svg>
    ),
  },
  "sec-trends": {
    from: "#f59e0b", to: "#fbbf24",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <rect x="5" y="13" width="3.2" height="6" rx="1" fill="#fff" />
        <rect x="10.4" y="9" width="3.2" height="10" rx="1" fill="#fff" opacity="0.85" />
        <rect x="15.8" y="5" width="3.2" height="14" rx="1" fill="#fff" opacity="0.7" />
        <path d="M4 8l5-3 4 2.5L19 4" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity="0.9" />
      </svg>
    ),
  },
  "sec-dashboard": {
    from: "#6366f1", to: "#22d3ee",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M4 15.5l5-5 3.5 3.5L19 7.5" stroke="#fff" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="19" cy="7.5" r="1.7" fill="#fff" />
        <path d="M4 20h16" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M7 17.5v-2M12 17.5v-4M17 17.5v-3" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" opacity="0.85" />
      </svg>
    ),
  },
  "sec-score": {
    from: "#ef4444", to: "#f87171",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M12 4a8 8 0 018 8" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
        <path d="M12 4a8 8 0 00-8 8" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity="0.5" />
        <path d="M12 12l4-4.5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
        <circle cx="12" cy="12" r="1.8" fill="#fff" />
      </svg>
    ),
  },
  "sec-forecast": {
    from: "#06b6d4", to: "#22d3ee",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <circle cx="9" cy="13" r="4.5" stroke="#fff" strokeWidth="1.8" />
        <path d="M13 9.5l6-3M14 14h6M14.5 17.5l4.5 2" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" opacity="0.85" />
      </svg>
    ),
  },
  "sec-advisor": {
    from: "#10b981", to: "#34d399",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M12 3l2.4 5.1 5.6.7-4.1 3.9 1 5.6-4.9-2.7-4.9 2.7 1-5.6L4 8.8l5.6-.7L12 3z" fill="#fff" />
      </svg>
    ),
  },
  "sec-review": {
    from: "#f59e0b", to: "#fbbf24",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <circle cx="11" cy="11" r="6.5" stroke="#fff" strokeWidth="1.8" />
        <path d="M15.5 15.5L20 20" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M8.5 11h5M11 8.5v5" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  "sec-notes": {
    from: "#64748b", to: "#94a3b8",
    icon: (
      <svg viewBox="0 0 24 24" fill="none">
        <rect x="5" y="4" width="14" height="16" rx="2.5" stroke="#fff" strokeWidth="1.8" />
        <path d="M8.5 9h7M8.5 12.5h7M8.5 16h4" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
};

/** Sticky in-page nav for the analysis sections: pastel icon tiles with a
 *  label under each (reference-sidebar style), highlights the section in
 *  view (IntersectionObserver) and smooth-scrolls to it on click. */
export function SectionNav({ visibleIds, lang }: {
  visibleIds: string[];
  lang: Lang;
}) {
  const [active, setActive] = useState<string | null>(null);
  const clickLock = useRef<number>(0);

  useEffect(() => {
    const ids = SECTIONS
      .map((s) => s.id)
      .filter((id) => visibleIds.includes(id));
    if (!ids.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (Date.now() < clickLock.current) return; // ignore during smooth scroll
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      // a band near the top of the viewport decides the active section
      { rootMargin: "-96px 0px -65% 0px", threshold: 0 },
    );
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [visibleIds]);

  if (visibleIds.length === 0) return null;

  const go = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    clickLock.current = Date.now() + 900; // suppress observer flicker
    setActive(id);
    el.scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" });
  };

  return (
    <nav className="section-nav" aria-label={lang === "ar" ? "أقسام التحليل" : "Analysis sections"}>
      {SECTIONS.filter((s) => visibleIds.includes(s.id)).map((s) => {
        const tile = ICON_TILES[s.id];
        const isActive = active === s.id;
        return (
          <button
            key={s.id}
            className={`sec-link ${isActive ? "active" : ""}`}
            onClick={() => go(s.id)}
            title={s[lang]}
          >
            <span
              className="sec-icon"
              style={{ background: `linear-gradient(135deg, ${tile.from}, ${tile.to})` }}
            >
              {tile.icon}
            </span>
            <span className="sec-label">{s[lang]}</span>
          </button>
        );
      })}
    </nav>
  );
}
