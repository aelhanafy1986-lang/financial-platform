import { useRef, useState } from "react";

/** Local dismissal of the quality-findings strip (per page visit). */
import { Glyph } from "./Glyph";
import type { Lang } from "./types";

/** «رفع القوائم المالية» — the dedicated upload page (reference-style):
 *  an active-file progress banner, the wide drop zone with the format
 *  legend, the scanned-OCR and Excel-scan support banners, and the
 *  supported-formats strip. The hidden <input type=file> drives the real
 *  upload flow; the page hosts it. */

/** File kind the user declares for the upload — drives the analysis route
 *  server-side (see Dashboard onUpload / /api/upload ``file_kind``). */
export type FileKind = "statements" | "trial_balance" | "sales";
/** Analysis mode for financial kinds: auto-detect or force a reading. */
export type AnalysisMode = "auto" | "force_trial_balance" | "financial_sheets";

const T = {
  title: { ar: "رفع القوائم المالية", en: "Financial statements upload" },
  subtitle: {
    ar: "ارفع قوائم المالية لبدء التحليل",
    en: "Upload financial statements to start the analysis",
  },
  dropTitle: { ar: "اسحب وأفلت القوائم المالية هنا", en: "Drop financial statements here" },
  or: { ar: "أو انقر لاختيار الملفات", en: "or click to select files" },
  kindLabel: { ar: "نوع الملف:", en: "File type:" },
  modeLabel: { ar: "آلية التحليل:", en: "Analysis mode:" },
  kStatements: { ar: "قوائم مالية", en: "Financial statements" },
  kTrial: { ar: "ميزان مراجعة", en: "Trial balance" },
  kSales: { ar: "مبيعات", en: "Sales" },
  mAuto: { ar: "كشف تلقائي", en: "Auto-detect" },
  mAutoHint: {
    ar: "يتعرف على شكل البيانات ويختار مسار التحليل المناسب",
    en: "Detects the data shape and picks the analysis route",
  },
  mFinancial: { ar: "تفسير مالي (أعمدة مفاهيم مالية)", en: "Financial reading (financial concepts)" },
  mFinancialHint: {
    ar: "يعامل كل ورقة كقوائم مالية رغم التشابه الشكلي مع مبيعات",
    en: "Treats every sheet as financial statements even if sales-like",
  },
  mTb: { ar: "تفسير ميزان مراجعة (مدين/دائن)", en: "Trial-balance reading (debit/credit)" },
  mTbHint: {
    ar: "يقرأ الأعمدة على أساس ميزان المراجعة ويبني القوائم الثلاث",
    en: "Reads columns as debit/credit and builds the three statements",
  },
  routeLabel: { ar: "المسار الذي سيُتّبع:", en: "Analysis route:" },
  rSalesDash: { ar: "🛒 داشبورد المبيعات (مناطق · مناديب · نمو شهري)", en: "🛒 Sales dashboard (regions · reps · monthly growth)" },
  rStatements: { ar: "📑 تحليل مالي كامل + القوائم الثلاث", en: "📑 Full financial analysis + the three statements" },
  rTbBuild: { ar: "⚖️ بناء القوائم الثلاث من ميزان المراجعة", en: "⚖️ Build the three statements from the trial balance" },
  rForcedFin: { ar: "📑 قراءة مالية قسرية — كاشف المبيعات مطفأ", en: "📑 Forced financial reading — sales detector off" },
  rForcedTb: { ar: "⚖️ قراءة مدين/دائن قسرية لكل ورقة", en: "⚖️ Forced debit/credit reading on every sheet" },
  fExcel: { ar: "Excel/CSV", en: "Excel/CSV" },
  fImage: { ar: "صور", en: "Images" },
  fWord: { ar: "Word", en: "Word" },
  fPdf: { ar: "PDF", en: "PDF" },
  ocrTitle: { ar: "OCR — دعم المستندات الممسوحة ضوئيًا", en: "OCR — scanned-document support" },
  ocrHint: {
    ar: "تُقرأ ملفات PDF الممسوحة ضوئيًا تلقائيًا باستخدام تقنية التعرف البصري على الحروف",
    en: "Scanned PDFs are indexed automatically with optical character recognition",
  },
  excelTitle: { ar: "Excel — دعم ميزان المراجعة", en: "Excel — trial-balance support" },
  excelHint: {
    ar: "ارفع ملف Excel يحتوي على ميزان المراجعة وسيقوم النظام تلقائيًا بإنشاء القوائم المالية الثلاثة (قائمة الدخل، الميزانية العمومية، التدفقات النقدية)",
    en: "A trial balance converts into statements automatically",
  },
  activeTitle: { ar: "الملفات المستخدمة", en: "Active files" },
  warnings: { ar: "تحذيرات الجودة في الملفات التي تم رفعها", en: "Quality findings from uploaded files" },
  clearWarn: { ar: "تجاهل التحذير", en: "Dismiss" },
  formats: { ar: "الصيغ المدعومة", en: "Supported formats" },
  pdfFmt: { ar: "ميزانيات وتقارير دفترية", en: "Textual & scanned reports" },
  wordFmt: { ar: "تقارير نصية بصيغة DOCX", en: "Textual DOCX reports" },
  imgFmt: { ar: "PNG/JPEG — ممسوحة ضوئيًا", en: "PNG/JPEG — scanned images" },
  excelFmt: { ar: "XLSX/XLS/CSV + ميزان المراجعة", en: "XLSX/XLS/CSV + trial balance" },
  globeFmt: { ar: "English · Français · العربية", en: "English · Français · العربية" },
};

export function UploadPage({
  lang,
  onFilesPicked,
  uploading = false,
  upProgress = null,
  elapsedSec = 0,
  progressPct = 0,
  fileKind = "statements",
  onFileKindChange,
  analysisMode = "auto",
  onAnalysisModeChange,
}: {
  lang: Lang;
  onFilesPicked: (files: FileList | null) => void;
  /** May read the chosen kind/mode: set via the optional setter below. */
  uploading?: boolean;
  upProgress?: {
    stage: string; page: number; total: number;
    done: number; fileTotal: number; file: string;
  } | null;
  elapsedSec?: number;
  progressPct?: number;
  fileKind?: FileKind;
  onFileKindChange?: (k: FileKind) => void;
  analysisMode?: AnalysisMode;
  onAnalysisModeChange?: (m: AnalysisMode) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [warnHidden, setWarnHidden] = useState(false);

  return (
    <div className="upload-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <header className="upg-head">
        <h2>{T.title[lang]}</h2>
        <p>{T.subtitle[lang]}</p>
      </header>

      {/* ===== route preview — what the current buttons will do ========= */}
      <div className="upg-route" role="status">
        <span className="upg-route-label">{T.routeLabel[lang]}</span>
        <span className={`upg-route-pill${fileKind === "sales" ? " is-sales" : ""}`}>
          {fileKind === "sales"
            ? T.rSalesDash[lang]
            : fileKind === "trial_balance"
              ? (analysisMode === "force_trial_balance"
                ? T.rForcedTb[lang]
                : T.rTbBuild[lang])
              : (analysisMode === "force_trial_balance"
                ? T.rForcedTb[lang]
                : analysisMode === "financial_sheets"
                  ? T.rForcedFin[lang]
                  : T.rStatements[lang])}
        </span>
      </div>

      {/* ===== file-kind buttons + analysis-mode picker ================== */}
      <div className="upg-kinds">
        <div className="upg-kind-group">
          <span className="upg-kind-label">{T.kindLabel[lang]}</span>
          <div className="upg-kind-btns" role="radiogroup" aria-label={T.kindLabel[lang]}>
            {([
              ["statements", "📑", T.kStatements[lang]],
              ["trial_balance", "⚖️", T.kTrial[lang]],
              ["sales", "🛒", T.kSales[lang]],
            ] as const).map(([k, ic, label]) => (
              <button
                key={k}
                role="radio"
                aria-checked={fileKind === k}
                className={`upg-kind-btn${fileKind === k ? " active" : ""}`}
                onClick={() => onFileKindChange?.(k)}
              >
                <span className="upg-kind-ic">{ic}</span>
                {label}
              </button>
            ))}
          </div>
        </div>
        {fileKind !== "sales" && (
          <div className="upg-kind-group">
            <span className="upg-kind-label">{T.modeLabel[lang]}</span>
            <div className="upg-kind-btns" role="radiogroup" aria-label={T.modeLabel[lang]}>
              {([
                ["auto", T.mAuto[lang], T.mAutoHint[lang]],
                ["force_trial_balance", T.mTb[lang], T.mTbHint[lang]],
                ["financial_sheets", T.mFinancial[lang], T.mFinancialHint[lang]],
              ] as const).map(([m, label, hint]) => (
                <button
                  key={m}
                  role="radio"
                  aria-checked={analysisMode === m}
                  title={hint}
                  className={`upg-kind-btn slim${analysisMode === m ? " active" : ""}`}
                  onClick={() => onAnalysisModeChange?.(m)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* live analysis progress banner — replaces the drop zone's idle copy
          while the upload request is in flight (OCR page ticks / creep) */}
      {uploading && (
        <div className="upg-live" role="status" aria-live="polite">
          <div className="up-progress-head">
            <span>
              {lang === "ar"
                ? upProgress?.stage === "ocr" && (upProgress?.total ?? 0) > 0
                  ? `جارٍ قراءة الملف الممسوح ضوئيًا بالـ OCR… صفحة ${upProgress?.page} من ${upProgress?.total}`
                  : (upProgress?.fileTotal ?? 0) > 1
                    ? `جارٍ تحليل الملفات… (${upProgress?.done ?? 0} من ${upProgress?.fileTotal ?? 0})`
                    : "جارٍ قراءة وتحليل الملف…"
                : upProgress?.stage === "ocr" && (upProgress?.total ?? 0) > 0
                  ? `OCR reading scanned file… page ${upProgress?.page} of ${upProgress?.total}`
                  : (upProgress?.fileTotal ?? 0) > 1
                    ? `Analysing files… (${upProgress?.done ?? 0} of ${upProgress?.fileTotal ?? 0})`
                    : "Reading & analysing file…"}
            </span>
            <span className="up-progress-sec">{elapsedSec}s</span>
          </div>
          <div className="up-progress-bar">
            <div
              className="up-progress-fill"
              style={{ width: `${Math.min(95, progressPct)}%` }}
            />
          </div>
          {upProgress?.file && (
            <small className="up-progress-file">{upProgress.file}</small>
          )}
        </div>
      )}

      {/* drop zone */}
      <div
        className={`upg-drop${dragOver ? " over" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onFilesPicked(e.dataTransfer.files);
        }}
      >
        <span className="upg-drop-icon">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
            <path d="M12 16V5m0 0 4 4m-4-4L8 9M5 19h14" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <strong>{T.dropTitle[lang]}</strong>
        <small>{T.or[lang]}</small>
        <div className="upg-legend">
          <span>{T.fExcel[lang]}</span>
          <span>{T.fImage[lang]}</span>
          <span>{T.fWord[lang]}</span>
          <span>{T.fPdf[lang]}</span>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".xlsx,.xlsm,.csv,.docx,.pdf,.png,.jpg,.jpeg"
          style={{ display: "none" }}
          onChange={(e) => onFilesPicked(e.target.files)}
        />
      </div>

      {/* support banners */}
      <div className="upg-banner amber">
        <strong>{T.ocrTitle[lang]}</strong>
        <small>{T.ocrHint[lang]}</small>
      </div>
      <div className="upg-banner gray">
        <strong>{T.excelTitle[lang]}</strong>
        <small>{T.excelHint[lang]}</small>
      </div>

      {/* supported formats */}
      <section className="upg-formats">
        <h3>{T.formats[lang]}</h3>
        <div className="upg-fmt-grid">
          <div className="upg-fmt">
            <span className="upg-fmt-tag">OCR</span>
            <strong>{T.fPdf[lang]}</strong>
            <small>{T.pdfFmt[lang]}</small>
          </div>
          <div className="upg-fmt">
            <strong>{T.fWord[lang]}</strong>
            <small>{T.wordFmt[lang]}</small>
          </div>
          <div className="upg-fmt">
            <span className="upg-fmt-tag">OCR</span>
            <strong>{T.fImage[lang]}</strong>
            <small>{T.imgFmt[lang]}</small>
          </div>
          <div className="upg-fmt">
            <strong>{T.fExcel[lang]}</strong>
            <small>{T.excelFmt[lang]}</small>
          </div>
          <div className="upg-fmt">
            <span className="upg-fmt-dot">🌐</span>
            <strong>{lang === "ar" ? "متعدد اللغات" : "Multilingual"}</strong>
            <small>{T.globeFmt[lang]}</small>
          </div>
        </div>
      </section>

      {/* live upload progress banner (driven by the main Dashboard state) */}
      {/* handled in Dashboard above the page when uploading; card area here
          mirrors the reference «الملفات المستخدمة» strip */}
      {!warnHidden && (
        <section className="upg-strip">
          <h3>{T.activeTitle[lang]}</h3>
          <div className="upg-strip-body">
            <span className="upg-strip-warn">
              <Glyph name="warning" size={11} />
              {T.warnings[lang]}
            </span>
            <button className="upg-dismiss" title={T.clearWarn[lang]} onClick={() => setWarnHidden(true)}>
              <Glyph name="cross" size={12} />
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
