# -*- coding: utf-8 -*-
"""Sidebar «مدقق» badge: the /api/analyses list carries an explicit
``audited`` flag — True only when the quality gate RAN on the analysis and
found NOTHING to flag. Legacy rows without an audit record are never
badged (they were never verified), and any error/warning finding revokes
the badge.
"""

import io
import json

from openpyxl import Workbook

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload_simple(client) -> int:
    wb = Workbook()
    ws = wb.active
    ws.title = "المقارنة"
    for row in [
        ["البند", "عام 2024", "عام 2025"],
        ["إجمالي المبيعات", 500000, 650000],
        ["تكلفة المبيعات", 300000, 380000],
        ["المصاريف التشغيلية", 70000, 85000],
    ]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = client.post(
        "/api/upload",
        files={"files": ("سليم.xlsx", buf, XLSX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["uploaded"][0]["id"]


def _meta(client, aid: int) -> dict:
    items = client.get("/api/analyses").json()
    return next(i for i in items if i["id"] == aid)


def test_clean_upload_is_audited(client):
    aid = _upload_simple(client)
    try:
        meta = _meta(client, aid)
        assert meta["audited"] is True
        assert meta["audit_errors"] == 0
        assert meta["audit_warnings"] == 0
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_warning_finding_revokes_audited(client):
    aid = _upload_simple(client)
    try:
        import app.database as database

        with database.SessionLocal() as db:
            row = db.get(database.Analysis, aid)
            res = json.loads(row.result_json)
            res["audit"] = {
                "ok": True,
                "errors": [],
                "warnings": [{"code": "W9", "severity": "warning",
                              "ar": "تنبيه تجريبي", "en": "test warning"}],
                "repairs": [],
                "checked_at": "2026-10-03T00:00:00+00:00",
            }
            row.result_json = json.dumps(res, ensure_ascii=False)
            db.commit()

        meta = _meta(client, aid)
        assert meta["audit_warnings"] == 1
        assert meta["audited"] is False
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_error_finding_revokes_audited(client):
    aid = _upload_simple(client)
    try:
        import app.database as database

        with database.SessionLocal() as db:
            row = db.get(database.Analysis, aid)
            res = json.loads(row.result_json)
            res["audit"] = {
                "ok": False,
                "errors": [{"code": "C7", "severity": "error",
                            "ar": "خطأ تجريبي", "en": "test error"}],
                "warnings": [],
                "repairs": [],
                "checked_at": "2026-10-03T00:00:00+00:00",
            }
            row.result_json = json.dumps(res, ensure_ascii=False)
            db.commit()

        meta = _meta(client, aid)
        assert meta["audit_errors"] == 1
        assert meta["audited"] is False
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)


def test_legacy_row_without_audit_not_audited(client):
    """A row whose audit record is absent was never verified — no badge."""
    aid = _upload_simple(client)
    try:
        import app.database as database

        with database.SessionLocal() as db:
            row = db.get(database.Analysis, aid)
            res = json.loads(row.result_json)
            res.pop("audit", None)
            row.result_json = json.dumps(res, ensure_ascii=False)
            db.commit()

        meta = _meta(client, aid)
        assert "audited" in meta
        assert meta["audited"] is False
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
