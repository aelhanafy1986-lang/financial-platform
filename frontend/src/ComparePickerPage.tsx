import { Glyph } from "./Glyph";
import type { AnalysisFull, Lang } from "./types";

/** «مقارنة التقارير» — the comparison control card (reference-style), now a
 *  full-width main-pane page instead of a drawer widget: baseline vs
 *  comparison selectors, the navy «قارن» button and the outline «قارن
 *  المجموعة» button. Group selection happens by clicking the analysis rows
 *  listed beneath the card. */

const T = {
  title: { ar: "مقارنة التقارير", en: "Report comparison" },
  subtitle: {
    ar: "قارن تحليلين أو مجموعة شركات جنبًا إلى جنب",
    en: "Compare two analyses or a group of companies side by side",
  },
  base: { ar: "المرجع", en: "Baseline" },
  target: { ar: "المقارن", en: "Comparison" },
  run: { ar: "قارن", en: "Compare" },
  group: { ar: "قارن المجموعة", en: "Compare group" },
  exit: { ar: "إنهاء المقارنة", en: "Exit compare" },
  pickHint: {
    ar: "حدد شركات متعددة من القائمة أدناه (نقر = اختيار/إلغاء)",
    en: "Select multiple companies from the list below (click to toggle)",
  },
  same: {
    ar: "اختر تحليلين مختلفين ثم اضغط قارن",
    en: "Pick two different analyses, then press Compare",
  },
  chooseSection: { ar: "اختر التحليلات للمجموعة", en: "Pick analyses for the group" },
  picked: { ar: "المحددة", en: "Picked" },
};

function nameOf(i: AnalysisFull): string {
  const name = i.display_name || i.filename;
  const m = name.match(/^(.*) — (.+)$/);
  return m ? m[2] : name.replace(/\.(xlsx|xls|pdf|docx|pptx|csv)$/i, "");
}

export function ComparePickerPage({
  items,
  lang,
  base,
  target,
  groupIds,
  sameHint,
  onBase,
  onTarget,
  onRun,
  onGroupRun,
  onToggle,
  onExit,
}: {
  items: AnalysisFull[];
  lang: Lang;
  base: number | null;
  target: number | null;
  groupIds: number[];
  sameHint: boolean;
  onBase: (id: number | null) => void;
  onTarget: (id: number | null) => void;
  onRun: () => void;
  onGroupRun: () => void;
  onToggle: (id: number) => void;
  onExit: () => void;
}) {
  return (
    <div className="compare-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <div className="cmp-card">
        <label className="cmp-field">
          <small>{T.base[lang]}</small>
          <select value={base ?? ""} onChange={(e) => onBase(Number(e.target.value) || null)}>
            <option value="">—</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {nameOf(i)}
              </option>
            ))}
          </select>
        </label>
        <label className="cmp-field">
          <small>{T.target[lang]}</small>
          <select value={target ?? ""} onChange={(e) => onTarget(Number(e.target.value) || null)}>
            <option value="">—</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {nameOf(i)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="cmp-run-btn"
          disabled={!base || !target || base === target}
          onClick={onRun}
        >
          <Glyph name="check" size={14} />
          {T.run[lang]}
        </button>
        <button
          className={groupIds.length >= 2 ? "cmp-group-btn active" : "cmp-group-btn"}
          disabled={groupIds.length < 2}
          onClick={onGroupRun}
        >
          {T.group[lang]}
          {groupIds.length > 0 ? ` (${groupIds.length})` : ""}
        </button>
        {sameHint && <span className="cmp-same-hint">{T.same[lang]}</span>}
        <button className="cmp-exit-btn" onClick={onExit}>
          {T.exit[lang]}
        </button>
      </div>

      <div className="cmp-section-label">
        {T.pickHint[lang]}
        {groupIds.length > 0 && (
          <span className="cmp-picked-count">
            {T.picked[lang]}: {groupIds.length}
          </span>
        )}
      </div>

      <ul className="cmp-pick-list">
        {items.map((i) => {
          const picked = groupIds.includes(i.id);
          const k = i.result?.kpis ?? {};
          const rev = k.revenue?.value ?? null;
          const net = k.net_profit?.value ?? null;
          return (
            <li key={i.id}>
              <button
                className={`cmp-pick-row${picked ? " picked" : ""}`}
                onClick={() => onToggle(i.id)}
              >
                <span className="cmp-pick-check">{picked ? "✓" : ""}</span>
                <span className="cmp-pick-name">{nameOf(i)}</span>
                {rev != null && <span className="cmp-pick-rev">{new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(rev)}</span>}
                {net != null && (
                  <span className={`cmp-pick-net ${net < 0 ? "neg" : "pos"}`}>
                    {new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Math.abs(net))}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
