import { useState } from "react";
import type { AnalysisFull, ConceptReviewItem, Lang } from "./types";
import { Glyph } from "./Glyph";

/** The concept vocabulary a manual correction may assign to — mirrors
 *  EDITABLE_CONCEPTS in app/analyzer.py with bilingual display names. */
const CONCEPTS: [string, string, string][] = [
  ["revenue", "الإيرادات", "Revenue"],
  ["cogs", "تكلفة المبيعات", "Cost of Sales"],
  ["gross_profit", "الربح الإجمالي", "Gross Profit"],
  ["opex", "المصاريف التشغيلية", "Operating Expenses"],
  ["net_profit", "صافي الربح", "Net Profit"],
  ["assets", "إجمالي الأصول", "Total Assets"],
  ["liabilities", "الالتزامات", "Liabilities"],
  ["equity", "حقوق الملكية", "Equity"],
  ["current_assets", "الأصول المتداولة", "Current Assets"],
  ["current_liabilities", "الالتزامات المتداولة", "Current Liabilities"],
  ["inventory", "المخزون", "Inventory"],
  ["cash", "النقدية", "Cash"],
  ["receivables", "المدينون", "Receivables"],
  ["payables", "الدائنون", "Payables"],
  ["finance_cost", "مصاريف التمويل", "Finance Costs"],
  ["tax_expense", "الزكاة والضرائب", "Zakat & Taxes"],
  ["investment_income", "دخل الاستثمار", "Investment Income"],
  ["cf_operating", "التدفق النقدي التشغيلي", "Operating Cash Flow"],
  ["cf_investing", "التدفق النقدي الاستثماري", "Investing Cash Flow"],
  ["cf_financing", "التدفق النقدي التمويلي", "Financing Cash Flow"],
  ["cf_other", "أثر العملات", "FX Effect"],
  ["cf_net_change", "صافي التغير في النقدية", "Net Change in Cash"],
  ["cf_cash_end", "النقدية نهاية الفترة", "Ending Cash"],
];

const fmtVal = (v: number) =>
  Math.abs(v) >= 1000
    ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : String(Math.round(v * 100) / 100);

type Props = {
  analysis: AnalysisFull;
  lang: Lang;
  /** Gate mode: shown right after upload, BEFORE the analysis is accepted. */
  gate?: boolean;
  onUpdated: (detail: AnalysisFull) => void;
  onDone?: () => void;
};

/** Manual correction panel for OCR-confused financial concepts: rows the
 *  classifier could not name are assigned their real concept, and captured
 *  concepts can be reclassified/renamed — every correction PATCHes the
 *  analysis, which recomputes ALL ratios immediately. */
export default function ConceptReview({
  analysis,
  lang,
  gate = false,
  onUpdated,
  onDone,
}: Props) {
  const result = analysis.result;
  const items = result.concept_review?.items ?? [];
  const pending = items.filter((it) => !it.applied);
  const fixes = result.concept_fixes ?? [];
  const metrics = result.metrics ?? {};

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      items.map((it) => [it.rid, it.candidates[0] ?? "revenue"])
    )
  );
  const [move, setMove] = useState<Record<string, string>>({});
  const [swapKeys, setSwapKeys] = useState<Record<string, boolean>>({});
  const [labelDraft, setLabelDraft] = useState<Record<string, string>>({});

  const conceptName = (key: string) => {
    const custom = result.concept_labels?.[key];
    if (custom) return custom;
    const hit = CONCEPTS.find((c) => c[0] === key);
    return hit ? (lang === "ar" ? hit[1] : hit[2]) : key;
  };

  const patch = async (body: unknown) => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/analyses/${analysis.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const detail = await res.json();
      if (!res.ok) {
        throw new Error(
          detail?.detail || `concept correction failed (${res.status})`
        );
      }
      onUpdated(detail);
      return true;
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const assignRow = (it: ConceptReviewItem) =>
    patch({ review_rows: { [it.rid]: { to: picks[it.rid] } } });

  const applyConcept = (key: string) => {
    const ch: Record<string, unknown> = {};
    const to = move[key];
    if (to && to !== key) {
      ch.to = to;
      if (swapKeys[key]) ch.swap = true;
    }
    const lab = (labelDraft[key] ?? "").trim();
    if (lab) ch.label = lab;
    if (!Object.keys(ch).length) return;
    return patch({ concepts: { [key]: ch } });
  };

  return (
    <div className="crev">
      <div className="crev-head">
        <h3>
          🧭{" "}
          {gate
            ? lang === "ar"
              ? "قبل اكتمال التحليل — راجع المفاهيم المقروءة من الملف"
              : "Before the analysis completes — review the concepts read from the file"
            : lang === "ar"
              ? "مراجعة المفاهيم"
              : "Concept review"}
        </h3>
        {result._ocr_used && (
          <span className="crev-ocr">
            {lang === "ar"
              ? "📄 قُرئ الملف ضوئيًا (OCR) — تحقق من الأسماء والقيم"
              : "📄 OCR-read file — verify names and values"}
          </span>
        )}
      </div>

      {gate && (
        <p className="crev-hint">
          {lang === "ar"
            ? "صحّح أي مفهوم مالي قرأه النظام بشكل مشوش — تُعاد حساب النسب فورًا مع كل تصحيح، ثم اعتمد التحليل للمتابعة."
            : "Fix any financial concept the system read incorrectly — ratios recompute instantly with every fix, then accept the analysis to continue."}
        </p>
      )}

      {pending.length > 0 && (
        <div className="crev-rows">
          <div className="crev-rows-title">
            {lang === "ar"
              ? `صفوف لم يتعرّف على مفهومها (${pending.length}) — اختر المفهوم الصحيح:`
              : `Rows with no recognised concept (${pending.length}) — pick the right one:`}
          </div>
          {pending.map((it) => (
            <div className="crev-row" key={it.rid}>
              <div className="crev-row-label">
                <code>«{it.label}»</code>
                {it.values.length > 0 && (
                  <span className="crev-vals">
                    {it.values.slice(0, 4).map(fmtVal).join(" · ")}
                    {it.values.length > 4 ? " …" : ""}
                  </span>
                )}
              </div>
              <div className="crev-row-actions">
                <select
                  value={picks[it.rid] ?? it.candidates[0] ?? "revenue"}
                  onChange={(e) =>
                    setPicks((p) => ({ ...p, [it.rid]: e.target.value }))
                  }
                  disabled={busy}
                >
                  {CONCEPTS.map(([k, ar, en]) => (
                    <option key={k} value={k}>
                      {lang === "ar" ? ar : en}
                    </option>
                  ))}
                </select>
                <button
                  className="btn small save"
                  disabled={busy}
                  onClick={() => assignRow(it)}
                >
                  {lang === "ar" ? "تعيين" : "Assign"} <Glyph name="check" size={10} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {pending.length === 0 && fixes.length > 0 && (
        <p className="crev-ok">
          <Glyph name="check" size={11} />{" "}
          {lang === "ar"
            ? `طُبّقت ${fixes.length} تصحيحًا — النسب محسوبة على القيم المصحّحة`
            : `${fixes.length} correction(s) applied — ratios computed on the corrected values`}
        </p>
      )}

      {Object.keys(metrics).length > 0 && (
        <details className="crev-concepts" open={gate && pending.length === 0}>
          <summary>
            {lang === "ar"
              ? "المفاهيم الملتقطة — إعادة تصنيف أو إعادة تسمية"
              : "Captured concepts — reclassify or rename"}
          </summary>
          {Object.entries(metrics).map(([key, vals]) => (
            <div className="crev-concept" key={key}>
              <div className="crev-concept-head">
                <strong>{conceptName(key)}</strong>
                <code className="crev-key">{key}</code>
                {result.concept_labels?.[key] && (
                  <span className="crev-badge">
                    {lang === "ar" ? "مُعاد تسميته" : "renamed"}
                  </span>
                )}
                <span className="crev-vals">
                  {(vals ?? []).slice(0, 3).map(fmtVal).join(" · ")}
                  {(vals ?? []).length > 3 ? " …" : ""}
                </span>
              </div>
              <div className="crev-concept-edit">
                <select
                  value={move[key] ?? ""}
                  onChange={(e) =>
                    setMove((m) => ({ ...m, [key]: e.target.value }))
                  }
                  disabled={busy}
                >
                  <option value="">
                    {lang === "ar"
                      ? "— أعد تصنيفه إلى…"
                      : "— reclassify to…"}
                  </option>
                  {CONCEPTS.filter(([k]) => k !== key).map(([k, ar, en]) => (
                    <option key={k} value={k}>
                      {lang === "ar" ? ar : en}
                    </option>
                  ))}
                </select>
                {move[key] && metrics[move[key]] && (
                  <label className="crev-swap">
                    <input
                      type="checkbox"
                      checked={!!swapKeys[key]}
                      onChange={(e) =>
                        setSwapKeys((s) => ({ ...s, [key]: e.target.checked }))
                      }
                    />
                    {lang === "ar" ? "تبديل القيمتين" : "swap values"}
                  </label>
                )}
                <input
                  className="crev-label"
                  placeholder={
                    lang === "ar"
                      ? "اسم مخصص (اختياري)"
                      : "custom label (optional)"
                  }
                  value={labelDraft[key] ?? ""}
                  maxLength={120}
                  onChange={(e) =>
                    setLabelDraft((d) => ({ ...d, [key]: e.target.value }))
                  }
                  disabled={busy}
                />
                <button
                  className="btn small save"
                  disabled={busy}
                  onClick={() => applyConcept(key)}
                >
                  {lang === "ar" ? "تطبيق" : "Apply"}
                </button>
              </div>
            </div>
          ))}
        </details>
      )}

      {err && <div className="crev-error">{err}</div>}

      {gate && (
        <div className="crev-gate-actions">
          <button className="btn save" onClick={onDone} disabled={busy}>
            {lang === "ar" ? "اعتماد التحليل" : "Accept analysis"} <Glyph name="check" size={11} />
            {pending.length
              ? lang === "ar"
                ? ` (${pending.length} صف بلا تصنيف)`
                : ` (${pending.length} unassigned)`
              : ""}
          </button>
        </div>
      )}
    </div>
  );
}
