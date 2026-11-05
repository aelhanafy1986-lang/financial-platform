import { createContext, useCallback, useContext, useEffect, useState } from "react";
import Dashboard from "./Dashboard";
import Landing from "./Landing";
import { AuthModal, PaywallModal } from "./AuthModal";
import { FALLBACK_LABELS, type AuthUser, type Labels, type Lang, type Theme } from "./types";

interface Toast {
  id: number;
  text: string;
}

const ToastContext = createContext<(text: string) => void>(() => {});

// useToast(): show a green success toast from any component.
export function useToast() {
  return useContext(ToastContext);
}

// Theme context: lets any panel read the current user preferences.
export const ThemeContext = createContext<Theme>({ primary: "#0f766e", font: "Cairo" });
export const AuthContext = createContext<{
  user: AuthUser | null;
  token: string | null;
  refresh: () => void;
  openPaywall: () => void;
}>({ user: null, token: null, refresh: () => {}, openPaywall: () => {} });

const THEMES: { name: string; primary: string; swatch: string }[] = [
  { name: "تركوازي", primary: "#0f766e", swatch: "#0f766e" },
  { name: "بنفسجي", primary: "#7c3aed", swatch: "#7c3aed" },
  { name: "أزرق", primary: "#2563eb", swatch: "#2563eb" },
  { name: "أخضر", primary: "#059669", swatch: "#059669" },
  { name: "ذهبي", primary: "#b45309", swatch: "#d97706" },
  { name: "كحلي", primary: "#1e3a5f", swatch: "#1e3a5f" },
];

const FONTS = [
  { name: "Cairo", label: "القاهرة" },
  { name: "Tajawal", label: "تجوال" },
  { name: "Almarai", label: "المراعي" },
  { name: "Segoe UI", label: "Segoe UI" },
  { name: "Tahoma", label: "Tahoma" },
];

const T = {
  logout: { ar: "تسجيل الخروج", en: "Log out" },
  customize: { ar: "🎨 تخصيص", en: "🎨 Theme" },
  lastLogin: { ar: "آخر دخول", en: "Last login" },
  siteStats: { ar: "إحصاءات الموقع العامة", en: "Public site statistics" },
  footer: {
    ar: "منصة تحليل مالي — تعمل محلياً بالكامل",
    en: "Financial analytics platform — runs fully locally",
  },
};

function applyTheme(theme: Theme) {
  document.documentElement.style.setProperty("--brand", theme.primary);
  // soft variant: 12% alpha over white-ish backgrounds
  document.documentElement.style.setProperty("--brand-soft", theme.primary + "26");
  document.body.style.fontFamily = `"${theme.font}", "Segoe UI", Tahoma, sans-serif`;
}

export default function App() {
  const [lang, setLang] = useState<Lang>("ar");
  const [labels, setLabels] = useState<Labels>(FALLBACK_LABELS);
  const [toasts, setToasts] = useState<Toast[]>([]);
  // view: landing (public) | app (inside the platform)
  const [view, setView] = useState<"landing" | "app">("landing");
  const [authModal, setAuthModal] = useState<"login" | "signup" | null>(null);
  // where the auth flow was opened from: plain signup keeps the visitor on
  // the landing page after registering, «لوحة التحكم» entries go straight in
  const [authVia, setAuthVia] = useState<"signup" | "login" | "dashboard">("signup");
  const [paywall, setPaywall] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>({ primary: "#0f766e", font: "Cairo" });
  const [showCustomize, setShowCustomize] = useState(false);

  const toast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, 3500);
  }, []);

  useEffect(() => {
    fetch("/api/labels")
      .then((r) => r.json())
      .then(setLabels)
      .catch(() => setLabels(FALLBACK_LABELS));
  }, []);

  // Brand identity: the browser tab carries the brand name in the ACTIVE
  // language (index.html ships the Arabic default; this keeps EN in sync).
  useEffect(() => {
    document.title = labels.title?.[lang] ?? FALLBACK_LABELS.title[lang];
  }, [lang, labels]);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Restore the session on first load.
  useEffect(() => {
    const saved = localStorage.getItem("sfp_session");
    if (!saved) return;
    fetch("/api/auth/me", { headers: { Authorization: `Bearer ${saved}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((u) => {
        setUser(u);
        setToken(saved);
        setView("app");
      })
      .catch(() => localStorage.removeItem("sfp_session"));
  }, []);

  const onAuthed = (u: AuthUser, t: string) => {
    setUser(u);
    setToken(t);
    localStorage.setItem("sfp_session", t);
    setAuthModal(null);
    // plain landing-page signup stays on the marketing page; logins and
    // «لوحة التحكم» entries open the workspace directly
    setView(authVia === "signup" ? "landing" : "app");
  };

  // nav «لوحة التحكم»: signed-in → the workspace, else the signup modal
  // (which lands in the workspace right after registering)
  const openDashboard = () => {
    if (user) {
      setView("app");
      return;
    }
    setAuthVia("dashboard");
    setAuthModal("signup");
  };

  const doLogout = async () => {
    if (token) {
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      }).catch(() => {});
    }
    localStorage.removeItem("sfp_session");
    setUser(null);
    setToken(null);
    setView("landing");
  };

  return (
    <ThemeContext.Provider value={theme}>
    <AuthContext.Provider
      value={{
        user,
        token,
        refresh: () => {
          if (!token) return;
          fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } })
            .then((r) => (r.ok ? r.json() : Promise.reject()))
            .then(setUser)
            .catch(() => {});
        },
        openPaywall: () => setPaywall(true),
      }}
    >
    <ToastContext.Provider value={toast}>
    <div className="app">
      <nav className="topbar">
        <div className="brand" onClick={() => user && setView("app")} style={{ cursor: user ? "pointer" : "default" }}>
          <img className="logo-img" src="/logo.svg" alt="" />
          <span className="logo">.fin</span>
          <div className="brand-text">
            <h1>{labels.title?.[lang] ?? FALLBACK_LABELS.title[lang]}</h1>
            <small className="brand-tagline">{labels.tagline?.[lang] ?? FALLBACK_LABELS.tagline[lang]}</small>
          </div>
        </div>
        <div className="topbar-actions">
          {view === "landing" && (
            <button className="btn small save" onClick={openDashboard}>
              📊 {lang === "ar" ? "لوحة التحكم" : "Dashboard"}
            </button>
          )}
          {view === "app" && (
            <>
              <button className="icon-btn" title={T.customize[lang]} onClick={() => setShowCustomize((v) => !v)}>
                🎨
              </button>
              {user && (
                <span className="user-chip">
                  <strong>👤 {user.username}</strong>
                  {user.provider === "google" && (
                    <span className="badge social">
                      {lang === "ar" ? "حساب Google" : "Google account"}
                    </span>
                  )}
                  {user.provider === "apple" && (
                    <span className="badge social">
                      {lang === "ar" ? "حساب Apple" : "Apple account"}
                    </span>
                  )}
                  <small>
                    {T.lastLogin[lang]}:{" "}
                    {user.last_login
                      ? new Date(user.last_login).toLocaleString("en-GB", {
                          day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                        })
                      : "—"}
                  </small>
                  {user.is_admin && <span className="badge admin">ADMIN</span>}
                  {user.subscription === "paid" ? (
                    <span className="badge paid">PRO</span>
                  ) : (
                    <button className="btn small save" onClick={() => setPaywall(true)}>
                      ⭐ {lang === "ar" ? "اشترك" : "Subscribe"}
                    </button>
                  )}
                  <button className="btn small ghost" onClick={doLogout}>
                    {T.logout[lang]}
                  </button>
                </span>
              )}
            </>
          )}
          <div className="lang-toggle">
            <button className={lang === "ar" ? "active" : ""} onClick={() => setLang("ar")}>
              العربية
            </button>
            <button className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>
              English
            </button>
          </div>
        </div>
      </nav>

      {showCustomize && view === "app" && (
        <div className="customizer">
          <div className="customizer-row">
            <small>{lang === "ar" ? "اللون الأساسي" : "Primary color"}</small>
            {THEMES.map((t) => (
              <button
                key={t.primary}
                className={`swatch ${theme.primary === t.primary ? "active" : ""}`}
                style={{ background: t.swatch }}
                title={t.name}
                onClick={() => setTheme({ ...theme, primary: t.primary })}
              />
            ))}
          </div>
          <div className="customizer-row">
            <small>{lang === "ar" ? "الخط" : "Font"}</small>
            {FONTS.map((f) => (
              <button
                key={f.name}
                className={`font-choice ${theme.font === f.name ? "active" : ""}`}
                style={{ fontFamily: `"${f.name}"` }}
                onClick={() => setTheme({ ...theme, font: f.name })}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {view === "landing" ? (
        <Landing
          lang={lang}
          onSignup={() => {
            setAuthVia("signup");
            setAuthModal("signup");
          }}
          onLogin={() => {
            setAuthVia("login");
            setAuthModal("login");
          }}
          onDashboard={openDashboard}
        />
      ) : (
        <Dashboard lang={lang} t={labels} />
      )}

      <footer className="footer">
        <span>{T.footer[lang]}</span>
        <span className="footer-sep">·</span>
        <a
          href={lang === "en" ? "/stats.html?lang=en" : "/stats.html"}
          target="_blank"
          rel="noreferrer"
        >
          {T.siteStats[lang]}
        </a>
      </footer>

      {authModal && (
        <AuthModal
          mode={authModal}
          lang={lang}
          onClose={() => setAuthModal(null)}
          onAuthed={onAuthed}
          onSwitch={(m) => setAuthModal(m)}
        />
      )}

      {paywall && token && (
        <PaywallModal
          lang={lang}
          token={token}
          onClose={() => setPaywall(false)}
          onPaid={() => {
            setPaywall(false);
            // refresh subscription state
            fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } })
              .then((r) => r.json())
              .then(setUser)
              .catch(() => {});
          }}
        />
      )}

      <div className="toast-stack" aria-live="polite">
        {toasts.map((x) => (
          <div className="toast" key={x.id}>
            ✅ {x.text}
          </div>
        ))}
      </div>
    </div>
    </ToastContext.Provider>
    </AuthContext.Provider>
    </ThemeContext.Provider>
  );
}
