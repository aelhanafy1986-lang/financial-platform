import { useEffect, useState } from "react";
import type { Lang } from "./types";
import { Glyph } from "./Glyph";

const T = {
  report: { ar: "تقرير التحليل المالي", en: "Financial Analysis Report" },
  issued: { ar: "تم إنشاؤه", en: "Created" },
  period: { ar: "فترة التحليل", en: "Analysis period" },
  company: { ar: "المنشأة", en: "Entity" },
  band: { ar: "الاشتراك", en: "Subscription" },
  planPaid: { ar: "برو", en: "PRO" },
  planFree: { ar: "النسخة المجانية", en: "Free edition" },
  yearly: { ar: "سنوي", en: "Yearly" },
  monthly: { ar: "شهري", en: "Monthly" },
  unspecified: { ar: "غير محددة", en: "Not specified" },
  auditOk: { ar: "مدقق", en: "Verified" },
  auditOkHint: {
    ar: "اجتاز مدقق الجودة المالي — الأرقام مترابطة وممكنة رياضيًا",
    en: "Passed the financial quality gate — figures are coherent and plausible",
  },
  auditWarned: { ar: "تنبيه جودة", en: "quality warnings" },
  auditFailed: { ar: "فشل المدقق", en: "Failed audit" },
};

/** Format "2026-09-30T07:12:30" as "30/9/2026" (Arabic-style, like CMRRS). */
function issuedDate(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}`;
}

export interface ReportHeaderData {
  title: string;
  analysedAt: string | null;
  period?: string;
  company?: string;
  /** Actual subscription badge: e.g. "PRO — Yearly" or the free edition. */
  band?: string;
  /** Quality-gate outcome: verified badge, warning count, or failed audit. */
  quality?: { errors: number; warnings: number; messages: string[] };
}

/** CMRRS-style report banner: logo tile + title + issue date + meta card
 *  (analysis period / company). Shown at the very top of the analysis view,
 *  directly above the executive brief. */
export function ReportHeader({
  data,
  lang,
  onEditCompany,
}: {
  data: ReportHeaderData;
  lang: Lang;
  /** Save an edited entity name: (draft, setSaving, done) — patched
   *  server-side as the analysis display_name. */
  onEditCompany?: (
    draft: string,
    setSaving: (v: boolean) => void,
    done: () => void,
  ) => void;
}) {
  const [logo, setLogo] = useState<string>("/logo.svg");
  // Inline editing of the Entity line (report banner «المنشأة») — PATCHes
  // the analysis display_name, exactly like the js-tree header pencil.
  const [editingCompany, setEditingCompany] = useState(false);
  const [companyDraft, setCompanyDraft] = useState("");
  const [savingCompany, setSavingCompany] = useState(false);

  useEffect(() => {
    // cache-busted fetch keeps the tile fresh after brand updates
    fetch("/api/logo.svg")
      .then((r) => (r.ok ? r.text() : ""))
      .then(() => setLogo("/logo.svg?v=report"))
      .catch(() => {});
  }, []);

  return (
    <section className="report-banner">
      <div className="report-banner-top">
        <div className="report-brand">
          <span className="report-logo">
            <img src={logo} alt="" />
          </span>
          <div className="report-titles">
            {/* the brand name in the ACTIVE language — the off-brand «SFP»
                abbreviation never appears in the report lockup */}
            <span className={`report-sub${lang === "ar" ? " ar" : ""}`}>
              {lang === "ar" ? "المنصة المالية الذكية" : "Smart Financial Platform"}
            </span>
            <h2 className="report-title">{T.report[lang]}</h2>
          </div>
        </div>
        <div className="report-meta-side">
          <span className="report-band">{data.band || T.band[lang]}</span>
          {data.quality &&
            (data.quality.errors > 0 ? (
              <span
                className="audit-chip audit-bad"
                title={data.quality.messages.join(" \u00b7 ")}
              >
                {T.auditFailed[lang]}
              </span>
            ) : data.quality.warnings > 0 ? (
              <span
                className="audit-chip audit-warn"
                title={data.quality.messages.join(" \u00b7 ")}
              >
                {data.quality.warnings} {T.auditWarned[lang]}
              </span>
            ) : (
              <span
                className="audit-chip audit-ok"
                title={T.auditOkHint[lang]}
              >
                {T.auditOk[lang]}
              </span>
            ))}
          <span className="report-issued">
            {T.issued[lang]} <strong>{issuedDate(data.analysedAt)}</strong>
          </span>
        </div>
      </div>

      <div className="report-banner-card">
        <div className="report-card-row">
          <span className="report-k">{T.period[lang]}</span>
          <span className="report-v">{data.period || "—"}</span>
        </div>
        <div className="report-card-row">
          <span className="report-k">{T.company[lang]}</span>
          {editingCompany ? (
            <span className="report-v report-edit-company">
              <input
                autoFocus
                value={companyDraft}
                maxLength={200}
                onChange={(e) => setCompanyDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onEditCompany?.(companyDraft, setSavingCompany, () => setEditingCompany(false));
                  if (e.key === "Escape") setEditingCompany(false);
                }}
              />
              <button
                className="btn small save"
                disabled={savingCompany}
                onClick={() =>
                  onEditCompany?.(companyDraft, setSavingCompany, () => setEditingCompany(false))
                }
              >
                {lang === "ar" ? "حفظ" : "Save"}
              </button>
              <button className="btn small ghost" onClick={() => setEditingCompany(false)}>
                {lang === "ar" ? "إلغاء" : "Cancel"}
              </button>
            </span>
          ) : (
            <span className="report-v report-company-cell">
              {data.company || data.title}
              <button
                className="icon-btn report-edit-pen"
                title={lang === "ar" ? "تعديل اسم المنشأة" : "Edit entity name"}
                onClick={() => {
                  setCompanyDraft(data.company || data.title);
                  setEditingCompany(true);
                }}
              >
                ✏️
              </button>
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
