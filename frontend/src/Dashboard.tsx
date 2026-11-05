import { useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Compare, { type ComparePayload } from "./Compare";
import GroupCompare, { type GroupComparePayload } from "./GroupCompare";
import Stats, { type StatsPayload } from "./Stats";
import Advisor, { StatementsPanel } from "./Advisor";
import type { Statements } from "./Advisor";
import { FinancialScore } from "./FinancialScore";
import { ExecBrief } from "./ExecBrief";
import { SalesAnalysisPanel } from "./SalesAnalysis";
import { RatioInsights } from "./RatioInsights";
import { useDownload } from "./useDownload";
import ReportTemplates from "./ReportTemplates";
import PaymentsPage from "./PaymentsPage";
import AssistantPage from "./AssistantPage";
import SupportCenter from "./SupportCenter";
import { AnalyticsDashboard } from "./AnalyticsDashboard";
import { Glyph } from "./Glyph";
import { BenchmarkAlignment } from "./BenchmarkAlignment";
import { YearlyComparisonTable } from "./YearlyComparison";
import { GrowthStrip } from "./GrowthStrip";
import ConceptReview from "./ConceptReview";
import { ReportHeader, type ReportHeaderData } from "./ReportHeader";
import { SectionNav } from "./SectionNav";
import { AdminPanel } from "./AdminPanel";
import { HomeOverview } from "./HomeOverview";
import { SideRail } from "./SideRail";
import { RecordsPage } from "./RecordsPage";
import { ComparePickerPage } from "./ComparePickerPage";
import { UploadPage, type FileKind, type AnalysisMode } from "./UploadPage";
import { AuthContext, useToast } from "./App";
import type {
  AnalysisFull,
  AnalysisResult,
  ForecastItem,
  HistoryFilter,
  Labels,
  Lang,
  Projection,
} from "./types";

const COLORS = ["#0f766e", "#f59e0b", "#6366f1", "#ef4444", "#10b981", "#3b82f6"];

/* History quick-filter predicates: an analysis is FLAGGED when its stored
   audit carries any error/warning finding, and CLEAN when the gate ran and
   found nothing (the same condition driving the green «مدقق» badge). */
const _auditFindings = (i: AnalysisFull) =>
  (i.result?.audit?.errors?.length ?? 0) + (i.result?.audit?.warnings?.length ?? 0) > 0;
const _auditClean = (i: AnalysisFull) => !!i.result?.audit && !_auditFindings(i);

const CMP = {
  mode_compare: { ar: "وضع المقارنة", en: "Compare mode" },
  base_pick: { ar: "المرجع", en: "Baseline" },
  target_pick: { ar: "المقارن", en: "Comparison" },
  compare_btn: { ar: "قارن ⇄", en: "Compare ⇄" },
  group_btn: { ar: "مقارنة مجموعة", en: "Group compare" },
  group_pick: { ar: "حدد شركات متعددة (نقر = اختيار/إلغاء)", en: "Select multiple companies (click to toggle)" },
  group_run: { ar: "قارن المجموعة", en: "Compare group" },
  exit_compare: { ar: "إنهاء المقارنة", en: "Exit compare" },
  pick_two: {
    ar: "اختر تحليلين مختلفين ثم اضغط قارن",
    en: "Pick two different analyses, then press Compare",
  },
};

const MODES = {
  hint_analysis: {
    ar: "ارفع ملفاً مالياً — تُحلَّل بياناته وتُعدّ القوائم المالية منها تلقائياً عند توافر البيانات",
    en: "Upload a financial file — its data is analysed and, when available, the financial statements are built from it",
  },
};

const SITE = {
  stats_link: { ar: "🌐 صفحة إحصاءات الموقع", en: "🌐 Site statistics page" },
};

function fmtNum(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface Props {
  lang: Lang;
  t: Labels;
}

const VALUE_LABELS = {
  values: { ar: "القيم (من الأقدم إلى الأحدث)", en: "Values (oldest to latest)" },
  add_value: { ar: "＋ قيمة", en: "＋ value" },
  reset: { ar: "استعادة القيم الأصلية", en: "Restore original values" },
  save_values: { ar: "حفظ وإعادة الحساب", en: "Save & recompute" },
  edited: {
    ar: "قيم معدّلة يدوياً — النسب والتنبؤات أعيد حسابها",
    en: "Manually edited values — ratios & forecast recomputed",
  },
  edit_hint: {
    ar: "عدّل القيم المستخرجة ثم احفظ لإعادة حساب النسب والتنبؤات",
    en: "Edit the extracted values, then save to recompute ratios & forecast",
  },
  stats_btn: { ar: "📈 الإحصاءات العامة", en: "📈 Statistics" },
  stats_admin_only: {
    ar: "الإحصاءات العامة متاحة للمدير فقط",
    en: "Statistics are admin-only",
  },
  stats_hide: { ar: "إخفاء الإحصاءات", en: "Hide statistics" },
  pptx: { ar: "📥 عرض تقديمي", en: "📥 PowerPoint" },
  reanalyze: { ar: "🔄 إعادة التحليل", en: "🔄 Re-analyze" },
  reanalyzed: { ar: "✅ تمت إعادة التحليل بأحدث محرّك استخراج", en: "✅ Re-analyzed with the latest extraction engine" },
  reanalyzing: { ar: "جارٍ إعادة التحليل…", en: "Re-analyzing…" },
  payNeeded: {
    ar: "يتطلب تحميل التقارير سداد الاشتراك",
    en: "Subscription required to download reports",
  },
  loginNeeded: {
    ar: "سجّل الدخول لتحميل الملفات والتقارير",
    en: "Log in to download files and reports",
  },
};

const TOASTS = {
  name_saved: { ar: "تم حفظ اسم التحليل", en: "Analysis name saved" },
  notes_saved: { ar: "تم حفظ الملاحظات", en: "Notes saved" },
  values_saved: {
    ar: "تم حفظ القيم وإعادة الحساب",
    en: "Values saved & recomputed",
  },
  values_reset: {
    ar: "استُعيدت القيم الأصلية",
    en: "Original values restored",
  },
  uploaded: { ar: "تم رفع الملف وتحليله", en: "File uploaded & analysed" },
  uploaded_multi: {
    ar: "تم رفع وتحليل {n} ملفات",
    en: "Uploaded & analysed {n} files",
  },
  uploaded_partial: {
    ar: "تم رفع {n} ملفات مع أخطاء في البعض — راجع الرسالة",
    en: "Uploaded {n} files with some errors — see the message",
  },
  demo_added: { ar: "أُضيفت البيانات التجريبية", en: "Demo data added" },
  deleted: { ar: "تم حذف التحليل", en: "Analysis deleted" },
  compared: { ar: "تمت المقارنة بنجاح", en: "Comparison ready" },
};

const CONCEPT_NAMES: Record<string, { ar: string; en: string }> = {
  gross_profit: { ar: "الربح الإجمالي", en: "Gross Profit" },
  cogs: { ar: "تكلفة المبيعات", en: "Cost of Sales" },
  liabilities: { ar: "الالتزامات", en: "Liabilities" },
  equity: { ar: "حقوق الملكية", en: "Equity" },
  opex: { ar: "المصاريف التشغيلية", en: "Operating Expenses" },
};

/** One merged forecast paragraph (user request 2026-10-12): the section
 *  heading carries the direction list (result.forecast) AND the projected
 *  values table (the advice payload). The Advisor's separate «التنبؤ
 *  بالمستقبل» panel was merged in here so the report shows ONE forecast
 *  section, not two near-identical ones. */
const FC_T = {
  item: { ar: "البند", en: "Item" },
  current: { ar: "الحالي", en: "Current" },
  projected: { ar: "المتوقع", en: "Projected" },
  change: { ar: "التغير", en: "Change" },
};

function ForecastSection({
  analysisId, lang, forecast, advLabel, upLabel, downLabel, flatLabel,
}: {
  analysisId: number;
  lang: Lang;
  forecast: ForecastItem[];
  advLabel: string;
  upLabel: string; downLabel: string; flatLabel: string;
}) {
  const [projections, setProjections] = useState<Projection[]>([]);
  const hasTrends = forecast.length > 0;
  const [tab, setTab] = useState<"trends" | "values">(
    hasTrends ? "trends" : "values"
  );

  useEffect(() => {
    let live = true;
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: { projections?: Projection[] }) => {
        if (live && d?.projections) setProjections(d.projections);
      })
      .catch(() => {});
    return () => { live = false; };
  }, [analysisId, lang]);

  if (!hasTrends && projections.length === 0) return null;

  return (
    <section className="panel" id="sec-forecast">
      <h3>{advLabel}</h3>
      {(hasTrends && projections.length > 0) && (
        <div className="forecast-tabs">
          <button className={`forecast-tab${tab === "trends" ? " active" : ""}`} onClick={() => setTab("trends")}>
            {lang === "ar" ? "الاتجاه" : "Trends"}
          </button>
          <button className={`forecast-tab${tab === "values" ? " active" : ""}`} onClick={() => setTab("values")}>
            {lang === "ar" ? "القيم المتوقعة" : "Projected values"}
          </button>
        </div>
      )}
      {tab === "trends" && hasTrends && (
        <ul className="forecast-list">
          {forecast.map((f) => (
            <li key={f.concept}>
              <span>{f[lang]}</span>
              <span className={`trend ${f.trend}`}>
                {f.change_pct > 0 ? "+" : ""}
                {f.change_pct}% ·{" "}
                {f.trend === "up" ? upLabel : f.trend === "down" ? downLabel : flatLabel}
              </span>
            </li>
          ))}
        </ul>
      )}
      {tab === "values" && projections.length > 0 && (
        <table className="cmp-table">
          <thead>
            <tr>
              <th>{FC_T.item[lang]}</th>
              <th>{FC_T.current[lang]}</th>
              <th>{FC_T.projected[lang]}</th>
              <th>{FC_T.change[lang]}</th>
            </tr>
          </thead>
          <tbody>
            {projections.map((p) => {
              const last = p.projections[p.projections.length - 1];
              return (
                <tr key={p.concept}>
                  <td>{lang === "ar" ? p.ar : p.en}</td>
                  <td className="num">{fmtNum(p.values[p.values.length - 1])}</td>
                  <td className="num">
                    {p.projections.map((x) => fmtNum(x.value)).join(" → ")}
                  </td>
                  <td className={`num ${p.trend}`}>
                    {last && last.change_pct > 0 ? "+" : ""}
                    {last?.change_pct}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ValuesEditor({
  result,
  lang,
  saving,
  onSave,
  onReset,
}: {
  result: AnalysisResult;
  lang: Lang;
  saving: boolean;
  onSave: (values: Record<string, number[]>) => void;
  onReset: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, number[]>>({});

  useEffect(() => {
    setDraft(JSON.parse(JSON.stringify(result.metrics ?? {})));
    // Re-seed the draft whenever the analysis being edited changes.
  }, [result]);

  const setValue = (concept: string, idx: number, raw: string) => {
    setDraft((prev) => {
      const arr = [...(prev[concept] ?? [])];
      const num = Number(raw.replace(/,/g, ""));
      arr[idx] = raw.trim() === "" || Number.isNaN(num) ? NaN : num;
      return { ...prev, [concept]: arr };
    });
  };

  const addValue = (concept: string) => {
    setDraft((prev) => {
      const arr = [...(prev[concept] ?? [])];
      const last = [...arr].reverse().find((v) => !Number.isNaN(v));
      arr.push(typeof last === "number" ? last : 0);
      return { ...prev, [concept]: arr };
    });
  };

  const removeValue = (concept: string, idx: number) => {
    setDraft((prev) => ({
      ...prev,
      [concept]: (prev[concept] ?? []).filter((_, i) => i !== idx),
    }));
  };

  const concepts = Object.keys(result.metrics ?? {});
  const hasEdits =
    JSON.stringify(draft) !== JSON.stringify(result.metrics ?? {});
  const valid = concepts.every((c) =>
    (draft[c] ?? []).every((v) => !Number.isNaN(v) && typeof v === "number")
  ) && concepts.every((c) => (draft[c] ?? []).length >= 1);

  return (
    <section className="panel values-editor">
      <div className="notes-head">
        <h3>✏️ {VALUE_LABELS.values[lang]}</h3>
      </div>
      <p className="values-hint">{VALUE_LABELS.edit_hint[lang]}</p>
      {concepts.map((concept) => {
        const meta =
          result.kpis[concept] ?? result.series[concept] ?? CONCEPT_NAMES[concept];
        const name = meta ? meta[lang] : concept;
        return (
          <div className="value-row" key={concept}>
            <span className="value-concept">{name}</span>
            <div className="value-cells">
              {(draft[concept] ?? []).map((v, idx) => (
                <span className="value-cell" key={idx}>
                  <input
                    value={Number.isNaN(v) ? "" : String(v)}
                    onChange={(e) => setValue(concept, idx, e.target.value)}
                    inputMode="decimal"
                    className={Number.isNaN(v) ? "bad" : ""}
                  />
                  <button
                    className="value-del"
                    title={lang === "ar" ? "حذف" : "Remove"}
                    disabled={(draft[concept] ?? []).length <= 1}
                    onClick={() => removeValue(concept, idx)}
                  >
                    <Glyph name="cross" size={10} />
                  </button>
                </span>
              ))}
              <button className="btn small ghost" onClick={() => addValue(concept)}>
                {VALUE_LABELS.add_value[lang]}
              </button>
            </div>
          </div>
        );
      })}
      <div className="notes-actions">
        <button
          className="btn small save"
          disabled={!valid || !hasEdits || saving}
          onClick={() =>
            onSave(
              Object.fromEntries(
                Object.entries(draft).map(([c, arr]) => [c, arr.filter((v) => !Number.isNaN(v))])
              )
            )
          }
        >
          {VALUE_LABELS.save_values[lang]}
        </button>
        <button className="btn small ghost" onClick={onReset}>
          ↺ {VALUE_LABELS.reset[lang]}
        </button>
      </div>
    </section>
  );
}

export default function Dashboard({ lang, t }: Props) {
  const toast = useToast();
  const { token, openPaywall, user } = useContext(AuthContext);
  const [items, setItems] = useState<AnalysisFull[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  // set when a quality-badge click asks to open the «فحوصات الجودة» block
  // of that analysis and highlight the violating checks — a TOKEN (not a
  // boolean) so every click re-triggers the focus, even on the same analysis
  const [qualityFocus, setQualityFocus] = useState<{ id: number; token: number } | null>(null);
  const [uploading, setUploading] = useState(false);
  /* upload-screen analysis routing: the declared file kind (financial
     statements / trial balance / sales) and the analysis reading mode */
  const [fileKind, setFileKind] = useState<FileKind>("statements");
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("auto");
  // Live OCR/parse progress card state (polled from the backend while the
  // upload request is in flight) — replaces the frozen «...» during slow
  // OCR reads of scanned files.
  const [upProgress, setUpProgress] = useState<{
    stage: string; page: number; total: number;
    done: number; fileTotal: number; file: string;
  } | null>(null);
  // stops the 1-second progress poll (set by onUpload, cleared in finally)
  const pollRef = useRef<(() => void) | null>(null);
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 402 (quota exhausted) keeps a dedicated banner so the fix is one click:
  // the message explains the free allowance and opens the paywall directly.
  const [quotaHit, setQuotaHit] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [cmpBase, setCmpBase] = useState<number | null>(null);
  const [cmpTarget, setCmpTarget] = useState<number | null>(null);
  const [cmpPayload, setCmpPayload] = useState<ComparePayload | null>(null);
  const [cmpError, setCmpError] = useState<string | null>(null);
  // multi-company group compare: ids picked from the history checkboxes
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [groupPayload, setGroupPayload] = useState<GroupComparePayload | null>(null);

  // Inline editing of the analysis name (display_name).
  const [editName, setEditName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);
  // Inline editing of the notes textarea.
  const [editNotes, setEditNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  // Manual editing of extracted values (KPIs + series).
  const [editingValues, setEditingValues] = useState(false);
  const [savingValues, setSavingValues] = useState(false);
  // Statements for the selected analysis (fetched + refreshed after TB upload).
  const [stmts, setStmts] = useState<Statements | null>(null);
  const [hasStmts, setHasStmts] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  // main-pane view switch: "overview" | "records" | "compare" | "upload"
  const [view, setView] = useState<
    "overview" | "records" | "compare" | "upload" | "templates" | "payments" | "assist" | "support"
  >("overview");
  // Analysis view toggle: dashboard+recommendations+forecast shown/hidden.
  const [showAnalysis, setShowAnalysis] = useState(true);
  const [reanalyzing, setReanalyzing] = useState(false);
  // Concept-review gate: set right after an upload whose analysis carries
  // unclassified/OCR-mangled concepts (or was OCR-read at all) — the user
  // fixes them BEFORE accepting the analysis; every fix recomputes ratios.
  const [reviewGateId, setReviewGateId] = useState<number | null>(null);
  // Green «مدقق» badges on clean analyses — hideable to reduce visual noise
  // (persisted; shown by default).
  const [showVerified, setShowVerified] = useState(
    () => localStorage.getItem("hideVerified") !== "1"
  );
  const toggleVerified = () => {
    setShowVerified((v) => {
      localStorage.setItem("hideVerified", v ? "1" : "0");
      return !v;
    });
  };
  // Quick history filter: all / with quality findings / clean-only
  // (persisted; "all" is the default).
  const [historyFilter, setHistoryFilter] = useState<HistoryFilter>(
    () => (localStorage.getItem("historyFilter") as HistoryFilter) || "all"
  );
  const setHistoryFilterPersist = (f: HistoryFilter) => {
    setHistoryFilter(f);
    localStorage.setItem("historyFilter", f);
  };

  const download = useDownload(token, openPaywall, toast, lang, {
    loginNeeded: VALUE_LABELS.loginNeeded[lang],
    payNeeded: VALUE_LABELS.payNeeded[lang],
  });

  const load = async () => {
    try {
      const res = await fetch("/api/analyses");
      const metas = await res.json();
      const full = (
        await Promise.all(
          metas.map(async (m: { id: number }) => {
            const r = await fetch(`/api/analyses/${m.id}`);
            // 404 = deleted in another tab/window since the list was read —
            // drop the stale entry instead of rendering a broken row.
            if (!r.ok) return null;
            return r.json();
          })
        )
      ).filter(Boolean);
      full.sort((a: AnalysisFull, b: AnalysisFull) => b.id - a.id);
      setItems(full);
      // Landing = «النظرة العامة» (post-login home) — no analysis is
      // auto-opened; the user picks from the history or the quick actions.
    } catch {
      setError("connection error");
    }
  };

  useEffect(() => {
    load();
    // Count one site visit for the public stats page (once per browser).
    if (!sessionStorage.getItem("visited")) {
      sessionStorage.setItem("visited", "1");
      fetch("/api/visit", { method: "POST" }).catch(() => {});
    }
  }, []);

  // Refresh the history when the tab regains focus so deletions made in
  // another window/tab surface automatically (stale 404 rows are dropped).
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    const onFocus = () => loadRef.current();
    const onVisibility = () => {
      if (!document.hidden) loadRef.current();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  // Elegant recovery when the selected analysis vanishes (404 from another
  // window): tell the user, then fall back to the newest remaining analysis.
  useEffect(() => {
    if (items === null || selected === null) return;
    if (items.some((i) => i.id === selected)) return;
    toast(
      lang === "ar"
        ? "🗑 تم حذف هذا التحليل من نافذة أخرى — تم تحديث السجل تلقائيًا"
        : "🗑 This analysis was deleted in another window — the list was refreshed"
    );
    setSelected(items[0]?.id ?? null);
  }, [items, selected, lang, toast]);

  const current = useMemo(
    () => items?.find((i) => i.id === selected) ?? null,
    [items, selected]
  );

  // Concept review availability: unclassified OCR-mangled rows (or any
  // OCR-read file) keep the review panel reachable after the gate closes.
  const reviewItems = current?.result.concept_review?.items ?? [];
  const reviewWorthy = reviewItems.length > 0 || !!current?.result._ocr_used;

  // Elapsed seconds while uploading — the timer ticks every second so the
  // «جارٍ القراءة…» card visibly moves even between OCR page ticks.
  const [elapsedSec, setElapsedSec] = useState(0);
  useEffect(() => {
    if (!uploading) return;
    const startedAt = Date.now();
    setElapsedSec(0);
    const iv = window.setInterval(
      () => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)),
      1000,
    );
    return () => window.clearInterval(iv);
  }, [uploading]);

  // Bar percent: a real OCR page count (stage "ocr") drives it precisely;
  // otherwise it creeps gently with time so something always advances.
  const progressPct = upProgress
    ? upProgress.stage === "ocr" && upProgress.total > 0
      ? Math.min(95, 10 + Math.round((upProgress.page / upProgress.total) * 85))
      : Math.min(90, 10 + elapsedSec * 3)
    : 0;

  // Financial statements of the selected analysis (for the inline
  // statements section after the executive brief).
  const loadStatements = async (id: number) => {
    try {
      const res = await fetch(`/api/analyses/${id}/statements`);
      if (!res.ok) { setHasStmts(false); setStmts(null); return; }
      const body = await res.json();
      setHasStmts(!!body.has_statements);
      setStmts(body.statements ?? null);
    } catch {
      setHasStmts(false);
      setStmts(null);
    }
  };

  useEffect(() => {
    if (current) loadStatements(current.id);
    else { setHasStmts(false); setStmts(null); }
  }, [current?.id]);

  const onUpload = async (files: FileList | null) => {
    if (!files?.length) return;
    if (!token) {
      toast(VALUE_LABELS.loginNeeded[lang]);
      return;
    }
    setUploading(true);
    setError(null);
    setQuotaHit(false);
    // Live progress: the backend ticks a progress slot keyed by this id
    // (minted here) while the upload request itself is still in flight —
    // a 1-second poll keeps the sidebar moving during slow OCR reads.
    const jobId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    const stopPoll = (() => {
      let stopped = false;
      const tick = async () => {
        if (stopped) return;
        try {
          const r = await fetch(`/api/upload/progress/${jobId}`);
          if (r.ok) {
            const p = await r.json();
            if (p.done) {
              stopped = true;
              return;
            }
            setUpProgress({
              stage: String(p.stage || ""),
              page: p.page ?? 0,
              total: p.total ?? 0,
              done: p.files_done ?? 0,
              fileTotal: p.files_total ?? 0,
              file: String(p.file || ""),
            });
          }
          // 404 / transient failure: just try again next second
        } catch {
          /* network hiccup — retry next tick */
        }
        setTimeout(tick, 1000);
        return;
      };
      setTimeout(tick, 1000);
      return () => {
        stopped = true;
      }
    })();
    pollRef.current = stopPoll;
    try {
      const form = new FormData();
      let count = 0;
      for (const f of Array.from(files)) {
        form.append("files", f);
        count += 1;
      }
      // user-declared analysis routing from the upload screen buttons
      form.append("file_kind", fileKind);
      form.append("analysis_mode", analysisMode);
      const res = await fetch("/api/upload", {
        method: "POST",
        body: form,
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Upload-Job-Id": jobId,
        },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail || `upload failed (${res.status})`);
      }
      const uploaded = Array.isArray(body.uploaded) ? body.uploaded : [];
      const okItems = uploaded.filter((u: { id?: number }) => u.id);
      const badItems = uploaded.filter((u: { error?: string }) => u.error);
      const lastId = okItems.length ? okItems[okItems.length - 1].id : null;
      if (lastId) {
        setSelected(lastId);
        // leave the upload/records/compare page and land on the new analysis
        setView("overview");
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
      await load();
      // re-assert the selection after the refresh so the new analysis is
      // the one rendered the moment `items` lands (auto-transition)
      if (lastId) setSelected(lastId);
      // Concept-review gate: surface OCR-confused concepts for manual
      // correction BEFORE the analysis is accepted (ratios recompute on
      // every fix; the analysis itself is already usable).
      const gateRes = (
        uploaded.find(
          (u: { id?: number; result?: AnalysisResult }) => u.id === lastId
        ) as { result?: AnalysisResult } | undefined
      )?.result;
      if (
        gateRes &&
        ((gateRes.concept_review?.items?.length ?? 0) > 0 ||
          gateRes._ocr_used)
      ) {
        setReviewGateId(lastId);
      }
      if (badItems.length) {
        setError(
          badItems.map((b: { filename?: string; error?: string }) => `${b.filename}: ${b.error}`).join(" · ")
        );
        toast(
          (lang === "ar"
            ? TOASTS.uploaded_partial.ar
            : TOASTS.uploaded_partial.en
          ).replace("{n}", String(okItems.length))
        );
      } else {
        toast(
          (lang === "ar" ? TOASTS.uploaded_multi.ar : TOASTS.uploaded_multi.en).replace(
            "{n}",
            String(okItems.length || count)
          )
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // upload 402 → quota exhausted: needs an upgrade, not a retry
      setQuotaHit(msg.includes("حصة التحليل"));
      setError(msg);
    } finally {
      pollRef.current?.();
      setUploading(false);
      setUpProgress(null);
    }
  };

  const loadStats = async () => {
    if (!user?.is_admin) return; // stats are admin-only
    try {
      const res = await fetch("/api/stats", {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (res.ok) setStats(await res.json());
    } catch {
      /* stats are optional; ignore failures */
    }
  };

  useEffect(() => {
    loadStats();
  }, [items]);

  // Merge a freshly PATCHed analysis detail into the list state so the
  // dashboard re-renders with the recomputed ratios immediately.
  const mergeDetail = (detail: AnalysisFull) => {
    setItems((prev) =>
      (prev ?? []).map((i) => (i.id === detail.id ? { ...i, ...detail } : i))
    );
  };

  const onDelete = async (id: number) => {
    setBusyId(id);
    await fetch(`/api/analyses/${id}`, { method: "DELETE" });
    if (selected === id) setSelected(null);
    await load();
    setBusyId(null);
    toast(TOASTS.deleted[lang]);
  };

  const addDemo = async () => {
    const res = await fetch("/api/demo", { method: "POST" });
    const body = await res.json();
    await load();
    setSelected(body.id);
    toast(TOASTS.demo_added[lang]);
  };

  const runCompare = async () => {
    if (!cmpBase || !cmpTarget || cmpBase === cmpTarget) return;
    setCmpError(null);
    try {
      const res = await fetch(`/api/compare/${cmpBase}/${cmpTarget}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `compare failed (${res.status})`);
      }
      setCmpPayload(await res.json());
      setCmpBase(null);
      setCmpTarget(null);
      toast(TOASTS.compared[lang]);
    } catch (e) {
      setCmpError(e instanceof Error ? e.message : String(e));
    }
  };

  const exitCompare = () => {
    setCompareMode(false);
    setCmpPayload(null);
    setCmpError(null);
    setGroupIds([]);
    setGroupPayload(null);
    setView("overview");
  };

  const toggleGroupId = (id: number) =>
    setGroupIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const runGroupCompare = async () => {
    if (groupIds.length < 2) return;
    setCmpError(null);
    try {
      const res = await fetch(`/api/compare-group?ids=${groupIds.join(",")}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `compare failed (${res.status})`);
      }
      setGroupPayload(await res.json());
      toast(TOASTS.compared[lang]);
    } catch (e) {
      setCmpError(e instanceof Error ? e.message : String(e));
    }
  };

  const saveValues = async (values: Record<string, number[]>) => {
    if (!current) return;
    setSavingValues(true);
    try {
      const res = await fetch(`/api/analyses/${current.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          values: Object.fromEntries(
            Object.entries(values).map(([c, arr]) => [c, { values: arr }])
          ),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `save values failed (${res.status})`);
      }
      setEditingValues(false);
      await load();
      toast(TOASTS.values_saved[lang]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingValues(false);
    }
  };

  const resetValues = async () => {
    if (!current) return;
    try {
      const res = await fetch(`/api/analyses/${current.id}/values/reset`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `reset failed (${res.status})`);
      }
      setEditingValues(false);
      await load();
      toast(TOASTS.values_reset[lang]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const saveName = async () => {
    if (!current) return;
    setSavingName(true);
    try {
      const res = await fetch(`/api/analyses/${current.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: nameDraft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `rename failed (${res.status})`);
      }
      setEditName(false);
      await load();
      toast(TOASTS.name_saved[lang]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingName(false);
    }
  };

  const saveNotes = async () => {
    if (!current) return;
    setSavingNotes(true);
    try {
      const res = await fetch(`/api/analyses/${current.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: notesDraft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `notes update failed (${res.status})`);
      }
      setEditNotes(false);
      await load();
      toast(TOASTS.notes_saved[lang]);
    } catch (e) {
      setError(e instanceof Error ? e.message : `notes update failed`);
    } finally {
      setSavingNotes(false);
    }
  };

  if (items === null) {
    return (
      <div className="loading">{error ?? "..."}</div>
    );
  }

  // History quick-filter: counts per bucket + the visible slice.
  const flaggedCount = items.filter(_auditFindings).length;
  const cleanCount = items.filter(_auditClean).length;
  const visibleItems =
    historyFilter === "flagged"
      ? items.filter(_auditFindings)
      : historyFilter === "clean"
        ? items.filter(_auditClean)
        : items;
  const FILTER_LABELS: Record<HistoryFilter, string> = {
    all: lang === "ar" ? "الكل" : "All",
    flagged:
      lang === "ar" ? `بحذارات جودة (${flaggedCount})` : `Flagged (${flaggedCount})`,
    clean: lang === "ar" ? `سليمة (${cleanCount})` : `Healthy (${cleanCount})`,
  };

  const result = current?.result;
  const hasData = !!result && Object.keys(result.kpis).length > 0;
  const title = current?.display_name || current?.filename || "";
  const textsSample = (result as unknown as { texts_sample?: string[] } | undefined)?.texts_sample ?? [];
  const isDocument = !!result?.audit && result.audit.mode === "document";
  // sales-kind analyses carry their own panel instead of the financial report
  const salesAnalysis = result?.kind === "sales" ? (result.sales_analysis ?? null) : null;
  const canEditValues =
    !!current?.editable && !!result?.metrics && Object.keys(result.metrics).length > 0;

  // Report banner data: period inferred from the number of extracted values
  // (quarterly/annual), company = the analysis display name.
  // Liabilities is a balance-sheet stock split into current/non-current rows
  // (up to 2 values within ONE period), so it must not inflate the count.
  const nPeriods = current
    ? Math.max(
        ...Object.entries(result?.metrics ?? {})
          .filter(([k]) => k !== "liabilities")
          .map(([, v]) => v.length),
        0,
      )
    : 0;

  // Subscription badge for the report banner: actual plan of the signed-in
  // user (paid tier + billing cycle), not a hardcoded label.
  const bandLabel = (() => {
    const T = {
      band: { ar: "الاشتراك", en: "Subscription" },
      pro: { ar: "برو", en: "PRO" },
      free: { ar: "النسخة المجانية", en: "Free edition" },
      yearly: { ar: "سنوي", en: "Yearly" },
      monthly: { ar: "شهري", en: "Monthly" },
    };
    const l = (o: { ar: string; en: string }) => o[lang];
    if (user?.subscription !== "paid") return `${l(T.band)}: ${l(T.free)}`;
    const cycle = user?.plan === "yearly" ? l(T.yearly) : user?.plan === "monthly" ? l(T.monthly) : null;
    return cycle ? `${l(T.band)}: ${l(T.pro)} — ${cycle}` : `${l(T.band)}: ${l(T.pro)}`;
  })();

  const reportHeader: ReportHeaderData | null = current
    ? (() => {
        const n = nPeriods;
        const unspecified = lang === "ar" ? "غير محددة" : "Not specified";
        // Real period labels from the source tables (e.g. "2023 - 2024")
        // when the file declares them; otherwise fall back to counting.
        const labels = (current.result.period_labels ?? []).filter(
          (x) => typeof x === "string" && x.trim() !== ""
        );
        const period =
          labels.length >= 2
            ? labels.join(" - ")
            : n === 0
              ? unspecified
              : lang === "ar"
                ? n === 1 ? "فترة واحدة" : n === 2 ? "فترتان" : `${n} فترات`
                : n === 1 ? "Single period" : `${n} periods`;
        // Entity name: prefer the user-facing display name; strip the file
        // extension from raw filenames so it reads like a report, not a path.
        const rawName = current.display_name || current.filename || "";
        const entity = current.display_name
          ? rawName
          : rawName.replace(/\.(xlsx|xls|pdf|docx|pptx|csv)$/i, "");
        // Quality gate verdict (backend audit): verified / warnings / failed
        const audit = current.result.audit;
        const quality = audit
          ? {
              errors: audit.errors?.length ?? 0,
              warnings: audit.warnings?.length ?? 0,
              // user-facing REVIEW: codes/IDs (W3, C4, R2…) stripped out —
              // the badge tooltip carries the plain-language message only
              messages: [
                ...(audit.errors ?? []),
                ...(audit.warnings ?? []),
              ].map((i) => (lang === "ar" ? i.ar : i.en)),
            }
          : undefined;
        return {
          title,
          analysedAt: current.result.analysed_at,
          period,
          company: entity,
          band: bandLabel,
          quality,
        };
      })()
    : null;

  return (
    <div className="dashboard with-rail">
      {/* permanent side rail (reference-style) */}
      <SideRail
        lang={lang}
        onOverview={() => {
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
          setSelected(null);
          setView("overview");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onHistory={() => {
          setView("records");
          setSelected(null);
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
        }}
        onSample={() => {
          const first = items?.[0];
          if (first) setSelected(first.id);
        }}
        onCompare={() => {
          setSelected(null);
          setShowStats(false);
          setShowAdmin(false);
          setView("compare");
          setCompareMode(true);
          if (items && items.length >= 2 && cmpBase == null && cmpTarget == null) {
            setCmpBase(items[1]?.id ?? null);
            setCmpTarget(items[0]?.id ?? null);
          }
        }}
        onUpload={() => {
          setSelected(null);
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
          setView("upload");
        }}
        onStats={() => setShowStats((v) => !v)}
        onAdmin={() => setShowAdmin((v) => !v)}
        onTemplates={() => {
          setSelected(null);
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
          setView("templates");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onPayments={() => {
          setSelected(null);
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
          setView("payments");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onAssist={() => {
          setSelected(null);
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
          setView("assist");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onSupport={() => {
          setSelected(null);
          setCompareMode(false);
          setShowStats(false);
          setShowAdmin(false);
          setView("support");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        hasStats={user?.is_admin === true && (items?.length ?? 0) >= 2}
        isAdmin={user?.is_admin === true}
      />

      {/* Main panel */}
      <main className="main">
        {view === "records" && !current && !compareMode && (
          <RecordsPage
            items={items ?? []}
            lang={lang}
            busyId={busyId}
            onOpen={(id) => setSelected(id)}
            onPdf={(id) => {
              const isSales = (items ?? []).find((x) => x.id === id)?.result?.kind === "sales";
              if (isSales) {
                download(`/api/analyses/${id}/sales-report?lang=${lang}`, `sales-report-${id}.pdf`);
              } else {
                download(`/api/analyses/${id}/report?lang=${lang}`, `financial-report-${id}.pdf`);
              }
            }}
            onPptx={(id) =>
              // the /pptx endpoint itself branches: sales analyses serve
              // the sales deck from the same URL — only the filename hints
              download(`/api/analyses/${id}/pptx?lang=${lang}`, `report-${id}.pptx`)
            }
            onReanalyze={async (id) => {
              setBusyId(id);
              try {
                const res = await fetch(`/api/analyses/${id}/reanalyze`, {
                  method: "POST",
                  headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                });
                const body = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(body.detail || `error ${res.status}`);
                await load();
                toast(VALUE_LABELS.reanalyzed[lang]);
              } catch (e) {
                toast(e instanceof Error ? e.message : String(e));
              } finally {
                setBusyId(null);
              }
            }}
            onDelete={onDelete}
          />
        )}
        {!current && !compareMode && !showStats && !showAdmin && view === "upload" && (
          <UploadPage
            lang={lang}
            onFilesPicked={onUpload}
            uploading={uploading}
            upProgress={upProgress}
            elapsedSec={elapsedSec}
            progressPct={progressPct}
            fileKind={fileKind}
            onFileKindChange={setFileKind}
            analysisMode={analysisMode}
            onAnalysisModeChange={setAnalysisMode}
          />
        )}
        {!current && !compareMode && !showStats && !showAdmin && view === "templates" && (
          <ReportTemplates lang={lang} onUpgrade={openPaywall} />
        )}
        {!current && !compareMode && !showStats && !showAdmin && view === "payments" && (
          <PaymentsPage lang={lang} token={token ?? ""} onSeePlan={openPaywall} openPaywall={openPaywall} />
        )}
        {!current && !compareMode && !showStats && !showAdmin && view === "assist" && (
          <AssistantPage lang={lang} token={token ?? ""} />
        )}
        {!current && !compareMode && !showStats && !showAdmin && view === "support" && (
          <SupportCenter
            lang={lang}
            token={token ?? ""}
            openPaywall={openPaywall}
            onOpenPayments={() => {
              setView("payments");
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        )}
        {!current && compareMode && view === "compare" && (
          <ComparePickerPage
            items={items ?? []}
            lang={lang}
            base={cmpBase}
            target={cmpTarget}
            groupIds={groupIds}
            sameHint={cmpBase !== null && cmpBase === cmpTarget}
            onBase={setCmpBase}
            onTarget={setCmpTarget}            onRun={runCompare}
            onGroupRun={runGroupCompare}
            onToggle={toggleGroupId}
            onExit={exitCompare}/>
        )}
        {!current && !compareMode && !showStats && !showAdmin && view === "overview" && (
          <HomeOverview
            items={items ?? []}
            lang={lang}
            onOpen={(id) => id > 0 && setSelected(id)}
            onUploadClick={() => {
              // navigate to the dedicated upload screen (the drawer input is
              // hidden by default, so the old .upload-box click did nothing)
              setSelected(null);
              setCompareMode(false);
              setShowStats(false);
              setShowAdmin(false);
              setView("upload");
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            onUpgrade={openPaywall}
            onGroup={() => {
              // land on the compare screen (picker) — not just flip the flag
              setSelected(null);
              setShowStats(false);
              setShowAdmin(false);
              setView("compare");
              setCompareMode(true);
              if (items && items.length >= 2 && cmpBase == null && cmpTarget == null) {
                setCmpBase(items[1]?.id ?? null);
                setCmpTarget(items[0]?.id ?? null);
              }
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        )}
        {cmpError && <div className="error-box">{cmpError}</div>}

        {/* upload failures (incl. the 402 quota banner — one-click fix via
            the paywall) surface here so the user is never left guessing */}
        {error && !current && (
          <div className="error-box">
            <span>{error}</span>
            {quotaHit && (
              <button className="btn small save" onClick={openPaywall}>
                {lang === "ar" ? "⭐ رقّ الباقة" : "⭐ Upgrade"}
              </button>
            )}
          </div>
        )}

        {compareMode && groupPayload && <GroupCompare payload={groupPayload} lang={lang} />}

        {compareMode && cmpPayload && <Compare payload={cmpPayload} lang={lang} t={t} />}

        {compareMode && !cmpPayload && current && (
          <div className="placeholder">{CMP.pick_two[lang]}</div>
        )}

        {showStats && stats && <Stats payload={stats} lang={lang} />}

        {showAdmin && user?.is_admin && token && <AdminPanel token={token} lang={lang} />}

        {!compareMode && current && (
          <div className="analysis-layout">
          <div className="analysis-content">
          <>
            {/* Concept review — user request 2026-10-12: shown BEFORE the
                report content when the analysis has unknown/unclassified
                concepts (the gate), folded out of the report flow after the
                user accepts (it stays editable from the «مراجعة المفاهيم»
                accordion button here). */}
            {reviewGateId === current.id && reviewWorthy && (
              <div className="crev-gate">
                <ConceptReview
                  analysis={current}
                  lang={lang}
                  gate
                  onUpdated={mergeDetail}
                  onDone={() => {
                    setReviewGateId(null);
                    toast(
                      lang === "ar"
                        ? "اعتُمد التحليل — يمكنك تصحيح المفاهيم لاحقًا من قسم «مراجعة المفاهيم»"
                        : "Analysis accepted — concepts stay fixable from the review section"
                    );
                  }}
                />
              </div>
            )}
            <header className="analysis-header">
              <div className="analysis-title">
                {editName ? (
                  <div className="name-editor">
                    <input
                      autoFocus
                      value={nameDraft}
                      maxLength={200}
                      placeholder={t.name_placeholder[lang]}
                      onChange={(e) => setNameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveName();
                        if (e.key === "Escape") setEditName(false);
                      }}
                    />
                    <button className="btn small save" disabled={savingName} onClick={saveName}>
                      {t.save[lang]}
                    </button>
                    <button className="btn small ghost" onClick={() => setEditName(false)}>
                      {t.cancel[lang]}
                    </button>
                  </div>
                ) : (
                  <>
                    <h2 title={current.filename}>{title}</h2>                    <button className="icon-btn" title={t.edit_name[lang]} onClick={() => { setNameDraft(current.display_name ?? ""); setEditName(true); }}>✏️</button>
                  </>
                )}
                <span className="meta">
                  {fmtDate(current.created_at)} · {t.tables_found[lang]}: {current.result.tables_found} · {t.texts_found[lang]}: {current.result.texts_found}
                </span>
              </div>
              <div className="header-actions">
                {(
                  <>
                    <button
                      className="pdf-btn"
                      onClick={() =>
                        salesAnalysis
                          ? download(
                              `/api/analyses/${current.id}/sales-report?lang=${lang}`,
                              `sales-report-${current.id}.pdf`,
                            )
                          : download(
                              `/api/analyses/${current.id}/report?lang=${lang}`,
                              `financial-report-${current.id}.pdf`,
                            )
                      }
                    >
                      <Glyph name="doc" size={12} /> {t.download_pdf[lang]}
                    </button>
                    <button
                      className="pdf-btn export-btn"
                      onClick={() =>
                        download(
                          `/api/analyses/${current.id}/export?lang=${lang}`,
                          `analysis-${current.id}-results.xlsx`,
                        )
                      }
                    >
                      📊 {t.export_excel[lang]}
                    </button>
                    <button
                      className="pdf-btn pptx-btn"
                      onClick={() =>
                        download(
                          `/api/analyses/${current.id}/pptx?lang=${lang}`,
                          `financial-deck-${current.id}.pptx`,
                        )
                      }
                    >
                      {VALUE_LABELS.pptx[lang]}
                    </button>
                    {current.has_file && (
                      <>
                      <button
                        className="pdf-btn reanalyze-btn"
                        disabled={reanalyzing}
                        onClick={async () => {
                          setReanalyzing(true);
                          try {
                            const res = await fetch(`/api/analyses/${current.id}/reanalyze`, {
                              method: "POST",
                              headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                            });
                            const body = await res.json().catch(() => ({}));
                            if (!res.ok) throw new Error(body.detail || `error ${res.status}`);
                            await load();
                            toast(VALUE_LABELS.reanalyzed[lang]);
                          } catch (e) {
                            toast(e instanceof Error ? e.message : String(e));
                          } finally {
                            setReanalyzing(false);
                          }
                        }}
                      >
                        {reanalyzing ? VALUE_LABELS.reanalyzing[lang] : VALUE_LABELS.reanalyze[lang]}
                      </button>
                      {(() => {
                        // frozen upload classification: the reanalyze route
                        // is LOCKED to the declared kind/mode — show it so
                        // the user knows re-analysis never re-classifies
                        const kLabels: Record<string, { ar: string; en: string }> = {
                          statements: { ar: "قوائم مالية", en: "Financial statements" },
                          trial_balance: { ar: "ميزان مراجعة", en: "Trial balance" },
                          sales: { ar: "مبيعات", en: "Sales" },
                        };
                        const mLabels: Record<string, { ar: string; en: string }> = {
                          force_trial_balance: { ar: "قراءة مدين/دائن", en: "Debit/credit reading" },
                          financial_sheets: { ar: "قراءة مالية قسرية", en: "Forced financial reading" },
                        };
                        const k = current.file_kind
                          ? kLabels[current.file_kind]?.[lang]
                          : null;
                        if (!k) return null;
                        const m = current.analysis_mode
                          ? mLabels[current.analysis_mode]?.[lang]
                          : null;
                        return (
                          <span
                            className={`pdf-btn kind-badge${m ? " forced" : ""}`}
                            title={m
                              ? (lang === "ar"
                                ? `التصنيف المثبّت: ${k} — ${m}`
                                : `Locked classification: ${k} — ${m}`)
                              : (lang === "ar"
                                ? `التصنيف المثبّت: ${k}`
                                : `Locked classification: ${k}`)}
                          >
                            🔒 {k}
                            {m && <small> · {m}</small>}
                          </span>
                        );
                      })()}
                      </>
                    )}
                    {current.has_file && (
                      <button
                        className="pdf-btn file-btn"
                        onClick={() => download(`/api/analyses/${current.id}/file`, current.filename)}
                      >
                        ⬇ {t.download_file[lang]}
                        <small className="orig-name" title={current.filename}>
                          {current.filename}
                        </small>
                      </button>
                    )}
                  </>
                )}
              </div>
            </header>

            {(
              <>
            {/* CMRRS-style report banner — first thing in the analysis */}
            {reportHeader && (
              <ReportHeader
                data={reportHeader}
                lang={lang}
                onEditCompany={async (
                  draft: string,
                  setSaving: (v: boolean) => void,
                  done: () => void,
                ) => {
                  if (!current) return;
                  setSaving(true);
                  try {
                    const res = await fetch(`/api/analyses/${current.id}`, {
                      method: "PATCH",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ display_name: draft }),
                    });
                    if (!res.ok) {
                      const body = await res.json().catch(() => ({}));
                      throw new Error(body.detail || `save failed (${res.status})`);
                    }
                    await load();
                    toast(TOASTS.name_saved[lang]);
                    done();
                  } catch (e) {
                    toast(e instanceof Error ? e.message : String(e));
                  } finally {
                    setSaving(false);
                  }
                }}
              />
            )}

            {/* Document-only fallback: a scanned file with no financial
                indicators is kept as a document — the LOUD notice says so
                and the extracted text is shown instead of an empty report */}
            {isDocument && (
              <div className="doc-notice" id="sec-document">
                <div className="doc-notice-head">
                  <strong>
                    <Glyph name="doc" size={13} /> {" "}
                    {lang === "ar"
                      ? "مستند بلا قوائم مالية"
                      : "Document without financial statements"}
                  </strong>
                  <span>
                    {lang === "ar"
                      ? "قُرئ الملف ضوئيًا (OCR) لكنه لا يحتوي مؤشرات مالية كافية للتحليل (إيرادات/مصاريف/أصول أو ميزان مراجعة) — النص المستخرج معروض أدناه للتوثيق فقط، ولا تُبنى منه قوائم أو نسب."
                      : "The file was OCR-read but carries no analysable financial indicators (revenue/expenses/assets or a trial balance) — the extracted text below is for reference only; no statements or ratios are built from it."}
                  </span>
                </div>
                {textsSample.length > 0 && (
                  <div className="doc-text">
                    <h4>{lang === "ar" ? "النص المستخرج (عينة القراءة)" : "Extracted text (reading sample)"}</h4>
                    <ul>
                      {textsSample.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Sales-operations analysis — replaces the financial report
                when the file is a sales grid (kind==="sales") */}
            {salesAnalysis && <SalesAnalysisPanel data={salesAnalysis} lang={lang} />}

            {/* Executive brief — directly after the banner, per CMRRS order */}
            {!salesAnalysis && (
              <div id="sec-exec-brief">
                {current && hasData && <ExecBrief analysisId={current.id} lang={lang} />}
              </div>
            )}

            {/* Financial statements — built from a trial balance, shown
                inline right after the executive brief */}
            <div id="sec-statements">
            {current && hasStmts && stmts && (
              <StatementsPanel analysisId={current.id} lang={lang} statements={stmts} />
            )}
            </div>

            {canEditValues && (
              <div className="values-bar">
                <button
                  className={editingValues ? "compare-btn active" : "compare-btn"}
                  onClick={() => setEditingValues((v) => !v)}
                >
                  ✏️ {lang === "ar" ? "تعديل القيم" : "Edit values"}
                </button>
                {current.result.edited_at && (
                  <span className="edited-note">{VALUE_LABELS.edited[lang]}</span>
                )}
              </div>
            )}

            {canEditValues && editingValues && current && result && (
              <ValuesEditor
                result={result}
                lang={lang}
                saving={savingValues}
                onSave={saveValues}
                onReset={resetValues}
              />
            )}

            {!hasData && <div className="placeholder">{t.no_data[lang]}</div>}

            {hasData && (
              <>
                {/* Horizontal growth between two periods (revenue/costs/profits) */}
                <GrowthStrip analysisId={current.id} lang={lang} />

                {/* KPI cards with mini-trend sparkline style */}
                <section className="kpi-grid" id="sec-kpis">
                  {Object.entries(result.kpis).map(([key, kpi], i) => {
                    const spark = result.series[key]?.values ?? [];
                    const color = COLORS[i % COLORS.length];
                    return (
                      <div className="kpi-card" key={key}>
                        <span className="kpi-label">{kpi[lang]}</span>
                        <span className={`kpi-value ${kpi.value < 0 ? "neg" : ""}`}>{fmtNum(kpi.value)}</span>
                        {spark.length >= 2 && (
                          <span className="kpi-spark">
                            {spark.slice(-3).map((v, j, arr) => (
                              <span
                                key={j}
                                className="spark-dot"
                                style={{
                                  background: color,
                                  height: `${
                                    6 + 10 * (v / Math.max(...arr.map(Math.abs), 1))
                                  }px`,
                                }}
                              />
                            ))}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </section>

                {/* Ratios as gauge rings (dashboard style) */}
                {Object.keys(result.ratios).length > 0 && (
                  <section className="panel" id="sec-ratios">
                    <h3>{t.ratios[lang]}</h3>
                    <div className="ratio-grid">
                      {Object.entries(result.ratios).map(([key, r]) => {
                        const pct = Math.max(0, Math.min(100, r.value));
                        const hue = pct > 60 ? "#dc2626" : pct > 35 ? "#f59e0b" : "#059669";
                        return (
                          <div className="ratio-gauge" key={key}>
                            <div
                              className="gauge-ring"
                              style={{
                                background: `conic-gradient(${hue} ${pct * 3.6}deg, #e2e8f0 0deg)`,
                              }}
                            >
                              <span className="gauge-value">{r.value}</span>
                            </div>
                            <span className="gauge-label">{r[lang]}</span>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}

                {/* النسب مقابل المعايير المرجعية — مثل شريحة العرض التقديمي */}
                <div id="sec-benchmarks">
                  {current && hasData && <BenchmarkAlignment analysisId={current.id} lang={lang} />}
                </div>

              </>
            )}

            {/* تحليل النسب المالية — مباشرة بعد النسب المئوية */}
            <div id="sec-ratio-insights">
            {current && hasData && (
              <RatioInsights
                analysisId={current.id}
                lang={lang}
                focusQuality={
                  qualityFocus && current.id === qualityFocus.id
                    ? qualityFocus.token
                    : 0
                }
                onQualityFocusDone={() => setQualityFocus(null)}
              />
            )}
            </div>

            {/* Horizontal + vertical comparative table */}
            <div id="sec-comparison">
            {current && hasData && <YearlyComparisonTable analysisId={current.id} lang={lang} />}
            </div>            {/* لوحة المؤشرات التحليلية — نفس بيانات شريحة العرض التقديمي */}
            <div id="sec-dashboard">
              {current && hasData && <AnalyticsDashboard analysisId={current.id} lang={lang} />}
            </div>

            {/* الرسوم البيانية التحليلية */}
            {hasData && Object.keys(result.series).length > 0 && (
              <section className="panel" id="sec-trends">
                    <h3>{t.series[lang]}</h3>
                    <div className="charts">
                      {Object.entries(result.series).map(([key, s], i) => {
                        const data = s.values.map((v, idx) => ({
                          idx: idx + 1,
                          value: v,
                        }));
                        const color = COLORS[i % COLORS.length];
                        return (
                          <div className="chart-box" key={key}>
                            <span className="chart-title">{s[lang]}</span>
                            <ResponsiveContainer width="100%" height={180}>
                              {data.length >= 3 ? (
                                <AreaChart data={data}>
                                  <defs>
                                    <linearGradient id={`g-${key}`} x1="0" y1="0" x2="0" y2="1">
                                      <stop offset="5%" stopColor={color} stopOpacity={0.5} />
                                      <stop offset="95%" stopColor={color} stopOpacity={0.05} />
                                    </linearGradient>
                                  </defs>
                                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                                  <XAxis dataKey="idx" tick={{ fontSize: 11 }} />
                                  <YAxis tick={{ fontSize: 11 }} width={60} tickFormatter={(v) => fmtNum(v)} />
                                  <Tooltip formatter={(v: number) => fmtNum(v)} />
                                  <Area type="monotone" dataKey="value" stroke={color} fill={`url(#g-${key})`} strokeWidth={2} />
                                </AreaChart>
                              ) : (
                                <BarChart data={data}>
                                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                                  <XAxis dataKey="idx" tick={{ fontSize: 11 }} />
                                  <YAxis tick={{ fontSize: 11 }} width={60} tickFormatter={(v) => fmtNum(v)} />
                                  <Tooltip formatter={(v: number) => fmtNum(v)} />
                                  <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} />
                                </BarChart>
                              )}
                            </ResponsiveContainer>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}

            {/* التقييم المالي — بعد الرسوم البيانية التحليلية */}
            <div id="sec-score">
            {current && hasData && <FinancialScore analysisId={current.id} lang={lang} />}
            </div>
            {/* التنبؤات — heading + trends (from result.forecast) + the
                projections table (from the advice payload) — ONE section,
                no more duplicate «التنبؤ بالمستقبل» further down */}
            {hasData && (result.forecast.length > 0 || current.id > 0) && (
              <ForecastSection analysisId={current.id} lang={lang} forecast={result.forecast} advLabel={t.forecast[lang]} upLabel={t.up[lang]} downLabel={t.down[lang]} flatLabel={t.flat[lang]} />
            )}

            {/* التوصيات — ثم الملاحظات أخيراً */}
            <div id="sec-advisor">
            {current && hasData && <Advisor analysisId={current.id} lang={lang} />}
            </div>

            {/* Concept review — removed from the report flow (user request
                2026-10-12 item 8): the review gate runs BEFORE the report is
                accepted (crev-gate above), and afterwards the concepts stay
                editable from the same gate when reopened via this compact
                button that floats at the bottom of the analysis */}

            {/* Notes — available even when no financial data was extracted */}
            {current && (
              <section className="panel notes-panel" id="sec-notes">
                  <div className="notes-head">
                    <h3>📝 {t.notes_label[lang]}</h3>
                    {!editNotes && (
                      <button
                        className="btn small ghost"
                        onClick={() => {
                          setNotesDraft(current.notes ?? "");
                          setEditNotes(true);
                        }}
                      >
                        {current.notes ? `✏️ ${t.edit_notes[lang]}` : `＋ ${t.add_note[lang]}`}
                      </button>
                    )}
                  </div>
                  {editNotes ? (
                    <div className="notes-editor">
                      <textarea
                        autoFocus
                        value={notesDraft}
                        rows={5}
                        onChange={(e) => setNotesDraft(e.target.value)}
                        placeholder={t.add_note[lang]}
                      />
                      <div className="notes-actions">
                        <button className="btn small save" disabled={savingNotes} onClick={saveNotes}>
                          {t.save[lang]}
                        </button>
                        <button className="btn small ghost" onClick={() => setEditNotes(false)}>
                          {t.cancel[lang]}
                        </button>
                      </div>
                    </div>
                  ) : current.notes ? (
                    <div className="notes-body">
                      {current.notes.split("\n").map((line, i) => (
                        <p key={i}>{line}</p>
                      ))}
                    </div>
                  ) : (
                    <div
                      className="notes-body empty clickable"
                      onClick={() => {
                        setNotesDraft("");
                        setEditNotes(true);
                      }}
                    >
                      {t.no_notes[lang]}
                    </div>
                  )}
              </section>
            )}
              </>
            )}
          </>
          </div>

          {/* sticky in-page navigation */}
          <SectionNav
            visibleIds={[
              "sec-home",
              ...(hasData ? ["sec-exec-brief", "sec-kpis"] : []),
              ...(hasStmts ? ["sec-statements"] : []),
              ...((result?.ratios && Object.keys(result.ratios).length > 0) ? ["sec-ratios", "sec-benchmarks"] : []),
              ...(hasData ? ["sec-ratio-insights", ...(nPeriods > 1 ? ["sec-comparison"] : []), "sec-trends", "sec-dashboard", "sec-score", "sec-forecast", "sec-advisor", "sec-notes"] : []),
            ]}
            lang={lang}
          />
          </div>
        )}
      </main>

    </div>
  );
}
