import { useContext, useEffect, useState } from "react";
import { AuthContext } from "./App";
import { useDownload } from "./useDownload";
import type { Lang } from "./types";

/** «سجل المدفوعات» — payments & invoices log for the signed-in account.
 *  Full page in the dashboard main pane (opened from the side rail). Empty
 *  state shows a card glyph with «سجلّ المدفوعات هنا بعد أول عملية دفع» and
 *  an «عرض الخطة» CTA (opens the current upgrade flow); once the account
 *  has charges every simulated activation row appears here: invoice no.,
 *  plan, amount, masked card and ISO date, newest first. */

interface PaymentRow {
  id: number;
  plan: string;
  amount: number;
  currency: string;
  masked_card: string | null;
  status: string;
  invoice_no: string | null;
  paid_at: string;
}

const PLAN_AR: Record<string, string> = {
  pro: "برو",
  business: "الأعمال",
  firm: "المؤسسات",
  monthly: "شهري",
  yearly: "سنوي",
};

const T = {
  headTitle: { ar: "سجل المدفوعات", en: "Payment history" },
  headSub: {
    ar: "عرض جميع معاملات الدفع الخاصة بك",
    en: "All your payment transactions in one place",
  },
  cardTitle: { ar: "سجل المدفوعات", en: "Payment history" },
  emptyTitle: { ar: "لا توجد مدفوعات", en: "No payments yet" },
  emptyHint: {
    ar: "سيظهر سجل المدفوعات هنا بعد أول عملية دفع",
    en: "Your payment history appears here after your first payment",
  },
  seePlan: { ar: "عرض الخطة", en: "View plan" },
  invoice: { ar: "رقم الفاتورة", en: "Invoice" },
  plan: { ar: "الباقة", en: "Plan" },
  amount: { ar: "المبلغ", en: "Amount" },
  card: { ar: "البطاقة", en: "Card" },
  date: { ar: "التاريخ", en: "Date" },
  status: { ar: "الحالة", en: "Status" },
  paid: { ar: "مدفوع", en: "Paid" },
  pdf: { ar: "فاتورة PDF", en: "Invoice PDF" },
  count: { ar: "عملية", en: "transactions" },
  allPlans: { ar: "كل الباقات", en: "All plans" },
  from: { ar: "من", en: "From" },
  to: { ar: "إلى", en: "To" },
  clear: { ar: "مسح", en: "Clear" },
  total: { ar: "إجمالي المدفوعات", en: "Total paid" },
  method: { ar: "وسيلة الدفع الحالية", en: "Current payment method" },
  none: { ar: "لم تُسجَّل بعد", en: "none yet" },
  expires: { ar: "الباقة تنتهي", en: "Plan expires" },
  shown: { ar: "معروضة", en: "shown" },
  of: { ar: "من", en: "of" },
};

export default function PaymentsPage({
  lang,
  token,
  onSeePlan,
  openPaywall,
}: {
  lang: Lang;
  token: string;
  onSeePlan: () => void;
  openPaywall: () => void;
}) {
  const { user } = useContext(AuthContext);
  const [rows, setRows] = useState<PaymentRow[] | null>(null);
  const [error, setError] = useState(false);
  // filters: plan key ("" = all) + inclusive date range (YYYY-MM-DD)
  const [plan, setPlan] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  // invoice PDFs use the same authenticated blob download as reports;
  // localised toasts for 401/402 (they live in Dashboard's VALUE_LABELS)
  const downloadInvoice = useDownload(token, openPaywall, (t) => t, lang, {
    loginNeeded: lang === "ar" ? "سجّل الدخول لتحميل الملفات والتقارير" : "Log in to download files and reports",
    payNeeded: lang === "ar" ? "يتطلب تحميل التقارير سداد الاشتراك" : "Subscription required to download reports",
  });

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const res = await fetch("/api/subscription/payments", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(String(res.status));
        const body = await res.json();
        if (!dead) setRows(body.payments ?? []);
      } catch {
        if (!dead) setError(true);
      }
    })();
    return () => {
      dead = true;
    };
  }, [token]);

  // client-side filtering over the already-fetched ledger (small N)
  const filtered = (rows ?? []).filter((r) => {
    if (plan && r.plan !== plan) return false;
    const day = r.paid_at?.slice(0, 10) ?? "";
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  });
  const total = filtered.reduce((s, r) => s + (r.amount || 0), 0);
  const isFiltered = !!(plan || from || to);

  return (
    <div className="payments-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <header className="pay-head">
        <div>
          <h2>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
              <rect x="2.5" y="5" width="19" height="14" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
              <path d="M2.5 9.5h19" stroke="currentColor" strokeWidth="1.8" />
            </svg>
            {T.headTitle[lang]}
          </h2>
          <p>{T.headSub[lang]}</p>
        </div>
        {/* current payment method — straight from the context user (/me):
            masked card + plan expiry, no extra request */}
        <div className="pay-method">
          <span className="pay-method-label">{T.method[lang]}:</span>
          <span className="pay-method-card mono">
            {user?.masked_card || T.none[lang]}
          </span>
          {user?.plan_expires && (
            <span className="pay-method-exp">
              {T.expires[lang]}: {user.plan_expires.slice(0, 10)}
            </span>
          )}
        </div>
      </header>

      <section className="panel pay-panel">
        <div className="pay-panel-head">
          <span className="pay-panel-title">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" aria-hidden="true">
              <rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.7" />
              <path d="M9 7h6M9 11h6M9 15h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            {T.cardTitle[lang]}
          </span>
          {rows && rows.length > 0 && (
            <span className="pay-count">
              {rows.length} {T.count[lang]}
            </span>
          )}
        </div>

        {/* filter bar + running total — only when there is a ledger */}
        {rows !== null && rows.length > 0 && (
          <div className="pay-filters">
            <label>
              <span>{T.plan[lang]}</span>
              <select value={plan} onChange={(e) => setPlan(e.target.value)}>
                <option value="">{T.allPlans[lang]}</option>
                {Object.entries(PLAN_AR).map(([k, ar]) => (
                  <option key={k} value={k}>
                    {lang === "ar" ? ar : (k === "pro" ? "Pro" : k === "business" ? "Business" : k)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{T.from[lang]}</span>
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>
              <span>{T.to[lang]}</span>
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </label>
            {isFiltered && (
              <button type="button" className="btn small ghost" onClick={() => { setPlan(""); setFrom(""); setTo(""); }}>
                {T.clear[lang]}
              </button>
            )}
            <span className="pay-total">
              {T.total[lang]}: <b>${total.toFixed(2)}</b>
              {isFiltered && filtered.length !== rows.length && (
                <small className="pay-total-scope">
                  ({filtered.length} {T.shown[lang]} {T.of[lang]} {rows.length})
                </small>
              )}
            </span>
          </div>
        )}

        {rows === null && !error && <p className="rs-empty">…</p>}
        {error && <p className="rs-empty">{lang === "ar" ? "تعذّر تحميل السجل — أعد المحاولة" : "Couldn't load history — try again"}</p>}

        {rows !== null && rows.length === 0 && (
          <div className="pay-empty">
            <span className="pay-empty-icon">
              <svg viewBox="0 0 24 24" width="40" height="40" fill="none" aria-hidden="true">
                <rect x="2.5" y="5" width="19" height="14" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
                <path d="M2.5 9.5h19" stroke="currentColor" strokeWidth="1.8" />
              </svg>
            </span>
            <strong>{T.emptyTitle[lang]}</strong>
            <p>{T.emptyHint[lang]}</p>
            <button type="button" className="btn small save" onClick={onSeePlan}>
              {T.seePlan[lang]}
            </button>
          </div>
        )}

        {rows !== null && rows.length > 0 && (
          <div className="pay-scroll">
            <table className="pay-table">
              <thead>
                <tr>
                  <th>{T.invoice[lang]}</th>
                  <th>{T.plan[lang]}</th>
                  <th>{T.amount[lang]}</th>
                  <th>{T.card[lang]}</th>
                  <th>{T.date[lang]}</th>
                  <th>{T.status[lang]}</th>
                  <th>{T.pdf[lang]}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.invoice_no}</td>
                    <td>{PLAN_AR[r.plan] ?? r.plan}</td>
                    <td className="mono">
                      ${r.amount?.toFixed?.(2) ?? r.amount}
                    </td>
                    <td className="mono">{r.masked_card}</td>
                    <td className="mono">{r.paid_at?.slice(0, 16).replace("T", " ")}</td>
                    <td>
                      <span className="badge ok">{T.paid[lang]}</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn small ghost pay-pdf-btn"
                        title={"PDF"}
                        onClick={() => downloadInvoice(`/api/subscription/payments/${r.id}/invoice?lang=${lang}`, `invoice-${r.invoice_no || r.id}.pdf`)}
                      >
                        ⬇ PDF
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
