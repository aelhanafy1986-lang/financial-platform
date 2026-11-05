import { useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AuthContext } from "./App";
import type { AdvicePayload, Lang, Statements } from "./types";

export type { Statements };

const T = {
  headline: { ar: "التوصيات", en: "Recommendations" },
  critical: { ar: "حرج", en: "Critical" },
  warning: { ar: "تنبيه", en: "Warning" },
  info: { ar: "إيجابي", en: "Positive" },
  solutions: {
    ar: "حلول مقترحة عند التدني أو الخسارة",
    en: "Suggested solutions for losses / weak results",
  },
  no_issues: {
    ar: "لا توجد مؤشرات سلبية — استمر في المتابعة الدورية",
    en: "No negative indicators — keep periodic monitoring",
  },
  // user request 2026-10-12: the projections table merged INTO the report's
  // «التنبؤات» section (sec-forecast) — its own «التنبؤ بالمستقبل» panel
  // here was a duplicate of that section, so it is no longer rendered.
  statements: { ar: "القوائم المالية", en: "Financial Statements" },
  is_title: { ar: "قائمة الدخل", en: "Income Statement" },
  bs_title: { ar: "قائمة المركز المالي", en: "Statement of Financial Position" },
  bs_assets: { ar: "الأصول", en: "Assets" },
  bs_total_assets: { ar: "إجمالي الأصول", en: "Total assets" },
  bs_liab_eq: { ar: "الالتزامات وحقوق الملكية", en: "Liabilities & Equity" },
  bs_liab_eq_total: {
    ar: "إجمالي الالتزامات وحقوق الملكية",
    en: "Total liabilities & equity",
  },
  cf_title: { ar: "قائمة التدفقات النقدية", en: "Cash Flow Statement" },
  eq_title: { ar: "قائمة التغير في حقوق الملكية", en: "Changes in Equity" },
  op_total: { ar: "صافي التدفق التشغيلي", en: "Net operating flow" },
  inv_total: { ar: "صافي التدفق الاستثماري", en: "Net investing flow" },
  fin_total: { ar: "صافي التدفق التمويلي", en: "Net financing flow" },
  other_total: { ar: "صافي أثر العملات والبنود الأخرى", en: "Net FX and other effects" },
  cash_end: { ar: "رصيد النقدية في نهاية الفترة", en: "Cash at end of period" },
  download: { ar: "⬇ تنزيل PDF (A4)", en: "⬇ Download PDF (A4)" },
  download_xlsx: { ar: "⬇ تنزيل Excel", en: "⬇ Download Excel" },
  upload_tb: { ar: "📎 إرفاق ميزان مراجعة (Excel)", en: "📎 Attach trial balance (Excel)" },
  uploading: { ar: "جارٍ الإعداد…", en: "Building…" },
  balanced: { ar: "متوازن", en: "Balanced" },
  unbalanced: { ar: "غير متوازن", en: "Unbalanced" },
  total: { ar: "الإجمالي", en: "Total" },
  item: { ar: "البند", en: "Item" },
  value: { ar: "القيمة", en: "Value" },
  debit: { ar: "مدين", en: "Debit" },
  credit: { ar: "دائن", en: "Credit" },
};

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

/* ------------------------------------------------------------------ */
/* Statements tables — restyled: each line shows its vertical-analysis */
/* % of the statement base (revenue / total assets / total L+E), and   */
/* — when a comparison column exists — % change + prior-period value,  */
/* matching the reference layout: item | %Δ | % | value | % | prior.   */
/* ------------------------------------------------------------------ */

const STMT_T = {
  item: { ar: "البند", en: "Item" },
  change_pct: { ar: "% التغير", en: "% Change" },
  pct: { ar: "%", en: "%" },
  section: { ar: "القسم", en: "Section" },
};

function pctOf(amount: number, base: number): string | null {
  if (!base || Math.abs(base) < 0.01) return null;
  // Share of the statement base — shown as a positive magnitude; the sign
  // lives in the value cell colouring (neg = deduction/expense).
  return ((Math.abs(amount) / Math.abs(base)) * 100).toFixed(0) + "%";
}

function changePct(cur: number, prev: number): string | null {
  if (prev === undefined || prev === null || Math.abs(prev) < 0.01) return null;
  const d = ((cur - Math.abs(prev)) / Math.abs(prev)) * 100;
  return (d >= 0 ? "+" : "") + d.toFixed(0) + "%";
}

export interface StmtRow {
  ar: string;
  en: string;
  amount: number;
  bold?: boolean;
  prevAmount?: number | null;
  /** section header row (shaded, no figures) */
  section?: boolean;
  /** section-closing total (bold navy on white, grey rule above) */
  subtotal?: boolean;
  /** vertical-analysis base for this row's % (defaults: statement base) */
  base?: number;
}

function StmtTable({
  rows,
  lang,
  base,
  showChange = false,
  showPct = true,
  footer,
}: {
  rows: StmtRow[];
  lang: Lang;
  base: number;
  showChange?: boolean;
  showPct?: boolean;
  footer?: ReactNode;
}) {
  const span = 1 + (showChange ? 1 : 0) + (showPct ? 1 : 0) + 1 + (showChange ? 2 : 0);
  return (
    <table className={`stmt-table stmt-new ${showChange ? "has-compare" : ""} ${showPct ? "" : "no-pct"}`}>
      <thead>
        <tr>
          <th className="col-item">{STMT_T.item[lang]}</th>
          {showChange && <th className="col-chg">{STMT_T.change_pct[lang]}</th>}
          {showPct && <th className="col-pct">{STMT_T.pct[lang]}</th>}
          <th className="col-amt">{lang === "ar" ? "القيمة" : "Value"}</th>
          {showChange && <th className="col-pct">{STMT_T.pct[lang]}</th>}
          {showChange && <th className="col-amt">{lang === "ar" ? "الفترة السابقة" : "Prior period"}</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) =>
          r.section ? (
            <tr className="stmt-section" key={i}>
              <td colSpan={span}>{lang === "ar" ? r.ar : r.en}</td>
            </tr>
          ) : (
            <tr key={i} className={r.subtotal ? "bold stmt-subtotal" : r.bold ? "bold" : ""}>
              <td className="col-item">{lang === "ar" ? r.ar : r.en}</td>
              {showChange && (
                <td className={`col-chg num ${chgCls(r.amount, r.prevAmount)}`}>
                  {changePct(r.amount, r.prevAmount as number) ?? "—"}
                </td>
              )}
              {showPct && <td className="col-pct num">{pctOf(r.amount, r.base ?? base) ?? "—"}</td>}
              <td className={`col-amt num ${r.amount < 0 ? "neg" : ""}`}>
                {fmt(Math.abs(r.amount))}
              </td>
              {showChange && (
                <td className="col-pct num">
                  {pctOf(Math.abs(r.prevAmount ?? 0), r.base ?? base) ?? "—"}
                </td>
              )}
              {showChange && (
                <td className={`col-amt num ${((r.prevAmount ?? 0) < 0) ? "neg" : ""}`}>
                  {fmt(Math.abs(r.prevAmount ?? 0))}
                </td>
              )}
            </tr>
          ),
        )}
      </tbody>
      {footer && <tfoot>{footer}</tfoot>}
    </table>
  );
}

/** Statement title block matching the CMRRS reference: centred navy title
 *  with a short amber underline + a grey standards line under it. */
export function StmtTitle({
  title,
  standard,
  lang,
}: {
  title: { ar: string; en: string };
  standard?: { ar: string; en: string } | null;
  lang: Lang;
}) {
  return (
    <div className="stmt-title-block">
      <h4 className="stmt-title-cmrrs">{lang === "ar" ? title.ar : title.en}</h4>
      <span className="stmt-title-rule" aria-hidden="true" />
      {standard && (
        <p className="stmt-standard">
          ({lang === "ar" ? standard.ar.replace("وفق ", "") : standard.en})
        </p>
      )}
    </div>
  );
}

function chgCls(cur: number, prev?: number | null): string {
  if (prev === undefined || prev === null || Math.abs(prev) < 0.01) return "";
  const d = (cur - Math.abs(prev)) / Math.abs(prev);
  return d > 0.005 ? "up" : d < -0.005 ? "down" : "";
}

function OldStatementTable({
  lines,
  lang,
}: {
  lines: { ar: string; en: string; amount: number; bold?: boolean }[];
  lang: Lang;
}) {
  return <StmtTable rows={lines} lang={lang} base={0} />;
}

function StatementTable({
  lines,
  lang,
  base = 0,
  showChange = false,
}: {
  lines: { ar: string; en: string; amount: number; bold?: boolean }[];
  lang: Lang;
  base?: number;
  showChange?: boolean;
}) {
  return <StmtTable rows={lines} lang={lang} base={base} showChange={showChange} />;
}

function CashFlowView({ st, lang }: { st: Statements; lang: Lang }) {
  const cf = st.cash_flow;
  const acts = [
    cf.operating,
    cf.investing,
    cf.financing,
    ...(cf.other ? [cf.other] : []),
  ];
  const totals = [
    T.op_total,
    T.inv_total,
    T.fin_total,
    ...(cf.other ? [T.other_total] : []),
  ];
  return (
    <>
      {acts.map((act, i) => (
        <StmtTable
          key={i}
          lang={lang}
          showPct={false}
          base={0}
          rows={act.lines as StmtRow[]}
          footer={
            <tr className="stmt-total-row">
              <td>{totals[i][lang]}</td>
              <td className={`col-amt num ${act.total < 0 ? "neg" : ""}`}>{fmt(act.total)}</td>
            </tr>
          }
        />
      ))}
      <StmtTable
        lang={lang}
        showPct={false}
        base={0}
        rows={[
          {
            ar: lang === "ar" ? cf.net_change_label.ar : cf.net_change_label.en,
            en: cf.net_change_label.en,
            amount: cf.net_change,
            bold: true,
          },
          { ar: T.cash_end.ar, en: T.cash_end.en, amount: cf.cash_balance },
        ]}
      />
      {cf.reconciles === false && (
        <span className="edited-note">{T.unbalanced[lang]}</span>
      )}
    </>
  );
}

function StatementsView({
  st,
  lang,
  analysisId,
}: {
  st: Statements;
  lang: Lang;
  analysisId: number;
}) {
  const { token, openPaywall } = useContext(AuthContext);
  const tb = st.trial_balance;
  const legacyCash = !st.cash_flow?.operating;
  // Vertical-analysis bases: income statement lines are % of revenue;
  // balance-sheet lines are % of total assets (= total L+E when balanced).
  const isBase =
    st.income_statement?.lines?.find((l) => l.en === "Revenue")?.amount ?? 0;
  const bsBase = st.balance_sheet?.assets?.total ?? 0;
  return (
    <>
      <div className="stmts-head">
        <h3>📘 {T.statements[lang]}</h3>
        {st.derived_from_metrics ? (
          <span className={`tb-badge ${tb.balanced ? "ok" : "bad"}`}>
            {tb.balanced
              ? (lang === "ar"
                ? "القوائم متوازنة — مبنية من مقاييس الملف"
                : "Balanced — built from the file's figures")
              : (lang === "ar"
                ? "القوائم غير متوازنة — مبنية من مقاييس الملف"
                : "Unbalanced — built from the file's figures")}
          </span>
        ) : (
          <span className={`tb-badge ${tb.balanced ? "ok" : "bad"}`}>
            {lang === "ar" ? "ميزان المراجعة: " : "Trial balance: "}
            {tb.balanced ? T.balanced[lang] : T.unbalanced[lang]}
          </span>
        )}
        <div className="stmt-downloads">
          <a
            className="pdf-btn"
            href={`/api/analyses/${analysisId}/report?lang=${lang}&auth_token=${
              token ? encodeURIComponent(`Bearer ${token}`) : ""
            }`}
          >
            {T.download[lang]}
          </a>
          <a
            className="pdf-btn export-btn"
            href={`/api/analyses/${analysisId}/export?lang=${lang}&auth_token=${
              token ? encodeURIComponent(`Bearer ${token}`) : ""
            }`}
          >
            {T.download_xlsx[lang]}
          </a>
        </div>
      </div>

      {/* Accounting framework line + centred titles (CMRRS reference) */}
      <StmtTitle title={T.is_title} standard={st.standard ?? null} lang={lang} />

      {/* Income statement — its own panel (base = revenue) */}
      <section className="panel stmts-panel">
        <StatementTable
          lines={st.income_statement?.lines ?? []}
          lang={lang}
          base={isBase}
        />
        {isBase > 0 && (
          <span className="stmt-base-note">
            {lang === "ar"
              ? "النسب = نسبة كل بند من الإيرادات (تحليل رأسي)"
              : "% = share of revenue (vertical analysis)"}
          </span>
        )}
      </section>

      {/* Balance sheet — ONE unified table with section header rows
          (Assets → Total assets → Liabilities & Equity), like the reference:
          the assets total sits directly under the assets lines, above the
          liabilities section, as a bold navy subtotal with a grey rule. */}
      <section className="panel stmts-panel">
        <StmtTitle title={T.bs_title} standard={null} lang={lang} />
        <StmtTable
          lang={lang}
          base={bsBase}
          rows={[
            { ar: T.bs_assets.ar, en: T.bs_assets.en, amount: 0, section: true },
            ...(st.balance_sheet.assets.lines as StmtRow[]),
            {
              ar: T.bs_total_assets.ar,
              en: T.bs_total_assets.en,
              amount: st.balance_sheet.assets.total,
              bold: true,
              subtotal: true,
            },
            { ar: T.bs_liab_eq.ar, en: T.bs_liab_eq.en, amount: 0, section: true },
            ...(st.balance_sheet.liabilities_equity.lines as StmtRow[]),
            {
              ar: T.bs_liab_eq_total.ar,
              en: T.bs_liab_eq_total.en,
              amount: st.balance_sheet.liabilities_equity.total,
              bold: true,
              subtotal: true,
            },
          ]}
        />
        {!st.balance_sheet.balanced && (
          <span className="edited-note">
            {T.unbalanced[lang]}: {fmt(Math.abs(st.balance_sheet.difference))}
          </span>
        )}
      </section>

      {/* Cash flow — its own panel */}
      <section className="panel stmts-panel">
        <StmtTitle title={T.cf_title} standard={null} lang={lang} />
        {legacyCash ? (
          <StatementTable lines={st.cash_flow?.lines ?? []} lang={lang} />
        ) : (
          <CashFlowView st={st} lang={lang} />
        )}
      </section>

      {/* Equity statement — own panel (from tb builds) */}
      {st.equity_statement?.lines && (
        <section className="panel stmts-panel">
          <StmtTitle title={T.eq_title} standard={null} lang={lang} />
          <StmtTable
            lang={lang}
            showPct={false}
            base={0}
            rows={st.equity_statement.lines}
            footer={
              <tr className="stmt-total-row grand">
                <td>{T.total[lang]}</td>
                <td className="col-amt num">{fmt(st.equity_statement.total)}</td>
              </tr>
            }
          />
        </section>
      )}
    </>
  );
}

export function StatementsPanel({
  analysisId,
  lang,
  statements,
  onUploaded,
}: {
  analysisId: number;
  lang: Lang;
  statements: Statements | null;
  onUploaded?: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (file?: File | null) => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/analyses/${analysisId}/trial-balance`, {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `failed (${res.status})`);
      }
      onUploaded?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  if (statements) {
    return (
      <>
        {error && <div className="error-box">{error}</div>}
        <StatementsView st={statements} lang={lang} analysisId={analysisId} />
      </>
    );
  }

  return (
    <section className="panel">
      <h3>📘 {T.statements[lang]}</h3>
      <label className="tb-upload">
        <input
          type="file"
          accept=".xlsx,.xlsm"
          style={{ display: "none" }}
          onChange={(e) => upload(e.target.files?.[0])}
        />
        {uploading ? T.uploading[lang] : T.upload_tb[lang]}
      </label>
      {error && <div className="error-box">{error}</div>}
      <p className="values-hint">
        {lang === "ar"
          ? "ارفع ميزان المراجعة (Excel) لنبني قائمة الدخل والميزانية والتدفقات النقدية تلقائياً"
          : "Upload a trial balance (Excel) to build the income statement, balance sheet and cash flows automatically"}
      </p>
    </section>
  );
}

function AdvicePanel({ analysisId, lang }: { analysisId: number; lang: Lang }) {
  const [advice, setAdvice] = useState<AdvicePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setAdvice(null);
    setError(null);
    fetch(`/api/analyses/${analysisId}/advice?lang=${lang}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setAdvice)
      .catch(() => setError("…"));
  }, [analysisId, lang]);

  if ((error && !advice) || !advice) return null;
  const sev = {
    critical: T.critical[lang],
    warning: T.warning[lang],
    info: T.info[lang],
  };
  return (
    <>
      <section className="panel advisor-panel">
        <h3>💡 {T.headline[lang]}</h3>
        <p className="values-hint">{advice.headline}</p>
        {advice.advice.length === 0 && (
          <div className="placeholder">{T.no_issues[lang]}</div>
        )}
        {advice.advice.map((a) => (
          <div className={`advice-item ${a.severity}`} key={a.key}>
            <span className="sev">
              {a.severity === "critical" ? "🔴" : a.severity === "warning" ? "🟠" : "🟢"}{" "}
              {sev[a.severity]}
            </span>
            <span className="advice-text">{lang === "ar" ? a.ar : a.en}</span>
          </div>
        ))}
        {advice.solutions.length > 0 && (
          <>
            <h4>🛠 {T.solutions[lang]}</h4>
            <ul className="solutions">
              {advice.solutions.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}

export default function Advisor({
  analysisId,
  lang,
}: {
  analysisId: number;
  lang: Lang;
}) {
  return <AdvicePanel analysisId={analysisId} lang={lang} />;
}
