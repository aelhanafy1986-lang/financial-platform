import { useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AuthContext } from "./App";
import { Glyph } from "./Glyph";
import type { AnalysisFull, Lang } from "./types";

/** Post-login «النظرة العامة» — the workspace home the user modelled on
 *  his CMRRS reference: a stat strip, company-distribution donut, the
 *  revenue-vs-net totals chart, quick-action cards and a recent-activity
 *  feed. Shown in the main pane whenever no analysis is selected (and as
 *  the «النظرة العامة» rail destination), so signing in now LANDS here
 *  instead of the bare upload placeholder. Serial badges (١، ٢، ٣) on the
 *  quick actions appear only while the workspace is still empty. */

const T = {
  overview: { ar: "النظرة العامة", en: "Overview" },
  hello: { ar: "مرحبًا بك في لوحة التحكم المالية", en: "Welcome to your financial control panel" },
  openLast: { ar: "فتح آخر تحليل", en: "Open last analysis" },
  secRecent: { ar: "التحليلات الأخيرة", en: "Recent analyses" },
  secDist: { ar: "توزيع الشركات", en: "Company distribution" },
  secTotals: { ar: "مقارنة الإيرادات والأرباح (بالملايين)", en: "Revenue vs profit comparison (millions)" },
  secActions: { ar: "إجراءات سريعة", en: "Quick actions" },
  secRecentAct: { ar: "آخر النشاطات", en: "Recent activity" },
  remainAn: { ar: "التحليلات المتبقية حسب الباقة", en: "Remaining analyses on plan" },
  totalAn: { ar: "إجمالي التحليلات", en: "Total analyses" },
  thisMonth: { ar: "هذا الشهر", en: "This month" },
  lastAn: { ar: "آخر تحليل", en: "Last analysis" },
  statements: { ar: "القوائم المبنية", en: "Built statements" },
  noData: {
    ar: "لا توجد تحليلات بعد — ابدأ برفع ملف مالي",
    en: "No analyses yet — start by uploading a financial file",
  },
  upload: { ar: "رفع ملف مالي", en: "Upload a financial file" },
  uploadHint: {
    ar: "حلّل قوائم الدخل والميزانيات فورًا",
    en: "Analyse income statements & balance sheets instantly",
  },
  sample: { ar: "آخر تحليل", en: "Last analysis" },
  sampleHint: {
    ar: "شاهد كيف تُقرأ القوائم خطوة بخطوة",
    en: "See how statements are read step by step",
  },
  lastIs: { ar: "آخر تحليل:", en: "Last analysis:" },
  group: { ar: "مقارنة التقارير", en: "Compare reports" },
  groupHint: {
    ar: "قارن عدة شركات في لوحة واحدة",
    en: "Compare several companies on one board",
  },
  open: { ar: "فتح", en: "Open" },
  revenue: { ar: "الإيرادات", en: "Revenue" },
  netProfit: { ar: "صافي الربح", en: "Net profit" },
  planTitle: { ar: "اشتراكك", en: "Your subscription" },
  status: { ar: "الحالة", en: "Status" },
  active: { ar: "نشط", en: "Active" },
  usedFiles: { ar: "الملفات المستخدمة", en: "Files used" },
  planFree: { ar: "مجاني", en: "Free" },
  planPro: { ar: "برو", en: "Pro" },
  planBusiness: { ar: "الأعمال", en: "Business" },
  planMonthly: { ar: "شهري", en: "Monthly" },
  planYearly: { ar: "سنوي", en: "Yearly" },
  planFirm: { ar: "مؤسسي", en: "Firm" },
  planAdmin: { ar: "مدير المنصة — غير محدود", en: "Admin — unlimited" },
  quotaLabel: { ar: "التحليلات المتبقية", en: "Analyses remaining" },
  quotaUsed: { ar: "المستخدمة", en: "Used" },
  unlimited: { ar: "استخدام غير محدود", en: "Unlimited usage" },
  upgrade: { ar: "ترقية الخطة", en: "Upgrade plan" },
  portfolio: { ar: "صافي المحفظة", en: "Portfolio net" },
  portfolioRev: { ar: "إجمالي إيرادات المحفظة", en: "Portfolio revenue" },
  portfolioNet: { ar: "صافي ربح المحفظة", en: "Portfolio net profit" },
  vsPrevMonth: { ar: "مقارنة بالشهر الماضي", en: "vs last month" },
  trendAlone: {
    ar: "شهر واحد — لا مقارنة سابقة",
    en: "Single month — no previous comparison",
  },
};

/** localStorage key: the id of the overview section the user last viewed.
 *  Restored (scrolled to) whenever the user returns to the overview so he
 *  resumes reading where he left off. "ho" = section id prefix. */
const HO_LAST_SECTION = "hoLastSection";

/** Track the overview section currently in view (scroll listener) and
 *  persist it; restore it on mount by scrolling that section into view
 *  just below the sticky top bar. Sections are the ho-panel ids
 *  (sec-ho-stats, sec-ho-dist, sec-ho-totals, sec-ho-actions,
 *  sec-ho-recent, sec-ho-plan). */
function useLastSectionRestore(itemsReady: boolean) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [restored, setRestored] = useState(false);

  // Restore once the data renders (sections exist) — after any view return.
  useEffect(() => {
    if (!itemsReady || restored) return;
    setRestored(true);
    const saved = localStorage.getItem(HO_LAST_SECTION);
    if (
      saved &&
      saved !== "sec-ho-stats" &&
      document.getElementById(saved)
    ) {
      document
        .getElementById(saved)
        ?.scrollIntoView({ behavior: "auto", block: "start" });
    }
  }, [itemsReady, restored]);

  // Scroll tracker — watch the whole viewport (the page, not the panel,
  // is what scrolls) and persist the section owning most of the viewport.
  useEffect(() => {
    const pick = () => {
      const panels = [
        ...document.querySelectorAll<HTMLElement>(".home-overview .panel[id]"),
      ];
      let best: Element | null = null;
      let bestOverlap = 0;
      const vhMid = window.innerHeight * 0.45;
      for (const p of panels) {
        const r = p.getBoundingClientRect();
        if (r.height <= 0) continue;
        const overlap = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
        // a section in whose span the mid-viewport line sits always wins
        if (r.top <= vhMid && r.bottom > vhMid) {
          best = p;
          break;
        }
        if (overlap > bestOverlap) {
          best = p;
          bestOverlap = overlap;
        }
      }
      if (best) localStorage.setItem(HO_LAST_SECTION, best.id);
    };
    const el = rootRef.current;
    if (!el) return;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        pick();
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [itemsReady]);

  return rootRef;
}

const NAVY = "#123059";
const GREEN = "#22c55e";
const PIE_COLORS = [NAVY, "#2d4a7a", "#4a6ba0", "#7d95bd", "#a9bcd8", "#cfd9ea"];

/** Arabic-Indic numerals for the empty-state step badges. */
function _arNum(n: number): string {
  const ar = "٠١٢٣٤٥٦٧٨٩";
  return String(n)
    .split("")
    .map((c) => ar[Number(c)] ?? c)
    .join("");
}

/** Last-analysis timestamp on the stats strip: «7 October 2026 · 19:51»
 *  (Arabic month name, Latin digits — as the header's «آخر دخول» stamp).
 *  An empty board reads «—». */
function lastStamp(iso: string | undefined, lang: Lang): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  if (lang === "ar") {
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${d.getDate()} ${d.toLocaleDateString("ar", { month: "long" })} ${d.getFullYear()} · ${hh}:${mm}`;
  }
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function timeAgo(iso: string, lang: Lang): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return lang === "ar" ? "الآن" : "just now";
  if (mins < 60) return lang === "ar" ? `قبل ${mins} دقيقة` : `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return lang === "ar" ? `قبل ${hrs} ساعة` : `${hrs} h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return lang === "ar" ? `قبل ${days} يوم` : `${days} d ago`;
  return new Date(iso).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-GB", {
    day: "numeric",
    month: "short",
  });
}

/** Shrink «workbook — sheet» display names to the sheet (entity) part. */
function shortName(i: AnalysisFull): string {
  const name = i.display_name || i.filename;
  const m = name.match(/^(.*) — (.+)$/);
  return m ? m[2] : name.replace(/\.(xlsx|xls|pdf|docx|pptx|csv)$/i, "");
}

function fmtM(v: number): string {
  return `${(v / 1_000_000).toFixed(1)}M`;
}

function fmtNum(v: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
}

/** Quota ladder mirroring the backend (app/main.py upload quota):
 *  free 1 one-time · pro 5/mo · business 20/mo · legacy monthly 15,
 *  yearly 20, firm unlimited · platform admin unlimited. */
function planQuota(user: { is_admin?: boolean; subscription: string; plan?: string | null }): {
  quota: number | null;
  planLabel: string;
} {
  const L = {
    free: "مجاني",
    pro: "برو",
    business: "الأعمال",
    monthly: "شهري",
    yearly: "سنوي",
    firm: "مؤسسي",
  };
  const ladder: Record<string, number | null> = {
    pro: 5,
    business: 20,
    monthly: 15,
    yearly: 20,
    firm: null,
  };
  if (user.is_admin)
    return { quota: null, planLabel: "مدير المنصة" };
  if (user.subscription === "paid") {
    const p = user.plan ?? "";
    return { quota: ladder[p] ?? 20, planLabel: (L as Record<string, string>)[p] ?? "برو" };
  }
  return { quota: 1, planLabel: L.free };
}

export function HomeOverview({
  items,
  lang,
  onOpen,
  onUploadClick,
  onGroup,
  onUpgrade,
}: {
  items: AnalysisFull[];
  lang: Lang;
  onOpen: (id: number) => void;
  onUploadClick: () => void;
  onGroup: () => void;
  onUpgrade: () => void;
}) {
  const { user } = useContext(AuthContext);
  const empty = items.length === 0;
  // track + restore the last viewed section across overview visits
  const rootRef = useLastSectionRestore(true);

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const monthCount = useMemo(
    () => items.filter((i) => new Date(i.created_at) >= monthStart).length,
    [items]
  );
  const stmtCount = useMemo(
    () =>
      items.filter(
        (i) =>
          i.has_tb ||
          !!(i.result as unknown as { statements?: unknown } | undefined)?.statements,
      ).length,
    [items]
  );

  const kpisOf = (i: AnalysisFull) => {
    const k = i.result?.kpis ?? {};
    return {
      rev: k.revenue?.value ?? null,
      net: k.net_profit?.value ?? null,
    };
  };

  const totals = useMemo(
    () =>
      items.reduce(
        (acc, i) => {
          const { rev, net } = kpisOf(i);
          if (rev && rev > 0) acc.rev += rev;
          if (net) acc.net += net;
          return acc;
        },
        { rev: 0, net: 0 }
      ),
    [items]
  );

  // Company distribution donut: one slice per entity sized by revenue
  // (equal slices when no revenue captured — still shows the portfolio).
  const dist = useMemo(() => {
    const byName = new Map<string, number>();
    for (const i of items) {
      const key = shortName(i);
      const { rev } = kpisOf(i);
      byName.set(key, (byName.get(key) ?? 0) + (rev && rev > 0 ? rev : 0));
    }
    const rows = [...byName.entries()].map(([name, revenue]) => ({ name, revenue }));
    const anyRev = rows.some((r) => r.revenue > 0);
    return rows.map((r) => ({ ...r, revenue: anyRev ? r.revenue : 1 }));
  }, [items]);

  // Revenue-vs-net horizontal bars per analysis (reference: navy vs green).
  const perCompany = useMemo(
    () =>
      items
        .slice()
        .sort((a, b) => (kpisOf(b).rev ?? 0) - (kpisOf(a).rev ?? 0) || b.id - a.id)
        .slice(0, 8)
        .map((i) => ({
          name: shortName(i),
          [T.revenue[lang]]: Math.round(kpisOf(i).rev ?? 0),
          [T.netProfit[lang]]: Math.round(kpisOf(i).net ?? 0),
        })),
    [items, lang]
  );

  // three items only — the card must hug its content and stay level with
  // the quick-actions / subscription boxes of the same row
  const recent = items.slice(0, 3);

  // Monthly aggregation of the analysed portfolio (by analysis date):
  // revenue and net profit accrued per calendar month, driving the
  // portfolio-net card's monthly trend bars (oldest → newest).
  const monthly = useMemo(() => {
    const byMonth = new Map<
      string,
      { key: string; label: string; rev: number; net: number }
    >();
    for (const i of items) {
      const d = new Date(i.created_at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const e =
        byMonth.get(key) ??
        {
          key,
          label: d.toLocaleDateString(lang === "ar" ? "ar-EG" : "en-GB", {
            month: "short",
          }),
          rev: 0,
          net: 0,
        };
      const { rev, net } = kpisOf(i);
      if (rev && rev > 0) e.rev += rev;
      if (net) e.net += net;
      byMonth.set(key, e);
    }
    return [...byMonth.values()].sort((a, b) => (a.key < b.key ? -1 : 1));
  }, [items, lang]);

  // Month-over-month direction of the portfolio net profit: last month vs
  // the one before it. A single data month (or an empty previous one) shows
  // a neutral state with a «لا مقارنة سابقة» hint instead of a fake trend.
  const trend = useMemo((): {
    dir: number;
    pct: null | number;
    label: string;
  } => {
    if (monthly.length < 2)
      return { dir: 0, pct: null, label: T.trendAlone[lang] };
    const last = monthly[monthly.length - 1];
    const prev = monthly[monthly.length - 2];
    if (prev.net === 0) return { dir: 0, pct: null, label: T.trendAlone[lang] };
    const pct = Math.round(((last.net - prev.net) / Math.abs(prev.net)) * 100);
    return { dir: Math.sign(pct), pct: Math.abs(pct), label: T.vsPrevMonth[lang] };
  }, [monthly, lang]);

  return (
    <div className="home-overview" dir={lang === "ar" ? "rtl" : "ltr"} ref={rootRef}>
      {/* ---------- header: greeting + open-last-analysis shortcut ---------- */}
      <header className="ho-header">
        <div className="ho-user">
          <strong>{user?.full_name || user?.username}</strong>
          <small>{T.hello[lang]}</small>
        </div>
        {!empty && (
          <button
            className="ho-open-last"
            onClick={() => items[0] && onOpen(items[0].id)}
            title={`${T.openLast[lang]} — ${shortName(items[0])}`}
          >
            <Glyph name="doc" size={14} />
            <span>{T.openLast[lang]}</span>
            <small>{shortName(items[0])}</small>
          </button>
        )}
      </header>

      {/* ---------- stats strip ---------- */}
      <div className="ho-stats">
        <div className="ho-stat">
          <span className="ho-stat-label">{T.remainAn[lang]}</span>
          <strong className="ho-stat-val">
            {planQuota({
              is_admin: user?.is_admin,
              subscription: user?.subscription ?? "free",
              plan: user?.plan,
            }).quota === null
              ? "∞"
              : Math.max(
                  0,
                  (planQuota({
                    is_admin: user?.is_admin,
                    subscription: user?.subscription ?? "free",
                    plan: user?.plan,
                  }).quota ?? 0) -
                    Math.max(
                      0,
                      Math.min(
                        planQuota({
                          is_admin: user?.is_admin,
                          subscription: user?.subscription ?? "free",
                          plan: user?.plan,
                        }).quota ?? 0,
                        user?.uploads_used ?? 0,
                      ),
                    ),
                )}
          </strong>
          <span className="ho-stat-icon">
            <Glyph name="doc" size={18} />
          </span>
        </div>
        <div className="ho-stat">
          <span className="ho-stat-label">{T.totalAn[lang]}</span>
          <strong className="ho-stat-val">{items.length}</strong>
          <span className="ho-stat-icon">
            <Glyph name="check" size={18} />
          </span>
        </div>
        <div className="ho-stat">
          <span className="ho-stat-label">{T.thisMonth[lang]}</span>
          <strong className="ho-stat-val">{monthCount}</strong>
          <span className="ho-stat-icon">
            <Glyph name="warning" size={18} />
          </span>
        </div>
        <div className="ho-stat">
          <span className="ho-stat-label">{T.lastAn[lang]}</span>
          <strong className={`ho-stat-val ho-stat-time`}>
            {lastStamp(items[0]?.created_at, lang)}
          </strong>
          <span className="ho-stat-icon">
            <Glyph name="clock" size={18} />
          </span>
        </div>
      </div>

      {/* ---------- portfolio net card: all companies + monthly trend ---------- */}
      <section className="panel ho-panel ho-portfolio" id="sec-ho-portfolio">
        <h3 className="ho-panel-title">{T.portfolio[lang]}</h3>
        {empty ? (
          <div className="ho-empty">{T.noData[lang]}</div>
        ) : (
          <div className="ho-pf-grid">
            <div className="ho-pf-kpis">
              <div className="ho-pf-kpi">
                <span>{T.portfolioRev[lang]}</span>
                <strong>{fmtNum(totals.rev)}</strong>
              </div>
              <div className="ho-pf-kpi">
                <span>{T.portfolioNet[lang]}</span>
                <strong className={totals.net < 0 ? "neg" : "pos"}>
                  {fmtNum(totals.net)}
                </strong>
              </div>
            </div>
            <div className="ho-pf-trend">
              <div className="ho-pf-trend-head">
                <span
                  className={`ho-pf-badge ${
                    trend.dir > 0 ? "up" : trend.dir < 0 ? "down" : "flat"
                  }`}
                >
                  {trend.dir > 0 ? "▲" : trend.dir < 0 ? "▼" : "●"} {trend.pct != null ? `${trend.pct}%` : "—"}
                </span>
                <small>{trend.label}</small>
              </div>
              <div className="ho-pf-months">
                <ResponsiveContainer width="100%" height={96}>
                  <BarChart data={monthly} margin={{ top: 4, right: 6, bottom: 0, left: 6 }}>
                    <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="label"
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                    />
                    <Tooltip formatter={(v: number) => `${fmtNum(v)} — ${T.netProfit[lang]}`} />
                    <Bar dataKey="net" radius={[4, 4, 0, 0]}>
                      {monthly.map((m, idx) => (
                        <Cell key={idx} fill={m.net < 0 ? "#ef4444" : NAVY} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ---------- row 1: distribution donut + totals chart ---------- */}
      <div className="ho-grid-2">
        <section className="panel ho-panel" id="sec-ho-dist">
          <h3 className="ho-panel-title">{T.secDist[lang]}</h3>
          {empty ? (
            <div className="ho-empty">{T.noData[lang]}</div>
          ) : (
            <div className="ho-donut-wrap">
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    data={dist}
                    dataKey="revenue"
                    nameKey="name"
                    innerRadius="62%"
                    outerRadius="88%"
                    paddingAngle={2}
                    stroke="none"
                  >
                    {dist.map((_, idx) => (
                      <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: number, n: string) => [fmtNum(v), n]} />
                </PieChart>
              </ResponsiveContainer>
              <div className="ho-donut-legend">
                {dist.slice(0, 5).map((d, idx) => (
                  <span className="ho-legend-item" key={d.name}>
                    <i style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }} />
                    {d.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="panel ho-panel" id="sec-ho-totals">
          <h3 className="ho-panel-title">{T.secTotals[lang]}</h3>
          {empty || totals.rev === 0 ? (
            <div className="ho-empty">{T.noData[lang]}</div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={perCompany}
                layout="vertical"
                margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
              >
                <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" horizontal={false} />
                <XAxis
                  type="number"
                  tickFormatter={fmtM}
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={90}
                  tick={{ fontSize: 12, fill: "#334155" }}
                />
                <Tooltip formatter={(v: number) => fmtNum(v)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey={T.revenue[lang]} fill={NAVY} radius={[4, 4, 0, 0]} />
                <Bar dataKey={T.netProfit[lang]} fill={GREEN} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>
      </div>

      {/* ---------- row 2: quick actions + recent activity ---------- */}
      <div className="ho-grid-2 ho-row-2">
        <section className="panel ho-panel" id="sec-ho-actions">
          <h3 className="ho-panel-title">{T.secActions[lang]}</h3>
          <div className="ho-actions">
            <button className="ho-action" onClick={onUploadClick}>
              <span className="ho-action-num">
                {empty ? _arNum(1) : ""}
              </span>
              <span className="ho-action-icon up">
                <Glyph name="doc" size={20} />
              </span>
              <span className="ho-action-text">
                <strong>{T.upload[lang]}</strong>
                <small>{T.uploadHint[lang]}</small>
              </span>
            </button>
            <button
              className="ho-action"
              onClick={() => items[0] && onOpen(items[0].id)}
              disabled={empty}
            >
              <span className="ho-action-num">{empty ? _arNum(2) : ""}</span>
              <span className="ho-action-icon doc">
                <Glyph name="doc" size={20} />
              </span>
              <span className="ho-action-text">
                <strong>{T.sample[lang]}</strong>
                <small>
                  {empty ? T.sampleHint[lang] : `${T.lastIs[lang]} ${shortName(items[0])}`}
                </small>
              </span>
            </button>
            <button
              className="ho-action"
              onClick={onGroup}
              disabled={items.length < 2}
            >
              <span className="ho-action-num">{empty ? _arNum(3) : ""}</span>
              <span className="ho-action-icon cmp">
                <Glyph name="check" size={20} />
              </span>
              <span className="ho-action-text">
                <strong>{T.group[lang]}</strong>
                <small>{T.groupHint[lang]}</small>
              </span>
            </button>
          </div>
        </section>

        <section className="panel ho-panel" id="sec-ho-recent">
          <h3 className="ho-panel-title">{T.secRecentAct[lang]}</h3>
          {empty ? (
            <div className="ho-empty">{T.noData[lang]}</div>
          ) : (
            <ul className="ho-recent-list">
              {recent.map((i) => {
                const { rev, net } = kpisOf(i);
                return (
                  <li key={i.id}>
                    <button className="ho-recent-item" onClick={() => onOpen(i.id)}>
                      <span className="ho-recent-name">{shortName(i)}</span>
                      <span className="ho-recent-meta">
                        {rev != null && <b>{fmtNum(rev)}</b>}
                        {net != null && (
                          <em className={net < 0 ? "neg" : "pos"}>
                            {net < 0 ? "▾" : "▴"} {fmtNum(Math.abs(net))}
                          </em>
                        )}
                        <time>{timeAgo(i.created_at, lang)}</time>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* ---------- subscription status card (reference-style) ---------- */}
        <section className="panel ho-panel ho-plan" id="sec-ho-plan">
          {(() => {
            const { quota, planLabel } = planQuota({
              is_admin: user?.is_admin,
              subscription: user?.subscription ?? "free",
              plan: user?.plan,
            });
            const used = user?.uploads_used ?? 0;
            const pct = quota ? Math.min(100, Math.round((used / quota) * 100)) : 100;
            return (
              <>
                {/* header: crown + title, current-plan pill on the far side */}
                <div className="hp-head">
                  <strong className="hp-title">
                    <span className="ho-crown" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
                        <path
                          d="M3.5 8.5 8 12l4-6 4 6 4.5-3.5L19 18H5L3.5 8.5z"
                          stroke="#d9a441"
                          strokeWidth="1.8"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                    {T.planTitle[lang]}
                  </strong>
                  <span className="hp-chip">{planLabel}</span>
                </div>
                <div className="hp-row">
                  <span>{T.status[lang]}</span>
                  <span className="hp-status">{T.active[lang]}</span>
                </div>
                <div className="hp-row">
                  <span>{T.usedFiles[lang]}</span>
                  <strong className="hp-val">
                    {quota === null
                      ? "∞"
                      : `${Math.min(used, quota)} ${lang === "ar" ? "من" : "of"} ${quota}`}
                  </strong>
                </div>
                <div className="ho-plan-bar">
                  <span
                    className={`ho-plan-fill${quota !== null && pct >= 100 ? " full" : ""}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                {!user?.is_admin && (
                  <button className="ho-plan-upgrade" onClick={onUpgrade}>
                    <span className="hp-bolt" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
                        <path
                          d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z"
                          stroke="#fff"
                          strokeWidth="1.8"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                    <span>{T.upgrade[lang]}</span>
                    <span className="hp-arr" aria-hidden="true">↗</span>
                  </button>
                )}
              </>
            );
          })()}
        </section>
      </div>

      {stmtCount > 0 && (
        <p className="ho-statements-note">
          {lang === "ar"
            ? `قوائم مالية مبنية من ميزان مراجعة: ${stmtCount}`
            : `Statements built from a trial balance: ${stmtCount}`}
        </p>
      )}
    </div>
  );
}
