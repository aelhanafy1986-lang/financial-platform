import type { Lang } from "./types";

/** Shared authenticated-download helper (blob + <a download>). Lived in
 *  Dashboard.tsx; extracted so PaymentsPage can reuse it for invoice PDFs.
 *  402 → opens the paywall (downloads are subscription-gated). */
export function useDownload(
  token: string | null,
  openPaywall: () => void,
  toast: (t: string) => void,
  lang: Lang,
  labels: { loginNeeded: string; payNeeded: string },
) {
  return async (url: string, fallbackName: string) => {
    const sep = url.includes("?") ? "&" : "?";
    const res = await fetch(`${url}${sep}auth_token=Bearer%20${token ?? ""}`);
    if (res.status === 401) {
      toast(labels.loginNeeded);
      return;
    }
    if (res.status === 402) {
      toast(labels.payNeeded);
      openPaywall();
      return;
    }
    if (!res.ok) {
      toast(`${res.status}`);
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fallbackName;
    a.click();
    URL.revokeObjectURL(a.href);
  };
}
