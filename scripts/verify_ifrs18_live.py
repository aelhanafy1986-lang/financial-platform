# -*- coding: utf-8 -*-
"""Live end-to-end verification of the IFRS 18 income-statement classification.

Creates a demo analysis, attaches a trial balance that carries financing /
investing / tax items, prints the classified income statement face returned
by the API, then deletes the temporary analysis.
"""
import io

import httpx
from openpyxl import Workbook

BASE = "http://127.0.0.1:8000"

TB_ROWS = [
    ["الحساب", "مدين", "دائن"],
    ["النقدية بالبنك", 700_000, 0],
    ["مدينون - العملاء", 85_000, 0],
    ["رأس المال", 0, 500_000],
    ["ايرادات المبيعات", 0, 1_000_000],
    ["تكلفة المبيعات", 600_000, 0],
    ["مصاريف رواتب", 80_000, 0],
    ["فوائد قروض", 40_000, 0],
    ["عوائد ودائع بنكية", 0, 15_000],
    ["زكاة الدخل", 10_000, 0],
]


def main() -> None:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "username": "admin", "password": "Admin@2026", "lang": "ar"}, timeout=30)
    token = r.json().get("token") or r.json().get("access_token")
    hdr = {"Authorization": f"Bearer {token}"}

    demo = httpx.post(f"{BASE}/api/demo", timeout=60).json()
    aid = demo["id"]
    print(f"demo analysis id={aid}")

    wb = Workbook()
    ws = wb.active
    for row in TB_ROWS:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = httpx.post(
        f"{BASE}/api/analyses/{aid}/trial-balance",
        files={"file": ("tb_ifrs18.xlsx", buf,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=hdr, timeout=120,
    )
    print("trial-balance attach:", resp.status_code)
    if resp.status_code != 200:
        print(resp.text[:400])
        return

    st = httpx.get(f"{BASE}/api/analyses/{aid}/statements", headers=hdr, timeout=60).json()
    isx = st.get("statements", st).get("income_statement")
    print("\n--- income statement face (from API) ---")
    for ln in isx["lines"]:
        bold = "*" if ln.get("bold") else " "
        cat = ln.get("category", "-")
        print(f" {bold} {ln['en']:<45} {ln['amount']:>14,.2f}   [{cat}]")
    print("\nifrs18 meta:", {
        "applied": isx["ifrs18"]["applied"],
        "categories": isx["ifrs18"]["categories"],
    })
    print("totals keys:", sorted(isx["totals"].keys()))
    bs = st.get("statements", st).get("balance_sheet")
    print(f"balance sheet balanced: {bs['balanced']} (assets {bs['assets']['total']:,.0f} "
          f"= L+E {bs['liabilities_equity']['total']:,.0f})")

    del_resp = httpx.delete(f"{BASE}/api/analyses/{aid}", headers=hdr, timeout=30)
    print("\ncleanup: deleted demo analysis", aid, "->", del_resp.status_code)


if __name__ == "__main__":
    main()
