# -*- coding: utf-8 -*-
"""Reading-sample inspector — the «did it read my file RIGHT?» trust view.

GET /api/analyses/{id}/reading-sample rebuilds the extractor's exact view
of the stored original: tables with their detected kind, column roles
(label / period / value / excluded), and rows accepted vs rejected with
reasons — with the SAME predicates the metric extractor uses.
"""

import io

from openpyxl import Workbook
from fastapi.testclient import TestClient

from tests.conftest import client  # noqa: F401

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _comparative_workbook() -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "قائمة الدخل"
    ws.append(["البند", "عام 2024", "عام 2025", "نسبة التغير"])
    ws.append(["إيرادات المبيعات", 500000, 650000, 0.3])
    ws.append(["تكلفة المبيعات", -300000, -380000, 0.267])
    ws.append(["مجمل الربح", 200000, 270000, 0.35])
    ws.append(["مصاريف بيعية", -45000, -55000, 0.222])
    ws.append(["صافي الربح", 95000, 115000, 0.21])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload(client: TestClient) -> int:
    resp = client.post(
        "/api/upload",
        files={"files": ("q.xlsx", _comparative_workbook(), XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item, item
    return item["id"]


def test_reading_sample_shape(client):
    aid = _upload(client)
    resp = client.get(f"/api/analyses/{aid}/reading-sample",
                      headers=client.auth_headers)
    assert resp.status_code == 200, resp.text
    s = resp.json()
    assert s["filename"]
    assert s["ocr_used"] is False  # a clean Excel file needs no OCR
    assert s["quality"]["score"] > 0
    assert s["tables_count"] >= 1
    t = s["tables"][0]
    # the change column is identified and EXCLUDED — the trust premise
    roles = {c["index"]: c["role"] for c in t["columns"]}
    assert "excluded" in roles.values()
    # header row rejected as summary; money rows accepted
    reasons = [r["reason"] for r in t["rows"]]
    assert any(r.startswith("summary:") for r in reasons)
    assert "accepted" in reasons
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_reading_sample_missing_file_is_409(client):
    aid = _upload(client)
    import sqlite3

    from app.database import DB_PATH

    db = sqlite3.connect(str(DB_PATH))
    db.execute("UPDATE analyses SET original_path=NULL WHERE id=?", (aid,))
    db.commit()
    db.close()
    resp = client.get(f"/api/analyses/{aid}/reading-sample",
                      headers=client.auth_headers)
    assert resp.status_code == 409
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_reading_sample_reads_are_public_like_the_platform(client):
    """Documented convention: reading endpoints are unauthenticated (all
    signed-in-or-public GETs read analyses freely; downloads paywall only)."""
    aid = _upload(client)
    resp = client.get(f"/api/analyses/{aid}/reading-sample")
    assert resp.status_code == 200
    client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
