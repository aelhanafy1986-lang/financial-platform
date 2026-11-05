import { useMemo } from "react";
import { Glyph } from "./Glyph";
import type { AnalysisFull, Lang } from "./types";

/** «سجل التحليلات» — the files-and-reports register page (reference-style):
 *  a compact stat strip (total analyses / quality checks / notes), then one
 *  wide row per analysis carrying its KPIs and the full action set (open,
 *  reading sample, PDF, Excel, PPTX, reanalyse, delete). Rendered as a view
 *  inside the main pane; opened from the side rail. */

const T = {
  title: { ar: "سجل التحليلات", en: "Analysis records" },
  subtitle: {
    ar: "عرض وإدارة نتيجة تحليل القوائم المالية للسابقة",
    en: "Browse and manage past financial-statement analyses",
  },
  totalAn: { ar: "إجمالي التحليلات", en: "Total analyses" },
  qualityOk: { ar: "نققة عالية", en: "Quality passed" },
  notes: { ar: "ملاحظات", en: "Notes" },
  open: { ar: "فتح التحليل", en: "Open analysis" },
  reading: { ar: "عينة قراءة", en: "Reading sample" },
  pdf: { ar: "تحميل PDF", en: "Download PDF" },
  pptx: { ar: "عرض تقديمي", en: "PowerPoint" },
  reanalyze: { ar: "إعادة تحليل التقرير", en: "Re-analyse report" },
  reanalyzing: { ar: "جارٍ إعادة التحليل…", en: "Re-analysing…" },
  delete: { ar: "حذف", en: "Delete" },
  empty: {
    ar: "لا توجد تحليلات بعد — ارفع ملفًا من الشريط الجانبي",
    en: "No analyses yet — upload a file from the side rail",
  },
  noKpis: { ar: "بدون مؤشرات", en: "No KPIs" },
  verified: { ar: "مدقق", en: "Verified" },
  flagged: { ar: "بحذارة جودة", en: "Quality findings" },
  kindBadge: { ar: "التصنيف المثبّت:", en: "Locked classification:" },
  kindStatements: { ar: "قوائم مالية", en: "Financial statements" },
  kindTrial: { ar: "ميزان مراجعة", en: "Trial balance" },
  kindSales: { ar: "مبيعات", en: "Sales" },
  modeAuto: { ar: "تلقائي", en: "Auto-detect" },
  modeTb: { ar: "قراءة مدين/دائن", en: "Debit/credit reading" },
  modeFin: { ar: "قراءة مالية قسرية", en: "Forced financial reading" },
};

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function RecordsPage({
  items,
  lang,
  busyId,
  onOpen,
  onPdf,
  onPptx,
  onReanalyze,
  onDelete,
}: {
  items: AnalysisFull[];
  lang: Lang;
  busyId: number | null;
  onOpen: (id: number) => void;
  onPdf: (id: number) => void;
  onPptx: (id: number) => void;
  onReanalyze: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  const stats = useMemo(() => {
    const total = items.length;
    const quality = items.filter(
      (i) => i.result?.audit && !(i.result.audit.errors?.length || i.result.audit.warnings?.length)
    ).length;
    const notes = items.filter((i) => (i.notes ?? "").trim().length > 0).length;
    return { total, quality, notes };
  }, [items]);

  const nameOf = (i: AnalysisFull) => {
    const name = i.display_name || i.filename;
    const m = name.match(/^(.*) — (.+)$/);
    return m ? m[2] : name.replace(/\.(xlsx|xls|pdf|docx|pptx|csv)$/i, "");
  };

  /** The frozen upload classification, badged next to the reanalyse
   *  button: re-analysing always takes the SAME declared route — it
   *  never re-classifies the file. mPrefix marks the analysis mode when
   *  a forced reading is pinned (red, to signal the non-default read). */
  const kindBadgeOf = (i: AnalysisFull): { text: string; mode?: string } | null => {
    const kind = i.file_kind ?? null;
    const mode = i.analysis_mode ?? "auto";
    const kindAr =
      kind === "sales" ? T.kindSales[lang]
      : kind === "trial_balance" ? T.kindTrial[lang]
      : kind === "statements" ? T.kindStatements[lang]
      : null;
    if (!kindAr) return null; // legacy row without a stamp — no badge
    const modeAr =
      mode === "force_trial_balance" ? T.modeTb[lang]
      : mode === "financial_sheets" ? T.modeFin[lang]
      : null;
    return modeAr ? { text: kindAr, mode: modeAr } : { text: kindAr };
  };

  return (
    <div className="records-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <header className="rec-head">
        <h2>{T.title[lang]}</h2>
        <p>{T.subtitle[lang]}</p>
      </header>

      {/* ---------- stat strip ---------- */}
      <div className="rec-stats">
        <div className="rec-stat">
          <span className="rec-stat-icon navy">
            <Glyph name="doc" size={17} />
          </span>
          <strong>{stats.total}</strong>
          <span className="rec-stat-label">{T.totalAn[lang]}</span>
        </div>
        <div className="rec-stat">
          <span className="rec-stat-icon green">
            <Glyph name="check" size={17} />
          </span>
          <strong>{stats.quality}</strong>
          <span className="rec-stat-label">{T.qualityOk[lang]}</span>
        </div>
        <div className="rec-stat">
          <span className="rec-stat-icon amber">
            <Glyph name="doc" size={17} />
          </span>
          <strong>{stats.notes}</strong>
          <span className="rec-stat-label">{T.notes[lang]}</span>
        </div>
      </div>

      {/* ---------- rows ---------- */}
      {items.length === 0 ? (
        <div className="rec-empty">{T.empty[lang]}</div>
      ) : (
        <div className="rec-rows">
          {items.map((i) => {
            const k = i.result?.kpis ?? {};
            const rev = k.revenue?.value ?? null;
            const net = k.net_profit?.value ?? null;
            const nm = i.result?.ratios?.net_margin?.value ?? null;
            const audit = i.result?.audit;
            const findings =
              (audit?.errors?.length ?? 0) + (audit?.warnings?.length ?? 0);
            const busy = busyId === i.id;
            const nmPos = (nm ?? 0) >= 0;
            return (
              <article className="rec-row" key={i.id}>
                {/* identity block */}
                <div className="rec-id">
                  <span className="rec-type-badge">{(i.file_type || "").replace(".", "").toUpperCase()}</span>
                  <div className="rec-id-text">
                    <button className="rec-name" onClick={() => onOpen(i.id)} title={T.open[lang]}>
                      {nameOf(i)}
                    </button>
                    <small>
                      {i.filename} · {shortDate(i.created_at)}
                    </small>
                  </div>
                </div>

                {/* KPI block */}
                <div className="rec-kpis">
                  {rev != null && (
                    <div className="rec-kpi">
                      <span className="rec-kpi-label">{lang === "ar" ? "الإيرادات" : "Revenue"}</span>
                      <strong>{fmt(rev)}</strong>
                      <em className="pos">{lang === "ar" ? "ريال سعودي" : "SAR"}</em>
                    </div>
                  )}
                  {net != null && (
                    <div className="rec-kpi">
                      <span className="rec-kpi-label">
                        {net < 0 ? (lang === "ar" ? "صافي الخسارة" : "Net loss") : lang === "ar" ? "صافي الربح" : "Net profit"}
                      </span>
                      <strong>{fmt(Math.abs(net))}</strong>
                      {nm != null && (
                        <em className={nmPos ? "pos" : "neg"}>
                          {nmPos ? "▲" : "▼"} {Math.abs(nm).toFixed(1)}%
                        </em>
                      )}
                    </div>
                  )}
                  {rev == null && net == null && (
                    <span className="rec-nokpi">{T.noKpis[lang]}</span>
                  )}
                </div>

                {/* quality chip */}
                {audit && (
                  <span className={`rec-chip ${findings ? "warn" : "ok"}`}>
                    {findings ? <Glyph name="warning" size={11} /> : <Glyph name="check" size={11} />}
                    {findings ? `${T.flagged[lang]} ${findings}` : T.verified[lang]}
                  </span>
                )}

                {/* actions */}
                <div className="rec-actions">
                  <button className="rec-btn danger icon" onClick={() => onDelete(i.id)} disabled={busy} title={T.delete[lang]}>
                    <Glyph name="cross" size={13} />
                  </button>
                  <button className="rec-btn ghost icon" onClick={() => onOpen(i.id)} title={T.open[lang]}>
                    <Glyph name="eye" size={14} />
                  </button>
                  <button
                    className="rec-btn outline"
                    onClick={() => onReanalyze(i.id)}
                    disabled={busy || !i.has_file}
                    title={!i.has_file ? (lang === "ar" ? "الملف الأصلي غير محفوظ — لا يمكن إعادة التحليل" : "Original file not stored — cannot re-analyse") : undefined}
                  >
                    <span>{busy ? T.reanalyzing[lang] : T.reanalyze[lang]}</span>
                  </button>
                  {(() => {
                    const badge = kindBadgeOf(i);
                    return badge ? (
                      <span
                        className={`rec-kind-badge${badge.mode ? " forced" : ""}`}
                        title={badge.mode
                          ? `${T.kindBadge[lang]} ${badge.text} — ${badge.mode}`
                          : `${T.kindBadge[lang]} ${badge.text}`}
                      >
                        🔒 {badge.text}
                        {badge.mode && <small> · {badge.mode}</small>}
                      </span>
                    ) : null;
                  })()}
                  <button className="rec-btn primary" onClick={() => onPdf(i.id)}>
                    <Glyph name="doc" size={13} />
                    <span>{T.pdf[lang]}</span>
                  </button>
                  <button className="rec-btn soft" onClick={() => onPptx(i.id)}>
                    <span>{T.pptx[lang]}</span>
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
