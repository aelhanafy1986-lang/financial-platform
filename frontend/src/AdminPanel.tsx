import { useCallback, useEffect, useState } from "react";
import type { AdminUser, Lang } from "./types";

const T = {
  title: { ar: "🛡 لوحة المدير", en: "🛡 Admin panel" },
  users: { ar: "المستخدمون", en: "Users" },
  username: { ar: "المستخدم", en: "User" },
  email: { ar: "البريد", en: "Email" },
  status: { ar: "الحالة", en: "Status" },
  sub: { ar: "الاشتراك", en: "Subscription" },
  actions: { ar: "إجراءات", en: "Actions" },
  grant: { ar: "تفعيل PRO", en: "Grant PRO" },
  revoke: { ar: "إلغاء PRO", en: "Revoke PRO" },
  disable: { ar: "تعطيل", en: "Disable" },
  enable: { ar: "تنشيط", en: "Enable" },
  you: { ar: "أنت", en: "you" },
  noUsers: { ar: "لا يوجد مستخدمون", en: "No users" },
};

export function AdminPanel({ token, lang }: { token: string; lang: Lang }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`error ${res.status}`);
      setUsers((await res.json()).users);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (id: number, body: object, path: string) => {
    setBusyId(id);
    try {
      const res = await fetch(`/api/admin/users/${id}/${path}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error(b.detail || `error ${res.status}`);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  if (error) return <div className="admin-panel"><div className="error-box">{error}</div></div>;

  return (
    <div className="admin-panel">
      <h3>{T.title[lang]}</h3>
      {users === null ? (
        <div className="placeholder">…</div>
      ) : users.length === 0 ? (
        <div className="placeholder">{T.noUsers[lang]}</div>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>{T.username[lang]}</th>
              <th>{T.email[lang]}</th>
              <th>{T.status[lang]}</th>
              <th>{T.sub[lang]}</th>
              <th>{T.actions[lang]}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.status === "disabled" ? "row-disabled" : ""}>
                <td>
                  <strong>{u.username}</strong>
                  {u.is_admin && <span className="badge admin">ADMIN</span>}
                </td>
                <td dir="ltr">{u.email}</td>
                <td>{u.status}</td>
                <td>
                  {u.subscription === "paid"
                    ? `PRO${u.plan ? ` · ${u.plan}` : ""}`
                    : "free"}
                  {u.uploads_used ? <small> ({u.uploads_used})</small> : null}
                </td>
                <td className="row-actions">
                  {!u.is_admin && (
                    <>
                      {u.subscription === "paid" ? (
                        <button
                          className="btn small ghost"
                          disabled={busyId === u.id}
                          onClick={() =>
                            act(u.id, { subscription: "free", lang }, "subscription")
                          }
                        >
                          {T.revoke[lang]}
                        </button>
                      ) : (
                        <button
                          className="btn small save"
                          disabled={busyId === u.id}
                          onClick={() =>
                            act(u.id, { subscription: "paid", plan: "pro", lang }, "subscription")
                          }
                        >
                          {T.grant[lang]}
                        </button>
                      )}
                      {u.status === "disabled" ? (
                        <button
                          className="btn small save"
                          disabled={busyId === u.id}
                          onClick={() => act(u.id, { active: true, lang }, "status")}
                        >
                          {T.enable[lang]}
                        </button>
                      ) : (
                        <button
                          className="btn small ghost"
                          disabled={busyId === u.id}
                          onClick={() => act(u.id, { active: false, lang }, "status")}
                        >
                          {T.disable[lang]}
                        </button>
                      )}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
