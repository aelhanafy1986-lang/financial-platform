import { useContext, useEffect, useState } from "react";
import { AuthContext } from "./App";
import type { Lang } from "./types";

/** «نماذج التقارير حسب الباقة» — a full-page catalogue screen (rendered
 *  inside the dashboard main pane, like records/upload/compare — not a
 *  modal) that shows what a generated report includes at each subscription
 *  tier: the financial indicators, the chart cards and the strategic
 *  recommendations a user gets when a plan is activated. Two viewing modes:
 *  a single-plan deep view, and a side-by-side comparison of two picked
 *  plans (columns per plan, rows per feature, differences highlighted and
 *  summarised as a diff strip). The ladder mirrors the backend plan quotas
 *  (free 1 one-time, pro 5/mo, business 20/mo, legacy monthly/yearly,
 *  firm/admin unlimited). Features of the user's CURRENT plan carry live
 *  ✓ marks, backed by the real quota (uploads_used) fetched from
 *  /api/auth/me — a plan that has run dry shows a depletion warning with
 *  an upgrade CTA instead of pretending everything is available. */

type PlanId = "free" | "pro" | "business" | "firm";
type SectionKey = "indicators" | "charts" | "recs";

interface PlanSpec {
  id: PlanId;
  ar: string;
  en: string;
  chip: string;
  accent: string;
  indicators: { ar: string; en: string; value: string }[];
  charts: { ar: string; en: string; sub: { ar: string; en: string } }[];
  recs: { ar: string; en: string }[];
  extras: { ar: string; en: string }[];
}

const T = {
  banner: {
    ar: "قارِن نافذة التقارير قبل الترقية: عدد المؤشرات المالية، وأنواع الرسوم البيانية المنتجة، وعمق التوصيات الاستراتيجية — كل باقة ترفع سقف ما يولّده التقرير.",
    en: "Compare the report window before upgrading: how many financial indicators, which chart types are generated, and how deep the strategic recommendations go — each plan raises the ceiling of what the report produces.",
  },
  title: { ar: "ما يتضمنه التقرير في هذه الباقة", en: "What the report includes in this plan" },
  activeChip: { ar: "الباقة الحالية", en: "Your current plan" },
  indicators: { ar: "المؤشرات المالية", en: "Financial indicators" },
  charts: { ar: "الرسوم البيانية", en: "Charts" },
  recs: { ar: "التوصيات الاستراتيجية", en: "Strategic recommendations" },
  quotaBadge: { ar: "مؤشر", en: "indicator" },
  closed: { ar: "غير مشمولة — تُفتح بالترقية", en: "Not included — unlock by upgrading" },
  quotaLeft: { ar: "متبقٍ لك", en: "left" },
  quotaInfinite: { ar: "حصة مفتوحة", en: "Unlimited quota" },
  quotaExhausted: { ar: "نفدت حصة تحليلات باقتك", en: "Your plan's analysis quota is used up" },
  upgradeCta: {
    ar: "ترقية الباقة الآن",
    en: "Upgrade now",
  },
  upgradeNote: {
    ar: "ترقية فورية — تُفتح المؤشرات والرسوم والتوصيات الإضافية مباشرة",
    en: "Instant upgrade — extra indicators, charts and recommendations unlock right away",
  },
  quotaUsed: { ar: "حصة التحليل المستهلكة", en: "Analysis quota used" },
  modeSingle: { ar: "عرض باقة", en: "Single plan" },
  modeCompare: { ar: "مقارنة باقتين", en: "Compare two plans" },
  pickPlan: { ar: "اختر الباقة", en: "Pick a plan" },
  diffTitle: { ar: "الفارق بين الباقتين", en: "Difference" },
  counts: {
    indicators: { ar: "مؤشرات", en: "indicators" },
    charts: { ar: "رسوم بيانية", en: "charts" },
    recs: { ar: "توصيات", en: "recommendations" },
  } as Record<SectionKey, { ar: string; en: string }>,
};

/** Per-plan feature ladder. The free tier shows a thin report (3 indicators,
 *  1 chart, 2 recommendations); each paid tier deepens it; the firm tier is
 *  the full catalogue. Numbers chosen to read as a clear, motivating ladder
 *  while staying consistent with the backend plan quotas' ordering. */
const PLANS: PlanSpec[] = [
  {
    id: "free",
    ar: "الباقة المجانية",
    en: "Free plan",
    chip: "المجانية",
    accent: "#64748b",
    indicators: [
      { ar: "هامش الربح الصافي", en: "Net profit margin", value: "14.2%" },
      { ar: "النسبة الجارية", en: "Current ratio", value: "1.85" },
      { ar: "العائد على حقوق الملكية (ROE)", en: "Return on equity (ROE)", value: "18.6%" },
    ],
    charts: [
      { ar: "الإيرادات السنوية", en: "Annual revenue", sub: { ar: "نمو سنوي للإيرادات", en: "Year-over-year revenue growth" } },
    ],
    recs: [
      { ar: "ركّز على تحسين خدمة العملاء خلال 30 يومًا", en: "Focus on improving customer service within 30 days" },
      { ar: "اعتمد التفاوض على عقود الموردين طويلة الأجل", en: "Adopt long-term supplier contract negotiation" },
    ],
    extras: [
      { ar: "تقرير PDF واحد قابل للتنزيل", en: "One downloadable PDF report" },
      { ar: "تحليل لمرة واحدة", en: "One-time analysis" },
    ],
  },
  {
    id: "pro",
    ar: "باقة برو",
    en: "Pro plan",
    chip: "برو",
    accent: "#0ea5e9",
    indicators: [
      { ar: "هامش الربح الإجمالي", en: "Gross profit margin", value: "42.7%" },
      { ar: "هامش الربح الصافي", en: "Net profit margin", value: "14.2%" },
      { ar: "النسبة الجارية", en: "Current ratio", value: "1.85" },
      { ar: "النسبة السريعة", en: "Quick ratio", value: "1.12" },
      { ar: "العائد على الأصول (ROA)", en: "Return on assets (ROA)", value: "9.4%" },
      { ar: "العائد على حقوق الملكية (ROE)", en: "Return on equity (ROE)", value: "18.6%" },
    ],
    charts: [
      { ar: "الإيرادات السنوية", en: "Annual revenue", sub: { ar: "نمو سنوي للإيرادات", en: "Year-over-year revenue growth" } },
      { ar: "هيكل التكاليف", en: "Cost structure", sub: { ar: "توزيع المصروفات التشغيلية", en: "Operating expense breakdown" } },
    ],
    recs: [
      { ar: "ركّز على تحسين خدمة العملاء خلال 30 يومًا", en: "Focus on improving customer service within 30 days" },
      { ar: "اعتمد التفاوض على عقود الموردين طويلة الأجل", en: "Adopt long-term supplier contract negotiation" },
      { ar: "خفّض المخزون الراكد لإطلاق سيولة قصيرة الأجل", en: "Reduce stale inventory to unlock short-term liquidity" },
      { ar: "تتبّع دورة التحويل النقدي شهريًا", en: "Track the cash conversion cycle monthly" },
    ],
    extras: [
      { ar: "5 تحليلات شهريًا · تقارير PDF قابلة للتنزيل", en: "5 analyses monthly · downloadable PDF reports" },
      { ar: "مقارنة تقارير مفتوحة", en: "Open report comparison" },
    ],
  },
  {
    id: "business",
    ar: "باقة الأعمال",
    en: "Business plan",
    chip: "الأعمال",
    accent: "#0f766e",
    indicators: [
      { ar: "هامش الربح الإجمالي", en: "Gross profit margin", value: "42.7%" },
      { ar: "هامش الربح الصافي", en: "Net profit margin", value: "14.2%" },
      { ar: "النسبة الجارية", en: "Current ratio", value: "1.85" },
      { ar: "النسبة السريعة", en: "Quick ratio", value: "1.12" },
      { ar: "دوران المخزون", en: "Inventory turnover", value: "6.2×" },
      { ar: "دوران الذمم المدينة", en: "Receivables turnover", value: "8.1×" },
      { ar: "دورة التحويل النقدي", en: "Cash conversion cycle", value: "41 يومًا" },
      { ar: "نسبة الدين إلى حقوق الملكية", en: "Debt-to-equity ratio", value: "0.64" },
      { ar: "العائد على الأصول (ROA)", en: "Return on assets (ROA)", value: "9.4%" },
      { ar: "العائد على حقوق الملكية (ROE)", en: "Return on equity (ROE)", value: "18.6%" },
    ],
    charts: [
      { ar: "الإيرادات السنوية", en: "Annual revenue", sub: { ar: "نمو سنوي للإيرادات", en: "Year-over-year revenue growth" } },
      { ar: "هيكل التكاليف", en: "Cost structure", sub: { ar: "توزيع المصروفات التشغيلية", en: "Operating expense breakdown" } },
      { ar: "التدفقات النقدية", en: "Cash flows", sub: { ar: "تشغيلية · استثمارية · تمويلية", en: "Operating · investing · financing" } },
      { ar: "السيولة عبر الزمن", en: "Liquidity over time", sub: { ar: "النسبة الجارية مقابل السريعة", en: "Current vs quick ratio" } },
    ],
    recs: [
      { ar: "ركّز على تحسين خدمة العملاء خلال 30 يومًا", en: "Focus on improving customer service within 30 days" },
      { ar: "اعتمد التفاوض على عقود الموردين طويلة الأجل", en: "Adopt long-term supplier contract negotiation" },
      { ar: "خفّض المخزون الراكد لإطلاق سيولة قصيرة الأجل", en: "Reduce stale inventory to unlock short-term liquidity" },
      { ar: "تتبّع دورة التحويل النقدي شهريًا", en: "Track the cash conversion cycle monthly" },
      { ar: "أعد توزيع القروض قصيرة الأجل إلى تمويل طويل الأجل", en: "Refinance short-term loans into long-term financing" },
      { ar: "اضبط سياسة الائتمان لتقصير فترة التحصيل", en: "Tune the credit policy to shorten collection days" },
    ],
    extras: [
      { ar: "20 تحليلًا شهريًا · تقارير PDF قابلة للتنزيل", en: "20 analyses monthly · downloadable PDF reports" },
      { ar: "مقارنة جماعية بين عدة تقارير", en: "Group comparison across several reports" },
    ],
  },
  {
    id: "firm",
    ar: "باقة المؤسسات",
    en: "Firm plan",
    chip: "المؤسسات",
    accent: "#7c3aed",
    indicators: [
      { ar: "هامش الربح الإجمالي", en: "Gross profit margin", value: "42.7%" },
      { ar: "هامش الربح الصافي", en: "Net profit margin", value: "14.2%" },
      { ar: "النسبة الجارية", en: "Current ratio", value: "1.85" },
      { ar: "النسبة السريعة", en: "Quick ratio", value: "1.12" },
      { ar: "دوران المخزون", en: "Inventory turnover", value: "6.2×" },
      { ar: "دوران الذمم المدينة", en: "Receivables turnover", value: "8.1×" },
      { ar: "دورة التحويل النقدي", en: "Cash conversion cycle", value: "41 يومًا" },
      { ar: "نسبة الدين إلى حقوق الملكية", en: "Debt-to-equity ratio", value: "0.64" },
      { ar: "نسبة تغطية الفوائد", en: "Interest coverage ratio", value: "5.3×" },
      { ar: "التدفق النقدي الحر", en: "Free cash flow", value: "2.4M" },
      { ar: "نسبة المديونية", en: "Leverage ratio", value: "0.58" },
      { ar: "جودة الأرباح", en: "Earnings quality", value: "0.87" },
      { ar: "العائد على الأصول (ROA)", en: "Return on assets (ROA)", value: "9.4%" },
      { ar: "العائد على حقوق الملكية (ROE)", en: "Return on equity (ROE)", value: "18.6%" },
    ],
    charts: [
      { ar: "الإيرادات السنوية", en: "Annual revenue", sub: { ar: "نمو سنوي للإيرادات", en: "Year-over-year revenue growth" } },
      { ar: "هيكل التكاليف", en: "Cost structure", sub: { ar: "توزيع المصروفات التشغيلية", en: "Operating expense breakdown" } },
      { ar: "التدفقات النقدية", en: "Cash flows", sub: { ar: "تشغيلية · استثمارية · تمويلية", en: "Operating · investing · financing" } },
      { ar: "السيولة عبر الزمن", en: "Liquidity over time", sub: { ar: "النسبة الجارية مقابل السريعة", en: "Current vs quick ratio" } },
      { ar: "مصفوفة الربحية", en: "Profitability matrix", sub: { ar: "الربحية مقابل النمو", en: "Profitability vs growth" } },
      { ar: "مؤشرات الاتجاه", en: "Trend indicators", sub: { ar: "مسار كل مؤشر عبر السنوات", en: "Each indicator's multi-year path" } },
    ],
    recs: [
      { ar: "ركّز على تحسين خدمة العملاء خلال 30 يومًا", en: "Focus on improving customer service within 30 days" },
      { ar: "اعتمد التفاوض على عقود الموردين طويلة الأجل", en: "Adopt long-term supplier contract negotiation" },
      { ar: "خفّض المخزون الراكد لإطلاق سيولة قصيرة الأجل", en: "Reduce stale inventory to unlock short-term liquidity" },
      { ar: "تتبّع دورة التحويل النقدي شهريًا", en: "Track the cash conversion cycle monthly" },
      { ar: "أعد توزيع القروض قصيرة الأجل إلى تمويل طويل الأجل", en: "Refinance short-term loans into long-term financing" },
      { ar: "اضبط سياسة الائتمان لتقصير فترة التحصيل", en: "Tune the credit policy to shorten collection days" },
      { ar: "وسّع خطوط الإنتاج ذات الهامش الأعلى أولًا", en: "Expand the highest-margin product lines first" },
      { ar: "ابنِ لوحة متابعة ربع سنوية لمجلس الإدارة", en: "Build a quarterly board-level tracking dashboard" },
    ],
    extras: [
      { ar: "تحليلات غير محدودة · أولوية في المعالجة", en: "Unlimited analyses · processing priority" },
      { ar: "تصدير بصيغ متعددة · دعم مخصص", en: "Multi-format export · dedicated support" },
    ],
  },
];

/** The user's current tier, derived the same way as HomeOverview.planQuota:
 *  admin wins, then paid plan, then free. Unknown paid plans fall back to
 *  pro — same fallback direction as the quota ladder. */
function currentPlan(user: { is_admin?: boolean; subscription: string; plan?: string | null } | null): PlanId {
  if (!user) return "free";
  if (user.is_admin) return "firm";
  if (user.subscription === "paid") {
    const p = user.plan ?? "";
    if (p === "business" || p === "monthly" || p === "yearly") return "business";
    if (p === "firm") return "firm";
    return "pro";
  }
  return "free";
}

const byId = (id: PlanId): PlanSpec => PLANS.find((p) => p.id === id) ?? PLANS[0];

/** Next tier up the ladder, or null when already at the top. */
function nextTier(id: PlanId): PlanId | null {
  const i = PLANS.findIndex((p) => p.id === id);
  return i >= 0 && i < PLANS.length - 1 ? PLANS[i + 1].id : null;
}

/** Feature list of a plan for a section (kept generic so the comparison
 *  table can union the same list across plans). */
function sectionList(p: PlanSpec, sec: SectionKey): { ar: string; en: string }[] {
  if (sec === "indicators") return p.indicators;
  if (sec === "charts") return p.charts;
  return p.recs;
}

/** Quota ladder — mirrors the backend (app/main.py upload quota):
 *  free 1 one-time · pro 5/mo · business 20/mo · legacy monthly 15,
 *  yearly 20, firm unlimited · platform admin unlimited. Same numbers as
 *  HomeOverview.planQuota so both surfaces agree. */
function planQuota(user: { is_admin?: boolean; subscription: string; plan?: string | null } | null): {
  quota: number | null;
} {
  const ladder: Record<string, number | null> = {
    pro: 5,
    business: 20,
    monthly: 15,
    yearly: 20,
    firm: null,
  };
  if (user?.is_admin) return { quota: null };
  if (user?.subscription === "paid") {
    return { quota: ladder[user.plan ?? ""] ?? 20 };
  }
  return { quota: 1 };
}

/** Feature mark: ✓ when the plan owns this feature, 🔒 when locked. When
 *  shown for the CURRENT plan the ✓ is live-backed (green, «مفعّلة») and the
 *  locked cells dim — driven by real quota data, not just plan membership. */
function FeatureMark({ owned, isCur, sr: _sr }: { owned: boolean; isCur?: boolean; sr?: string }) {
  return owned ? (
    <span className={`rt-mark${isCur ? " cur" : ""}`}>
      <svg viewBox="0 0 24 24" width={13} height={13} fill="none" aria-hidden="true">
        <path d="M5 12.5l4 4L19 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  ) : (
    <span className="rt-kpi-lock rt-mark-lock">
      <LockGlyph size={12} />
    </span>
  );
}

/** Local glyphs — Glyph.tsx has no lock/chart variants and this screen is
 *  the only consumer, so they live here instead of the shared set. */
function LockGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden="true">
      <rect x="5" y="10.5" width="14" height="9.5" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 10.5V8a4 4 0 1 1 8 0v2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function ChartGlyph({ size = 14 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden="true">
      <path d="M4 20h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M7 20v-6M12 20V9M17 20v-9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function Count({ n, label, lang }: { n: number | null; label: string; lang: Lang }) {
  return (
    <span className={`rt-count${n == null ? " full" : ""}`}>
      <span className="rt-count-dot" />
      {n == null
        ? lang === "ar"
          ? "مؤشرات كاملة"
          : "Full indicators"
        : `${T.quotaBadge[lang]}: ${n}`}
    </span>
  );
}

/** One value cell of a comparison row: the feature when included, or a
 *  locked placeholder when the plan lacks it. */
function CmpCell({
  has,
  sec,
  accent,
  lang,
  isCur = false,
}: {
  has: { ar: string; en: string } | undefined;
  sec: SectionKey;
  accent: string;
  lang: Lang;
  isCur?: boolean;
}) {
  if (!has)
    return (
      <div className={`rt-cmp-cell rt-cmp-lacks${isCur ? " rt-lacks-cur" : ""}`}>
        <span className="rt-kpi-lock">
          <LockGlyph size={12} />
        </span>
        <small>{T.closed[lang]}</small>
      </div>
    );
  if (sec === "indicators") {
    const ind = has as { ar: string; en: string; value?: string };
    return (
      <div className="rt-cmp-cell rt-cmp-win">
        <FeatureMark owned isCur={isCur} />
        <span className="rt-cmp-feat">{lang === "ar" ? ind.ar : ind.en}</span>
        {"value" in ind && <span className="rt-kpi-val">{ind.value}</span>}
      </div>
    );
  }
  if (sec === "charts") {
    const c = has as { ar: string; en: string; sub?: { ar: string; en: string } };
    return (
      <div className="rt-cmp-cell rt-cmp-win">
        <span className="rt-chart-icon" style={{ background: `${accent}1a`, color: accent }}>
          <ChartGlyph size={13} />
        </span>
        <span className="rt-cmp-chart-txt">
          <strong>{lang === "ar" ? c.ar : c.en}</strong>
          {c.sub && <small>{lang === "ar" ? c.sub.ar : c.sub.en}</small>}
        </span>
        <FeatureMark owned isCur={isCur} />
      </div>
    );
  }
  return (
    <div className="rt-cmp-cell rt-cmp-win">
      <FeatureMark owned isCur={isCur} />
      <span className="rt-cmp-feat">{lang === "ar" ? has.ar : has.en}</span>
    </div>
  );
}

/** Plan column header: chip + current badge + picker + per-section counts. */
function CmpHead({
  plan,
  other,
  onPick,
  lang,
  isCurrent,
}: {
  plan: PlanSpec;
  other: PlanSpec;
  onPick: (id: PlanId) => void;
  lang: Lang;
  isCurrent: boolean;
}) {
  return (
    <div className="rt-cmp-cell rt-cmp-planhead">
      <div className="rt-cmp-planrow">
        <span className="rt-chip" style={{ background: plan.accent }}>
          {lang === "ar" ? plan.chip : plan.en}
        </span>
        {isCurrent && <span className="badge ok">{T.activeChip[lang]}</span>}
      </div>
      <select
        className="rt-cmp-select"
        value={plan.id}
        onChange={(e) => onPick(e.target.value as PlanId)}
        aria-label={T.pickPlan[lang]}
      >
        {PLANS.map((p) => (
          <option key={p.id} value={p.id} disabled={p.id === other.id}>
            {lang === "ar" ? p.ar : p.en}
          </option>
        ))}
      </select>
      <div className="rt-cmp-planstats">
        {(Object.keys(T.counts) as SectionKey[]).map((sec) => (
          <span key={sec}>
            {T.counts[sec][lang]}: <b>{sectionList(plan, sec).length}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function ReportTemplates({
  lang,
  onUpgrade,
}: {
  lang: Lang;
  onUpgrade?: () => void;
}) {
  const { user, token, openPaywall } = useContext(AuthContext);
  // dedicated prop wins (testable/standalone use); default to the central
  // paywall modal so the CTA works with zero wiring at every call site
  const upgrade = onUpgrade ?? openPaywall;
  const cur = currentPlan(user);
  // live quota: the real uploads_used / laddered quota from the backend
  // (/api/auth/me). 401/unauthenticated degrades gracefully to the
  // context user (same fields, refreshed value wins).
  const [q, setQ] = useState({
    used: user?.uploads_used ?? 0,
    quota: planQuota({ is_admin: user?.is_admin, subscription: user?.subscription ?? "free", plan: user?.plan }).quota,
  });
  useEffect(() => {
    let dead = false;
    (async () => {
      if (!token) return;
      try {
        const res = await fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
        if (!res.ok) return;
        const me = await res.json();
        if (dead) return;
        setQ({
          used: me.uploads_used ?? 0,
          quota: planQuota({ is_admin: me.is_admin, subscription: me.subscription ?? "free", plan: me.plan }).quota,
        });
      } catch {
        /* offline / auth hiccup: context values stay in place */
      }
    })();
    return () => { dead = true; };
    // [token, user]: after a successful (simulated) payment App.tsx refreshes
    // the context user, so this effect re-runs and the quota/badges/ladder
    // reflect the NEW plan immediately — no manual reload needed.
  }, [token, user]);
  const quotaInfo = q;
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [tab, setTab] = useState<PlanId>(cur);
  // comparison pair defaults to «current → next tier» (admin sits at the
  // top, so the widest free↔firm pair shows the full span instead)
  const [cmpA, setCmpA] = useState<PlanId>(cur === "firm" ? "free" : cur);
  const [cmpB, setCmpB] = useState<PlanId>(cur === "firm" ? "firm" : nextTier(cur) ?? "firm");

  const plan = byId(tab);
  const isCurrent = plan.id === cur;
  const planA = byId(cmpA);
  const planB = byId(cmpB);
  const secs: SectionKey[] = ["indicators", "charts", "recs"];

  return (
    <div className="report-templates" dir={lang === "ar" ? "rtl" : "ltr"}>
      <div className="rt-head">
        <div>
          <div className="rt-head-row">
            <h2>{lang === "ar" ? "نماذج التقارير حسب الباقة" : "Report templates by plan"}</h2>
            {/* current-plan badge, styled like the ADMIN pill but tinted
                with the plan's accent colour */}
            <span
              className="badge plan"
              style={{ background: byId(cur).accent }}
              title={T.activeChip[lang]}
            >
              {lang === "ar" ? byId(cur).chip : byId(cur).en}
            </span>
          </div>
          <p>{lang === "ar" ? "استعرض عمق التقرير المولَّد عند تفعيل كل باقة" : "See how deep the generated report goes on each plan"}</p>
        </div>
        <div className="rt-mode" role="tablist" aria-label={lang === "ar" ? "طريقة العرض" : "View mode"}>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "single"}
            className={`rt-mode-btn${mode === "single" ? " active" : ""}`}
            onClick={() => setMode("single")}
          >
            {T.modeSingle[lang]}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "compare"}
            className={`rt-mode-btn${mode === "compare" ? " active" : ""}`}
            onClick={() => setMode("compare")}
          >
            {T.modeCompare[lang]}
          </button>
        </div>
      </div>
      <p className="rt-banner">{T.banner[lang]}</p>

      {/* live quota strip: real numbers from the backend, not plan specs */}
      <div className={`rt-quota${quotaInfo.quota !== null && quotaInfo.used >= quotaInfo.quota ? " dry" : ""}`}>
        <span className="rt-quota-label">{T.quotaUsed[lang]}:</span>
        {quotaInfo.quota === null ? (
          <span className="rt-quota-inf">∞ {T.quotaInfinite[lang]}</span>
        ) : quotaInfo.used >= quotaInfo.quota ? (
          <span className="rt-quota-nums">
            <b>{quotaInfo.used}</b> / {quotaInfo.quota} ·<span className="rt-quota-dry-txt">{T.quotaExhausted[lang]}</span>
          </span>
        ) : (
          <span className="rt-quota-nums">
            <b>{quotaInfo.used}</b> / {quotaInfo.quota} ·{" "}
            {T.quotaLeft[lang]} <b>{Math.max(0, quotaInfo.quota - quotaInfo.used)}</b>
          </span>
        )}
        <span className="rt-quota-plan">({lang === "ar" ? byId(cur).chip : byId(cur).en})</span>
        {quotaInfo.quota !== null && quotaInfo.used >= quotaInfo.quota && (
          <button type="button" className="btn small save rt-quota-up" onClick={() => upgrade()}>
            {T.upgradeCta[lang]}
          </button>
        )}
      </div>

      <div className="rt-tabs" role="tablist" aria-label={lang === "ar" ? "الباقة" : "Plan"}>
        {PLANS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            aria-selected={tab === p.id}
            className={`rt-tab${tab === p.id ? " active" : ""}`}
            onClick={() => setTab(p.id)}
          >
            {lang === "ar" ? p.ar : p.en}
            {p.id === cur && <span className="rt-tab-dot" title={T.activeChip[lang]} />}
          </button>
        ))}
      </div>

      {mode === "compare" ? (
        (() => {
          // diff summary: per section, which plan is richer and by how much
          const diffs = secs
            .map((sec) => ({
              sec,
              d: sectionList(planB, sec).length - sectionList(planA, sec).length,
            }))
            .filter((x) => x.d !== 0);
          return (
            <section className="rt-cmp-wrap">
              {diffs.length > 0 && (
                <div className="rt-cmp-diff">
                  <span className="rt-cmp-diff-title">{T.diffTitle[lang]}:</span>
                  {diffs.map(({ sec, d }) => {
                    const richer = d > 0 ? planB : planA;
                    return (
                      <span className="rt-cmp-pill" key={sec}>
                        <b style={{ color: richer.accent }}>{lang === "ar" ? richer.chip : richer.en}</b>
                        {` +${Math.abs(d)} ${T.counts[sec][lang]}`}
                      </span>
                    );
                  })}
                </div>
              )}
              <div className="rt-cmp-scroll">
                <div className="rt-cmp">
                  <div className="rt-cmp-head">
                    <div className="rt-cmp-cell rt-cmp-labelcell" />
                    <CmpHead
                      plan={planA}
                      other={planB}
                      onPick={setCmpA}
                      lang={lang}
                      isCurrent={planA.id === cur}
                    />
                    <CmpHead
                      plan={planB}
                      other={planA}
                      onPick={setCmpB}
                      lang={lang}
                      isCurrent={planB.id === cur}
                    />
                  </div>
                  {secs.map((sec) => {
                    // union of features in canonical (firm) order — every
                    // plan's list is a subset of the firm catalogue
                    const union = sectionList(PLANS[3], sec);
                    return (
                      <div className="rt-cmp-sec" key={sec}>
                        <div className="rt-cmp-sec-title">
                          {T[sec][lang]}{" "}
                          <span className="rt-sec-n">
                            ({sectionList(planA, sec).length} ↔ {sectionList(planB, sec).length})
                          </span>
                        </div>
                        {union.map((f) => {
                          const hasA = sectionList(planA, sec).find((x) => x.ar === f.ar);
                          const hasB = sectionList(planB, sec).find((x) => x.ar === f.ar);
                          const diff = !!hasA !== !!hasB;
                          return (
                            <div className={`rt-cmp-row${diff ? " diff" : ""}`} key={f.ar}>
                              <div className="rt-cmp-cell rt-cmp-name">
                                {lang === "ar" ? f.ar : f.en}
                              </div>
                              <CmpCell has={hasA} sec={sec} accent={planA.accent} lang={lang} isCur={planA.id === cur} />
                              <CmpCell has={hasB} sec={sec} accent={planB.accent} lang={lang} isCur={planB.id === cur} />
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          );
        })()
      ) : (
        <section className="rt-card">
          <div className="rt-card-head">
            <div className="rt-card-title">
              <span className="rt-chip" style={{ background: plan.accent }}>
                {lang === "ar" ? plan.chip : plan.en}
              </span>
              <h3>{T.title[lang]}</h3>
              {isCurrent && <span className="badge ok">{T.activeChip[lang]}</span>}
              <Count n={plan.id === "free" ? 3 : plan.id === "pro" ? 6 : plan.id === "business" ? 10 : null} label="" lang={lang} />
            </div>
            <ul className="rt-feats">
              {plan.extras.map((f) => (
                <li key={f.ar}>{lang === "ar" ? f.ar : f.en}</li>
              ))}
            </ul>
          </div>

          <div className="rt-sec">
            <h4>
              {T.indicators[lang]}{" "}
              <span className="rt-sec-n">({plan.indicators.length})</span>
            </h4>
            <div className="rt-grid">
              {PLANS[3].indicators.map((f) => {
                const owned = plan.indicators.some((p) => p.ar === f.ar);
                return (
                  <div className={`rt-kpi${owned ? "" : " locked"}`} key={f.ar}>
                    <FeatureMark owned={owned} isCur={owned && isCurrent} />
                    <span className="rt-kpi-name">{lang === "ar" ? f.ar : f.en}</span>
                    {owned && <span className="rt-kpi-val">{f.value}</span>}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rt-sec">
            <h4>
              {T.charts[lang]} <span className="rt-sec-n">({plan.charts.length})</span>
            </h4>
            <div className="rt-grid">
              {PLANS[3].charts.map((f) => {
                const owned = plan.charts.some((p) => p.ar === f.ar);
                return owned ? (
                  <div className="rt-chart" key={f.ar}>
                    <span className="rt-chart-icon" style={{ background: `${plan.accent}1a`, color: plan.accent }}>
                      <ChartGlyph size={14} />
                    </span>
                    <span>
                      <strong>{lang === "ar" ? f.ar : f.en}</strong>
                      <small>{lang === "ar" ? f.sub.ar : f.sub.en}</small>
                    </span>
                    <FeatureMark owned isCur={isCurrent} />
                  </div>
                ) : (
                  <div className="rt-chart locked" key={f.ar}>
                    <span className="rt-chart-icon">
                      <LockGlyph size={13} />
                    </span>
                    <span>
                      <strong>{lang === "ar" ? f.ar : f.en}</strong>
                      <small>{T.closed[lang]}</small>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rt-sec">
            <h4>
              {T.recs[lang]} <span className="rt-sec-n">({plan.recs.length})</span>
            </h4>
            <ul className="rt-recs">
              {PLANS[3].recs.map((r) => {
                const owned = plan.recs.some((p) => p.ar === r.ar);
                return (
                  <li className={owned ? "" : "locked"} key={r.ar}>
                    {owned && <FeatureMark owned isCur={isCurrent} />}
                    <span className="rt-cmp-feat">{lang === "ar" ? r.ar : r.en}</span>
                    {!owned && (
                      <span className="rt-kpi-lock">
                        <LockGlyph size={12} />
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
            {plan.id !== "firm" && (
              <div className="rt-locked-row">
                <button type="button" className="btn small save rt-upgrade-btn" onClick={() => upgrade()}>
                  {T.upgradeCta[lang]}
                </button>
                <p className="rt-hint">{T.upgradeNote[lang]}</p>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
