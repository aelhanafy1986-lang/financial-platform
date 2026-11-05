import { useEffect, useRef, useState } from "react";
import type { AuthUser, Lang, PlanInfo } from "./types";
import { Glyph } from "./Glyph";

const T = {
  signup: { ar: "إنشاء حساب", en: "Sign up" },
  login: { ar: "تسجيل الدخول", en: "Log in" },
  name: { ar: "الاسم الكامل", en: "Full name" },
  email: { ar: "البريد الإلكتروني", en: "Email" },
  country: { ar: "الدولة", en: "Country" },
  username: { ar: "اسم المستخدم", en: "Username" },
  password: { ar: "كلمة المرور", en: "Password" },
  confirmPassword: { ar: "تأكيد كلمة المرور", en: "Confirm password" },
  mismatch: { ar: "كلمتا المرور غير متطابقتين", en: "Passwords do not match" },
  confirm: { ar: "تأكيد", en: "Confirm" },
  code: { ar: "كود التفعيل (أُرسل إلى إيميلك)", en: "Activation code (sent to your email)" },
  verify: { ar: "تفعيل الحساب", en: "Activate account" },
  haveAccount: { ar: "لدي حساب — تسجيل الدخول", en: "I have an account — log in" },
  noAccount: { ar: "ليس لدي حساب — إنشاء حساب", en: "No account — sign up" },
  cardTitle: { ar: "سداد الاشتراك", en: "Subscription payment" },
  cardHint: {
    ar: "فعّل الاشتراك لتحميل التقارير والملفات (محاكاة سداد آمنة محلياً)",
    en: "Subscribe to unlock downloads (simulated local payment)",
  },
  cardNumber: { ar: "رقم البطاقة الائتمانية", en: "Card number" },
  cardHolder: { ar: "اسم حامل البطاقة", en: "Card holder" },
  expiry: { ar: "تاريخ الانتهاء MM/YY", en: "Expiry MM/YY" },
  cvv: { ar: "CVV", en: "CVV" },
  pay: { ar: "سداد وتفعيل الاشتراك", en: "Pay & subscribe" },
  paid: { ar: "✅ تم تفعيل الاشتراك بنجاح", en: "✅ Subscription activated" },
  lastLogin: { ar: "آخر دخول", en: "Last login" },
  logout: { ar: "تسجيل الخروج", en: "Log out" },
  close: { ar: "إغلاق", en: "Close" },
  welcome: { ar: "مرحباً،", en: "Welcome," },
  sending: { ar: "جارٍ الإرسال…", en: "Sending…" },
  sentHint: {
    ar: "تم إرسال كود التفعيل إلى إيميلك — أدخله أدناه",
    en: "Activation code sent to your email — enter it below",
  },
  devHint: {
    ar: "وضع محلي: كود التفعيل ظاهر أمامك",
    en: "Local mode: your activation code is shown",
  },
  or: { ar: "أو", en: "or" },
  socialSignupGoogle: { ar: "التسجيل عبر Google", en: "Sign up with Google" },
  socialSignupApple: { ar: "التسجيل عبر Apple", en: "Sign up with Apple" },
  socialLoginGoogle: { ar: "تسجيل الدخول عبر Google", en: "Log in with Google" },
  socialLoginApple: { ar: "تسجيل الدخول عبر Apple", en: "Log in with Apple" },
  socialTitle: { ar: "متابعة عبر", en: "Continue with" },
  socialHint: {
    ar: "سننشئ حسابك أو ندخلك عبر بريد المزوّد (محاكاة محلية — بلا كلمة مرور)",
    en: "We'll create or unlock your account via the provider email (local simulation — passwordless)",
  },
  socialContinue: { ar: "متابعة", en: "Continue" },
  back: { ar: "رجوع", en: "Back" },
};

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.5 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.4 5.8c4.4-4 7.2-10 7.2-17.5z" />
      <path fill="#FBBC05" d="M10.4 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6.1C.9 16.5 0 20.1 0 24s.9 7.5 2.6 10.8l7.8-6.1z" />
      <path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.3-5.5l-7.4-5.8c-2 1.4-4.7 2.2-7.9 2.2-6.3 0-11.7-3.7-13.6-9l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

function AppleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="#000">
      <path d="M16.7 12.9c0-2.5 2-3.7 2.1-3.8-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.7.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 2.9-.4 7.3 1.2 9.7.8 1.2 1.8 2.5 3.1 2.4 1.2-.1 1.7-.8 3.2-.8 1.5 0 1.9.8 3.2.8 1.3 0 2.2-1.2 3-2.4.9-1.4 1.3-2.7 1.3-2.8-.1 0-2.6-1-2.7-3.7zM14.4 5.6c.7-.8 1.1-1.9 1-3.1-1 0-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 2.2-.6 2.9-1.4z" />
    </svg>
  );
}

const input = (v: string) => ({ ar: "أدخل " + v, en: "Enter " + v });

export function AuthModal({
  mode,
  lang,
  onClose,
  onAuthed,
  onSwitch,
}: {
  mode: "login" | "signup";
  lang: Lang;
  onClose: () => void;
  onAuthed: (u: AuthUser, token: string) => void;
  onSwitch: (m: "login" | "signup") => void;
}) {
  const [form, setForm] = useState({
    full_name: "", email: "", country: "", username: "", password: "",
  });
  const [code, setCode] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pending, setPending] = useState<{ email: string; dev_code: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [social, setSocial] = useState<"google" | "apple" | null>(null);
  const [socialEmail, setSocialEmail] = useState("");
  const [socialName, setSocialName] = useState("");
  // real OAuth config: which providers are wired via env (GOOGLE_CLIENT_ID /
  // APPLE_CLIENT_ID). Unconfigured → the local simulated buttons stay.
  const [socialCfg, setSocialCfg] = useState<
    { google: { enabled: boolean; client_id: string | null };
      apple: { enabled: boolean; client_id: string | null } } | null
  >(null);
  const gisRef = useRef<HTMLDivElement | null>(null);
  const authedRef = useRef(onAuthed);
  const langRef = useRef(lang);

  useEffect(() => { authedRef.current = onAuthed; }, [onAuthed]);
  useEffect(() => { langRef.current = lang; }, [lang]);

  useEffect(() => {
    fetch("/api/auth/social-config")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setSocialCfg)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!socialCfg) return;
    const w = window as any;
    const initGoogle = () => {
      try {
        w.google.accounts.id.initialize({
          client_id: socialCfg.google.client_id,
          callback: (resp: { credential?: string }) => {
            if (!resp?.credential) return;
            setBusy(true); setError(null);
            fetch("/api/auth/social/google", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ credential: resp.credential, lang: langRef.current }),
            })
              .then((r) => r.json())
              .then((b) => {
                if (!b.token) throw new Error(b.detail || "error");
                authedRef.current(b.user, b.token);
              })
              .catch((e) => setError(e instanceof Error ? e.message : String(e)))
              .finally(() => setBusy(false));
          },
        });
        if (gisRef.current) {
          w.google.accounts.id.renderButton(gisRef.current, {
            theme: "outline", size: "large", width: 320, text: "continue_with",
          });
        }
      } catch { /* GSI unavailable offline — simulated fallback stays */ }
    };
    const initApple = () => {
      try {
        w.AppleID.auth.init({
          clientId: socialCfg.apple.client_id,
          scope: "name email",
          redirectURI: window.location.origin + "/",
          usePopup: true,
        });
      } catch { /* Apple JS unavailable */ }
    };
    const load = (src: string, onload: () => void) => {
      const s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = onload;
      document.head.appendChild(s);
    };
    if (socialCfg.google.enabled && socialCfg.google.client_id) {
      if (w.google?.accounts?.id) initGoogle();
      else load("https://accounts.google.com/gsi/client", initGoogle);
    }
    if (socialCfg.apple.enabled) {
      if (w.AppleID) initApple();
      else load(
        "https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js",
        initApple,
      );
    }
  }, [socialCfg]);

  const appleSignIn = async () => {
    const w = window as any;
    if (!w.AppleID) return;
    setBusy(true); setError(null);
    try {
      const res = await w.AppleID.auth.signIn();
      const idToken = res?.authorization?.id_token;
      if (!idToken) throw new Error("لم يصل توكن Apple");
      const r = await fetch("/api/auth/social/apple", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken, lang: langRef.current }),
      });
      const b = await r.json();
      if (!r.ok || !b.token) throw new Error(b.detail || "error");
      authedRef.current(b.user, b.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const showRealSocial = !!(socialCfg && (socialCfg.google.enabled || socialCfg.apple.enabled));

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submitSignup = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, lang }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "error");
      setPending({ email: form.email, dev_code: body.dev_code ?? null });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const submitActivate = async () => {
    if (!pending) return;
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/auth/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: pending.email, code, lang }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "error");
      // auto-login after activation
      const loginRes = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: form.username, password: form.password, lang }),
      });
      const loginBody = await loginRes.json();
      if (!loginRes.ok) throw new Error(loginBody.detail || "error");
      onAuthed(loginBody.user, loginBody.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const submitLogin = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: form.username, password: form.password, lang }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "error");
      onAuthed(body.user, body.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const submitSocial = async () => {
    if (!social) return;
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/auth/social", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: social, email: socialEmail,
          full_name: socialName || null, lang,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "error");
      onAuthed(body.user, body.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="close">
          <Glyph name="cross" size={13} />
        </button>

        {!pending && social ? (
          <>
            <h3>{T.socialTitle[lang]} {social === "google" ? "Google" : "Apple"}</h3>
            <p className="values-hint">{T.socialHint[lang]}</p>
            {error && <div className="error-box">{error}</div>}
            {mode === "signup" && (
              <label>
                <small>{T.name[lang]}</small>
                <input value={socialName} onChange={(e) => setSocialName(e.target.value)} />
              </label>
            )}
            <label>
              <small>{T.email[lang]}</small>
              <input type="email" value={socialEmail} onChange={(e) => setSocialEmail(e.target.value)} dir="ltr" />
            </label>
            <button
              className="btn-primary wide"
              disabled={busy || !socialEmail}
              onClick={submitSocial}
            >
              {busy ? T.sending[lang] : T.socialContinue[lang]}
            </button>
            <button className="link-btn" onClick={() => { setSocial(null); setError(null); }}>
              {T.back[lang]}
            </button>
          </>
        ) : !pending ? (
          <>
            <h3>{mode === "signup" ? T.signup[lang] : T.login[lang]}</h3>
            {error && <div className="error-box">{error}</div>}
            {mode === "signup" && (
              <>
                <label>
                  <small>{T.name[lang]}</small>
                  <input value={form.full_name} onChange={set("full_name")} />
                </label>
                <label>
                  <small>{T.email[lang]}</small>
                  <input type="email" value={form.email} onChange={set("email")} dir="ltr" />
                </label>
                <label>
                  <small>{T.country[lang]}</small>
                  <input value={form.country} onChange={set("country")} />
                </label>
              </>
            )}
            <label>
              <small>{T.username[lang]}</small>
              <input value={form.username} onChange={set("username")} dir="ltr" />
            </label>
            <label>
              <small>{T.password[lang]}</small>
              <input type="password" value={form.password} onChange={set("password")} dir="ltr" />
            </label>
            {mode === "signup" && (
              <label>
                <small>{T.confirmPassword[lang]}</small>
                <input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} dir="ltr" />
              </label>
            )}
            {mode === "signup" && confirmPw !== "" && confirmPw !== form.password && (
              <div className="error-box">{T.mismatch[lang]}</div>
            )}
            <button
              className="btn-primary wide"
              disabled={busy || !form.username || !form.password ||
                (mode === "signup" && (!form.full_name || !form.email || confirmPw !== form.password))}
              onClick={mode === "signup" ? submitSignup : submitLogin}
            >
              {busy ? T.sending[lang] : mode === "signup" ? T.confirm[lang] : T.login[lang]}
            </button>
            {showRealSocial ? (
              <>
                <div className="social-divider"><span>{T.or[lang]}</span></div>
                <div className="social-btns">
                  {socialCfg?.google.enabled && <div ref={gisRef} className="gis-host" />}
                  {socialCfg?.apple.enabled && (
                    <button type="button" className="social-btn" onClick={appleSignIn} disabled={busy}>
                      <AppleIcon />
                      <span>{(mode === "signup" ? T.socialSignupApple : T.socialLoginApple)[lang]}</span>
                    </button>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="social-divider"><span>{T.or[lang]}</span></div>
                <div className="social-btns">
                  <button type="button" className="social-btn" onClick={() => setSocial("google")}>
                    <GoogleIcon />
                    <span>{(mode === "signup" ? T.socialSignupGoogle : T.socialLoginGoogle)[lang]}</span>
                  </button>
                  <button type="button" className="social-btn" onClick={() => setSocial("apple")}>
                    <AppleIcon />
                    <span>{(mode === "signup" ? T.socialSignupApple : T.socialLoginApple)[lang]}</span>
                  </button>
                </div>
              </>
            )}
            <button className="link-btn" onClick={() => onSwitch(mode === "signup" ? "login" : "signup")}>
              {mode === "signup" ? T.haveAccount[lang] : T.noAccount[lang]}
            </button>
          </>
        ) : (
          <>
            <h3>{T.verify[lang]}</h3>
            <p className="values-hint">{T.sentHint[lang]}</p>
            {pending.dev_code && (
              <div className="dev-code">
                {T.devHint[lang]}: <strong>{pending.dev_code}</strong>
              </div>
            )}
            {error && <div className="error-box">{error}</div>}
            <label>
              <small>{T.code[lang]}</small>
              <input value={code} onChange={(e) => setCode(e.target.value)} dir="ltr" inputMode="numeric" />
            </label>
            <button className="btn-primary wide" disabled={busy || !code} onClick={submitActivate}>
              {busy ? T.sending[lang] : T.confirm[lang]}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// Per-plan feature lists — MIRROR the landing page's pricing cards
// (Landing.tsx) so the paywall never advertises less than the marketing page.
const PLAN_FEATURES: Record<string, { ar: string; en: string }[]> = {
  pro: [
    { ar: "5 تحليلات شهريًا", en: "5 analyses / month" },
    { ar: "كل مزايا المجانية + تنبؤات وسيناريوهات موسّعة", en: "Everything in Free + extended forecasts & scenarios" },
    { ar: "تصدير PDF وExcel وPowerPoint بلا قيود", en: "Unlimited PDF, Excel and PowerPoint exports" },
  ],
  business: [
    { ar: "20 تحليلاً شهريًا", en: "20 analyses / month" },
    { ar: "كل مزايا برو", en: "Everything in Pro" },
    { ar: "أولوية قصوى في المعالجة والدعم — للفرق والمكاتب", en: "Top processing & support priority — for teams and firms" },
  ],
};

export function PaywallModal({
  lang,
  token,
  onClose,
  onPaid,
}: {
  lang: Lang;
  token: string;
  onClose: () => void;
  onPaid: () => void;
}) {
  const [card, setCard] = useState({ card_number: "", holder: "", expiry: "", cvv: "" });
  const [plans, setPlans] = useState<PlanInfo[]>([]);
  const [plan, setPlan] = useState("pro");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    fetch("/api/subscription/plans")
      .then((r) => r.json())
      .then((b) => setPlans(b.plans ?? []))
      .catch(() => {});
  }, []);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/subscription/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ...card, plan, lang }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "error");
      setDone(true);
      setTimeout(onPaid, 900);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const set = (k: keyof typeof card) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setCard({ ...card, [k]: e.target.value });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="close">
          <Glyph name="cross" size={13} />
        </button>
        <h3>💳 {T.cardTitle[lang]}</h3>
        <p className="values-hint">{T.cardHint[lang]}</p>
        {plans.length > 0 && (
          <div className="plans-grid">
            {plans.map((p) => {
              const feats = PLAN_FEATURES[p.key] ?? [];
              return (
                <button
                  key={p.key}
                  type="button"
                  className={`plan-card ${plan === p.key ? "selected" : ""}`}
                  onClick={() => setPlan(p.key)}
                >
                  <span className="plan-name">{lang === "ar" ? p.ar : p.en}</span>
                  <span className="plan-price">${p.price}</span>
                  <span className="plan-quota">
                    {p.uploads === null
                      ? (lang === "ar" ? "تحليل غير محدود" : "Unlimited analyses")
                      : (lang === "ar" ? `${p.uploads} تحليل / شهر` : `${p.uploads} analyses / mo`)}
                  </span>
                  {feats.length > 0 && (
                    <ul className="plan-features">
                      {feats.map((f, i) => (
                        <li key={i}>{(lang === "ar" ? f.ar : f.en) as string}</li>
                      ))}
                    </ul>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {done ? (
          <div className="dev-code">{T.paid[lang]}</div>
        ) : (
          <>
            {error && <div className="error-box">{error}</div>}
            <label>
              <small>{T.cardNumber[lang]}</small>
              <input value={card.card_number} onChange={set("card_number")} dir="ltr" inputMode="numeric" placeholder="4242 4242 4242 4242" />
            </label>
            <label>
              <small>{T.cardHolder[lang]}</small>
              <input value={card.holder} onChange={set("holder")} dir="ltr" />
            </label>
            <div className="row-2">
              <label>
                <small>{T.expiry[lang]}</small>
                <input value={card.expiry} onChange={set("expiry")} dir="ltr" placeholder="12/28" />
              </label>
              <label>
                <small>{T.cvv[lang]}</small>
                <input value={card.cvv} onChange={set("cvv")} dir="ltr" inputMode="numeric" placeholder="123" />
              </label>
            </div>
            <button
              className="btn-primary wide"
              disabled={busy || !card.card_number || !card.holder || !card.expiry || !card.cvv}
              onClick={submit}
            >
              {busy ? T.sending[lang] : T.pay[lang]}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
