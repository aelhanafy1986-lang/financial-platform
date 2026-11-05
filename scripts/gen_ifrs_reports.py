# -*- coding: utf-8 -*-
"""Login and generate live reports for analysis 11 to verify IFRS content."""
import httpx

BASE = "http://127.0.0.1:8000"

r = httpx.post(f"{BASE}/api/auth/login", json={
    "username": "admin", "password": "Admin@2026", "lang": "ar"}, timeout=30)
print("login:", r.status_code)
token = r.json().get("token") or r.json().get("access_token")
assert token, r.text[:300]

jobs = [
    ("GET", f"{BASE}/api/analyses/11/report?lang=ar", "reports/report_11_ar.pdf"),
    ("GET", f"{BASE}/api/analyses/11/report?lang=en", "reports/report_11_en.pdf"),
    ("GET", f"{BASE}/api/analyses/11/pptx?lang=ar", "reports/pptx_11_ar.pptx"),
    ("GET", f"{BASE}/api/analyses/11/export?lang=ar", "reports/excel_11_ar.xlsx"),
]
hdr = {"Authorization": f"Bearer {token}"}
for method, url, out in jobs:
    resp = httpx.request(method, url, headers=hdr, timeout=120)
    ok = resp.status_code == 200 and len(resp.content) > 1000
    if ok:
        with open(out, "wb") as f:
            f.write(resp.content)
    print(f"{out}: {resp.status_code}, {len(resp.content)} bytes, ok={ok}")
    if not ok:
        print(resp.text[:300])
