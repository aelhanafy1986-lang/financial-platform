import { useEffect, useState } from "react";
import { Glyph } from "./Glyph";

export interface ReadingSampleData {
  filename: string;
  ocr_used: boolean;
  quality: {
    score: number;
    labeled_rows: number;
    concepts: string[];
    spine: boolean;
  };
  tables_count: number;
  texts_count: number;
  tables: {
    name: string;
    kind: string;
    rows_total: number;
    accepted_count: number;
    rejected_count: number;
    columns: { index: number; role: string; year?: number }[];
    rows: { label: string; reason: string }[];
  }[];
}

type Lang = "ar" | "en";

const T = {
  title: { ar: "عينة قراءة الملف", en: "File Reading Sample" },
  subtitle: {
    ar: "هكذا قرأ المحلل ملفك — تحقق قبل الاعتماد على النتائج",
    en: "How the analyzer read your file — verify before trusting the results",
  },
  ocrBadge: { ar: "قراءة ضوئية (OCR)", en: "OCR read" },
  textBadge: { ar: "طبقة نصية أصلية", en: "Native text layer" },
  quality: { ar: "جودة القراءة", en: "Read quality" },
  labeled: { ar: "صفوف مالية مسمّاة", en: "labeled money rows" },
  spine: { ar: "عمود قائمة الدخل مكتمل", en: "income spine complete" },
  noSpine: { ar: "عمود قائمة الدخل غير مكتمل", en: "income spine incomplete" },
  tables: { ar: "الجداول المكتشفة", en: "Detected tables" },
  columns: { ar: "الأعمدة", en: "Columns" },
  rowsSample: { ar: "الصفوف (مقبولة / مرفوضة)", en: "Rows (accepted / rejected)" },
  accepted: { ar: "مقبول", en: "accepted" },
  kind: {
    ar: {
      balance_sheet: "قائمة مركز مالي",
      income_statement: "قائمة دخل",
      cash_flow: "تدفقات نقدية",
      trial_balance: "ميزان مراجعة",
      equity: "تغيرات حقوق ملكية",
      mixed: "وجهان في جدول واحد",
      generic: "جدول عام",
    } as Record<string, string>,
    en: {
      balance_sheet: "Balance sheet",
      income_statement: "Income statement",
      cash_flow: "Cash flow",
      trial_balance: "Trial balance",
      equity: "Equity changes",
      mixed: "Mixed faces",
      generic: "Generic table",
    } as Record<string, string>,
  },
  role: {
    ar: {
      label: "تسمية",
      period: "فترة",
      value: "قيمة",
      excluded: "مستبعد",
    } as Record<string, string>,
    en: {
      label: "Label",
      period: "Period",
      value: "Value",
      excluded: "Excluded",
    } as Record<string, string>,
  },
  reason: {
    ar: {
      accepted: "مقبول",
      no_concept: "بلا مفهوم معروف",
      no_values: "بلا قيم رقمية",
    } as Record<string, string>,
    en: {
      accepted: "Accepted",
      no_concept: "Unknown concept",
      no_values: "No numeric values",
    } as Record<string, string>,
  },
  noFile: {
    ar: "الملف الأصلي غير محفوظ لهذا التحليل — العينة غير متاحة",
    en: "The original file was not kept for this analysis — no sample",
  },
  load: { ar: "عرض عينة القراءة", en: "Show reading sample" },
  loading: { ar: "جارٍ فحص القراءة…", en: "Inspecting the read…" },
  col: { ar: "عمود", en: "col" },
  rowsTotals: { ar: "صفوف", en: "rows" },
  ok: { ar: "مقبول", en: "ok" },
  rej: { ar: "مرفوض", en: "rejected" },
};

const REASON_PREFIX = "summary:";

export default function ReadingSample({
  token,
  analysisId,
  lang,
  onClose,
}: {
  token: string;
  analysisId: number;
  lang: Lang;
  onClose?: () => void;
}) {
  const [data, setData] = useState<ReadingSampleData | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error" | "nofile">(
    "idle"
  );

  async function load() {
    setState("loading");
    try {
      const res = await fetch(
        `/api/analyses/${analysisId}/reading-sample?lang=${lang}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (res.status === 409) {
        setState("nofile");
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      setData(await res.json());
      setState("idle");
    } catch {
      setState("error");
    }
  }

  useEffect(() => {
    if (analysisId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  if (state === "nofile")
    return (
      <div className="reading-sample">
        <p className="rs-empty">{T.noFile[lang]}</p>
      </div>
    );
  if (state === "loading")
    return (
      <div className="reading-sample">
        <p className="rs-empty">{T.loading[lang]}</p>
      </div>
    );
  if (state === "error" || !data)
    return (
      <div className="reading-sample">
        <button className="btn small ghost" onClick={load}>
          {T.load[lang]}
        </button>
      </div>
    );

  return (
    <div className="reading-sample">
      <div className="rs-head">
        <h3>{T.title[lang]}</h3>
        {onClose && (
          <button className="btn small ghost" onClick={onClose} aria-label="close">
            <Glyph name="cross" size={12} />
          </button>
        )}
      </div>
      <p className="rs-sub">{T.subtitle[lang]}</p>
      <div className="rs-meta">
        <span className="rs-file">📄 {data.filename}</span>
        <span className={`badge ${data.ocr_used ? "warn" : "ok"}`}>
          {data.ocr_used ? T.ocrBadge[lang] : T.textBadge[lang]}
        </span>
        <span
          className={`badge ${data.quality.spine ? "ok" : "warn"}`}
          title={`score ${data.quality.score}`}
        >
          {T.quality[lang]}: {data.quality.score} ·{" "}
          {data.quality.spine ? T.spine[lang] : T.noSpine[lang]}
        </span>
        <span className="rs-count">
          {data.quality.labeled_rows} {T.labeled[lang]}
        </span>
      </div>
      {data.tables.map((t) => (
        <div className="rs-table" key={t.name}>
          <div className="rs-table-head">
            <strong>{t.name}</strong>
            <span className="badge kind">{T.kind[lang][t.kind] ?? t.kind}</span>
            <span className="rs-count">
              {t.rows_total} {T.rowsTotals[lang]} · {t.accepted_count}{" "}
              {T.ok[lang]} · {t.rejected_count} {T.rej[lang]}
            </span>
          </div>
          <div className="rs-cols">
            {t.columns.map((c) => (
              <span key={c.index} className={`rs-col rs-col-${c.role}`}>
                {T.col[lang]} {c.index + 1}
                {c.year ? ` · ${c.year}` : ""}: {T.role[lang][c.role] ?? c.role}
              </span>
            ))}
          </div>
          <ul className="rs-rows">
            {t.rows.map((r, i) => {
              const isSummary = r.reason.startsWith(REASON_PREFIX);
              const reason = isSummary
                ? `${lang === "ar" ? "سطر محسوب من" : "computed from"} ${
                    T.reason[lang][r.reason.slice(REASON_PREFIX.length)] ??
                    r.reason.slice(REASON_PREFIX.length)
                  }`
                : T.reason[lang][r.reason] ?? r.reason;
              return (
                <li
                  key={`${r.label}-${i}`}
                  className={r.reason === "accepted" ? "ok" : "rej"}
                >
                  <span className="rs-label">{r.label}</span>
                  <span className="rs-reason">{reason}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
