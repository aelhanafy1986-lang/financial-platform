import { useContext, useEffect, useState } from "react";
import { AuthContext, useToast } from "./App";
import { useDownload } from "./useDownload";
import type { Lang } from "./types";

/** «الدعم والمراجع» — support & downloads center. Activated the side-rail
 *  item that sat at «قريبًا» since the beginning. All artifacts download
 *  through the already-existing endpoints (PDF report per analysis, PPTX,
 *  Excel export, BI ZIP bundle, comparison PDF, payment invoices);
 *  availability comes live from GET /api/support/content (paid + counts).
 *  Free accounts see a lock strip + «عرض الخطة» CTA (openPaywall). */

interface GuideStep {
  title: { ar: string; en: string };
  body: { ar: string; en: string };
}

interface Availability {
  paid: boolean;
  can_download: boolean;
  report_pdf: number;
  pptx: number;
  excel: number;
  bi_pack: number;
  comparison_pdf: number;
  statements_version: number;
  invoices: boolean;
}

const T = {
  headTitle: { ar: "الدعم والمراجع", en: "Support & references" },
  headSub: {
    ar: "كل تنزيلاتك وجاهزياتها في مكان واحد — ودليل استخدام المنصة",
    en: "All your downloads and readiness in one place — plus the platform guide",
  },
  guideCard: { ar: "كيفية استخدام المنصة", en: "How to use the platform" },
  downloadsCard: { ar: "مركز التنزيلات", en: "Downloads center" },
  reports: { ar: "تقارير PDF", en: "PDF reports" },
  reportsSub: {
    ar: "تقرير رسمي لكل تحليل محفوظ",
    en: "An official report per saved analysis",
  },
  pptx: { ar: "عروض PowerPoint", en: "PowerPoint decks" },
  pptxSub: {
    ar: "عرض تقديمي بمؤشرات النمو والتنبؤ",
    en: "A deck of KPIs, growth & forecast",
  },
  excel: { ar: "ملفات Excel", en: "Excel files" },
  excelSub: {
    ar: "القيم المستخرجة والنسب المعاد حسابها",
    en: "Extracted values & recomputed ratios",
  },
  bi: { ar: "حزمة BI (ZIP)", en: "BI bundle (ZIP)" },
  biSub: {
    ar: "CSV + Excel + SQL + دليل ربط Power BI/Tableau",
    en: "CSV + Excel + SQL + Power BI/Tableau guide",
  },
  compare: { ar: "تقارير المقارنة PDF", en: "Comparison PDFs" },
  compareSub: {
    ar: "تقرير المقارنة لكل زوج من تحليلاتك",
    en: "A report per pair of your analyses",
  },
  invoices: { ar: "فواتير الدفع", en: "Payment invoices" },
  invoicesSub: {
    ar: "فاتورة PDF رسمية لكل عملية دفع",
    en: "An official PDF invoice per payment",
  },
  ready: { ar: "جاهز", en: "Ready" },
  items: { ar: "عنصر", en: "items" },
  downloadBtn: { ar: "تنزيل", en: "Download" },
  downloadLatest: { ar: "تنزيل الأحدث", en: "Download latest" },
  pick: { ar: "اختر تحليلًا", en: "Pick an analysis" },
  lockedTitle: {
    ar: "التنزيلات مقفلة حتى تفعيل الباقة",
    en: "Downloads are locked until the plan is activated",
  },
  unlock: { ar: "عرض الخطة", en: "View plan" },
  noAnalyses: {
    ar: "لا توجد تحليلات محفوظة بعد — ارفع ملفك المالي أولًا ليظهر كل التنزيلات هنا",
    en: "No saved analyses yet — upload a financial file first and every download will appear here",
  },
  error: { ar: "تعذّر تحميل بيانات الدعم", en: "Couldn't load support data" },
};

const PLANS_AR: Record<string, string> = { pro: "برو", business: "الأعمال" };

export default function SupportCenter({
  lang,
  token,
  openPaywall,
  onOpenPayments,
}: {
  lang: Lang;
  token: string;
  openPaywall: () => void;
  onOpenPayments: () => void;
}) {
  const toast = useToast();
  const { user } = useContext(AuthContext);
  const [guide, setGuide] = useState<GuideStep[]>([]);
  const [avail, setAvail] = useState<Availability | null>(null);
  const [analyses, setAnalyses] = useState<{ id: number; name: string }[]>([]);
  const loadFail = guide.length === 0 && avail === null;

  // one authored request: availability + guide; analyses list for the pickers
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const [support, list] = await Promise.all([
          fetch(`/api/support/content?lang=${lang}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          }),
          fetch("/api/analyses"),
        ]);
        const body = support.ok ? await support.json() : null;
        if (!dead && body) {
          setGuide(body.guide ?? []);
          setAvail(body.availability ?? null);
        }
        if (list.ok && !dead) {
          const metas = await list.json();
          setAnalyses(
            metas.map((m: { id: number; display_name?: string; filename: string }) => ({
              id: m.id,
              name: m.display_name || m.filename,
            })),
          );
        }
      } catch {
        /* loadFail renders the retry notice */
      }
    })();
    return () => {
      dead = true;
    };
  }, [lang, token]);

  const download = useDownload(token, openPaywall, toast, lang, {
    loginNeeded: lang === "ar" ? "سجّل الدخول لتحميل الملفات والتقارير" : "Log in to download files and reports",
    payNeeded: lang === "ar" ? "يتطلب تحميل التقارير سداد الاشتراك" : "Subscription required to download reports",
  });

  const DownloadBtn = ({ url, filename }: { url: string | null; filename: string }) =>
    url ? (
      <button type="button" className="btn small save supp-dl-btn" onClick={() => download(url, filename)}>
        ⬇ {T.downloadBtn[lang]}
      </button>
    ) : null;

  // resolved artifact URLs — null when the kind is not available right now
  const a0 = analyses[0];
  const aid = a0?.id ?? null;
  const newestLabel = a0?.name ?? "";
  const urls = {
    report: avail?.can_download && aid ? `/api/analyses/${aid}/report?lang=${lang}` : null,
    pptx: avail?.can_download && aid ? `/api/analyses/${aid}/pptx?lang=${lang}` : null,
    excel: avail?.can_download && aid ? `/api/analyses/${aid}/export?lang=${lang}` : null,
    bi: avail?.can_download && aid ? `/api/analyses/${aid}/bi-pack?lang=${lang}` : null,
    // the newest comparison needs two analyses; numbers come from the server
    compare:
      avail?.can_download && (avail?.comparison_pdf ?? 0) > 0 && analyses.length >= 2
        ? `/api/compare/${analyses[1].id}/${analyses[0].id}/report?lang=${lang}`
        : null,
    invoices: avail?.can_download ? "navigate-payments" : null,
  };

  return (
    <div className="support-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <header className="supp-head">
        <div>
          <h2>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
              <circle cx="12" cy="7" r="3" stroke="currentColor" strokeWidth="1.8" />
              <path d="M12 13a8 8 0 0 1 8 10H4a8 8 0 0 1 8-10Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            {T.headTitle[lang]}
          </h2>
          <p>{T.headSub[lang]}</p>
        </div>
        <span className="supp-plan-badge">
          {avail?.paid
            ? `${lang === "ar" ? "الباقة" : "Plan"}: ${PLANS_AR[user?.plan ?? ""] ?? user?.plan ?? "PRO"}`
            : lang === "ar" ? "النسخة المجانية" : "Free edition"}
        </span>
      </header>

      {loadFail && <div className="error-box">{T.error[lang]}</div>}

      <section className="panel">
        <h3 className="supp-card-title">{T.guideCard[lang]}</h3>
        <ol className="supp-guide">
          {guide.map((s, i) => (
            <li key={i}>
              <strong>{s.title[lang]}</strong>
              <p>{s.body[lang]}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="panel">
        <h3 className="supp-card-title">{T.downloadsCard[lang]}</h3>

        {avail?.paid === false && (
          <div className="supp-lock">
            <span>🔒</span>
            <p>{T.lockedTitle[lang]}</p>
            <button type="button" className="btn small save" onClick={openPaywall}>
              {T.unlock[lang]}
            </button>
          </div>
        )}

        {avail?.paid && analyses.length === 0 && (
          <div className="supp-empty">{T.noAnalyses[lang]}</div>
        )}

        <div className="supp-grid">
          <div className="supp-item">
            <div className="supp-item-head">
              <span className="supp-item-name">{T.reports[lang]}</span>
              {avail?.report_pdf ? (
                <span className="supp-count">{avail.report_pdf} {T.items[lang]}</span>
              ) : (
                <span className="supp-locked-chip">🔒</span>
              )}
            </div>
            <p>{T.reportsSub[lang]}</p>
            <DownloadBtn url={urls.report} filename={`financial-report-${aid}.pdf`} />
            {avail?.can_download && analyses.length > 1 && (
              <details className="supp-pick">
                <summary>{T.pick[lang]}</summary>
                {analyses.map((a) => (
                  <button key={a.id} type="button" onClick={() => download(`/api/analyses/${a.id}/report?lang=${lang}`, `financial-report-${a.id}.pdf`)}>
                    {a.name}
                  </button>
                ))}
              </details>
            )}
          </div>

          <div className="supp-item">
            <div className="supp-item-head">
              <span className="supp-item-name">{T.pptx[lang]}</span>
              {avail?.pptx ? <span className="supp-count">{avail.pptx} {T.items[lang]}</span> : <span className="supp-locked-chip">🔒</span>}
            </div>
            <p>{T.pptxSub[lang]}</p>
            {urls.pptx && (
              <button type="button" className="btn small save supp-dl-btn" onClick={() => download(urls.pptx!, `financial-deck-${aid}.pptx`)}>
                ⬇ {T.downloadLatest[lang]}{newestLabel ? ` — ${newestLabel}` : ""}
              </button>
            )}
          </div>

          <div className="supp-item">
            <div className="supp-item-head">
              <span className="supp-item-name">{T.excel[lang]}</span>
              {avail?.excel ? <span className="supp-count">{avail.excel} {T.items[lang]}</span> : <span className="supp-locked-chip">🔒</span>}
            </div>
            <p>{T.excelSub[lang]}</p>
            {urls.excel && (
              <button type="button" className="btn small save supp-dl-btn" onClick={() => download(urls.excel!, `analysis-${aid}-results.xlsx`)}>
                ⬇ {T.downloadLatest[lang]}
              </button>
            )}
          </div>

          <div className="supp-item">
            <div className="supp-item-head">
              <span className="supp-item-name">{T.bi[lang]}</span>
              {avail?.bi_pack ? <span className="supp-count">{avail.bi_pack} {T.items[lang]}</span> : <span className="supp-locked-chip">🔒</span>}
            </div>
            <p>{T.biSub[lang]}</p>
            {urls.bi && (
              <button type="button" className="btn small save supp-dl-btn" onClick={() => download(urls.bi!, `bi-pack-${aid}.zip`)}>
                ⬇ {T.downloadLatest[lang]}
              </button>
            )}
          </div>

          <div className="supp-item">
            <div className="supp-item-head">
              <span className="supp-item-name">{T.compare[lang]}</span>
              {(avail?.comparison_pdf ?? 0) > 0 ? <span className="supp-count">{avail!.comparison_pdf} {T.items[lang]}</span> : <span className="supp-locked-chip">🔒</span>}
            </div>
            <p>{T.compareSub[lang]}</p>
            {urls.compare && (
              <button type="button" className="btn small save supp-dl-btn" onClick={() => download(urls.compare!, `comparison-report-${analyses[1].id}-${analyses[0].id}.pdf`)}>
                ⬇ {T.downloadLatest[lang]}
              </button>
            )}
          </div>

          <div className="supp-item">
            <div className="supp-item-head">
              <span className="supp-item-name">{T.invoices[lang]}</span>
              {avail?.invoices ? <span className="supp-count" title={T.ready[lang]}>✓</span> : <span className="supp-locked-chip">🔒</span>}
            </div>
            <p>{T.invoicesSub[lang]}</p>
            {urls.invoices === "navigate-payments" && (
              <button type="button" className="btn small ghost supp-dl-btn" onClick={onOpenPayments}>
                {lang === "ar" ? "فتح سجل المدفوعات" : "Open payment history"}
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
