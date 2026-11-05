import { useEffect, useState } from "react";
import type { PublicStats } from "./types";

/** Crown mark used by the reference subscription cards (same as the
 *  dashboard's «اشتراكك» card) — inline so Landing stays dependency-free. */
function Crown({ size = 15 }: { size?: number }) {
  return (
    <span className="ho-crown" aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size} height={size} fill="none">
        <path
          d="M3.5 8.5 8 12l4-6 4 6 4.5-3.5L19 18H5L3.5 8.5z"
          stroke="#d9a441"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

/** Bolt mark for the upgrade-style CTA (reference design). */
function Bolt({ size = 15 }: { size?: number }) {
  return (
    <span className="hp-bolt" aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size} height={size} fill="none">
        <path
          d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z"
          stroke="#fff"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

const T = {
  // ---- top nav sections (cmrrs.net-style marketing bar) --------------------
  navHome: { ar: "الرئيسية", en: "Home" },
  navAbout: { ar: "من نحن", en: "About" },
  navPricing: { ar: "الأسعار", en: "Pricing" },
  navDashboard: { ar: "لوحة التحكم", en: "Dashboard" },
  // ---- hero ----------------------------------------------------------------
  heroTitle: {
    ar: "المنصة المالية الذكية",
    en: "Smart Financial Platform",
  },
  heroTagline: {
    ar: "محلّلك المالي المدعوم بالذكاء الاصطناعي",
    en: "Your Smart AI Financial Analyst",
  },
  heroSub: {
    ar: "ارفع ملفاتك المالية واحصل على تحليل فوري، قوائم مالية كاملة، توصيات وتنبؤات — كل ذلك بضغطة واحدة",
    en: "Upload your financial files and get instant analysis, full statements, recommendations and forecasts — in one click",
  },
  cta: { ar: "ابدأ الآن — إنشاء حساب", en: "Get started — sign up" },
  loginCta: { ar: "تسجيل الدخول", en: "Log in" },
  scrollHint: { ar: "↓ تصفّح الأقسام", en: "↓ Browse sections" },
  // ---- من نحن ---------------------------------------------------------------
  aboutKicker: { ar: "من نحن", en: "About us" },
  aboutTitle: {
    ar: "منصة تحليل مالي تعمل بالكامل محليًا",
    en: "A financial analytics platform that runs fully locally",
  },
  aboutBody: {
    ar: "نحوّل ميزان المراجعة وقوائمك المالية إلى قرارات: مؤشرات ونسب مالية فورية، قوائم كاملة، تقارير PDF وPowerPoint ثنائية اللغة، وتنبؤات مستقبلية — دون أن يغادر أي ملف أجهزتك.",
    en: "We turn your trial balance and statements into decisions: instant KPIs and ratios, full statements, bilingual PDF/PowerPoint reports, and forward forecasts — no file ever leaves your machine.",
  },
  aboutPoints: [
    {
      icon: "🔒",
      ar: "خصوصية كاملة — المعالجة على جهازك",
      en: "Full privacy — processed on your machine",
    },
    {
      icon: "🧮",
      ar: "منهجية مالية موثّقة وقابلة للتدقيق",
      en: "Documented, auditable financial methodology",
    },
    {
      icon: "🌍",
      ar: "عربية/إنجليزية في كل تقرير وشريحة",
      en: "Arabic/English in every report and slide",
    },
  ],
  // ---- الأسعار ---------------------------------------------------------------
  pricingKicker: { ar: "الأسعار", en: "Pricing" },
  pricingTitle: {
    ar: "ابدأ مجانًا وطوّر باقتك عند الحاجة",
    en: "Start free, upgrade when you need it",
  },
  planFree: { ar: "المجانية", en: "Free" },
  planFreePrice: { ar: "0 ر.س / شهر", en: "SAR 0 / mo" },
  planFreePoint1: {
    ar: "تحليل واحد (لمرة واحدة)",
    en: "One analysis (one-time)",
  },
  planFreePoint2: {
    ar: "قوائم مالية ونسب ومؤشرات كاملة",
    en: "Full statements, ratios and KPIs",
  },
  planFreePoint3: {
    ar: "تقارير PDF وExcel وPowerPoint",
    en: "PDF, Excel and PowerPoint reports",
  },
  planFreeBtn: { ar: "ابدأ مجانًا", en: "Start free" },
  planFreeFiles: { ar: "ملف واحد", en: "1 file" },
  planFreeStatus: { ar: "مجانًا", en: "Free" },
  planPro: { ar: "برو", en: "Pro" },
  planProPrice: { ar: "50$ / شهريًا", en: "$50 / month" },
  planProBadge: { ar: "الأكثر طلبًا", en: "Most popular" },
  planProPoint1: {
    ar: "5 تحليلات شهريًا",
    en: "5 analyses / month",
  },
  planProPoint2: {
    ar: "كل مزايا المجانية + تنبؤات وسيناريوهات موسّعة",
    en: "Everything in Free + extended forecasts & scenarios",
  },
  planProPoint3: {
    ar: "تصدير PDF وExcel وPowerPoint بلا قيود",
    en: "Unlimited PDF, Excel and PowerPoint exports",
  },
  planProBtn: { ar: "اشترك الآن", en: "Subscribe now" },
  planProFiles: { ar: "5 ملفات", en: "5 files" },
  planProStatus: { ar: "الأكثر طلبًا", en: "Most popular" },
  planBusiness: { ar: "الأعمال", en: "Business" },
  planBusinessPrice: { ar: "100$ / شهريًا", en: "$100 / month" },
  planBusinessPoint1: {
    ar: "20 تحليلاً شهريًا",
    en: "20 analyses / month",
  },
  planBusinessPoint2: {
    ar: "كل مزايا برو",
    en: "Everything in Pro",
  },
  planBusinessPoint3: {
    ar: "أولوية قصوى في المعالجة والدعم — للفرق والمكاتب",
    en: "Top processing & support priority — for teams and firms",
  },
  planBusinessBtn: { ar: "اشترك الآن", en: "Subscribe now" },
  planBusinessFiles: { ar: "20 ملفًا", en: "20 files" },
  planBusinessStatus: { ar: "للفرق", en: "For teams" },
  planNote: {
    ar: "الدفع والتدقيق يتمون داخل المنصة بعد إنشاء الحساب.",
    en: "Payment and verification happen inside the platform after sign-up.",
  },
  // ---- لوحة التحكم ------------------------------------------------------------
  dashKicker: { ar: "لوحة التحكم", en: "Dashboard" },
  dashTitle: {
    ar: "كل تحليلاتك في مكان واحد",
    en: "All your analyses in one place",
  },
  dashBody: {
    ar: "بعد تسجيل الدخول تدير تحليلاتك المحفوظة: إعادة تحليل، مقارنة سنوية، لوحة مؤشرات تحليلية، تصدير PDF/Excel/PowerPoint — بواجهة عربية/إنجليزية وثيمات قابلة للتخصيص.",
    en: "After signing in you manage your saved analyses: re-analysis, yearly comparison, the analytics dashboard, PDF/Excel/PowerPoint export — bilingual and themeable.",
  },
  dashPoint1: {
    ar: "رفع ملف واحد أو عدة ملفات (Excel/Word/PDF)",
    en: "One or many files (Excel/Word/PDF)",
  },
  dashPoint2: {
    ar: "تحليل فوري وحفظ تلقائي لكل عملية",
    en: "Instant analysis, every run saved",
  },
  dashPoint3: {
    ar: "تصدير احترافي جاهز للعرض على الإدارة",
    en: "Board-ready professional exports",
  },
  dashCta: { ar: "الدخول إلى لوحة التحكم", en: "Open the dashboard" },
  // ---- stats ------------------------------------------------------------------
  statsTitle: { ar: "إحصاءات المنصة المباشرة", en: "Live platform statistics" },
  statAnalyses: { ar: "عملية تحليل مالي", en: "Financial analyses" },
  statStatements: { ar: "قوائم مالية أُنشئت", en: "Statements built" },
  statVisits: { ar: "زيارة للموقع", en: "Site visits" },
  recent: { ar: "آخر التحليلات", en: "Latest analyses" },
  empty: { ar: "لا توجد تحليلات بعد", en: "No analyses yet" },
  features: [
    {
      icon: "📊",
      ar: "تحليل فوري",
      en: "Instant analysis",
      d_ar: "مؤشرات ونسب مالية دقيقة من أي ملف Excel أو Word أو PDF",
      d_en: "Accurate KPIs and ratios from any Excel, Word or PDF file",
    },
    {
      icon: "📘",
      ar: "قوائم مالية كاملة",
      en: "Full statements",
      d_ar: "قائمة الدخل، المركز المالي، التدفقات النقدية وحقوق الملكية من ميزان المراجعة",
      d_en: "Income, position, cash flows and equity statements from a trial balance",
    },
    {
      icon: "💡",
      ar: "توصيات ذكية",
      en: "Smart advice",
      d_ar: "تنبيهات على المخاطر المالية وحلول عملية مقترحة",
      d_en: "Financial risk alerts with practical solutions",
    },
    {
      icon: "🔮",
      ar: "تنبؤات مستقبلية",
      en: "Forecasts",
      d_ar: "توقعات الاتجاهات للفترات القادمة بالانحدار الخطي",
      d_en: "Linear-regression projections for upcoming periods",
    },
  ],
};

function fmt(n: number | undefined): string {
  return new Intl.NumberFormat("en-US").format(n || 0);
}

export default function Landing({
  lang,
  onSignup,
  onLogin,
  onDashboard,
}: {
  lang: "ar" | "en";
  onSignup: () => void;
  onLogin: () => void;
  onDashboard: () => void;
}) {
  const [stats, setStats] = useState<PublicStats | null>(null);

  useEffect(() => {
    fetch("/api/public/stats")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setStats)
      .catch(() => {});
  }, []);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="landing">
      {/* ---- marketing top nav — cmrrs.net-style section links ------------ */}
      <nav className="landing-nav">
        <button className="lnk-logo" onClick={() => scrollTo("home")}>
          <img src="/logo.svg" alt="" />
          <span>.fin</span>
        </button>
        <div className="lnk-links">
          <button onClick={() => scrollTo("home")}>{T.navHome[lang]}</button>
          <button onClick={() => scrollTo("about")}>{T.navAbout[lang]}</button>
          <button onClick={() => scrollTo("pricing")}>{T.navPricing[lang]}</button>
          <button className="lnk-cta" onClick={onDashboard}>
            {T.navDashboard[lang]}
          </button>
        </div>
      </nav>

      {/* ---- hero over the user-supplied photo ----------------------------- */}
      <section className="hero" id="home">
        <div className="hero-bg" aria-hidden="true">
          <img src="/hero-bg.png" alt="" />
          <div className="hero-overlay" />
        </div>
        <div className="hero-content">
          <img src="/logo.svg" alt="" className="hero-logo" />
          <h1>{T.heroTitle[lang]}</h1>
          <p className="hero-tagline">{T.heroTagline[lang]}</p>
          <p>{T.heroSub[lang]}</p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={onSignup}>
              {T.cta[lang]}
            </button>
            <button className="btn-ghost" onClick={onLogin}>
              {T.loginCta[lang]}
            </button>
          </div>
          <button className="hero-scroll" onClick={() => scrollTo("about")}>
            {T.scrollHint[lang]}
          </button>
        </div>
      </section>

      {/* ---- من نحن --------------------------------------------------------- */}
      <section className="landing-section" id="about">
        <p className="section-kicker">{T.aboutKicker[lang]}</p>
        <h2 className="section-title">{T.aboutTitle[lang]}</h2>
        <p className="section-body">{T.aboutBody[lang]}</p>
        <div className="section-points">
          {T.aboutPoints.map((p, i) => (
            <div className="point-card" key={i}>
              <span className="point-icon">{p.icon}</span>
              <span>{(lang === "ar" ? p.ar : p.en) as string}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="features">
        {T.features.map((f, i) => (
          <div className="feature-card" key={i}>
            <span className="feature-icon">{f.icon}</span>
            <h3>{f[lang] as string}</h3>
            <p>{(lang === "ar" ? f.d_ar : f.d_en) as string}</p>
          </div>
        ))}
      </section>

      {/* ---- الأسعار --------------------------------------------------------- */}
      <section className="landing-section" id="pricing">
        <p className="section-kicker">{T.pricingKicker[lang]}</p>
        <h2 className="section-title">{T.pricingTitle[lang]}</h2>
        <div className="pricing-grid">
          {/* reference-style subscription cards — same design language as the
              dashboard's «اشتراكك» card: navy top bar, crown title + plan
              chip, status/files rows, backdrop bar and a wide navy CTA. */}
          <div className="price-card ref-card">
            <div className="hp-head">
              <h3 className="hp-title">
                <Crown />
                {T.planFree[lang]}
              </h3>
              <span className="hp-chip">{T.planFreeStatus[lang]}</span>
            </div>
            <p className="price-num">{T.planFreePrice[lang]}</p>
            <div className="hp-row">
              <span>{lang === "ar" ? "الملفات" : "Files"}</span>
              <strong className="hp-val">{T.planFreeFiles[lang]}</strong>
            </div>
            <div className="ho-plan-bar">
              <span className="ho-plan-fill" style={{ width: "20%" }} />
            </div>
            <ul>
              <li>{T.planFreePoint1[lang]}</li>
              <li>{T.planFreePoint2[lang]}</li>
              <li>{T.planFreePoint3[lang]}</li>
            </ul>
            <button className="price-cta free" onClick={onSignup}>
              <span>{T.planFreeBtn[lang]}</span>
              <span className="hp-arr" aria-hidden="true">↗</span>
            </button>
          </div>
          <div className="price-card ref-card featured">
            <div className="hp-head">
              <h3 className="hp-title">
                <Crown />
                {T.planPro[lang]}
              </h3>
              <span className="hp-chip">{T.planProStatus[lang]}</span>
            </div>
            <p className="price-num">{T.planProPrice[lang]}</p>
            <div className="hp-row">
              <span>{lang === "ar" ? "الملفات" : "Files"}</span>
              <strong className="hp-val">{T.planProFiles[lang]}</strong>
            </div>
            <div className="ho-plan-bar">
              <span className="ho-plan-fill" style={{ width: "55%" }} />
            </div>
            <ul>
              <li>{T.planProPoint1[lang]}</li>
              <li>{T.planProPoint2[lang]}</li>
              <li>{T.planProPoint3[lang]}</li>
            </ul>
            <button className="price-cta navy" onClick={onSignup}>
              <Bolt />
              <span>{T.planProBtn[lang]}</span>
              <span className="hp-arr" aria-hidden="true">↗</span>
            </button>
          </div>
          <div className="price-card ref-card">
            <div className="hp-head">
              <h3 className="hp-title">
                <Crown />
                {T.planBusiness[lang]}
              </h3>
              <span className="hp-chip">{T.planBusinessStatus[lang]}</span>
            </div>
            <p className="price-num">{T.planBusinessPrice[lang]}</p>
            <div className="hp-row">
              <span>{lang === "ar" ? "الملفات" : "Files"}</span>
              <strong className="hp-val">{T.planBusinessFiles[lang]}</strong>
            </div>
            <div className="ho-plan-bar">
              <span className="ho-plan-fill" style={{ width: "85%" }} />
            </div>
            <ul>
              <li>{T.planBusinessPoint1[lang]}</li>
              <li>{T.planBusinessPoint2[lang]}</li>
              <li>{T.planBusinessPoint3[lang]}</li>
            </ul>
            <button className="price-cta navy" onClick={onSignup}>
              <Bolt />
              <span>{T.planBusinessBtn[lang]}</span>
              <span className="hp-arr" aria-hidden="true">↗</span>
            </button>
          </div>
        </div>
        <p className="pricing-note">{T.planNote[lang]}</p>
      </section>

      {/* ---- لوحة التحكم ------------------------------------------------------ */}
      <section className="landing-section dash-section" id="dashboard">
        <p className="section-kicker">{T.dashKicker[lang]}</p>
        <h2 className="section-title">{T.dashTitle[lang]}</h2>
        <p className="section-body">{T.dashBody[lang]}</p>
        <div className="section-points">
          <div className="point-card">
            <span className="point-icon">📁</span>
            <span>{T.dashPoint1[lang]}</span>
          </div>
          <div className="point-card">
            <span className="point-icon">⚡</span>
            <span>{T.dashPoint2[lang]}</span>
          </div>
          <div className="point-card">
            <span className="point-icon">📤</span>
            <span>{T.dashPoint3[lang]}</span>
          </div>
        </div>
        <button className="btn-primary" onClick={onDashboard}>
          {T.dashCta[lang]}
        </button>
      </section>

      {/* ---- live stats ------------------------------------------------------ */}
      <section className="stats-strip">
        <h2>{T.statsTitle[lang]}</h2>
        <div className="stats-cards">
          <div className="stat-card">
            <span className="stat-icon">📊</span>
            <span className="stat-num">{fmt(stats?.analyses_count)}</span>
            <span className="stat-lbl">{T.statAnalyses[lang]}</span>
          </div>
          <div className="stat-card">
            <span className="stat-icon">📘</span>
            <span className="stat-num">{fmt(stats?.statements_count)}</span>
            <span className="stat-lbl">{T.statStatements[lang]}</span>
          </div>
          <div className="stat-card">
            <span className="stat-icon">👁</span>
            <span className="stat-num">{fmt(stats?.visits)}</span>
            <span className="stat-lbl">{T.statVisits[lang]}</span>
          </div>
        </div>
        {stats && stats.recent.length > 0 && (
          <div className="recent-list">
            <h3>{T.recent[lang]}</h3>
            <ul>
              {stats.recent.slice(0, 5).map((r) => (
                <li key={r.id}>
                  <span>{r.name}</span>
                  <span className="recent-date">
                    {new Date(r.date).toLocaleDateString("en-GB")}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
