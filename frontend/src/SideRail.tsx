import { useContext } from "react";
import { AuthContext } from "./App";
import { Glyph } from "./Glyph";
import type { Lang } from "./types";

/** Reference-style permanent side rail: navy, grouped navigation with
 *  pastel glyph tiles, the user grid pinned at the bottom and scroll
 *  arrows (the «CMRRS» chrome — now SFP). Group items that point at real
 *  content scroll/act; placeholder items are rendered but inert until
 *  their feature lands (titles explain them). */

const T = {
  jumpUpload: { ar: "رفع الملف المالي", en: "Upload financial file" },
  jumpModel: { ar: "سجل الملفات والتقارير", en: "Files & reports" },
  secBrowse: { ar: "التصفح والتحليل", en: "Browsing & analysis" },
  browseHistory: { ar: "لوحة النظرة العامة", en: "Overview board" },
  browseSample: { ar: "التحليلات المفصلة", en: "Detailed analyses" },
  browseCompare: { ar: "مقارنة التقارير", en: "Report comparison" },
  secHelp: { ar: "المساعدة والتنظيم", en: "Help & organisation" },
  helpStudy: { ar: "المساعد الذكي", en: "AI assistant" },
  helpSupport: { ar: "الدعم والمراجع", en: "Support" },
  secData: { ar: "التنظيم والمشاركة", en: "Organisation & sharing" },
  dataChats: { ar: "الملفات المُنظمة", en: "Organised files" },
  dataSnapshot: { ar: "نماذج التقارير حسب الباقة", en: "Report templates by plan" },
  dataFolder: { ar: "الفواتير والمدفوعات", en: "Invoices & payments" },
  logout: { ar: "تسجيل الخروج", en: "Sign out" },
  brand: { ar: "SFP", en: "SFP" },
  soon: { ar: "قريبًا", en: "coming soon" },
};

interface RailItem {
  key: string;
  ar: string;
  en: string;
  icon: JSX.Element;
  from: string;
  to: string;
  active?: boolean;
  action?: "overview" | "history" | "sample" | "compare" | "upload" | "stats" | "admin" | "templates" | "payments" | "assist" | "support";
  soon?: boolean;
}

interface RailGroup {
  id: string;
  ar?: string;
  en?: string;
  items: RailItem[];
}

function _tiles(): RailGroup[] {
  const g = (
    from: string,
    to: string,
    path: string,
  ): JSX.Element => (
    <svg viewBox="0 0 24 24" fill="none">
      <path d={path} stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
  return [
    {
      id: "g-start",
      items: [
        {
          key: "upload",
          ar: T.jumpUpload.ar,
          en: T.jumpUpload.en,
          icon: g("#10b981", "#34d399", "M12 16V5m0 0 4 4m-4-4L8 9M5 19h14"),
          from: "#10b981",
          to: "#34d399",
          action: "upload",
        },
        {
          key: "history",
          ar: T.jumpModel.ar,
          en: T.jumpModel.en,
          icon: g("#38bdf8", "#7dd3fc", "M12 8v4l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"),
          from: "#0ea5e9",
          to: "#38bdf8",
          action: "history",
        },
      ],
    },
    {
      id: "g-browse",
      ar: T.secBrowse.ar,
      en: T.secBrowse.en,
      items: [
        {
          key: "overview",
          ar: T.browseHistory.ar,
          en: T.browseHistory.en,
          icon: g("#0ea5e9", "#60a5fa", "M4 11.2 12 4.5l8 6.7M6.5 10v9h11v-9"),
          from: "#0ea5e9",
          to: "#60a5fa",
          active: true,
          action: "overview",
        },
        {
          key: "detailed",
          ar: T.browseSample.ar,
          en: T.browseSample.en,
          icon: g("#14b8a6", "#2dd4bf", "M6 3.5h8.5L19 8v12.5H6zM9 17v-3.5M12 17v-6M15 17v-2"),
          from: "#14b8a6",
          to: "#2dd4bf",
          action: "sample",
        },
        {
          key: "compare",
          ar: T.browseCompare.ar,
          en: T.browseCompare.en,
          icon: g("#f59e0b", "#fbbf24", "M4 6h9M4 12h6M4 18h12M17 8l3 3-3 3"),
          from: "#f59e0b",
          to: "#fbbf24",
          action: "compare",
        },
      ],
    },
    {
      id: "g-help",
      ar: T.secHelp.ar,
      en: T.secHelp.en,
      items: [
        {
          key: "assist",
          ar: T.helpStudy.ar,
          en: T.helpStudy.en,
          icon: g("#0ea5e9", "#7dd3fc", "M12 3a7 7 0 0 1 4 12.7V18H8v-2.3A7 7 0 0 1 12 3zM10 21h4"),
          from: "#0ea5e9",
          to: "#7dd3fc",
          action: "assist",
        },
        {
          key: "support",
          ar: T.helpSupport.ar,
          en: T.helpSupport.en,
          icon: g("#64748b", "#94a3b8", "M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-1a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z"),
          from: "#64748b",
          to: "#94a3b8",
          action: "support",
        },
      ],
    },
    {
      id: "g-data",
      ar: T.secData.ar,
      en: T.secData.en,
      items: [
        {
          key: "organised",
          ar: T.dataChats.ar,
          en: T.dataChats.en,
          icon: g("#0ea5e9", "#7dd3fc", "M4 6.5h6l2 2.5h8M4 6.5v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2"),
          from: "#0ea5e9",
          to: "#7dd3fc",
          action: "history",
        },
        {
          key: "templates",
          ar: T.dataSnapshot.ar,
          en: T.dataSnapshot.en,
          icon: g("#16a34a", "#4ade80", "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Zm9.5 2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"),
          from: "#16a34a",
          to: "#4ade80",
          action: "templates",
        },
        {
          key: "payments",
          ar: T.dataFolder.ar,
          en: T.dataFolder.en,
          icon: g("#334155", "#64748b", "M2.5 6.5h19v11h-19zM2.5 10h19M6 14.5h6"),
          from: "#334155",
          to: "#64748b",
          action: "payments",
        },
      ],
    },
  ];
}

export function SideRail({
  lang,
  onOverview,
  onHistory,
  onSample,
  onCompare,
  onUpload,
  onStats,
  onAdmin,
  onTemplates,
  onPayments,
  onAssist,
  onSupport,
  hasStats,
  isAdmin,
}: {
  lang: Lang;
  onOverview: () => void;
  onHistory: () => void;
  onSample: () => void;
  onCompare: () => void;
  onUpload: () => void;
  onStats: () => void;
  onAdmin: () => void;
  onTemplates: () => void;
  onPayments: () => void;
  onAssist: () => void;
  onSupport: () => void;
  hasStats: boolean;
  isAdmin: boolean;
}) {
  const { user } = useContext(AuthContext);
  const groups = _tiles();

  const run = (item: RailItem) => {
    if (item.soon) return;
    switch (item.action) {
      case "overview":
        onOverview();
        break;
      case "history":
        onHistory();
        break;
      case "sample":
        onSample();
        break;
      case "compare":
        onCompare();
        break;
      case "upload":
        onUpload();
        break;
      case "stats":
        onStats();
        break;
      case "admin":
        onAdmin();
        break;
      case "templates":
        onTemplates();
        break;
      case "payments":
        onPayments();
        break;
      case "assist":
        onAssist();
        break;
      case "support":
        onSupport();
        break;
      default:
        break;
    }
  };

  const initials = (user?.full_name || user?.username || "SFP")
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <nav className="side-rail" aria-label={lang === "ar" ? "التنقل السريع" : "Quick navigation"}>
      {/* top chrome: brand + collapse affordance (decorative) */}
      <div className="rail-top">
        <span className="rail-brand">{T.brand[lang]}</span>
        <span className="rail-chip">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
            <rect x="4" y="5" width="4" height="14" rx="1" fill="#FFD54A" />
            <rect x="10" y="7" width="4" height="12" rx="1" fill="#fff" opacity="0.85" />
            <rect x="16" y="9" width="4" height="10" rx="1" fill="#fff" opacity="0.6" />
          </svg>
        </span>
      </div>

      <div className="rail-scroll">
        {groups.map((grp, gi) => (
          <div className="rail-group" key={grp.id}>
            {grp.ar && (
              <div className="rail-group-label">
                <span className="rail-group-num">{_arGroup(gi + 1, lang)}</span>
                {lang === "ar" ? grp.ar : grp.en}
              </div>
            )}
            {grp.items.map((item) => (
              <button
                key={item.key}
                className={`rail-item${item.active ? " active" : ""}${item.soon ? " soon" : ""}`}
                onClick={() => run(item)}
                title={item.soon ? `${lang === "ar" ? item.ar : item.en} — ${T.soon[lang]}` : lang === "ar" ? item.ar : item.en}
                type="button"
              >
                <span
                  className="rail-tile"
                  style={{ background: `linear-gradient(135deg, ${item.from}, ${item.to})` }}
                >
                  {item.icon}
                </span>
                <span className="rail-label">{lang === "ar" ? item.ar : item.en}</span>
              </button>
            ))}
          </div>
        ))}
      </div>

      {/* scroll arrows + user grid, like the reference chrome */}
      <div className="rail-arrows" aria-hidden="true">
        <span>◀</span>
        <span className="rail-arrows-mid" />
        <span>▶</span>
      </div>

      <div className="rail-user">
        <div className="rail-user-id">
          <span className="rail-avatar">{initials}</span>
          <span className="rail-user-meta">
            <strong>{user?.full_name || user?.username}</strong>
            <small>{user?.email ?? ""}</small>
          </span>
        </div>
        <button
          className="rail-user-btn"
          onClick={onStats}
          disabled={!hasStats}
          title={lang === "ar" ? "الإحصاءات العامة" : "Statistics"}
        >
          <Glyph name="doc" size={14} />
        </button>
        <button
          className="rail-user-btn"
          onClick={onAdmin}
          disabled={!isAdmin}
          title={lang === "ar" ? "لوحة المدير" : "Admin panel"}
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
            <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="1.8" />
            <path
              d="M12 2.8 14 5h4l1 4 2 2-2 2-1 4h-4l-2 2.2L10 17H6l-1-4-2-2 2-2 1-4h4l2-2.2z"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </nav>
  );
}

/** Arabic-Indic group numeral (١، ٢، …) for RTL, plain digits for LTR. */
function _arGroup(n: number, lang: Lang): string {
  if (lang !== "ar") return String(n);
  const ar = "٠١٢٣٤٥٦٧٨٩";
  return String(n)
    .split("")
    .map((c) => ar[Number(c)] ?? c)
    .join("");
}
