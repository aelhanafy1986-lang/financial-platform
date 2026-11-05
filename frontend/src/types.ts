export type Lang = "ar" | "en";

export interface Kpi {
  value: number;
  en: string;
  ar: string;
}

export interface Ratio {
  value: number;
  en: string;
  ar: string;
}

export interface Series {
  values: number[];
  en: string;
  ar: string;
}

export interface ForecastItem {
  concept: string;
  en: string;
  ar: string;
  change_pct: number;
  trend: "up" | "down" | "flat";
}

/** One unclassified (OCR-mangled) row offered for a manual concept fix. */
export interface ConceptReviewItem {
  rid: string;
  label: string;
  values: number[];
  candidates: string[];
  source: "table" | "text";
  /** Set once the row was assigned a concept (PATCH review_rows). */
  applied?: string | null;
}

/** Stored log entry of one manual concept correction. */
export interface ConceptFix {
  concept?: string;
  review_row?: string;
  label?: string;
  to: string;
  swap?: boolean;
  at: string;
}

export interface AnalysisResult {
  kpis: Record<string, Kpi>;
  ratios: Record<string, Ratio>;
  series: Record<string, Series>;
  forecast: ForecastItem[];
  tables_found: number;
  texts_found: number;
  analysed_at: string | null;
  /** Raw per-concept values (oldest -> latest); present when editable. */
  metrics?: Record<string, number[]>;
  /** Period column headers detected in the source tables (oldest -> latest),
   *  e.g. ["2023", "2024"] or ["Q1", "Q2"]. Present when the file declares
   *  its periods; absent otherwise (banner falls back to counting). */
  period_labels?: string[];
  /** Set when raw values were manually edited (ISO timestamp). */
  edited_at?: string | null;
  /** Quality-gate verdict (مدقق الجودة) — absent on legacy rows. */
  audit?: AnalysisAudit;
  /** OCR-mangled rows the classifier could not name — the user's review
   *  list; correcting one assigns its values and recomputes the ratios. */
  concept_review?: { items: ConceptReviewItem[] };
  /** User-corrected concept display names {conceptKey: label}. */
  concept_labels?: Record<string, string>;
  /** Audit log of manual concept corrections (reclassify/assign). */
  concept_fixes?: ConceptFix[];
  /** True when the file was read through OCR (values may be suspect). */
  _ocr_used?: boolean;
  /** Analysis kind: "financial" (default) or "sales" (sales-operations
   *  grid analysed by the dedicated sales engine). */
  kind?: "financial" | "sales";
  /** Sales-operations analysis payload (present when kind === "sales"). */
  sales_analysis?: import("./SalesAnalysis").SalesAnalysis;
}

/** Quality-gate finding counts surfaced in the history list (0 = clean). */
export interface AuditCounts {
  audit_warnings?: number;
  audit_errors?: number;
  /** The gate ran AND found nothing — drives the green «مدقق» badge. */
  audited?: boolean;
}

/** Quick filter above the history list: all / with quality findings / clean. */
export type HistoryFilter = "all" | "flagged" | "clean";

/** One quality-gate finding, bilingual for display. */
export interface AuditIssue {
  code: string;
  severity: "error" | "warning" | "repair";
  ar: string;
  en: string;
}

/** Stored record of the backend quality gate for one analysis. */
export interface AnalysisAudit {
  ok: boolean;
  errors: AuditIssue[];
  warnings: AuditIssue[];
  repairs: AuditIssue[];
  checked_at?: string;
  /** "document" = OCR prose-only file kept as extracted text (no metrics). */
  mode?: string;
}

export interface AnalysisMeta extends AuditCounts {
  id: number;
  filename: string;
  display_name: string | null;
  notes: string | null;
  has_file: boolean;
  /** True when full statements were built from a trial balance. */
  has_tb: boolean;
  file_type: string;
  /** Frozen upload-screen declaration driving the locked reanalyze route. */
  file_kind?: "statements" | "trial_balance" | "sales" | null;
  analysis_mode?: "auto" | "force_trial_balance" | "financial_sheets" | null;
  size_bytes: number;
  created_at: string;
}

export interface StatementLine {
  ar: string;
  en: string;
  amount: number;
  bold?: boolean;
  account?: string;
  depreciation?: boolean;
  /** Prior-period value when a comparative column exists (optional). */
  prevAmount?: number | null;
}

export interface Statements {
  /** Accounting framework line shown under the titles (IFRS / SOCPA). */
  standard?: { ar: string; en: string };
  /** Metrics-derived statements (comparison files without a trial balance). */
  derived_from_metrics?: boolean;
  trial_balance: {
    total_debit: number;
    total_credit: number;
    balanced: boolean;
    accounts: { account: string; debit: number; credit: number }[];
  };
  income_statement: { lines: StatementLine[] };
  balance_sheet: {
    assets: { lines: StatementLine[]; total: number };
    liabilities_equity: { lines: StatementLine[]; total: number };
    balanced: boolean;
    difference: number;
  };
  cash_flow: {
    /** Legacy single-table shape (pre multi-activity). */
    lines?: StatementLine[];
    operating: { label: { ar: string; en: string }; lines: StatementLine[]; total: number };
    investing: { label: { ar: string; en: string }; lines: StatementLine[]; total: number };
    financing: { label: { ar: string; en: string }; lines: StatementLine[]; total: number };
    /** Stated FX / other effects on cash (per-file line, when captured). */
    other?: { lines: StatementLine[]; total: number };
    net_change_label: { ar: string; en: string };
    net_change: number;
    cash_balance: number;
    /** Only present when the movement is checkable (both periods carry cash). */
    reconciles?: boolean;
  };
  equity_statement: { lines: StatementLine[]; total: number };
  notes: {
    no: number;
    ar: string;
    en: string;
    text_ar?: string;
    text_en?: string;
    lines?: { account: string; amount: number; depreciation?: boolean }[];
  }[];
}

export interface AdviceItem {
  key: string;
  severity: "critical" | "warning" | "info";
  value?: number;
  ar: string;
  en: string;
  solutions_ar: string[];
  solutions_en: string[];
}

export interface Projection {
  concept: string;
  ar: string;
  en: string;
  values: number[];
  projections: { period: number; value: number; change_pct: number }[];
  trend: "up" | "down" | "flat";
}

export interface RatioInsight {
  key: string;
  label: string;
  value: number;
  is_percent?: boolean;
  /** Collection-period card: the value is a day count, not a multiple. */
  is_days?: boolean;
  verdict: "good" | "bad" | "neutral";
  what: string;
  why: string;
  opinion: string;
}

export interface ConsistencyCheck {
  label: string;
  ok: boolean;
  detail: string;
}

export interface YearlyComparisonRow {
  key: string;
  label: string;
  /** Which statement the row belongs to — reports/UI group the table into
   *  visually-closed blocks (income statement, then balance sheet). */
  stmt?: "income" | "balance";
  curr: string;
  prev: string;
  change: string;
  change_pct: string;
  pct_curr: string;
  pct_prev: string;
  color?: "good" | "bad" | null;
  /** Numeric mirrors for the UI heatmap colour intensity. */
  change_pct_val?: number;
  pct_curr_val?: number;
  /** Full history (up to last 6 periods) for the UI sparkline. */
  history?: number[];
}

export interface YearlyComparison {
  title: string;
  columns: string[];
  rows: YearlyComparisonRow[];
  note?: string;
  /** Number of available periods (max over rows). */
  periods?: number;
}

/** Financial-health radar (مؤشر الصحة المالية): one polygon per period. */
export interface HealthRadarDim {
  key: string;
  ar: string;
  en: string;
  /** period label -> 0-100 score (null = no data for that axis) */
  values: Record<string, number | null>;
}

export interface HealthRadar {
  periods: string[];
  radar: HealthRadarDim[];
}

export interface AdvicePayload {
  headline: string;
  advice: AdviceItem[];
  projections: Projection[];
  summary: { critical: number; warning: number; positive: number };
  solutions: string[];
  statements?: Statements | null;
  score?: ScorePayload | null;
  health?: HealthRadar | null;
  scenarios?: ScenariosPayload | null;
  brief?: ExecBrief | null;
  /** Data-quality warnings (broken revenue signs auto-fixed, etc.). */
  data_warnings?: string[];
  /** CMRRS-style interpretive ratio cards + consistency checks. */
  ratio_insights?: RatioInsight[];
  consistency_checks?: ConsistencyCheck[];
  /** Horizontal + vertical comparative table (two periods). */
  yearly_comparison?: YearlyComparison | null;
}

export interface ExecBriefResultItem {
  label: string;
  value: string;
  negative?: boolean;
}

export interface ActivityFit {
  key: string;
  title: string;
  activity: string;
  turnover_txt: string;
  range_txt: string;
  verdict: "fit" | "slow" | "fast" | "unknown";
  verdict_label: string;
}

export interface ExecBrief {
  company: {
    activity?: string;
    size?: string;
    pattern?: string;
    activity_fit?: ActivityFit;
  };
  results: ExecBriefResultItem[];
  strengths: string[];
  weaknesses: string[];
  verdict: string;
  paragraph: string;
}

export interface ScoreDimension {
  key: string;
  ar: string;
  en: string;
  weight: number;
  points: number;
}

export interface ScorePayload {
  score: number | null;
  grade: { ar: string; en: string; color: string } | null;
  dimensions: ScoreDimension[];
  ar?: string;
  en?: string;
}

export interface Scenario {
  key: "optimistic" | "realistic" | "conservative";
  ar: string;
  en: string;
  growth_pct: number;
  revenue: number;
  net: number;
  margin_pct: number;
}

export interface ScenariosPayload {
  scenarios: Scenario[];
  base_revenue: number;
  base_net: number | null;
}

export interface PlanInfo {
  key: string;
  months: number;
  uploads: number | null;
  price: number;
  ar: string;
  en: string;
}

export interface AdminUser {
  id: number;
  full_name: string;
  username: string;
  email: string;
  country: string | null;
  subscription: "free" | "paid";
  plan: string | null;
  is_admin: boolean;
  status: string;
  created_at: string;
  last_login: string | null;
  uploads_used: number;
}

export interface AuthUser {
  id: number;
  full_name: string;
  username: string;
  email: string;
  country: string | null;
  subscription: string;
  plan?: string | null;
  is_admin?: boolean;
  last_login?: string | null;
  uploads_used?: number;
  provider?: string | null;
  plan_expires?: string | null;
  masked_card?: string | null;
}

export interface SiteStats {
  analyses_count: number;
  statements_count: number;
  visits: number;
  last_visit: string | null;
  since: string;
}

export interface PublicStats extends SiteStats {
  recent: { id: number; name: string; date: string }[];
}

export interface Theme {
  primary: string;
  font: string;
}

export interface AnalysisFull extends AnalysisMeta {
  result: AnalysisResult;
  /** True when raw values are stored, so manual value editing is allowed. */
  editable?: boolean;
}

export type Labels = Record<string, { ar: string; en: string }>;

export const FALLBACK_LABELS: Labels = {
  title: { ar: "المنصة المالية الذكية", en: "Smart Financial Platform" },
  tagline: {
    ar: "محلّلك المالي المدعوم بالذكاء الاصطناعي",
    en: "Your Smart AI Financial Analyst",
  },
  dashboard: { ar: "الداشبورد", en: "Dashboard" },
  history: { ar: "سجل التحليلات", en: "History" },
};
