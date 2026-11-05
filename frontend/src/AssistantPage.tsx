import { useContext, useEffect, useRef, useState } from "react";
import { AuthContext } from "./App";
import type { Lang } from "./types";

/** «المساعد الذكي» — AI chat screen (side-rail item, replaces the old
 *  «الاستعانة الذكية» placeholder). Full page in the dashboard main pane;
 *  the backend /api/assistant/chat grounds every turn in the signed-in
 *  user's real platform data and calls Google Gemini. The conversation is
 *  PERSISTED per user (GET/DELETE /api/assistant/history), so it resumes
 *  after closing/reloading the page. Welcome state shows quick-question
 *  chips; bubbles render bold/bullet markdown lightly. */

interface Msg {
  role: "user" | "assistant";
  content: string;
}

interface AnalysisOption {
  id: number;
  name: string;
}

const T = {
  headTitle: { ar: "المساعد الذكي", en: "AI assistant" },
  headSub: {
    ar: "محادثة مباشرة مع مساعدك المالي — يقتبس تحليلاتك وباقتك ويشرح مؤشراتك",
    en: "Chat with your financial assistant — it quotes your analyses and plan",
  },
  powered: { ar: "مدعوم بـ Google Gemini", en: "Powered by Google Gemini" },
  welcome: {
    ar: "مرحبًا بك! أنا المساعد الذكي للمنصة. اسألني عن مؤشراتك المالية، أو تحليلاتك المحفوظة، أو كيفية استخدام المنصة، أو الباقات والاشتراكات.",
    en: "Welcome! I'm the platform AI assistant. Ask me about your financial ratios, your saved analyses, how to use the platform, or plans and subscriptions.",
  },
  chips: {
    c1: { ar: "ما وضع تحليلاتي الحالية؟", en: "How are my analyses doing?" },
    c2: { ar: "اشرح لي مؤشر السيولة", en: "Explain the liquidity ratio" },
    c3: { ar: "كم تبقى من تحليلات في باقتي؟", en: "How many analyses are left in my plan?" },
    c4: { ar: "كيف أنزّل تقرير PDF؟", en: "How do I download a PDF report?" },
  },
  scopeAll: { ar: "كل تحليلاتي (نظرة عامة)", en: "All my analyses (general)" },
  scopeLabel: { ar: "نطاق الإجابة:", en: "Answer scope:" },
  scopeTitle: {
    ar: "حدد تحليلًا ليصبح المساعد يجيب من أرقامه هو تحديدًا",
    en: "Pick an analysis so the assistant answers from its exact numbers",
  },
  inputPh: { ar: "اكتب سؤالك للمساعد الذكي…", en: "Type your question…" },
  send: { ar: "إرسال", en: "Send" },
  clear: { ar: "مسح المحادثة", en: "Clear chat" },
  login: {
    ar: "سجّل الدخول لاستخدام المساعد الذكي",
    en: "Log in to use the AI assistant",
  },
  typing: { ar: "المساعد يكتب…", en: "Assistant is typing…" },
  error: { ar: "تعذّر إرسال الرسالة — أعد المحاولة", en: "Couldn't send the message — try again" },
  clearFail: { ar: "تعذّر مسح المحادثة — أعد المحاولة", en: "Couldn't clear the chat — try again" },
  clearResume: {
    ar: "محادثتك محفوظة — تُستأنف تلقائيًا عند العودة",
    en: "Your chat is saved — it resumes automatically",
  },
};

export default function AssistantPage({ lang, token }: { lang: Lang; token: string }) {
  const { user } = useContext(AuthContext);
  // null = still loading the stored transcript; [] = empty conversation
  const [msgs, setMsgs] = useState<Msg[] | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // chat scope: null = whole platform; a number = this analysis only
  const [scopeId, setScopeId] = useState<number | null>(null);
  const [options, setOptions] = useState<AnalysisOption[]>([]);

  // Resume the persisted conversation: pulled from the backend on mount
  // (authoritative for this account — survives reloads and other windows).
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const res = await fetch("/api/assistant/history", {
          headers: { Authorization: `Bearer ${token}` },
        });
        const body = res.ok ? await res.json() : null;
        if (!dead) setMsgs((body?.messages ?? []) as Msg[]);
      } catch {
        if (!dead) setMsgs([]); // offline/failure — a fresh chat, still usable
      }
    })();
    return () => {
      dead = true;
    };
  }, [token]);

  // keep the latest bubble in view as the conversation grows
  useEffect(() => {
    const el = listRef.current;
    if (el && msgs) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [msgs, busy]);

  // pick-list options: saved analyses, newest first, short display names
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const res = await fetch("/api/analyses");
        if (!res.ok) return;
        const metas = await res.json();
        if (!dead)
          setOptions(
            metas.map((m: { id: number; display_name?: string; filename: string }) => ({
              id: m.id,
              name: m.display_name || m.filename,
            })),
          );
      } catch {
        /* picker stays empty — the chat keeps the whole-platform scope */
      }
    })();
    return () => {
      dead = true;
    };
  }, []);

  const send = async (text?: string) => {
    const content = (text ?? draft).trim();
    if (!content || busy) return;
    if (!token) {
      setErr(T.login[lang]);
      return;
    }
    setErr(null);
    const history = (msgs ?? []).slice(-8).map((m) => ({ role: m.role, content: m.content }));
    setMsgs((prev) => [...(prev ?? []), { role: "user", content }]);
    setDraft("");
    setBusy(true);
    try {
      const res = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: content, history, lang, analysis_id: scopeId }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 401) {
        setErr(T.login[lang]);
        return;
      }
      if (!res.ok) throw new Error(body.detail || `error ${res.status}`);
      const reply: string = body.reply || (lang === "ar" ? "لم أتلقَّ ردًا." : "No reply received.");
      setMsgs((prev) => [...(prev ?? []), { role: "assistant", content: reply }]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : T.error[lang]);
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (busy || !msgs?.length) return;
    try {
      const res = await fetch("/api/assistant/history", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(String(res.status));
      setMsgs([]);
      setErr(null);
    } catch {
      setErr(T.clearFail[lang]);
    }
  };

  /** light markdown: **bold** spans, bullet lines, paragraph breaks */
  const renderRich = (text: string) =>
    text.split(/\n+/).map((raw, i) => {
      const clean = raw.trim();
      if (!clean) return null;
      const bullet = /^[-•*]\s+/.test(clean);
      const body = bullet ? clean.replace(/^[-•*]\s+/, "") : clean;
      const parts = body.split(/(\*\*[^*]+\*\*)/g).map((p, j) =>
        p.startsWith("**") && p.endsWith("**") && p.length > 4 ? <b key={j}>{p.slice(2, -2)}</b> : p
      );
      return bullet ? (
        <div className="asst-li" key={i}>
          <span className="asst-li-dot" aria-hidden="true">•</span>
          <span>{parts}</span>
        </div>
      ) : (
        <p key={i}>{parts}</p>
      );
    });

  return (
    <div className="assist-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <header className="assist-head">
        <div>
          <h2>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
              <path
                d="M12 3a7 7 0 0 1 4 12.7V18H8v-2.3A7 7 0 0 1 12 3zM10 21h4"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {T.headTitle[lang]}
          </h2>
          <p>{T.headSub[lang]}</p>
        </div>
        {msgs !== null && msgs.length > 0 && (
          <span className="assist-resume-note">💾 {T.clearResume[lang]}</span>
        )}
      </header>

      {/* scope bar: null = whole platform, else the answers come from this
          analysis's stored KPIs/ratios/series verbatim */}
      <div className="assist-scope" title={T.scopeTitle[lang]}>
        <span className="assist-scope-label">{T.scopeLabel[lang]}</span>
        <select
          value={scopeId ?? ""}
          onChange={(e) => setScopeId(e.target.value ? Number(e.target.value) : null)}
          aria-label={T.scopeLabel[lang]}
        >
          <option value="">{T.scopeAll[lang]}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name.length > 70 ? `${o.name.slice(0, 70)}…` : o.name}
            </option>
          ))}
        </select>
      </div>

      <section className="panel assist-panel">
        <div className="assist-msgs" ref={listRef}>
          {msgs === null && !busy && <p className="rs-empty">…</p>}

          {msgs !== null && msgs.length === 0 && !busy && (
            <div className="assist-welcome">
              <span className="assist-avatar big" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="26" height="26" fill="none">
                  <path
                    d="M12 3a7 7 0 0 1 4 12.7V18H8v-2.3A7 7 0 0 1 12 3zM10 21h4"
                    stroke="#fff"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <strong>
                {lang === "ar"
                  ? `مرحبًا ${user?.full_name || ""}! أنا المساعد الذكي`
                  : `Hi ${user?.full_name || ""}! I'm the AI assistant`}
              </strong>
              <p>{T.welcome[lang]}</p>
              <div className="assist-chips">
                {(["c1", "c2", "c3", "c4"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    className="assist-chip"
                    onClick={() => send(T.chips[k][lang])}
                  >
                    {T.chips[k][lang]}
                  </button>
                ))}
              </div>
            </div>
          )}

          {(msgs ?? []).map((m, i) => (
            <div className={`asst-row ${m.role}`} key={i}>
              {m.role === "assistant" && (
                <span className="assist-avatar" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                    <path
                      d="M12 3a7 7 0 0 1 4 12.7V18H8v-2.3A7 7 0 0 1 12 3zM10 21h4"
                      stroke="#fff"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              )}
              <div className={`asst-bubble ${m.role}`}>
                {m.role === "user" ? m.content : renderRich(m.content)}
              </div>
            </div>
          ))}

          {busy && (
            <div className="asst-row assistant" aria-live="polite">
              <span className="assist-avatar" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                  <path
                    d="M12 3a7 7 0 0 1 4 12.7V18H8v-2.3A7 7 0 0 1 12 3zM10 21h4"
                    stroke="#fff"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <div className="asst-bubble assistant typing" title={T.typing[lang]}>
                <span className="asst-dot" />
                <span className="asst-dot" />
                <span className="asst-dot" />
              </div>
            </div>
          )}
        </div>

        {err && <div className="assist-error">{err}</div>}

        <form
          className="assist-input"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={T.inputPh[lang]}
            disabled={busy}
            maxLength={4000}
            aria-label={T.inputPh[lang]}
          />
          {msgs !== null && msgs.length > 0 && (
            <button
              type="button"
              className="btn small ghost assist-clear-btn"
              title={T.clear[lang]}
              disabled={busy}
              onClick={clear}
            >
              🗑 {T.clear[lang]}
            </button>
          )}
          <button type="submit" className="btn small save assist-send-btn" disabled={busy || !draft.trim()}>
            {T.send[lang]} ➤
          </button>
        </form>
      </section>
    </div>
  );
}
