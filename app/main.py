"""FastAPI backend: file upload, analysis, history, PDF reports, comparison, demo data."""

from __future__ import annotations

import asyncio
import io
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .advisor import build_advisor
from .assistant import (
    assistant_reply,
    build_analysis_context,
    build_user_context,
    clear_history as assistant_clear_history,
    read_history as assistant_read_history,
    _save_turn as assistant_save_turn,
)
from .bi_export import (BI_TABLES, build_bi_pack, build_table_rows, to_csv)
from .analyzer import (EDITABLE_CONCEPTS, analyze, recompute_result,
                       result_to_metrics, table_has_revenue, texts_sample)
from .audit import run_quality_gate, validate_statements
from .auth import (
    AuthError,
    activate_subscription,
    activate_user,
    ensure_admin,
    list_users,
    login_user,
    list_payments,
    logout as auth_logout,
    register_user,
    social_auth,
    set_user_active,
    set_user_subscription,
    user_from_token,
    user_payload,
)
from .brief import (
    build_executive_brief,
    build_key_findings,
    build_strategic_recs,
)
from .compare import compare_analyses, compare_group, compare_results
from .hygiene import backfill_warnings, clean_result, data_quality_warnings
from .oauth import verify_apple_id_token, verify_google_id_token
from .ifrs import basis_of_preparation as ifrs_basis_of_preparation
from .ifrs import detect_applicable as ifrs_detect_applicable
from .ratio_explain import (
    build_benchmark_alignment,
    build_consistency_checks,
    build_ratio_insights,
    build_yearly_comparison,
    DAYS_KEYS,
    _judge,
)
from .database import (
    Analysis,
    SessionLocal,
    User,
    bump_analyses,
    bump_statements,
    bump_visits,
    get_site_stats,
    init_db,
    _sync_counters,
)
from .labels import UI
from .parsers import parse_file
from .report import (UnsupportedGlyphError, build_comparison_report,
                     build_report, build_stats_report)
from .invoice_pdf import build_invoice_pdf

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
REPORTS = ROOT / "reports"
UPLOADS.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

ALLOWED = {".xlsx", ".xlsm", ".csv", ".docx", ".pdf", ".pptx", ".png", ".jpg", ".jpeg"}
MAX_SIZE = 25 * 1024 * 1024  # 25 MB

# ---- live upload progress ---------------------------------------------
# /api/upload responds only after every file is analysed (a scanned batch
# takes ~20s per file), so the sidebar looked frozen. The upload path now
# ticks a tiny in-memory store keyed by an id the frontend mints per
# request; GET /api/upload/progress/{id} polls it. Parse runs on a worker
# thread (not the event loop) so these reads stay live DURING the upload.
_UPLOAD_PROGRESS: dict[str, dict] = {}
_UPLOAD_PROGRESS_MAX = 40  # bounded: forget the oldest jobs beyond this
_UPLOAD_PARSE_POOL = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="pb-parse"
)


def _progress_for(job_id: str) -> dict:
    slot = _UPLOAD_PROGRESS.get(job_id)
    if slot is None:
        _UPLOAD_PROGRESS[job_id] = slot = {}
    return slot


def _progress_done(job_id: str, files_done: int, files_total: int) -> None:
    slot = _UPLOAD_PROGRESS.get(job_id)
    if slot is not None:
        slot["stage"] = "done"
        slot["files_done"] = int(files_done)
        slot["files_total"] = int(files_total)
        slot["ts"] = datetime.now(timezone.utc).timestamp()
    while len(_UPLOAD_PROGRESS) > _UPLOAD_PROGRESS_MAX:
        oldest = min(_UPLOAD_PROGRESS, key=lambda k: (_UPLOAD_PROGRESS[k].get("ts") or 0))
        _UPLOAD_PROGRESS.pop(oldest, None)

app = FastAPI(title="Smart Financial Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()
_sync_counters()
ensure_admin()
try:
    backfill_warnings()  # flag legacy analyses with broken sign series
except Exception:
    pass  # never block startup over hygiene backfill


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excel_safe_name(name: str) -> str:
    """Strip characters Excel forbids in sheet names."""
    for ch in r"[]:*?/\\":
        name = name.replace(ch, " ")
    return name.strip() or "Results"


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Authentication: register (email code) + login + subscription
# ---------------------------------------------------------------------------

class RegisterPayload(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: str = Field(max_length=200)
    country: str | None = Field(default=None, max_length=100)
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=200)
    lang: str = "ar"


class ActivatePayload(BaseModel):
    email: str
    code: str
    lang: str = "ar"


class LoginPayload(BaseModel):
    username: str
    password: str
    lang: str = "ar"


class SocialAuthPayload(BaseModel):
    provider: str          # google | apple (simulated locally)
    email: str
    full_name: str | None = None
    lang: str = "ar"


class SocialGooglePayload(BaseModel):
    credential: str        # Google Identity Services ID token (JWT)
    lang: str = "ar"


class SocialApplePayload(BaseModel):
    id_token: str          # Sign in with Apple ID token (JWT)
    lang: str = "ar"


class CardPayload(BaseModel):
    card_number: str
    holder: str
    expiry: str
    cvv: str
    plan: str = "pro"
    lang: str = "ar"


def _auth_error(exc: AuthError):
    raise HTTPException(exc.status, str(exc))


@app.post("/api/auth/register")
def auth_register(payload: RegisterPayload):
    try:
        return register_user(
            payload.full_name, payload.email, payload.country,
            payload.username, payload.password, payload.lang,
        )
    except AuthError as exc:
        _auth_error(exc)


@app.post("/api/auth/activate")
def auth_activate(payload: ActivatePayload):
    try:
        activate_user(payload.email, payload.code, payload.lang)
        return {"ok": True}
    except AuthError as exc:
        _auth_error(exc)


@app.post("/api/auth/login")
def auth_login(payload: LoginPayload):
    try:
        return login_user(payload.username, payload.password, payload.lang)
    except AuthError as exc:
        _auth_error(exc)


@app.post("/api/auth/social")
def auth_social(payload: SocialAuthPayload):
    """Sign up / in through Google or Apple (simulated locally — the
    provider email is trusted; see auth.social_auth for the production
    caveat). Replaced by /api/auth/social/google|apple when OAuth client
    ids are configured via environment variables."""
    try:
        return social_auth(payload.provider, payload.email,
                           payload.full_name, payload.lang)
    except AuthError as exc:
        _auth_error(exc)


@app.get("/api/auth/social-config")
def auth_social_config():
    """Which real OAuth providers are configured (ids are PUBLIC values)."""
    import os

    google_id = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip() or None
    apple_id = (os.environ.get("APPLE_CLIENT_ID") or "").strip() or None
    return {
        "google": {"enabled": bool(google_id), "client_id": google_id},
        "apple": {"enabled": bool(apple_id), "client_id": apple_id},
    }


@app.post("/api/auth/social/google")
def auth_social_google(payload: SocialGooglePayload):
    """Real Google sign-in: verify the GIS ID token cryptographically,
    then create-or-match the account (same ladder as the local flow)."""
    try:
        claims = verify_google_id_token(payload.credential)
        return social_auth("google", claims["email"],
                           claims.get("name") or None, payload.lang)
    except AuthError as exc:
        _auth_error(exc)


@app.post("/api/auth/social/apple")
def auth_social_apple(payload: SocialApplePayload):
    """Real Sign-in-with-Apple: verify Apple's ID token, then link/create."""
    try:
        claims = verify_apple_id_token(payload.id_token)
        return social_auth("apple", claims["email"],
                           claims.get("name") or None, payload.lang)
    except AuthError as exc:
        _auth_error(exc)


@app.post("/api/auth/logout")
def auth_logout_endpoint(token: str | None = None):
    if token:
        auth_logout(token)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None), auth_token: str | None = None):
    token = authorization.removeprefix("Bearer ") if authorization else None
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "not authenticated")
    return user_payload(user)


def _require_admin(authorization: str | None, auth_token: str | None = None):
    """Resolve the caller; 403 unless the account is an admin."""
    token = authorization.removeprefix("Bearer ") if authorization else (
        auth_token if auth_token else None
    )
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول أولاً")
    if not user.is_admin:
        raise HTTPException(403, "هذه الصلاحية للمدير فقط")
    return user


@app.get("/api/admin/users")
def admin_list_users(authorization: str | None = Header(default=None), auth_token: str | None = None):
    """All registered users with plan/status/quota info (admin only)."""
    _require_admin(authorization, auth_token)
    return {"users": list_users()}


class AdminSubPayload(BaseModel):
    subscription: str  # free | paid
    plan: str | None = None
    lang: str = "ar"


@app.patch("/api/admin/users/{user_id}/subscription")
def admin_set_subscription(user_id: int, payload: AdminSubPayload,
                           authorization: str | None = Header(default=None),
                           auth_token: str | None = None):
    """Grant or revoke a paid plan for any user (admin only)."""
    _require_admin(authorization, auth_token)
    try:
        return set_user_subscription(user_id, payload.subscription, payload.plan, payload.lang)
    except AuthError as exc:
        _auth_error(exc)


class AdminActivePayload(BaseModel):
    active: bool
    lang: str = "ar"


@app.patch("/api/admin/users/{user_id}/status")
def admin_set_status(user_id: int, payload: AdminActivePayload,
                     authorization: str | None = Header(default=None),
                     auth_token: str | None = None):
    """Enable/disable a user account (admin only; admin accounts protected)."""
    _require_admin(authorization, auth_token)
    try:
        return set_user_active(user_id, payload.active, payload.lang)
    except AuthError as exc:
        _auth_error(exc)


@app.get("/api/subscription/plans")
def subscription_plans():
    """Available subscription plans (monthly/yearly/business/firm)."""
    from .auth import plan_list

    return {"plans": plan_list()}


@app.post("/api/subscription/activate")
def subscription_activate(payload: CardPayload, authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Simulated card charge that unlocks downloads for the account."""
    token = authorization.removeprefix("Bearer ") if authorization else None
    try:
        return activate_subscription(
            token, payload.card_number, payload.holder,
            payload.expiry, payload.cvv, payload.lang, payload.plan,
        )
    except AuthError as exc:
        _auth_error(exc)


@app.get("/api/subscription/payments")
def subscription_payments(authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Payment history for the authenticated user (سجل المدفوعات screen)."""
    token = (authorization.removeprefix("Bearer ") if authorization else None) or auth_token
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لعرض سجل المدفوعات")
    return {"payments": list_payments(user.id)}


@app.get("/api/subscription/payments/{payment_id}/invoice")
def payment_invoice(payment_id: int, lang: str = "ar",
                    authorization: str | None = Header(default=None),
                    auth_token: str | None = None):
    """Official invoice PDF for one of the caller's own payment rows."""
    token = (authorization.removeprefix("Bearer ") if authorization else None) or auth_token
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لتنزيل الفاتورة")
    if lang not in ("ar", "en"):
        lang = "ar"
    with SessionLocal() as db:
        from .database import Payment

        row = db.get(Payment, payment_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "invoice not found")
    from .auth import PLANS

    out = REPORTS / f"invoice_{payment_id}_{lang}.pdf"
    if not out.exists():
        try:
            build_invoice_pdf(
                {
                    "plan": row.plan,
                    "amount": row.amount,
                    "invoice_no": row.invoice_no,
                    "paid_at": row.paid_at,
                    "masked_card": row.masked_card,
                    "account_name": user.full_name or user.username,
                    "plan_expires": user.plan_expires,
                    "months": PLANS.get(row.plan, {}).get("months", 1),
                },
                out,
                lang,
            )
        except UnsupportedGlyphError as exc:
            raise HTTPException(422, exc.message(lang)) from None
    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"invoice-{payment_id}-{lang}.pdf",
    )


class AssistantChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # recent turns [{role: "user"|"assistant", content: str}] for continuity
    history: list[dict] = Field(default_factory=list)
    lang: str = "ar"
    # optional scope: when set, the assistant answers from THIS analysis's
    # real numbers only (rich context block built in assistant.py)
    analysis_id: int | None = None


@app.post("/api/assistant/chat")
def assistant_chat(payload: AssistantChatPayload,
                   authorization: str | None = Header(default=None),
                   auth_token: str | None = None):
    """المساعد الذكي — one AI chat turn (Google Gemini) grounded in the
    signed-in user's real platform context (plan + stored analyses)."""
    token = (authorization.removeprefix("Bearer ") if authorization else None) or auth_token
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لاستخدام المساعد الذكي")
    if payload.lang not in ("ar", "en"):
        payload.lang = "ar"
    # Persisted conversation, not the client payload: the client may pass
    # history too, but the server's stored transcript is authoritative
    # (it survives reloads and multiple tabs/windows).
    stored = assistant_read_history(user.id)
    recent = (
        stored[-9:]
        if stored
        else [
            {"role": str(t.get("role", "")), "content": str(t.get("content", ""))}
            for t in (payload.history or [])[-9:]
        ]
    )
    assistant_save_turn(user.id, "user", payload.message)
    scope: str = ""
    if payload.analysis_id is not None:
        scope_ctx = build_analysis_context(payload.analysis_id)
        if scope_ctx is None:
            raise HTTPException(404, "التحليل المحدد غير موجود")
        scope = scope_ctx
    context = build_user_context(user_payload(user))
    if scope:
        context = context + "\n\n" + scope
    reply, err = assistant_reply(payload.message, recent, context, payload.lang)
    # Only REAL model answers enter the persisted transcript — synthesized
    # failure notices (rate-limit/overload) would pollute the history and
    # inflate the per-minute token usage on the free tier.
    if err is None:
        assistant_save_turn(user.id, "assistant", reply)
    return {"reply": reply, "error": err}


@app.get("/api/assistant/history")
def assistant_history(authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Persisted «المساعد الذكي» conversation of the signed-in user —
    the chat resumes after a page reload (oldest first)."""
    token = (authorization.removeprefix("Bearer ") if authorization else None) or auth_token
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لعرض محادثة المساعد الذكي")
    msgs = assistant_read_history(user.id)
    return {"messages": msgs}


@app.delete("/api/assistant/history")
def assistant_history_delete(authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Every user clears their own stored conversation only."""
    token = (authorization.removeprefix("Bearer ") if authorization else None) or auth_token
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لاستخدام المساعد الذكي")
    return {"cleared": assistant_clear_history(user.id)}


@app.get("/api/support/content")
def support_content(lang: str = "ar",
                    authorization: str | None = Header(default=None),
                    auth_token: str | None = None):
    """«الدعم والمراجع» screen data: usage guide + the signed-in user's
    live downloads availability (paid?, N analyses, comparable pairs)."""
    token = (authorization.removeprefix("Bearer ") if authorization else None) or auth_token
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لعرض مركز الدعم")
    if lang not in ("ar", "en"):
        lang = "ar"
    from .support_center import downloads_availability, usage_guide

    with SessionLocal() as db:
        n = db.query(Analysis).count()
    paid = user.subscription == "paid"
    return {
        "paid": paid,
        "plan": user.plan,
        "n_analyses": n,
        "guide": usage_guide(lang, paid),
        "availability": downloads_availability(paid, n, n),
    }


def _require_paid(authorization: str | None = None, auth_token: str | None = None):
    """Downloads are locked until the account has paid the subscription.

    ``authorization`` may arrive as a header (Bearer token) or as a query
    parameter (for direct <a href> downloads) in the form
    ``authorization=Bearer%20<token>``. Returns the authenticated user so
    callers can brand exports with the actual subscription tier.
    """
    from urllib.parse import unquote

    token = None
    if authorization:
        token = unquote(authorization).removeprefix("Bearer ").strip()
    elif auth_token:
        token = unquote(auth_token).removeprefix("Bearer ").strip()
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول لتحميل الملفات والتقارير")
    if user.subscription != "paid":
        raise HTTPException(
            402,
            "يتطلب تحميل التقارير سداد الاشتراك — فعّل الاشتراك أولاً",
        )
    return user


def _entity_name(row) -> str:
    """Report-facing entity name: the user-facing display name when set,
    otherwise the filename without its extension (matches the UI banner)."""
    if getattr(row, "display_name", None):
        return row.display_name
    name = getattr(row, "filename", "") or ""
    low = name.lower()
    for ext in (".xlsx", ".xls", ".pdf", ".docx", ".pptx", ".csv"):
        if low.endswith(ext):
            return name[: -len(ext)]
    return name


_SUBSCRIPTION_L = {
    "ar": {"band": "الاشتراك", "pro": "برو", "business": "الأعمال",
           "free": "النسخة المجانية"},
    "en": {"band": "Subscription", "pro": "PRO", "business": "Business",
           "free": "Free edition"},
}


def _subscription_label(user, lang: str) -> str:
    """Actual-plan badge for report headers (mirrors the UI banner)."""
    L = _SUBSCRIPTION_L[lang]
    if user is None or getattr(user, "subscription", None) != "paid":
        return f"{L['band']}: {L['free']}"
    plan = (getattr(user, "plan", "") or "").lower()
    if "business" in plan or "firm" in plan:
        return f"{L['band']}: {L['business']}"
    # pro + legacy keys (monthly/yearly) all carry the PRO badge
    return f"{L['band']}: {L['pro']}"


def _period_text(result: dict, lang: str) -> str:
    """Analysis-period text for report headers: real period labels detected
    in the source tables ("2023 - 2024") when present, otherwise the period
    count — same logic as the UI report banner."""
    labels = [str(x).strip() for x in (result.get("period_labels") or []) if str(x).strip()]
    if len(labels) >= 2:
        return " - ".join(labels)
    n = 0
    for key, vals in (result.get("metrics") or {}).items():
        if key == "liabilities" or not isinstance(vals, list):
            continue
        n = max(n, len(vals))
    for s in (result.get("series") or {}).values():
        vals = (s.get("values") or []) if isinstance(s, dict) else []
        n = max(n, len(vals))
    if n == 0:
        return "غير محددة" if lang == "ar" else "Not specified"
    if lang == "ar":
        return "فترة واحدة" if n == 1 else "فترتان" if n == 2 else f"{n} فترات"
    return "Single period" if n == 1 else f"{n} periods"


@app.post("/api/visit")
def register_visit():
    """Count one site visit — called by the frontend on first load."""
    bump_visits()
    return {"ok": True}


@app.get("/api/public/stats")
def public_stats():
    """Public site statistics for the external-facing landing page."""
    with SessionLocal() as db:
        row = get_site_stats(db)
        analyses = db.query(Analysis).order_by(Analysis.id.desc()).limit(5).all()
        return {
            "analyses_count": row.analyses_count or 0,
            "statements_count": row.statements_count or 0,
            "visits": row.visits or 0,
            "last_visit": row.last_visit,
            "since": row.since,
            "recent": [
                {
                    "id": a.id,
                    "name": a.display_name or a.filename,
                    "date": a.created_at,
                }
                for a in analyses
            ],
        }


@app.get("/api/labels")
def labels():
    return UI


@app.get("/api/analyses")
def list_analyses():
    with SessionLocal() as db:
        rows = db.query(Analysis).order_by(Analysis.id.desc()).all()
        out = []
        for r in rows:
            # quality-gate counts for the sidebar badge (0 when clean/absent)
            try:
                parsed_r = json.loads(r.result_json or "{}") or {}
            except Exception:
                parsed_r = {}
            audit = parsed_r.get("audit") or {}
            out.append(
                {
                    "id": r.id,
                    "filename": r.filename,
                    "display_name": r.display_name,
                    "notes": r.notes,
                    # sales-kind: the records page routes its PDF/PPTX
                    # buttons to the sales exporters (a financial deck of a
                    # sales analysis renders zero-value statements slides)
                    "kind": parsed_r.get("kind") or "financial",
                    # the frozen upload-screen declaration, for the UI badge
                    # next to the re-analyze button («مزّان مراجعة»…)
                    "file_kind": parsed_r.get("_file_kind"),
                    "analysis_mode": parsed_r.get("_analysis_mode"),
                    "has_file": bool(r.original_path and Path(r.original_path).exists()),
                    "has_tb": bool(r.has_tb),
                    "file_type": r.file_type,
                    "size_bytes": r.size_bytes,
                    "created_at": r.created_at,
                    "audit_warnings": len(audit.get("warnings") or []),
                    "audit_errors": len(audit.get("errors") or []),
                    # «مدقق»: the quality gate RAN on this row and found
                    # nothing to flag (legacy rows without an audit record
                    # are never badged — they were never verified)
                    "audited": bool(audit)
                    and not (audit.get("errors") or [])
                    and not (audit.get("warnings") or []),
                }
            )
        return out


def _detail(row: Analysis) -> dict:
    # the frozen upload-declaration is surfaced with the detail so the UI
    # can badge the reanalyze button with the route that will be taken
    try:
        _row_file_kind = json.loads(row.result_json or "{}").get("_file_kind")
        _row_analysis_mode = json.loads(row.result_json or "{}").get("_analysis_mode")
    except Exception:
        _row_file_kind = None
        _row_analysis_mode = None
    return {
        "id": row.id,
        "filename": row.filename,
        "display_name": row.display_name,
        "notes": row.notes,
        "has_file": bool(row.original_path and Path(row.original_path).exists()),
        "has_tb": bool(row.has_tb),
        "file_type": row.file_type,
        "file_kind": _row_file_kind,
        "analysis_mode": _row_analysis_mode,
        "size_bytes": row.size_bytes,
        "created_at": row.created_at,
        "result": json.loads(row.result_json),
        "editable": bool(json.loads(row.result_json).get("metrics")),
        "statements": json.loads(row.statements_json) if row.statements_json else None,
    }


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: int):
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")
        result = json.loads(row.result_json)
        # Legacy rows (created before manual value editing) get their raw
        # values reconstructed on first view so they become editable too.
        if not isinstance(result.get("metrics"), dict) or not result["metrics"]:
            result["metrics"] = result_to_metrics(result)
            result.setdefault("original_metrics", dict(result["metrics"]))
            row.result_json = json.dumps(result, ensure_ascii=False)
            db.commit()
        return _detail(row)


class ConceptValues(BaseModel):
    """Edited raw values (ordered oldest -> latest) for one concept."""

    values: list[float] = Field(min_length=1, max_length=24)


class ConceptCorrection(BaseModel):
    """Fix ONE confused concept: reclassify its series to another concept
    key (``to``), swap with the target when the target already carries
    values, override its display label, and/or replace its raw values."""

    to: str | None = None
    swap: bool = False
    label: str | None = Field(default=None, max_length=120)
    clear_label: bool = False
    values: list[float] | None = Field(default=None, min_length=1, max_length=24)


class ReviewRowCorrection(BaseModel):
    """Assign an unclassified review row (an OCR-mangled concept label the
    classifier lost) to a real concept key, using the row's read values
    unless explicit values are provided."""

    to: str
    values: list[float] | None = Field(default=None, min_length=1, max_length=24)


class AnalysisUpdate(BaseModel):
    """Optional fields: omitted keys keep their current value; null clears."""

    display_name: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    values: dict[str, ConceptValues] | None = None
    concepts: dict[str, ConceptCorrection] | None = None
    review_rows: dict[str, ReviewRowCorrection] | None = None


def _invalidate_cached_pdfs(analysis_id: int) -> None:
    """Drop cached artifacts whose content depends on the editable
    name/notes/values/concepts."""
    for pattern in (
        f"report_{analysis_id}_*.pdf",
        f"compare_{analysis_id}_vs_*_*.pdf",
        f"compare_*_vs_{analysis_id}_*.pdf",
        # the presentation deck caches under its own prefix — it reads the
        # same statements/result JSON and must not outlive this invalidation
        f"pptx_{analysis_id}_*.pptx",
        # the Excel export caches under its own prefix and reads the same
        # metrics — a stale export must not outlive this invalidation either
        f"export_{analysis_id}.xlsx",
    ):
        for stale in REPORTS.glob(pattern):
            stale.unlink(missing_ok=True)


def _move_series(metrics: dict, src: str, tgt: str, swap: bool) -> None:
    """Move one concept's series onto another key — the user's fix for a
    confused concept. An occupied target only moves as an EXPLICIT swap
    (the classic OCR mix-up: two rows captured under each other's name)."""
    if metrics.get(tgt):
        if not swap:
            raise HTTPException(
                409,
                f"التصنيف «{tgt}» يحمل قيمًا بالفعل — فعّل التبديل لتبديل "
                "السلسلتين أو صحّح قيمه أولًا",
            )
        tgt_series = metrics.pop(tgt)
        src_series = metrics.pop(src, None)
        metrics[src] = tgt_series
        if src_series is not None:
            metrics[tgt] = src_series
        return
    series = metrics.pop(src, None)
    if series is not None:
        metrics[tgt] = series


def _apply_concept_corrections(
    result: dict,
    metrics: dict,
    concept_changes: dict,
    review_changes: dict,
) -> None:
    """Apply manual concept fixes from a PATCH before the immediate
    recompute: reclassify a concept's series to another key, swap two
    concepts OCR mixed up, override a display label, revalue a series, and
    assign an unclassified review row (an OCR-mangled label) its real
    concept. Mutates ``result``/``metrics`` in place; raises HTTPException
    on unknown keys or occupied targets — nothing is committed on error."""
    labels = dict(result.get("concept_labels") or {})
    fixes = list(result.get("concept_fixes") or [])
    items = list((result.get("concept_review") or {}).get("items") or [])
    by_rid = {it.get("rid"): it for it in items}
    changed = False

    def check_target(tgt: str) -> None:
        if tgt not in EDITABLE_CONCEPTS:
            raise HTTPException(422, f"unknown concept: {tgt}")

    for src, ch in (concept_changes or {}).items():
        tgt = (ch.to or "").strip() or None
        if tgt is not None:
            check_target(tgt)
        if src not in metrics and src not in labels:
            raise HTTPException(404, f"concept not found: {src}")
        key = src
        if tgt and tgt != src:
            _move_series(metrics, src, tgt, ch.swap)
            if src in labels and tgt not in labels:
                labels[tgt] = labels.pop(src)
            key = tgt
            fixes.append(
                {"concept": src, "to": tgt, "swap": ch.swap, "at": _now()})
            changed = True
        if ch.clear_label:
            labels.pop(key, None)
            changed = True
        elif ch.label is not None:
            lab = ch.label.strip()[:120]
            if lab:
                labels[key] = lab
            else:
                labels.pop(key, None)
            changed = True
        if ch.values is not None:
            metrics[key] = [float(v) for v in ch.values]
            changed = True

    for rid, rc in (review_changes or {}).items():
        item = by_rid.get(rid)
        if not item:
            raise HTTPException(404, f"review row not found: {rid}")
        tgt = (rc.to or "").strip()
        if not tgt:
            raise HTTPException(422, "review-row correction needs a target concept")
        check_target(tgt)
        # A row already applied may NOT be re-assigned here: its values are
        # already inside the target series — a second POST would double-count
        # them. The user's legitimate paths are the concepts endpoint (a
        # source→target move handles its own occupancy) or values (manual
        # series edit); the review-row assignment stays idempotent-safe.
        if item.get("applied"):
            raise HTTPException(
                409,
                f"صف المراجعة «{rid}» مُصنَّف مسبقًا إلى «{item['applied']}» — "
                "لا يمكن إسناده مرة أخرى؛ استخدم تصحيح المفاهيم أو الترجمة "
                "اليدوية إن غيّرت رأيك",
            )
        if rc.values is not None:
            vals = [float(v) for v in rc.values]
        else:
            vals = [float(v) for v in (item.get("values") or [])]
        if not vals:
            raise HTTPException(
                422, "صف المراجعة لا يحمل قيمًا مقروءة — أدخل القيم يدويًا")
        existing = metrics.get(tgt)
        if isinstance(existing, list) and existing:
            # same rid re-apply: its previous contribution is already inside
            # — replace the last len(item-values) slice instead of appending
            prev_vals = [float(v) for v in (item.get("values") or [])]
            if item.get("applied") == tgt and len(existing) >= len(prev_vals):
                metrics[tgt] = (
                    existing[: -len(prev_vals)] + vals if prev_vals else vals
                )
            else:
                metrics[tgt] = existing + vals
        else:
            metrics[tgt] = vals
        item["applied"] = tgt
        fixes.append({
            "review_row": rid, "label": item.get("label"),
            "to": tgt, "at": _now(),
        })
        changed = True

    if changed:
        if labels:
            result["concept_labels"] = labels
        else:
            result.pop("concept_labels", None)
        result["concept_fixes"] = fixes[-80:]
        review = result.get("concept_review")
        if isinstance(review, dict):
            review["items"] = items


@app.patch("/api/analyses/{analysis_id}")
def update_analysis(analysis_id: int, payload: AnalysisUpdate):
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")

        fields = payload.model_dump(exclude_unset=True)
        if "display_name" in fields:
            row.display_name = fields["display_name"]
        if "notes" in fields:
            row.notes = fields["notes"]

        if (fields.get("values") or payload.concepts or payload.review_rows):
            result = json.loads(row.result_json)
            metrics = result_to_metrics(result)
            if fields.get("values"):
                for concept, change in fields["values"].items():
                    metrics[concept] = [float(v) for v in change["values"]]
            # confused-concept fixes land in the SAME transaction, then the
            # ratios/series/forecast recompute from the corrected set below —
            # the PATCH response already carries the fresh numbers
            _apply_concept_corrections(result, metrics,
                                       payload.concepts or {},
                                       payload.review_rows or {})
            result["metrics"] = metrics
            clean_result(result)
            recomputed = recompute_result(result)
            recomputed["edited_at"] = _now()
            row.result_json = json.dumps(recomputed, ensure_ascii=False)

        db.commit()

    _invalidate_cached_pdfs(analysis_id)
    return _detail(row)


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: int):
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")
        original = row.original_path
        db.delete(row)
        db.commit()

    if original:
        Path(original).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/analyses/{analysis_id}/values/reset")
def reset_values(analysis_id: int):
    """Restore the originally extracted values and recompute from them."""
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")
        result = json.loads(row.result_json)
        original = result.get("original_metrics")
        if not isinstance(original, dict) or not original:
            raise HTTPException(
                409, "original values are not archived for this analysis"
            )
        result["metrics"] = {
            c: [float(v) for v in vals]
            for c, vals in original.items()
            if isinstance(vals, list) and vals
        }
        # user concept corrections are edits too — a reset returns the
        # analysis to the as-extracted classification entirely
        result.pop("concept_labels", None)
        result.pop("concept_fixes", None)
        for item in (result.get("concept_review") or {}).get("items") or []:
            item.pop("applied", None)
        clean_result(result)
        recomputed = recompute_result(result)
        recomputed["edited_at"] = None
        row.result_json = json.dumps(recomputed, ensure_ascii=False)
        db.commit()

    _invalidate_cached_pdfs(analysis_id)
    return _detail(row)


@app.get("/api/analyses/{analysis_id}/reading-sample")
def reading_sample(analysis_id: int, lang: str = "ar"):
    """Reading-sample inspector: HOW the parsers read the stored file —
    detected tables (with their kind), which columns were taken as periods,
    which were excluded (change/total columns), and which rows were
    rejected and why. Read-only over the ORIGINAL file; no side effects."""
    from .reading_sample import build_reading_sample

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")
        path = Path(row.original_path) if row.original_path else None
        if not path or not path.exists():
            raise HTTPException(
                409, "الملف الأصلي غير محفوظ — لا توجد عينة قراءة"
                if lang == "ar" else "original file not kept — no reading sample")
        try:
            prev = json.loads(row.result_json or "{}")
        except Exception:
            prev = {}
        sample = build_reading_sample(path, prev.get("_sheet"))
        sample["filename"] = row.display_name or row.filename
        return sample


@app.post("/api/analyses/{analysis_id}/reanalyze")
def reanalyze(analysis_id: int):
    """Re-run extraction on the original file with the current analyzer
    (fixes analyses created before parser fixes) and archive fresh values."""
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")
        path = Path(row.original_path) if row.original_path else None
        if not path or not path.exists():
            raise HTTPException(409, "الملف الأصلي غير محفوظ — لا يمكن إعادة التحليل")
        try:
            parsed = parse_file(path)
            # Split workbooks: the analysis is bound to ONE sheet — re-read
            # only that sheet so sibling companies don't pollute the numbers.
            try:
                prev = json.loads(row.result_json or "{}")
            except Exception:
                prev = {}
            sheet = prev.get("_sheet")
            if sheet:
                tables = [
                    t for t in (parsed.get("tables") or [])
                    if t.get("name") == sheet
                ]
                if tables:
                    parsed = {"tables": tables, "texts": []}
            # ROUTING LOCK: the upload-screen declaration (file_kind /
            # analysis_mode) was stamped on the result at upload time and is
            # the binding contract for re-analysis — a reanalyze re-runs the
            # SAME declared route verbatim (sales stays sales, a forced
            # trial-balance reading stays forced) and never re-classifies the
            # file. Legacy rows without the stamp fall back to the stored
            # result kind, exactly as before.
            declared_kind = prev.get("_file_kind")
            declared_mode = prev.get("_analysis_mode")
            if declared_kind not in ("statements", "trial_balance", "sales"):
                declared_kind = None
            if declared_mode not in ("auto", "force_trial_balance", "financial_sheets"):
                declared_mode = "auto"
            # sales-kind analyses re-take the SALES route: analyze() reads
            # an invoice sheet as financial statement rows and the quality
            # gate refuses the rebuild — a reanalyze of 90/91 must keep the
            # sales dashboard, not zero-financials garbage.
            from .sales_analyzer import analyze_sales

            stored_kind = json.loads(row.result_json or "{}").get("kind")
            # «kind» is a SALES-only marker: a financial analysis legitimately
            # has no kind field — it is NOT a lost-kind row. The legacy
            # wiped-kind probe may only fire when the stored result carries
            # NO analysable content at all (the historical wipe accidents),
            # otherwise a financial row whose sales-shaped OCR table happened
            # to read as a sales grid would be re-classified into a sales
            # dashboard and LOSE its captured financials — exactly what a
            # locked-route reanalysis must never do.
            has_financial_content = bool(
                prev.get("metrics")
                or prev.get("kpis")
                or prev.get("ratios")
            )
            if stored_kind is None and not has_financial_content:
                # kindLost rows (legacy wipe accidents) get one probe:
                # detect_sales_table only fires on genuine sales grids —
                # financial statements return None — so a wiped sales row
                # can still find its way back to the sales route.
                try:
                    _probe = _sales_records_for_tables(parsed.get("tables") or [])
                except Exception:
                    _probe = None
                if _probe:
                    stored_kind = "sales"
            # the route decision comes AFTER the legacy probe so wiped-kind
            # rows keep their sales rescue path
            route_kind = "sales" if (
                declared_kind == "sales" or
                (declared_kind is None and stored_kind == "sales")
            ) else "financial"
            if route_kind == "sales":
                records = _sales_records_for_tables(parsed.get("tables") or [])
                if not records:
                    raise HTTPException(
                        422,
                        "لم يُعثر على صفوف مبيعات صالحة في الملف الأصلي عند إعادة التحليل",
                    )
                result = {
                    "kpis": {}, "ratios": {}, "series": {}, "forecast": [],
                    "metrics": {},
                    "sales_analysis": analyze_sales(records),
                    "kind": "sales",
                    "texts_found": len(parsed.get("texts") or []),
                    "analysed_at": _now(),
                }
                if sheet and len(parsed["tables"]) == 1:
                    result["_sheet"] = sheet
            else:
                # re-run the financial extraction under the SAME reading
                # mode declared at upload (auto for legacy rows) — the
                # declaration, not the file shapes, decides the reading.
                result = analyze(parsed["tables"], parsed["texts"], mode=declared_mode)
            if result.get("kind") != "sales":
                if sheet:
                    result["_sheet"] = sheet
                result["metrics"] = result_to_metrics(result)
                clean_result(result)
                result["original_metrics"] = result["metrics"]
            # re-stamp the declaration so every future reanalyze keeps the
            # same route verbatim (legacy rows acquire the stamp here)
            result["_file_kind"] = declared_kind or (
                "sales" if route_kind == "sales" else "statements"
            )
            result["_analysis_mode"] = declared_mode
            # remember the extraction path BEFORE the quality gate: the
            # audit's W3 «suspect OCR numbers» warning only applies to
            # OCR-read files
            result["_ocr_used"] = bool(parsed.get("ocr_used"))
        except Exception as exc:
            raise HTTPException(400, f"failed to reanalyze: {exc}") from exc
        # quality gate: reanalysis must never overwrite a stored analysis
        # with a corrupt rebuild either
        # quality gate: reanalysis must never overwrite a stored analysis
        # with a corrupt rebuild either — EXCEPT sales-kind results, whose
        # «metrics» block is intentionally empty by design (the financial
        # C7 check would refuse every sales grid); the upload path makes
        # the same skip, and reanalyze must keep that parity or a sales
        # reanalysis becomes impossible.
        is_sales = result.get("kind") == "sales"
        if is_sales:
            result["audit"] = {
                "ok": True, "errors": [], "warnings": [], "repairs": [],
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "mode": "sales",
            }
        else:
            gate = run_quality_gate(result)
            if gate["fatal"]:
                raise HTTPException(
                    422,
                    "رفض مدقق الجودة نتيجة إعادة التحليل — لم يُعدّل السجل: "
                    + "; ".join(gate["messages"]),
                )
        # keep user data: name, notes — and TRIAL-BALANCE statements (the
        # user attached them deliberately). Metrics-DERIVED statements are
        # platform artifacts: they must be rebuilt from the fresh capture,
        # otherwise a reanalysis leaves stale derived faces behind (e.g.
        # built before a capture fix landed).
        try:
            prev_stmts = (json.loads(row.statements_json)
                          if row.statements_json else None)
        except Exception:
            prev_stmts = None
        if prev_stmts and prev_stmts.get("derived_from_metrics"):
            row.statements_json = None
        row.result_json = json.dumps(result, ensure_ascii=False)
        had_statements = bool(row.statements_json)
        db.commit()
        data = _detail(row)

    # analyses without statements (comparison files, pre-attach records)
    # get them rebuilt from the FRESH metrics — a reanalysis that leaves
    # stale/absent statements behind is not a reanalysis. SALES-kind rows
    # are excluded: attaching statements from a sales grid re-derives a
    # financial capture of the grid rows and OVERWRITES result_json —
    # wiping the sales_analysis block entirely.
    if not had_statements and (
        json.loads(row.result_json or "{}").get("kind") != "sales"
    ):
        tb_rows = [
            r
            for table in (parsed.get("tables") or [])
            for r in (table.get("rows") or [])
        ]
        if tb_rows:
            _try_attach_statements(analysis_id, tb_rows)

    _invalidate_cached_pdfs(analysis_id)
    return data


@app.get("/api/analyses/{analysis_id}/file")
def download_original(analysis_id: int, authorization: str | None = Header(default=None), auth_token: str | None = None):
    _require_paid(authorization, auth_token)
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        original = row.original_path if row else None
        filename = row.filename if row else "file"

    if not original or not Path(original).exists():
        raise HTTPException(404, "original file not available for this analysis")

    return FileResponse(
        original,
        filename=filename,
        media_type="application/octet-stream",
    )


@app.get("/api/analyses/{analysis_id}/export")
def export_results(analysis_id: int, lang: str = "ar", authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Export results as a styled multi-sheet workbook matching the site's
    look (brand colours, logo, banner) and pre-fitted for A4 printing."""
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins

    user = _require_paid(authorization, auth_token)
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    if lang not in ("ar", "en"):
        lang = "ar"

    result = json.loads(row.result_json)
    try:
        stmts = json.loads(row.statements_json) if row.statements_json else None
    except Exception:
        stmts = None
    ifrs_notes = ifrs_detect_applicable(result, stmts)
    ifrs_basis = ifrs_basis_of_preparation(lang)
    title = row.display_name or row.filename
    rtl = lang == "ar"
    text_align = "right" if rtl else "left"

    L = {
        "ar": {
            "dashboard": "الملخص", "summary": "الملخص", "trends": "الرسوم البيانية التحليلية",
            "forecast": "التنبؤات", "notes": "ملاحظات",
            "kpis": "المؤشرات الرئيسية", "ratios": "النسب المالية",
            "ratio_insights": "تحليل النسب المالية",
            "consistency": "التحقق من صحة الأرقام",
            "ratio_lbl": "النسبة", "value_lbl": "القيمة",
            "what_lbl": "ما هي؟", "why_lbl": "ما فائدتها؟", "opinion_lbl": "الرأي",
            "check_col": "البند", "check_result_col": "النتيجة",
            "item": "البند", "value": "القيمة", "period": "الفترة",
            "change": "التغير المتوقع", "trend": "الاتجاه",
            "source": "المصدر: {name}", "date": "تاريخ التحليل: {date}",
            "entity": "المنشأة: {name}", "period": "فترة التحليل: {period}",
            "edited": "⚠ قيم معدّلة يدوياً — النسب أعيد حسابها",
            "up": "صاعد ▲", "down": "هابط ▼", "flat": "مستقر ◄►",
            "printed": "أُنتج بواسطة المنصة المالية الذكية",
            "trends_sub": "سلسلة المؤشرات عبر الفترات وتوزيع المصروفات",
            "forecast_sub": "توقع اتجاه البنود للفترات القادمة (انحدار خطي)",
            "growth_fc": "النمو السنوي والتوقع",
            "growth_fc_sub": "القيم عبر السنوات ونسب التغير + توقع السنة القادمة (متوسط النمو التاريخي)",
            "growth_values": "القيم عبر السنوات + التوقع",
            "growth_yoy": "نسبة التغير السنوي + متوسط النمو (التوقع)",
            "notes_sub": "ملاحظات المستخدم على التحليل",
            "brief": "الملخص التنفيذي", "score": "التقييم المالي",
            "scenarios": "السيناريوهات المستقبلية",
            "score_value": "الدرجة (من 100)", "score_grade": "التقدير",
            "scenario_growth": "النمو المتوقع", "scenario_rev": "الإيراد المتوقع",
            "scenario_net": "صافي الربح المتوقع",
            "company_activity": "نشاط الشركة", "company_size": "حجم الشركة",
            "company_pattern": "نمط التشغيل",
            "ifrs_title": "الإطار المعياري (IFRS)",
            "opex_pie_title": "توزيع مصاريف التشغيل (من دفتر الأستاذ)",
            "opex_others": "بنود أخرى",
            "stmts_title": "القوائم المالية (من ميزان المراجعة)",
            "is_title": "قائمة الدخل", "bs_title": "قائمة المركز المالي",
            "cf_title": "قائمة التدفقات النقدية",
            "tb_title": "ميزان المراجعة",
            "total_col": "الإجمالي",
            "cf_operating": "الأنشطة التشغيلية", "cf_investing": "الأنشطة الاستثمارية",
            "cf_financing": "الأنشطة التمويلية",
            "cf_change": "صافي التغير في النقدية", "cf_balance": "رصيد النقدية",
            "net_lbl": "صافي الربح", "gross_lbl": "الربح الإجمالي",
            "op_lbl": "الربح التشغيلي", "rev_lbl": "الإيرادات",
            "cogs_lbl": "تكلفة المبيعات", "opex_lbl": "المصاريف التشغيلية",
            "fin_lbl": "الفئات (استثمارية/تمويلية/ضرائب)",
            "waterfall_title": "شلال الربحية: من الإيراد إلى صافي الربح",
            "cf_waterfall_title": "شلال التدفق النقدي: تشغيلي ← استثماري ← تمويلي ← الرصيد",
            "activity_title": "تطور دورة التحول النقدي ومكوناتها عبر الفترات",
            "dso_lbl": "فترة التحصيل (يوم)", "inv_turn_lbl": "دوران المخزون (x)",
            "dpo_lbl": "فترة السداد (يوم)", "ccc_lbl": "دورة التحول النقدي (يوم)",
            "prev_compare": "مقارنة بالفترة السابقة",
            "is_change_title": "مقارنة قائمة الدخل",
            "change_amount": "التغير بالقيمة (ريال)",
            "prev_period": "الفترة السابقة", "curr_period": "الفترة الحالية",
            "derived_title": "القوائم المالية (لكل فترة)",
            "compare_col": "مقارنة بالفترات",
            "bs_total_assets": "إجمالي الأصول (مقارنة)",
            "bs_total_liabilities": "إجمالي الالتزامات (مقارنة)",
            "bs_equity": "حقوق الملكية (مقارنة)",
        },
        "en": {
            "dashboard": "Summary", "summary": "Summary", "trends": "Analytical Charts",
            "forecast": "Forecast", "notes": "Notes",
            "kpis": "Key Indicators", "ratios": "Financial Ratios",
            "ratio_insights": "Ratio Analysis",
            "consistency": "Consistency checks",
            "ratio_lbl": "Ratio", "value_lbl": "Value",
            "what_lbl": "What is it?", "why_lbl": "Why it matters", "opinion_lbl": "Verdict",
            "check_col": "Check", "check_result_col": "Result",
            "item": "Item", "value": "Value", "period": "Period",
            "change": "Expected Change", "trend": "Trend",
            "source": "Source: {name}", "date": "Analysed: {date}",
            "entity": "Entity: {name}", "period": "Analysis period: {period}",
            "edited": "⚠ Manually edited values — ratios recomputed",
            "up": "Up ▲", "down": "Down ▼", "flat": "Flat ◄►",
            "printed": "Produced by Smart Financial Platform",
            "trends_sub": "Indicator series across periods & expense breakdown",
            "forecast_sub": "Projected direction of items for upcoming periods (linear regression)",
            "growth_fc": "Annual Growth & Forecast",
            "growth_fc_sub": "Yearly values & YoY change + next-year forecast (mean historical growth)",
            "growth_values": "Values by year + forecast",
            "growth_yoy": "YoY change % + forecast mean growth",
            "notes_sub": "User notes on this analysis",
            "brief": "Executive Summary", "score": "Financial Score",
            "scenarios": "Future Scenarios",
            "score_value": "Score (of 100)", "score_grade": "Grade",
            "scenario_growth": "Growth", "scenario_rev": "Projected Revenue",
            "scenario_net": "Projected Net",
            "company_activity": "Activity", "company_size": "Company size",
            "company_pattern": "Operating pattern",
            "ifrs_title": "Standards Framework (IFRS)",
            "opex_pie_title": "Operating Expenses Breakdown (from the ledger)",
            "opex_others": "Other items",
            "stmts_title": "Financial Statements (from the trial balance)",
            "is_title": "Income Statement", "bs_title": "Statement of Financial Position",
            "cf_title": "Cash Flow Statement",
            "tb_title": "Trial Balance",
            "total_col": "Total",
            "cf_operating": "Operating activities", "cf_investing": "Investing activities",
            "cf_financing": "Financing activities",
            "cf_change": "Net change in cash", "cf_balance": "Cash balance",
            "net_lbl": "Net Profit", "gross_lbl": "Gross Profit",
            "op_lbl": "Operating Profit", "rev_lbl": "Revenue",
            "cogs_lbl": "Cost of Sales", "opex_lbl": "Operating Expenses",
            "fin_lbl": "Categories (investing/financing/taxes)",
            "waterfall_title": "Profit Waterfall: revenue to net profit",
            "cf_waterfall_title": "Cash Flow Waterfall: operating → investing → financing → balance",
            "activity_title": "Cash Conversion Cycle & Components Trend",
            "dso_lbl": "Collection Period (days)", "inv_turn_lbl": "Inventory Turnover (x)",
            "dpo_lbl": "Payment Period (days)", "ccc_lbl": "Cash Conversion Cycle (days)",
            "prev_compare": "vs Previous Period",
            "is_change_title": "Income Statement Comparison",
            "change_amount": "Change (SAR)",
            "prev_period": "Previous Period", "curr_period": "Current Period",
            "derived_title": "Financial Statements (per period)",
            "compare_col": "Period Comparison",
            "bs_total_assets": "Total Assets (comp)",
            "bs_total_liabilities": "Total Liabilities (comp)",
            "bs_equity": "Equity (comp)",
        },
    }[lang]

    TEAL, TEAL_SOFT, MUTED = "0F766E", "F0FDFA", "64748B"
    GREEN, RED, LINE = "059669", "DC2626", "E2E8F0"
    thin = Side(style="thin", color=LINE)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ---- SALES-kind analyses get the SALES workbook: a financial workbook
    # of a sales analysis renders zero-value statement sheets.
    if result.get("kind") == "sales":
        sales = result.get("sales_analysis") or {}
        if not sales:
            raise HTTPException(422, "التحليل لا يحتوي بيانات مبيعات قابلة للتصدير")
        from .bi_export import build_sales_table_rows

        wb_s = Workbook()
        ws = wb_s.active
        ws.sheet_view.rightToLeft = rtl
        sections = build_sales_table_rows(sales, lang)
        r = 1
        for title, headers, data_rows in sections:
            r += 1
            c = ws.cell(row=r, column=1, value=title)
            c.font = Font(bold=True, size=13, color=TEAL)
            r += 1
            for i, h in enumerate(headers, 1):
                hc = ws.cell(row=r, column=i, value=h)
                hc.font = Font(bold=True, color=TEAL)
                hc.fill = PatternFill("solid", fgColor=TEAL_SOFT)
                hc.alignment = Alignment(horizontal="center", wrap_text=True)
            r += 1
            for dr in data_rows:
                for i, v in enumerate(dr, 1):
                    cell = ws.cell(row=r, column=i, value=v)
                    if i > 1 and isinstance(v, (int, float)):
                        cell.number_format = "#,##0"
                    if i == 1:
                        cell.alignment = Alignment(horizontal="right" if rtl else "left")
                r += 1
        # column sizing (A ~ text, the rest numeric)
        ws.column_dimensions["A"].width = 26
        for col in range(2, 10):
            ws.column_dimensions[get_column_letter(col)].width = 15
        buf = io.BytesIO()
        wb_s.save(buf)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":
                     f'attachment; filename="sales-export-{analysis_id}-{lang}.xlsx"'},
        )

    wb = Workbook()
    wb.remove(wb.active)

    def _sheet(name: str):
        ws = wb.create_sheet(_excel_safe_name(name)[:31])
        ws.sheet_view.rightToLeft = rtl
        ws.sheet_view.showGridLines = False
        # ---- A4 print setup: fits the sheet width on one page ----------
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.orientation = "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_margins = PageMargins(left=0.5, right=0.5, top=0.6, bottom=0.6)
        ws.print_options.horizontalCentered = True
        # Repeat row 1 (table headers) on every printed page for long sheets.
        ws.print_title_rows = "1:1"
        return ws

    # first content row below the platform banner every sheet now carries:
    # logo rows 1-3 + name 4 + tagline 5 + subtitle 6 + gap 7 + section title 8
    # — used by headers, data rows and chart anchors so content lands below
    # the banner on every sheet (mirrors _brand_banner's row layout)
    HEADER_SPAN = 9

    def _brand_banner(ws, title_text: str, subtitle: str, extra: str | None = None) -> int:
        """Site-branded banner: logo + platform name + report title.
        Returns the first free row below the banner."""
        logo = ROOT / "frontend" / "public" / "logo.svg"
        png_logo = logo.with_suffix(".png")
        r = 1
        if png_logo.exists():
            try:
                img = XLImage(str(png_logo))
                img.height, img.width = 44, 44
                ws.add_image(img, f"A{r}")
                r = 4
            except Exception:
                r = 1
        name_cell = ws.cell(row=r, column=2, value=UI["title"][lang])
        name_cell.font = Font(bold=True, size=13, color=TEAL)
        ws.merge_cells(
            start_row=r, start_column=2, end_row=r, end_column=6
        )
        r += 1
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        tag = ws.cell(row=r, column=2, value=UI["tagline"][lang])
        tag.font = Font(size=9.5, color="B45309")
        r += 1
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        sub = ws.cell(row=r, column=2, value=subtitle)
        sub.font = Font(size=10, color=MUTED)
        r += 1
        if extra:
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
            xcell = ws.cell(row=r, column=2, value=extra)
            xcell.font = Font(size=10, color=MUTED)
            r += 1
        r += 1
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        t = ws.cell(row=r, column=1, value=title_text)
        t.font = Font(bold=True, size=15, color=TEAL)
        t.alignment = Alignment(horizontal=text_align, vertical="center")
        return r + 1

    def _branded_sheet(sheet_title: str, section_title: str, subtitle: str | None = None):
        """Sheet with the platform banner (name + tagline) on top — every
        printed sheet opens with the brand, not just the summary."""
        ws = _sheet(sheet_title)
        _print_footer(ws)
        _brand_banner(ws, section_title, subtitle or sheet_title)
        return ws

    def _print_footer(ws):
        ws.oddFooter.right.text = L["printed"]
        ws.oddFooter.right.size = 8
        ws.oddFooter.right.color = "64748B"
        ws.oddFooter.left.text = "&P / &N"
        ws.oddFooter.left.size = 8
        ws.oddFooter.left.color = "64748B"

    def _autosize(ws, skip_rows: int = 2, min_w: int = 11, max_w: int = 46) -> None:
        """Column widths from real content, with a text-aware multiplier:
        Arabic labels are narrow glyphs, so pure char-count under-sizes the
        label column and squeezes it on print. Long text columns (what/why/
        verdict) are width-capped and wrapped instead of stretched."""
        wrap_cols: set[int] = set()
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.alignment and c.alignment.wrap_text:
                    wrap_cols.add(c.column)
        for col in ws.columns:
            letter = get_column_letter(col[0].column)
            lengths = [
                len(str(c.value)) for c in col
                if c.row > skip_rows and c.value is not None
            ]
            raw = max(lengths) if lengths else 0
            if col[0].column in wrap_cols:
                width = 34
            else:
                # value/number columns are compact; label columns breathe
                width = max(min_w, min(max_w, int(raw * 1.15) + 4))
            ws.column_dimensions[letter].width = width

    def _header(ws, r: int, headers: list) -> None:
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=r, column=c, value=h)
            cell.font = Font(bold=True, color="FFFFFF", size=11)
            cell.fill = PatternFill("solid", fgColor=TEAL)
            cell.alignment = Alignment(horizontal=text_align, vertical="center", wrap_text=True)
            cell.border = box

    def _section(ws, r: int, text: str) -> int:
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = Font(bold=True, size=13, color=TEAL)
        return r + 1

    def _data_rows(ws, r: int, rows: list, fmts: dict | None = None) -> int:
        for i, data in enumerate(rows):
            rr = r + i
            for c, v in enumerate(data, 1):
                cell = ws.cell(row=rr, column=c, value=v)
                cell.border = box
                if isinstance(v, str):
                    cell.alignment = Alignment(horizontal=text_align, vertical="center")
                if i % 2 == 1:
                    cell.fill = PatternFill("solid", fgColor=TEAL_SOFT)
                if fmts and fmts.get(c):
                    cell.number_format = fmts[c]
        return r + len(rows)

    # ---- Sheet 1: live dashboard (mini financial report) ------------------
    # One rich sheet: brand banner + KPIs + ratios + score/scenarios + a live
    # native Excel chart fed by the KPI values — updates when values change.
    from .brief import build_executive_brief
    from .scoring import compute_scenarios, compute_score

    result["_filename"] = title
    brief = build_executive_brief(result, lang)
    score = compute_score(result)
    scenarios = compute_scenarios(result)

    ws = _sheet(L["dashboard"])
    try:
        date_text = datetime.fromisoformat(row.created_at).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        date_text = row.created_at
    next_row = _brand_banner(
        ws,
        title,
        L["entity"].format(name=_entity_name(row)) + " · "
        + L["period"].format(period=_period_text(result, lang)) + " · "
        + L["date"].format(date=date_text),
        extra=_subscription_label(user, lang),
    )
    # ---- IFRS framework: basis of preparation + applicable standards --------
    ifrs_head = ws.cell(row=next_row, column=1, value=L["ifrs_title"])
    ifrs_head.font = Font(bold=True, size=10, color=TEAL)
    ws.merge_cells(start_row=next_row, start_column=1, end_row=next_row, end_column=6)
    next_row += 1
    bcell = ws.cell(row=next_row, column=1, value=ifrs_basis)
    bcell.font = Font(size=9, color=MUTED)
    bcell.alignment = Alignment(horizontal=text_align, vertical="top", wrap_text=True)
    ws.merge_cells(start_row=next_row, start_column=1, end_row=next_row, end_column=6)
    ws.row_dimensions[next_row].height = 34
    next_row += 1
    for n in ifrs_notes[:6]:
        ccode = ws.cell(row=next_row, column=1, value=n["code"])
        ccode.font = Font(bold=True, size=9.5, color=TEAL)
        ntitle = n["ar"] if lang == "ar" else n["en"]
        nwhy = n["why_ar"] if lang == "ar" else n["why_en"]
        ctext = ws.cell(row=next_row, column=2, value=f"{ntitle} — {nwhy}")
        ctext.font = Font(size=9, color=MUTED)
        ctext.alignment = Alignment(horizontal=text_align, vertical="center", wrap_text=True)
        ws.merge_cells(start_row=next_row, start_column=2, end_row=next_row, end_column=6)
        ws.row_dimensions[next_row].height = 24
        next_row += 1
    next_row += 1
    _print_footer(ws)
    if result.get("edited_at"):
        cell = ws.cell(row=next_row, column=1, value=L["edited"])
        cell.font = Font(size=10, bold=True, color="B45309")
        next_row += 1

    # executive summary block
    if brief:
        next_row = _section(ws, next_row, L["brief"])
        company = brief.get("company") or {}
        company_rows = [
            ((L["company_activity"]), company.get("activity", "")),
            ((L["company_size"]), company.get("size", "")),
            ((L["company_pattern"]), company.get("pattern", "")),
        ]
        # «ملاءمة الأنشطة»: activity type vs its sector's turnover band
        fit = company.get("activity_fit") or {}
        if fit:
            company_rows.append((
                fit.get("title", ""),
                f"{fit.get('turnover_txt', '')} · {fit.get('range_txt', '')}"
                f" — {fit.get('verdict_label', '')}",
            ))
        for lbl, val in company_rows:
            c1 = ws.cell(row=next_row, column=1, value=lbl)
            c1.font = Font(bold=True, size=10, color=MUTED)
            c2 = ws.cell(row=next_row, column=2, value=val)
            c2.alignment = Alignment(horizontal=text_align, vertical="center")
            next_row += 1
        para = ws.cell(row=next_row, column=1, value=brief.get("paragraph", ""))
        para.alignment = Alignment(wrap_text=True, horizontal=text_align, vertical="top")
        para.font = Font(size=10)
        ws.merge_cells(start_row=next_row, start_column=1, end_row=next_row, end_column=6)
        ws.row_dimensions[next_row].height = 30
        next_row += 2

    # KPI cards row (label / value pairs, brand-coloured)
    next_row = _section(ws, next_row, L["kpis"])
    _header(ws, next_row, [L["item"], L["value"]])
    kpi_entries = list((result.get("kpis") or {}).values())
    kpi_rows = [
        [kpi.get(lang) or kpi.get("en") or "", kpi.get("value")]
        for kpi in kpi_entries
    ]
    next_row = _data_rows(ws, next_row + 1, kpi_rows, fmts={2: "#,##0.00"})
    kpi_header_row = next_row - 1 - len(kpi_rows)

    # native live bar chart over the KPI values (updates with edits)
    if len(kpi_entries) >= 2:
        try:
            from openpyxl.chart import BarChart, Reference

            chart = BarChart()
            chart.type = "bar"
            chart.style = 10
            chart.title = L["kpis"]
            chart.height = 6
            chart.width = 13
            data_ref = Reference(
                ws, min_col=2, min_row=kpi_header_row,
                max_row=kpi_header_row + len(kpi_rows),
            )
            cats_ref = Reference(
                ws, min_col=1, min_row=kpi_header_row + 1,
                max_row=kpi_header_row + len(kpi_rows),
            )
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            ws.add_chart(chart, f"E{kpi_header_row + 1}")
        except Exception:
            pass

    next_row += 1
    next_row = _section(ws, next_row, L["ratios"])
    _header(ws, next_row, [L["item"], L["value"]])
    # Percent-type ratios keep the unit glued to the number via the number
    # format («30.40%»), multiples print «1.42x», day-ratios «62 يوم» — no
    # bare values.
    from .ratio_explain import _PERCENT_KEYS
    percent_keys = _PERCENT_KEYS
    ratio_rows = []
    ratio_keys = []
    for rkey, ratio in (result.get("ratios") or {}).items():
        ratio_rows.append([ratio.get(lang) or ratio.get("en") or "", ratio.get("value")])
        ratio_keys.append(rkey)
    ratio_start = next_row + 1
    _data_rows(ws, ratio_start, ratio_rows)
    # per-cell unit format: percent-type ratios print «30.40%», multiples
    # «1.42x», day-ratios «62 يوم / 62 days»
    for i, rkey in enumerate(ratio_keys):
        if rkey in percent_keys:
            fmt = '0.00"%"'
        elif rkey in DAYS_KEYS:
            fmt = '0.00" يوم"' if lang == "ar" else '0.00" days"'
        else:
            fmt = '0.00"x"'
        ws.cell(row=ratio_start + i, column=2).number_format = fmt
    next_row = ratio_start + len(ratio_rows)

    # Conditional formatting on the ratio value cells: green fill + green
    # text when the ratio meets its reference benchmark, red when it does
    # not — driven by the same gate thresholds (_judge) that power the
    # interpretive cards and the PDF benchmark-alignment section, so all
    # verdicts agree across the platform. Falls back to static font colour
    # when conditional formatting is unavailable in the host openpyxl.
    try:
        from openpyxl.formatting.rule import CellIsRule

        good_fill = PatternFill(start_color="E5F3EA", end_color="E5F3EA",
                                fill_type="solid")
        bad_fill = PatternFill(start_color="FBE5E5", end_color="FBE5E5",
                               fill_type="solid")
        good_font = Font(color="157A2E", bold=True)
        bad_font = Font(color="B3261E", bold=True)
        ranges = {"good": [], "bad": []}
        for i, rkey in enumerate(ratio_keys):
            value = (result.get("ratios") or {}).get(rkey, {}).get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            verdict = _judge(rkey, value)
            if verdict in ranges:
                ranges[verdict].append(f"B{ratio_start + i}")
        # (chip cells in column D carry the same verdict statically below)
        if ranges["good"]:
            sel = " ".join(ranges["good"])
            ws.conditional_formatting.add(
                sel, CellIsRule(operator="greaterThan", formula=["-1e99"],
                                fill=good_fill, font=good_font))
        if ranges["bad"]:
            sel = " ".join(ranges["bad"])
            ws.conditional_formatting.add(
                sel, CellIsRule(operator="greaterThan", formula=["-1e99"],
                                fill=bad_fill, font=bad_font))
    except Exception:
        pass

    # Static fallback colouring (works everywhere): a coloured status chip
    # in column D beside the value (column C hosts the live chart), and
    # tinted label cells for green/red verdicts.
    for i, rkey in enumerate(ratio_keys):
        value = (result.get("ratios") or {}).get(rkey, {}).get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        verdict = _judge(rkey, value)
        chip = ws.cell(row=ratio_start + i, column=4,
                       value={"good": "✓", "bad": "✗"}.get(verdict, "≈"))
        chip.alignment = Alignment(horizontal="center", vertical="center")
        if verdict == "good":
            chip.font = Font(bold=True, color="157A2E")
            chip.fill = PatternFill("solid", fgColor="E5F3EA")
            ws.cell(row=ratio_start + i, column=1).fill = PatternFill(
                "solid", fgColor="E5F3EA")
        elif verdict == "bad":
            chip.font = Font(bold=True, color=RED)
            chip.fill = PatternFill("solid", fgColor="FBE5E5")
            ws.cell(row=ratio_start + i, column=1).fill = PatternFill(
                "solid", fgColor="FBE5E5")

    # CMRRS-style interpretive cards + consistency checks
    insights = build_ratio_insights(result, lang)
    checks = build_consistency_checks(result, lang)
    comp = build_yearly_comparison(result, lang)
    if comp:
        next_row += 2
        next_row = _section(ws, next_row, comp["title"])
        _header(ws, next_row, comp["columns"])
        comp_rows = [
            [r["label"], r["curr"], r["prev"], r["change"],
             r["change_pct"], r["pct_curr"], r["pct_prev"]]
            for r in comp["rows"]
        ]
        _data_rows(ws, next_row + 1, comp_rows)
        next_row += len(comp_rows)
        note = ws.cell(row=next_row + 1, column=1, value=comp.get("note", ""))
        note.font = Font(size=9, italic=True, color="64748B")
    if insights:
        next_row += 2
        next_row = _section(ws, next_row, L["ratio_insights"])
        _header(ws, next_row, [L["ratio_lbl"], L["value_lbl"], L["what_lbl"], L["why_lbl"], L["opinion_lbl"]])
        verdict_color = {"good": GREEN, "bad": RED, "neutral": MUTED}
        ins_rows = []
        for c in insights:
            if c.get("is_percent"):
                val_txt = f"{c['value']:,.2f}%"
            elif c.get("is_days"):
                val_txt = f"{c['value']:,.0f}" + (" يوم" if lang == "ar" else " days")
            else:
                val_txt = f"{c['value']:,.2f}x"
            ins_rows.append([
                c["label"],
                val_txt,
                c["what"], c["why"], c["opinion"],
            ])
        insight_start = next_row + 1
        _data_rows(ws, insight_start, ins_rows)
        # wrap the long text columns + colour the verdict column
        for i, c in enumerate(insights):
            for col in (3, 4, 5):
                cell = ws.cell(row=insight_start + i, column=col)
                cell.alignment = Alignment(
                    horizontal=text_align, vertical="top", wrap_text=True)
            vcell = ws.cell(row=insight_start + i, column=5)
            vcell.font = Font(size=10, bold=True,
                              color=verdict_color.get(c.get("verdict"), MUTED))
            ws.row_dimensions[insight_start + i].height = 42
        next_row += len(ins_rows)
    if checks:
        next_row += 2
        next_row = _section(ws, next_row, L["consistency"])
        _header(ws, next_row, [L["check_col"], L["check_result_col"]])
        chk_rows = [
            [c["label"], ("✓ " if c["ok"] else "✗ ") + c["detail"]]
            for c in checks
        ]
        _data_rows(ws, next_row + 1, chk_rows)
        next_row += len(chk_rows)

    # score + verdict
    if score and score.get("score") is not None:
        next_row += 1
        next_row = _section(ws, next_row, L["score"])
        grade = score.get("grade") or {}
        rows = [
            [L["score_value"], score["score"]],
            [L["score_grade"], grade.get(lang) or grade.get("en") or ""],
        ]
        for d in score.get("dimensions") or []:
            rows.append([d.get(lang) or d.get("en") or d.get("key", ""), f"{d['points']}/{d['weight']}"])
        _data_rows(ws, next_row + 1, rows, fmts={2: "0.0"})

    # scenarios
    if scenarios:
        next_row += 1
        next_row = _section(ws, next_row, L["scenarios"])
        _header(ws, next_row, [L["item"], L["scenario_growth"], L["scenario_rev"], L["scenario_net"]])
        sc_rows = [
            [
                s.get(lang) or s.get("en") or s.get("key"),
                f"{s['growth_pct']:+.1f}%",
                s["revenue"],
                s["net"],
            ]
            for s in scenarios["scenarios"]
        ]
        _data_rows(ws, next_row + 1, sc_rows, fmts={3: "#,##0", 4: "#,##0"})
    _autosize(ws)

    # ---- Sheet 2: trends + opex distribution (charts sheet) ---------------
    # The sheet exists when there are multi-period series AND/OR an opex
    # breakdown from the built statements (company ledgers) — so single-
    # period ledger companies get their pie chart too.
    opex_detail: list[dict] = []
    if stmts:
        try:
            opex_detail = [
                ln for ln in ((stmts.get("income_statement") or {}).get("detail") or {}).get("opex") or []
                if isinstance(ln.get("amount"), (int, float))
                and not isinstance(ln.get("amount"), bool)
                and ln["amount"] > 0
            ]
        except Exception:
            opex_detail = []
    series = result.get("series") or {}
    if series or len(opex_detail) >= 2:
        ws = _branded_sheet(L["trends"], L["trends"], L["trends_sub"])
        n = 0
        if series:
            concepts = list(series.items())
            headers = [L["period"]] + [
                s.get(lang) or s.get("en") or concept for concept, s in concepts
            ]
            _header(ws, HEADER_SPAN, headers)
            n = max(len(s.get("values") or []) for _, s in concepts)
            rows = []
            for i in range(n):
                rows.append([i + 1] + [
                    (s.get("values") or [])[i] if i < len(s.get("values") or []) else None
                    for _, s in concepts
                ])
            fmts = {c: "#,##0" for c in range(1, len(headers) + 1)}
            _data_rows(ws, HEADER_SPAN + 1, rows, fmts=fmts)
            ws.freeze_panes = f"A{HEADER_SPAN + 1}"
        _autosize(ws)
        # ---- native charts: the sheet PROMISES charts — deliver them -----
        try:
            from openpyxl.chart import BarChart, LineChart, PieChart, Reference
            from openpyxl.chart.label import DataLabelList

            if series:
                # One combined line chart (all concepts over periods) + one
                # bar chart per concept so every indicator is visual.
                concepts = list(series.items())
                headers_len = 1 + len(concepts)
                line = LineChart()
                line.title = L["trends"]
                line.style = 12
                line.height, line.width = 9, 20
                line.add_data(
                    Reference(ws, min_col=2, max_col=headers_len,
                              min_row=HEADER_SPAN, max_row=HEADER_SPAN + n),
                    titles_from_data=True,
                )
                line.set_categories(Reference(ws, min_col=1, min_row=HEADER_SPAN + 1,
                                              max_row=HEADER_SPAN + n))
                for s_obj in line.series:
                    s_obj.smooth = False
                ws.add_chart(line, f"A{HEADER_SPAN + n + 4}")

                for j, (concept, s_obj) in enumerate(concepts[:6]):
                    col = 2 + j
                    bar = BarChart()
                    bar.type = "col"
                    bar.style = 10
                    bar.height, bar.width = 7, 9
                    bar.title = s_obj.get(lang) or s_obj.get("en") or concept
                    bar.add_data(
                        Reference(ws, min_col=col, min_row=HEADER_SPAN,
                                  max_row=HEADER_SPAN + n),
                        titles_from_data=True,
                    )
                    bar.set_categories(Reference(ws, min_col=1, min_row=HEADER_SPAN + 1,
                                                 max_row=HEADER_SPAN + n))
                    bar.legend = None
                    # two per row under the combined line chart
                    row_off = (j // 2) * 15
                    col_off = (j % 2) * 10
                    anchor_row = HEADER_SPAN + n + 4 + 19 + row_off
                    ws.add_chart(bar, f"{chr(65 + col_off)}{anchor_row}")

            # ---- opex distribution pie (from the ledger's expense detail) --
            if len(opex_detail) >= 2:
                top = sorted(opex_detail, key=lambda x: x["amount"],
                             reverse=True)[:8]
                if len(opex_detail) > 8:
                    others = sum(x["amount"] for x in opex_detail[8:])
                    top.append({"account": L["opex_others"],
                                "amount": round(others, 2)})
                pie_row = (HEADER_SPAN + n + 4 + 19 + 30 + 17) if series \
                    else HEADER_SPAN + 2
                head = ws.cell(row=pie_row, column=1, value=L["opex_pie_title"])
                head.font = Font(bold=True, size=12, color=TEAL)
                base = pie_row + 1
                ws.cell(row=base, column=1, value=L["item"]).font = Font(bold=True, size=10)
                ws.cell(row=base, column=2, value=L["value"]).font = Font(bold=True, size=10)
                for i, ln in enumerate(top):
                    ws.cell(row=base + 1 + i, column=1, value=ln["account"])
                    amt = ws.cell(row=base + 1 + i, column=2,
                                  value=round(ln["amount"], 2))
                    amt.number_format = "#,##0"
                pie = PieChart()
                pie.title = L["opex_pie_title"]
                pie.height, pie.width = 9.5, 13
                pie.add_data(
                    Reference(ws, min_col=2, min_row=base, max_row=base + len(top)),
                    titles_from_data=True,
                )
                pie.set_categories(
                    Reference(ws, min_col=1, min_row=base + 1,
                              max_row=base + len(top)))
                pie.dataLabels = DataLabelList()
                pie.dataLabels.showPercent = True
                ws.add_chart(pie, f"D{pie_row}")
        except Exception:
            pass

        # ---- activity evolution: collection period & inventory turnover --
        # per-period working-capital heartbeat: its own small table plus a
        # native line chart (days and turns are both small numbers, so one
        # axis stays readable)
        try:
            from .analyzer import compute_activity_series
            act = compute_activity_series(result.get("metrics") or {})
            if act:
                act_row = (HEADER_SPAN + n + 92) if series \
                    else 25 + HEADER_SPAN
                head = ws.cell(row=act_row, column=1,
                               value=L["activity_title"])
                head.font = Font(bold=True, size=12, color=TEAL)
                base = act_row + 1
                # only the series the analysis actually supports become
                # table columns / chart lines (days series + turnover)
                col_defs = (("receivable_days", L["dso_lbl"]),
                            ("inventory_turnover", L["inv_turn_lbl"]),
                            ("days_payable", L["dpo_lbl"]),
                            ("cash_conversion_cycle", L["ccc_lbl"]))
                present = [(k, lbl) for k, lbl in col_defs if k in act]
                _header(ws, base, [L["period"]] + [lbl for _, lbl in present])
                col_vals = [(act[k] or {}).get("values") or []
                            for k, _ in present]
                m = max((len(v) for v in col_vals), default=0)
                rows = [[i + 1] + [(v[i] if i < len(v) else None)
                                   for v in col_vals]
                        for i in range(m)]
                _data_rows(ws, base + 1, rows, fmts={
                    c + 2: ("#,##0.00" if k == "inventory_turnover"
                            else "#,##0.0")
                    for c, (k, _) in enumerate(present)
                })
                chart = LineChart()
                chart.title = L["activity_title"]
                chart.style = 12
                chart.height, chart.width = 8, 15
                chart.add_data(
                    Reference(ws, min_col=2,
                              max_col=1 + len(present),
                              min_row=base, max_row=base + m),
                    titles_from_data=True,
                )
                chart.set_categories(Reference(ws, min_col=1,
                                               min_row=base + 1,
                                               max_row=base + m))
                for s_obj in chart.series:
                    s_obj.smooth = False
                ws.add_chart(chart, f"{chr(64 + 3 + len(present))}{base}")
        except Exception:
            pass

    # ---- Sheet 3: forecast -------------------------------------------------
    forecast = result.get("forecast") or []
    if forecast:
        ws = _branded_sheet(L["forecast"], L["forecast"], L["forecast_sub"])
        _header(ws, HEADER_SPAN, [L["item"], L["change"], L["trend"]])
        rows = []
        for f in forecast:
            trend_key = f.get("trend")
            rows.append([
                f.get(lang) or f.get("en") or "",
                f.get("change_pct"),
                L.get(trend_key, ""),
            ])
        _data_rows(ws, HEADER_SPAN + 1, rows, fmts={2: '+0.0"%";-0.0"%";0.0"%"'})
        for i, f in enumerate(forecast):
            color = GREEN if f.get("trend") == "up" else RED if f.get("trend") == "down" else MUTED
            ws.cell(row=HEADER_SPAN + 1 + i, column=3).font = Font(bold=True, color=color)
        _autosize(ws)

    # ---- Sheet 3b: annual growth + next-year forecast (mean growth) --------
    ycomp = build_yearly_comparison(result, lang)
    if ycomp and ycomp.get("years"):
        yrz = list(ycomp["years"])
        fc_label = ycomp.get("forecast_label") or ""
        head = [L["item"]] + yrz + ([fc_label] if fc_label else [])
        n_fc = len(head)
        ws = _branded_sheet(L["growth_fc"], L["growth_fc"], L["growth_fc_sub"])
        AMBER = "B45309"
        # table 1: values by year, then the forecast column
        r = _section(ws, HEADER_SPAN, L["growth_values"])
        _header(ws, r, head)
        r += 1
        for grow_row in ycomp["rows"]:
            pts = grow_row["points"]
            fc = grow_row.get("forecast")
            vals = [grow_row["label"]] + [p["raw"] for p in pts]
            vals += [None] * (len(yrz) - len(pts))
            vals.append(fc["raw"] if fc else None)
            _data_rows(ws, r, [vals],
                       fmts={c: "#,##0.00" for c in range(2, n_fc + 1)})
            if fc:
                ws.cell(row=r, column=n_fc).font = Font(bold=True, color=AMBER)
            r += 1
        # table 2: YoY % per year, then the forecast mean growth
        r = _section(ws, r + 1, L["growth_yoy"])
        _header(ws, r, head)
        r += 1
        for grow_row in ycomp["rows"]:
            pts = grow_row["points"]
            fc = grow_row.get("forecast")
            vals = [grow_row["label"]]
            for k, p in enumerate(pts):
                g = None
                if k and pts[k - 1]["raw"]:
                    g = (p["raw"] - pts[k - 1]["raw"]) \
                        / abs(pts[k - 1]["raw"]) * 100
                vals.append(g)
            vals += [None] * (len(yrz) - len(pts))
            vals.append(float(str(fc["growth"]).rstrip("%")) if fc else None)
            _data_rows(ws, r, [vals],
                       fmts={c: '+0.0"%";-0.0"%";0.0"%"'
                             for c in range(2, n_fc + 1)})
            if fc:
                ws.cell(row=r, column=n_fc).font = Font(bold=True, color=AMBER)
            r += 1
        note = ws.cell(row=r + 1, column=1,
                       value=ycomp.get("growth_note") or "")
        note.font = Font(size=9, color=MUTED, italic=True)
        note.alignment = Alignment(horizontal=text_align, vertical="center")
        _autosize(ws)

    # ---- Sheet 4: notes -----------------------------------------------------
    if row.notes:
        ws = _branded_sheet(L["notes"], L["notes"], L["notes_sub"])
        r = HEADER_SPAN
        for line in str(row.notes).splitlines() or [str(row.notes)]:
            cell = ws.cell(row=r, column=1, value=line)
            cell.alignment = Alignment(wrap_text=True, horizontal=text_align, vertical="top")
            r += 1
        ws.column_dimensions["A"].width = 100

    # ---- Sheet 5: financial statements (print-ready) -----------------------
    def _statements_worksheet(st: dict) -> None:
        """Print-ready statements sheet: trial balance + income statement +
        statement of financial position + cash flow, each as a bordered
        table, plus a native profit waterfall chart (revenue → net profit)."""
        from openpyxl.chart import BarChart, Reference
        from openpyxl.chart.series import DataPoint

        derived = bool(st.get("derived_from_metrics"))
        ws = _sheet(L["derived_title"] if derived else L["stmts_title"])
        _print_footer(ws)
        r = _brand_banner(ws, title,
                          L["derived_title"] if derived else L["stmts_title"])
        num = "#,##0.00"

        def _table(head_row: int, section: str, headers: list,
                   data: list, bold_rows: set | None = None) -> int:
            """One bordered table; returns the next free row. Numbers keep
            numeric values with an accounting-ish format; totals bolded."""
            rr = _section(ws, head_row, section)
            _header(ws, rr, headers)
            rr += 1
            for i, row_vals in enumerate(data):
                for c, v in enumerate(row_vals, 1):
                    cell = ws.cell(row=rr, column=c, value=v)
                    cell.border = box
                    if c == 1:
                        cell.alignment = Alignment(horizontal=text_align, vertical="center")
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        cell.number_format = num
                        cell.alignment = Alignment(horizontal="right" if not rtl else "left"
                                                   if False else "center", vertical="center")
                    if bold_rows and i in bold_rows:
                        cell.font = Font(bold=True, size=10, color=TEAL)
                        cell.fill = PatternFill("solid", fgColor=TEAL_SOFT)
                    elif i % 2 == 1:
                        cell.fill = PatternFill("solid", fgColor=TEAL_SOFT)
                rr += 1
            return rr + 1

        def _derived_periods_body(st: dict) -> None:
            """Comparison-file statements (derived from metric series, no
            trial balance): for EACH period — income statement, financial
            position and simplified cash flow under a per-period title —
            then one comparative grid (rows = concepts, columns = periods)."""
            from .statements import _derived_comparative_grid

            nonlocal r

            for p in st.get("periods") or []:
                lbl = (p.get("label") or {}).get(lang) \
                    or (p.get("label") or {}).get("en") or ""
                isx_p = p.get("income_statement") or {}
                lines = isx_p.get("lines") or []
                if lines:
                    data = [[ln.get(lang) or ln.get("en"), ln.get("amount")]
                            for ln in lines]
                    bold = {i for i, ln in enumerate(lines) if ln.get("bold")}
                    r = _table(r, f"{L['is_title']} — {lbl}",
                               [L["item"], L["value"]], data, bold)
                bs = p.get("balance_sheet") or {}
                bs_data = [[ln.get("ar"), ln.get("en"), ln.get("amount")]
                           for ln in (bs.get("assets", {}).get("lines") or [])]
                bs_data += [[ln.get("ar"), ln.get("en"), ln.get("amount")]
                            for ln in (bs.get("liabilities_equity", {}).get("lines") or [])]
                if bs_data:
                    r = _table(r, f"{L['bs_title']} — {lbl}",
                               [L["item"], L["item"], L["value"]], bs_data,
                               bold_rows={len(bs_data) - 1})
                cf = p.get("cash_flow") or {}
                cf_data = []
                # «other» = the file's own FX/other-effects block when stated
                # (absent on TB-derived faces — the guard below skips it)
                for key in ("operating", "investing", "financing", "other"):
                    block = cf.get(key) or {}
                    if not block:
                        continue
                    cf_data.append([block.get("label", {}).get(lang)
                                    or block.get("label", {}).get("en")
                                    or (L["cf_" + key] if key != "other" else
                                        ("أثر العملات والبنود الأخرى" if lang == "ar"
                                         else "FX and other effects")),
                                    block.get("total")])
                    for ln in block.get("lines") or []:
                        cf_data.append(["   " + str(ln.get("ar") if lang == "ar"
                                                     else ln.get("en")),
                                        ln.get("amount")])
                if cf.get("net_change") is not None:
                    cf_data.append([L["cf_change"], cf.get("net_change")])
                if cf.get("cash_balance") is not None:
                    cf_data.append([L["cf_balance"], cf.get("cash_balance")])
                if cf_data:
                    r = _table(r, f"{L['cf_title']} — {lbl}",
                               [L["item"], L["value"]], cf_data)

            headers, rows, bold = _derived_comparative_grid(st, lang)
            if rows:
                # rows already carry their label in column 1 (label, *values)
                r = _table(r, L["compare_col"], [L["item"]] + list(headers),
                           [list(row) for row in rows], bold)

            # «مقارنة قائمة الدخل» — the income-statement comparison with the
            # CHANGE-BY-VALUE column (ريال) beside its percentage: one row per
            # P&L concept (current vs prior), judgment-coloured changes. This
            # is the ONLY income comparison a derived file gets, so it carries
            # the same horizontal analysis the yearly-comparison UI shows.
            ycmp = build_yearly_comparison(result, lang)
            if ycmp and ycmp.get("rows"):
                yhead = list(ycmp["columns"][:5])   # البند، الحالية، السابقة، بالقيمة، بالنسبة
                ydata = [[rw["label"], rw["curr"], rw["prev"],
                          rw["change"], rw["change_pct"]]
                         for rw in ycmp["rows"]]
                r = _table(r, L["is_change_title"], yhead, ydata)
                first_y = r - len(ydata) - 1
                for i, rw in enumerate(ycmp["rows"]):
                    color = {"good": GREEN, "bad": RED}.get(rw.get("color"), MUTED)
                    for col in (4, 5):   # التغير بالقيمة + التغير بالنسبة
                        ws.cell(row=first_y + i, column=col).font = \
                            Font(bold=True, size=10, color=color)

                # mini clustered column chart BESIDE the comparison table:
                # the two periods' values per concept row (same data as the
                # table's الحالية/السابقة columns, numeric block in F..H)
                from openpyxl.chart import BarChart, Reference

                blk_hdr = first_y - 1
                for c, h in enumerate((L["item"], L["prev_period"],
                                       L["curr_period"]), 6):
                    cell = ws.cell(row=blk_hdr, column=c, value=h)
                    cell.font = Font(bold=True, color="FFFFFF", size=10)
                    cell.fill = PatternFill("solid", fgColor=TEAL)
                    cell.alignment = Alignment(horizontal="center",
                                               vertical="center", wrap_text=True)
                    cell.border = box
                for j, rw in enumerate(ycmp["rows"]):
                    rr = blk_hdr + 1 + j
                    for c, v in ((6, rw["label"]), (7, rw.get("prev_val")),
                                 (8, rw.get("curr_val"))):
                        cell = ws.cell(row=rr, column=c, value=v)
                        cell.border = box
                        if c == 6:
                            cell.font = Font(size=10)
                            cell.alignment = Alignment(
                                horizontal=text_align, vertical="center")
                        else:
                            cell.number_format = "#,##0"
                            cell.alignment = Alignment(horizontal="center",
                                                       vertical="center")
                            cell.font = Font(size=10)
                chart = BarChart()
                chart.type = "col"
                chart.style = 10
                chart.title = L["is_change_title"]
                chart.height, chart.width = 6.8, 12.5
                chart.gapWidth = 60
                data = Reference(ws, min_col=7, max_col=8, min_row=blk_hdr,
                                 max_row=blk_hdr + len(ycmp["rows"]))
                cats = Reference(ws, min_col=6, min_row=blk_hdr + 1,
                                 max_row=blk_hdr + len(ycmp["rows"]))
                chart.add_data(data, titles_from_data=True)
                chart.set_categories(cats)
                chart.series[0].graphicalProperties.solidFill = "94A3B8"
                chart.series[1].graphicalProperties.solidFill = "0F766E"
                chart.legend.position = "b"
                ws.add_chart(chart, f"I{blk_hdr}")

        # ---- trial balance (condensed: account / debit / credit) ----------
        tb = st.get("trial_balance") or {}
        tb_rows = [
            [a.get("account"), a.get("debit"), a.get("credit")]
            for a in (tb.get("accounts") or [])
        ]
        if tb_rows:
            r = _table(r, L["tb_title"], [L["item"], L["value"], L["value"]],
                       tb_rows)

        # ---- income statement -------------------------------------------
        # with two periods available, each line gains a judgment-coloured
        # «مقارنة بالفترة السابقة» column (revenue up = green, costs up = red)
        if st.get("derived_from_metrics"):
            # comparison file (United-style): the per-period faces + the
            # comparative grid already show every period side by side, so
            # the single-face comparison column does not apply.
            _derived_periods_body(st)
            _autosize(ws)
            return
        isx = st.get("income_statement") or {}
        is_lines = isx.get("lines") or []
        if is_lines:
            comp = _income_comparison(result, st)
            has_comp = bool(comp)
            data = []
            for idx, ln in enumerate(is_lines):
                row = [ln.get(lang) or ln.get("en"), ln.get("amount")]
                if has_comp:
                    # change AMOUNT (SAR) first, then the % — the signed
                    # difference beside its percentage (2023 vs 2022)
                    row.append(comp[idx]["change"] if idx in comp else None)
                    row.append(comp[idx]["pct"] if idx in comp else None)
                data.append(row)
            bold = {i for i, ln in enumerate(is_lines) if ln.get("bold")}
            headers = ([L["item"], L["value"]]
                       + ([L["change_amount"], L["prev_compare"]] if has_comp else []))
            is_head_row = r
            r = _table(r, L["is_title"], headers, data, bold)
            if has_comp:
                for idx, ln in enumerate(is_lines):
                    amt_cell = ws.cell(row=is_head_row + 2 + idx, column=3)
                    pct_cell = ws.cell(row=is_head_row + 2 + idx, column=4)
                    if idx in comp:
                        change = comp[idx]["change"]
                        pct = comp[idx]["pct"]
                        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◄►")
                        good = (pct < 0) if comp[idx]["is_cost"] else (pct > 0)
                        color = MUTED if pct == 0 else (GREEN if good else RED)
                        amt_cell.value = f"{change:+,.0f} {arrow}"
                        amt_cell.number_format = "@"
                        amt_cell.alignment = Alignment(horizontal="center",
                                                       vertical="center")
                        amt_cell.font = Font(bold=True, size=10, color=color)
                        pct_cell.value = f"{pct:+.1f}% {arrow}"
                        pct_cell.font = Font(bold=True, size=10, color=color)
                    else:
                        amt_cell.value = "—"
                        amt_cell.font = Font(size=10, color=MUTED)
                        pct_cell.value = "—"
                        pct_cell.font = Font(size=10, color=MUTED)

                # mini clustered column chart BESIDE the face: the two
                # periods' values for every line carrying the new change
                # columns — its data block sits in F..H (visible, fed to the
                # chart), the chart floats beside the block
                from openpyxl.chart import BarChart, Reference

                comp_rows = [idx for idx in comp]
                blk_hdr = is_head_row + 1
                for c, h in enumerate((L["item"], L["prev_period"],
                                       L["curr_period"]), 6):
                    cell = ws.cell(row=blk_hdr, column=c, value=h)
                    cell.font = Font(bold=True, color="FFFFFF", size=10)
                    cell.fill = PatternFill("solid", fgColor=TEAL)
                    cell.alignment = Alignment(horizontal="center",
                                               vertical="center", wrap_text=True)
                    cell.border = box
                for j, idx in enumerate(comp_rows):
                    rr = blk_hdr + 1 + j
                    label = is_lines[idx].get(lang) or is_lines[idx].get("en")
                    for c, v in ((6, label), (7, comp[idx]["prev"]),
                                 (8, comp[idx]["curr"])):
                        cell = ws.cell(row=rr, column=c, value=v)
                        cell.border = box
                        if c == 6:
                            cell.font = Font(size=10)
                            cell.alignment = Alignment(
                                horizontal=text_align, vertical="center")
                        else:
                            cell.number_format = "#,##0"
                            cell.alignment = Alignment(horizontal="center",
                                                       vertical="center")
                            cell.font = Font(size=10)
                chart = BarChart()
                chart.type = "col"
                chart.style = 10
                chart.title = L["is_change_title"]
                chart.height, chart.width = 6.8, 12.5
                chart.gapWidth = 60
                data = Reference(ws, min_col=7, max_col=8, min_row=blk_hdr,
                                 max_row=blk_hdr + len(comp_rows))
                cats = Reference(ws, min_col=6, min_row=blk_hdr + 1,
                                 max_row=blk_hdr + len(comp_rows))
                chart.add_data(data, titles_from_data=True)
                chart.set_categories(cats)
                chart.series[0].graphicalProperties.solidFill = "94A3B8"
                chart.series[1].graphicalProperties.solidFill = "0F766E"
                chart.legend.position = "b"
                ws.add_chart(chart, f"I{blk_hdr}")

        # ---- statement of financial position -----------------------------
        # the income comparison's balance-sheet twin: with two periods whose
        # latest values tie the face, every line gains a judgment-coloured
        # «مقارنة بالفترة السابقة» column (assets/equity up = green,
        # liabilities up = red). Totals (assets / liabilities / equity) are
        # appended as comparison rows when their concept is captured.
        bs = st.get("balance_sheet") or {}
        bs_lines = (bs.get("assets", {}).get("lines") or []) + \
            (bs.get("liabilities_equity", {}).get("lines") or [])
        if bs_lines:
            bcomp = _balance_comparison(result, st)
            has_bcomp = bool(bcomp)

            def _bs_row(ln, extra=None):
                row = [ln.get("ar"), ln.get("en"), ln.get("amount")]
                if extra is not None:
                    row.append(extra)
                return row

            bs_data = [_bs_row(ln, None if not has_bcomp else
                               (bcomp[i]["pct"] if i in bcomp else "—"))
                       for i, ln in enumerate(bs_lines)]
            if has_bcomp:
                # comparison totals — appended as extra rows ONLY when the
                # comparison column exists (never break the table alignment)
                bs_totals = {
                    "assets": (bs.get("assets") or {}).get("total"),
                    "liabilities": (bs.get("liabilities_equity") or {}).get("total"),
                    "equity": next((ln.get("amount") for ln in
                                    (bs.get("liabilities_equity") or {}).get("lines") or []
                                    if str(ln.get("en")) == "Equity"), None),
                }
                mets = result.get("metrics") or {}
                extra_comp: list[tuple[int, str]] = []  # (bs_data index, kind)
                for tkey, en_name, lbl in (("assets", "Total Assets", L["bs_total_assets"]),
                                           ("liabilities", "Total Liabilities", L["bs_total_liabilities"]),
                                           ("equity", "Equity", L["bs_equity"])):
                    tval = bs_totals.get(tkey)
                    if tval is None:
                        continue
                    kind = "liability" if tkey == "liabilities" else "good_up"
                    mvals = [abs(float(v)) for v in (mets.get(tkey) or [])
                             if isinstance(v, (int, float)) and not isinstance(v, bool)]
                    if not mvals or not _same_ish(mvals[-1], abs(float(tval))):
                        continue  # face total not tied to the captured series
                    prev_v = next((v for v in reversed(mvals[:-1])
                                   if v and not _same_ish(v, mvals[-1])), None)
                    if prev_v:
                        pct = round((mvals[-1] - prev_v) / prev_v * 100, 1)
                        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◄►")
                        bs_data.append([lbl, en_name, tval, f"{pct:+.1f}% {arrow}"])
                        extra_comp.append((len(bs_data) - 1, kind))
                    else:
                        bs_data.append([lbl, en_name, tval, "—"])
                        extra_comp.append((len(bs_data) - 1, kind))
            headers_bs = [L["item"], L["item"], L["value"]] + \
                ([L["prev_compare"]] if has_bcomp else [])
            n_lines = len(bs_lines)
            n_all = len(bs_data)
            r = _table(r, L["bs_title"], headers_bs, bs_data,
                       bold_rows={n_all - 1})
            if has_bcomp:
                first_data = r - n_all - 1
                for i, ln in enumerate(bs_lines):
                    if i >= n_lines:
                        break  # total rows keep their own judgment colour
                    cell = ws.cell(row=first_data + i, column=4)
                    if i in bcomp:
                        pct = bcomp[i]["pct"]
                        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◄►")
                        cell.value = f"{pct:+.1f}% {arrow}"
                        good = (bcomp[i]["kind"] == "good_up") if pct > 0 else \
                            ((bcomp[i]["kind"] != "good_up") if pct < 0 else None)
                        color = MUTED if pct == 0 else (GREEN if good else RED)
                        cell.font = Font(bold=True, size=10, color=color)
                    else:
                        cell.value = "—" if cell.value is None else cell.value
                        cell.font = Font(size=10, color=MUTED)
                # total rows created directly in _table (beyond n_lines):
                # cols 1-3 branded teal; col 4 keeps the JUDGMENT colour
                extra_kind = dict(extra_comp)
                for extra_i in range(n_lines, n_all):
                    row_cells = ws[first_data + extra_i]
                    for col in (1, 2, 3):
                        c2 = row_cells[col - 1]
                        c2.font = Font(bold=True, size=10, color=TEAL)
                        c2.fill = PatternFill("solid", fgColor=TEAL_SOFT)
                    kind = extra_kind.get(extra_i)
                    if kind is None:
                        continue
                    c4 = row_cells[3]
                    val = c4.value
                    if isinstance(val, str) and val.endswith(("▲", "▼", "◄►")):
                        pct = float(val.split("%")[0])
                        good = (kind == "good_up") if pct > 0 else \
                            ((kind != "good_up") if pct < 0 else None)
                        c4.font = Font(bold=True, size=10,
                                       color=MUTED if pct == 0 else (GREEN if good else RED))
                    else:
                        c4.font = Font(size=10, color=MUTED)

        # ---- cash flow (three activities) --------------------------------
        cf = st.get("cash_flow") or {}
        cf_data = []
        # «other» = the file's own FX/other-effects block when stated
        # (absent on TB-derived faces — the guard below skips it)
        for key, lbl in (("operating", "cf_operating"), ("investing", "cf_investing"),
                         ("financing", "cf_financing"), ("other", None)):
            block = cf.get(key) or {}
            if not block:
                continue
            cf_data.append([block.get("label", {}).get(lang)
                            or block.get("label", {}).get("en")
                            or (L[lbl] if lbl else
                                ("أثر العملات والبنود الأخرى" if lang == "ar"
                                 else "FX and other effects")),
                            block.get("total")])
            for ln in block.get("lines") or []:
                cf_data.append(["   " + str(ln.get("ar") if lang == "ar" else ln.get("en")),
                                ln.get("amount")])
        if cf.get("net_change") is not None:
            cf_data.append([L["cf_change"], cf.get("net_change")])
        if cf.get("cash_balance") is not None:
            cf_data.append([L["cf_balance"], cf.get("cash_balance")])
        bold_cf = set()
        if cf_data:
            r = _table(r, L["cf_title"], [L["item"], L["value"]], cf_data, bold_cf)

        def _waterfall_block(start_row: int, title: str, wsteps: list,
                             anchor_row: int | None = None) -> int:
            """Hidden base/rise/fall/sum helper rows + a native stacked-column
            waterfall for `wsteps` [(label, amount, kind)]: kind 'total' and
            'subtotal' render a full bar (and reset the runner), anything else
            is a rise/fall from the running total. The closing bar is painted
            brand teal. Returns the block's header row."""
            ws.cell(row=start_row, column=1, value=title).font = \
                Font(bold=True, size=12, color=TEAL)
            whdr = start_row + 1
            for c, h in enumerate((L["item"], "base", "rise", "fall", "sum"), 1):
                ws.cell(row=whdr, column=c, value=h).font = Font(size=8, color=MUTED)
            running = 0.0
            final_si = 1
            for i, (lbl, amount, kind) in enumerate(wsteps):
                rr = whdr + 1 + i
                ws.cell(row=rr, column=1, value=lbl).font = Font(size=8, color=MUTED)
                rise = fall = None
                if kind in ("total", "subtotal"):
                    base_v, run, rise = 0.0, amount, amount
                    running = amount
                    if amount < 0:  # a loss closes in the fall series
                        rise, fall, base_v = None, -amount, 0.0
                else:
                    if amount >= 0:
                        rise, base_v = amount, running
                    else:
                        fall, base_v = -amount, running + amount
                    running = round(running + amount, 2)
                    run = running
                ws.cell(row=rr, column=2, value=round(base_v, 2)).number_format = num
                if rise is not None:
                    ws.cell(row=rr, column=3, value=round(rise, 2)).number_format = num
                if fall is not None:
                    ws.cell(row=rr, column=4, value=round(fall, 2)).number_format = num
                ws.cell(row=rr, column=5, value=round(run, 2)).number_format = num
                final_si = 1 if rise is not None else 2
            wch = BarChart()
            wch.type = "col"
            wch.grouping = "stacked"
            wch.overlap = 100
            wch.title = title
            wch.height, wch.width = 9, 18
            wch.legend = None
            wch.add_data(
                Reference(ws, min_col=2, max_col=4, min_row=whdr,
                          max_row=whdr + len(wsteps)),
                titles_from_data=True,
            )
            wch.set_categories(Reference(ws, min_col=1, min_row=whdr + 1,
                                         max_row=whdr + len(wsteps)))
            wcolors = {2: "E8EDF3", 3: GREEN, 4: RED}  # base(ghost), rise, fall
            for si, s_obj in enumerate(wch.series):
                s_obj.graphicalProperties.solidFill = wcolors[2 + si]
                s_obj.graphicalProperties.line.noFill = True
            # closing bar (net profit / cash balance) in brand teal —
            # whichever series actually carries it (rise ≥ 0, fall < 0)
            try:
                dp = DataPoint(idx=len(wsteps) - 1)
                dp.graphicalProperties.solidFill = TEAL
                wch.series[final_si].data_points = [dp]
            except Exception:
                pass
            ws.add_chart(wch, f"F{anchor_row or whdr}")
            return whdr

        # ---- native profit waterfall (revenue → net profit) ---------------
        totals = isx.get("totals") or {}
        rev = totals.get("revenue")
        cogs_amt = next((abs(ln["amount"]) for ln in is_lines
                         if ln.get("en") == "Cost of Sales"), None)
        gross = totals.get("gross_profit")
        opex_amt = totals.get("opex")
        op = totals.get("operating_profit")
        net = totals.get("net_profit")
        fin_delta = None
        if op is not None and net is not None and gross is not None:
            fin_delta = round(net - op, 2)  # IFRS 18 categories + taxes net
        steps, hdr = [], None
        if None not in (rev, cogs_amt, gross, opex_amt, net):
            steps = [
                (L["rev_lbl"], rev, "total"),
                (L["cogs_lbl"], -cogs_amt, "minus"),
                (L["gross_lbl"], gross, "subtotal"),
                (L["opex_lbl"], -opex_amt, "minus"),
            ]
            if op is not None:
                steps.append((L["op_lbl"], op, "subtotal"))
            if fin_delta:
                steps.append((L["fin_lbl"], fin_delta, "minus" if fin_delta < 0 else "plus"))
            steps.append((L["net_lbl"], net, "total"))
            hdr = _waterfall_block(r + 1, L["waterfall_title"], steps)

        # ---- native cash-flow waterfall (operating → investing → financing → balance)
        cf_totals = {k: (cf.get(k) or {}).get("total")
                     for k in ("operating", "investing", "financing")}
        if all(v is not None for v in cf_totals.values()) \
                and cf.get("cash_balance") is not None:
            cf_steps = [
                (L["cf_operating"], cf_totals["operating"], "total"),
                (L["cf_investing"], cf_totals["investing"], "delta"),
                (L["cf_financing"], cf_totals["financing"], "delta"),
                (L["cf_balance"], cf.get("cash_balance"), "total"),
            ]
            if hdr:
                # chart 1 is ~9 cm tall (≈ 18 rows): block + chart sit below it
                wf_row, chart_row = hdr + len(steps) + 2, hdr + len(steps) + 21
            else:
                wf_row = chart_row = r + 1
            _waterfall_block(wf_row, L["cf_waterfall_title"], cf_steps,
                             anchor_row=chart_row)
        _autosize(ws)

    # Comparison files without a trial balance (United-style metric capture)
    # still get the statements sheet: the faces are derived per period from
    # the multi-period metric series. Real trial-balance statements (or a
    # previously attached sheet) always win.
    if not stmts:
        try:
            from .statements import build_statements_from_metrics
            stmts = build_statements_from_metrics(
                result.get("metrics") or {},
                result.get("period_labels") or [],
            )
        except Exception:
            stmts = None

    if stmts and isinstance(stmts, dict) \
            and (stmts.get("income_statement") or stmts.get("periods")):
        _statements_worksheet(stmts)

    out = REPORTS / f"export_{analysis_id}.xlsx"
    wb.save(out)
    return FileResponse(
        out,
        filename=f"analysis-{analysis_id}-results.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


_PERIOD_SHEET_RE = re.compile(
    r"(?:19|20)\d{2}|Q[1-4]|الربع|H[12]|"
    r"يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر",
    re.IGNORECASE,
)

# Consolidated/rollup sheets (الإجمالي، الإجمالي العام، Total…) — they mix
# several statement blocks and duplicate the sum of the entity sheets.
_ROLLUP_SHEET_RE = re.compile(r"إجمالي|اجمالي|total", re.IGNORECASE)


def _sales_records_for_tables(tables: list) -> list[dict]:
    """Sales records for a DECLARED sales file (upload-screen «مبيعات»
    kind), trying EVERY parsed table — a multi-sheet invoice workbook
    (one sheet per month/branch) no longer loses its sibling sheets.

    Per sheet: the fixed HEADER detector first (التاريخ أشهرًا، مسؤول المبيعات
    مندوبًا، الكمية عمليات، المبلغ الإجمالي مبيعات) — it maps invoice-grain
    columns correctly; the positional-tolerant _force_sales_records is
    the fallback for sheets whose headers it cannot match at all.
    Returns [] when NO sheet yields any sales row.
    """
    from .sales_analyzer import detect_sales_table

    records: list[dict] = []
    for t in tables:
        recs = detect_sales_table(t.get("rows") or [])
        if recs:
            records.extend(recs)
            continue
        records.extend(_force_sales_records(t.get("rows") or []))
    return records


def _force_sales_records(rows: list) -> list[dict]:
    """Convert rows of a DECLARED sales file (upload-screen «مبيعات» kind)
    into sales records, bypassing the strict header detection.

    The user has already said this is a sales grid, so the reading is
    positional-tolerant: find the numeric-sales column (highest numeric
    density), then month / region / rep columns among the text columns by
    their value contents (month labels, repeated groups, names). Rows with
    no numeric sales and no month/rep/region hint are detail junk and
    skipped. Returns [] when the sheet cannot yield any sales row at all —
    the endpoint then refuses the file with an explanatory error instead
    of producing a wrong-reading financial analysis.
    """
    from .sales_analyzer import _month_index, _num

    if not rows or len(rows) < 2:
        return []
    n = max(len(r) for r in rows)

    def cell(r, i):
        return r[i] if i < len(r) else None

    # column profiles
    text_density, num_ok, repeat_groups = [], [], []
    for i in range(n):
        vals = [cell(r, i) for r in rows[1:]]
        vals = [v for v in vals if v is not None and str(v).strip()]
        text_density.append(
            sum(1 for v in vals if _num(v) is None) / max(1, len(vals))
        )
        nums = [_num(v) for v in vals]
        num_ok.append(sum(1 for v in nums if v is not None and v > 0) / max(1, len(vals)))
        uniq = {str(v).strip() for v in vals}
        repeat_groups.append(len(uniq) / max(1, len(vals)))

    # sales column: high numeric density; prefer the RIGHT-most such column
    # (Arabic financial sheets put the amount adjacent to the last text col)
    sales_idx = max(
        (i for i in range(n) if num_ok[i] > 0.55), default=None, key=None
    )
    if sales_idx is None:
        return []

    # month column: text column whose values mostly parse as month labels
    month_idx = None
    for i in range(n):
        if i == sales_idx or text_density[i] < 0.5:
            continue
        vals = [str(cell(r, i) or "").strip() for r in rows[1:]]
        vals = [v for v in vals if v]
        if vals and sum(1 for v in vals if _month_index(v) is not None) / len(vals) >= 0.5:
            month_idx = i
            break

    # region / rep among remaining text columns: group columns (low unique
    # ratio) → region; the freest text column → rep
    remaining = [i for i in range(n) if i not in (sales_idx, month_idx) and text_density[i] >= 0.5]
    region_idx = min((i for i in remaining if repeat_groups[i] <= 0.55), default=None)
    rep_idx = None
    reps_left = [i for i in remaining if i != region_idx]
    if reps_left:
        rep_idx = max(reps_left, key=lambda i: repeat_groups[i])

    records = []
    for r in rows[1:]:
        sales = _num(cell(r, sales_idx))
        if sales is None or sales <= 0:
            continue
        month = str(cell(r, month_idx) or "").strip() if month_idx is not None else ""
        region = str(cell(r, region_idx) or "").strip() if region_idx is not None else ""
        rep = str(cell(r, rep_idx) or "").strip() if rep_idx is not None else ""
        if not month and not region and not rep:
            continue
        records.append({
            "month": month, "region": region, "rep": rep,
            "txns": 0, "sales": sales,
            "new_customers": 0,
            "target": None,
        })
    return records


def _split_entity_sheets(tables: list, suffix: str = "") -> list:
    """Sheets of a multi-ENTITY SPREADSHEET: at least two sheets that each
    carry their own revenue row (a self-contained income statement per
    company) and whose names are not period labels. Sheet-per-year workbooks
    (names like 2023/2024) stay merged as one multi-period analysis; a
    workbook of one company split across an income-statement + balance-sheet
    sheet never reaches two revenue sheets and stays merged too.

    The consolidated «الإجمالي / total» sheet JOINS the split as the group's
    own consolidated analysis (its stacked statement blocks give the
    consolidation its periods) — the upload path aligns its chronology to
    the companies' sum via _align_rollup_chronology.

    Only spreadsheet files split at all: a Word/PDF/PPTX document is ONE
    entity by construction — its tables are complementary statements of the
    same company (income statement + balance sheet + cash flows), and
    treating each as a separate company produced three wrong analyses for a
    single Microsoft-style statements document.
    """
    if suffix and suffix not in {".xlsx", ".xlsm"}:
        return []
    entities = [
        t for t in (tables or [])
        if t.get("name")
        and not _PERIOD_SHEET_RE.search(str(t.get("name")))
        and table_has_revenue(t)
    ]
    return entities if len(entities) >= 2 else []


def _align_rollup_chronology(rollup_res: dict, rollup_rows: list,
                             company_res: list[dict]) -> dict:
    """A consolidated «الإجمالي» sheet may stack its statement blocks
    [current, prior] — the analyzer reads row order, so its LAST value
    would wrongly become «latest». The companies extracted from the same
    workbook are the ground truth: the sum of their latest values IS the
    current consolidated period. When the rollup's revenue series OPENS at
    that sum instead of closing at it, every metric series is reversed so
    periods run oldest → latest.

    The stated net lines (الربح) reverse with the same decision — the
    generic extractor keeps only the last one as a KPI, losing the series.
    """
    def _latest(res: dict, concept: str) -> float | None:
        vals = (res.get("metrics") or {}).get(concept) or []
        nums = [abs(float(v)) for v in vals
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return nums[-1] if nums else None

    anchor = sum(v for v in (_latest(r, "revenue") for r in company_res) if v)
    rev = [float(v) for v in ((rollup_res.get("metrics") or {}).get("revenue") or [])
           if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not anchor or len(rev) < 2:
        return rollup_res
    open_v, close_v = abs(rev[0]), abs(rev[-1])
    if not (abs(open_v - anchor) <= 0.005 * anchor
            and abs(open_v - anchor) < abs(close_v - anchor)):
        return rollup_res  # already oldest → latest — nothing to do

    metrics: dict[str, list[float]] = {}
    for concept, values in (rollup_res.get("metrics") or {}).items():
        nums = [float(v) for v in (values or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        metrics[concept] = list(reversed(nums)) if len(nums) >= 2 else nums

    # stated net lines from the sheet itself (الربح / صافي الربح — never
    # مجمل الربح), one value per block, reversed with the same decision
    net_vals: list[float] = []
    for row in rollup_rows or []:
        cells = [str(c).strip() for c in (row or []) if c is not None and str(c).strip()]
        if not cells:
            continue
        head = cells[0]
        if (head.startswith("الربح") or head.startswith("صافي")) and "مجمل" not in head:
            for c in (row or [])[1:]:
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    net_vals.append(float(c))
                    break
    if len(net_vals) >= 2:
        metrics["net_profit"] = list(reversed(net_vals))

    rollup_res["metrics"] = metrics
    return rollup_res


def _tb_acceptable(cand: dict) -> bool:
    """A REAL trial balance: enough accounts, non-empty totals — and it
    BALANCES. Income-statement sheets parsed as pseudo-accounts yield
    unbalanced garbage; the balance gate rejects them."""
    tb = (cand or {}).get("trial_balance") or {}
    accounts = tb.get("accounts") or []
    return (
        len(accounts) >= 6
        and (tb.get("total_debit") or 0) > 0
        and bool(tb.get("balanced"))
    )


# Income-statement face lines → concept/kind for the previous-period
# comparison column in the statements worksheet. `kind` drives the judgment
# colour (profit lines: up = good; cost lines: up = bad), mirroring
# build_yearly_comparison's rule. Lines absent here render «—».
_INCOME_LINE_CONCEPTS = {
    "Revenue": ("revenue", "profit"),
    "Cost of Sales": ("cogs", "cost"),
    "Gross Profit": ("gross_profit", "profit"),
    "Operating Expenses": ("opex", "cost"),
    "Operating Profit": ("operating_profit", "profit"),
    "Investment Income": ("investment_income", "profit"),
    "Finance Costs": ("finance_cost", "cost"),
    "Profit before Financing and Income Taxes": ("before_fin_tax", "profit"),
    "Zakat and Income Tax": ("tax_expense", "cost"),
    "Net Profit": ("net_profit", "profit"),
}

# Derived face subtotals, composed from their concepts exactly as
# build_statements composes the face (IFRS 18 chain). A component concept
# ABSENT from the metrics contributes zero to both periods; PRESENT but
# single-period blocks the derived line's comparison.
_INCOME_DERIVED = {
    "gross_profit": (("revenue", 1.0), ("cogs", -1.0)),
    "operating_profit": (("revenue", 1.0), ("cogs", -1.0), ("opex", -1.0)),
    "before_fin_tax": (("revenue", 1.0), ("cogs", -1.0), ("opex", -1.0),
                       ("investment_income", 1.0), ("finance_cost", -1.0)),
    "net_profit": (("revenue", 1.0), ("cogs", -1.0), ("opex", -1.0),
                   ("investment_income", 1.0), ("finance_cost", -1.0),
                   ("tax_expense", -1.0)),
}


def _income_comparison(result: dict, st: dict) -> dict[int, dict]:
    """«مقارنة بالفترة السابقة» per income-statement face line — only when
    the analysis carries MORE THAN ONE period for the P&L concepts AND the
    captured latest values tie to the attached statements' face (i.e. the
    attached statements ARE the latest captured period; comparing them
    against an unrelated period would be dishonest).

    The previous figure of each concept is its previous DISTINCT non-zero
    period (a trial-balance sheet sharing the workbook re-states the latest
    values — those duplicates are skipped, not treated as a period).
    Returns {line_index: {"pct": float, "change": float, "curr": float,
    "prev": float, "is_cost": bool}} — «change» is the signed SAR amount
    (curr − prev) beside the percentage, and «curr»/«prev» are the two
    periods' magnitudes feeding the mini period-comparison column chart;
    lines absent from the dict render «—». An empty dict means no comparison
    column."""
    metrics = result.get("metrics") or {}
    is_lines = ((st.get("income_statement") or {}).get("lines")) or []
    if not is_lines or not metrics:
        return {}

    def series(concept: str) -> list[float]:
        return [abs(float(v)) for v in (metrics.get(concept) or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]

    def same(a: float, b: float) -> bool:
        return abs(a - b) <= max(1.0, abs(a) * 0.01)

    def ties_face(value: float, face_amount) -> bool:
        return (isinstance(face_amount, (int, float))
                and not isinstance(face_amount, bool)
                and same(value, abs(float(face_amount))))

    def prev_of(concept: str):
        """(curr, prev) when the concept's latest captured value has a
        distinct non-zero predecessor; else None."""
        vals = series(concept)
        if not vals:
            return None
        curr = vals[-1]
        for v in reversed(vals[:-1]):
            if v == 0 or same(v, curr):
                continue  # a re-stated duplicate or a TB artefact, not a period
            return curr, v
        return None

    comps = {c: prev_of(c) for c in ("revenue", "cogs", "opex",
                                     "investment_income", "finance_cost",
                                     "tax_expense")}

    def compose(chain) -> tuple[float, float] | None:
        curr = prev = 0.0
        for concept, sign in chain:
            if not series(concept):
                continue  # category absent from this analysis: zero both sides
            got = comps.get(concept)
            if not got:
                return None  # present but single-period: no honest previous
            curr += sign * got[0]
            prev += sign * got[1]
        return curr, prev

    out: dict[int, dict] = {}
    for i, ln in enumerate(is_lines):
        spec = _INCOME_LINE_CONCEPTS.get(str(ln.get("en") or ""))
        if not spec:
            continue
        concept, kind = spec
        face_amount = ln.get("amount")
        if concept in comps:  # direct concept line
            got = comps[concept]
            if not got or not ties_face(got[0], face_amount):
                continue
            curr_mag, prev_mag = got[0], got[1]
        else:  # derived subtotal: compose, then tie the composition
            got = compose(_INCOME_DERIVED[concept])
            if not got or not ties_face(got[0], face_amount):
                continue
            curr_mag, prev_mag = abs(got[0]), abs(got[1])
        if prev_mag == 0:
            continue
        pct = (curr_mag - prev_mag) / prev_mag * 100
        out[i] = {"pct": round(pct, 1), "is_cost": kind == "cost",
                  "change": round(curr_mag - prev_mag, 2),
                  "curr": round(curr_mag, 2), "prev": round(prev_mag, 2)}
    return out


# Balance-sheet face line → (balance concept, kind) for the previous-period
# comparison column. Assets/profit-key are 'good up'; liabilities/equity
# follow their own judgment: liabilities up = worse (financing strain),
# equity up = stronger cushion (mirrors the liabilities growth red flag in
# build_yearly_comparison).
_BS_LINE_CONCEPTS = {
    "Cash & Banks": ("cash", "good_up"),
    "Receivables": ("receivables", "good_up"),
    "Inventory": ("inventory", "good_up"),
    "Fixed Assets": ("fixed_assets", "good_up"),
    "Other": ("other_assets", "good_up"),
    "Payables": ("payables", "liability"),
    "Loans": ("loans", "liability"),
    "Other (credit)": ("other_liab", "liability"),
    "Equity": ("equity", "good_up"),
    "Total Assets": ("assets", "good_up"),
    "Total Liabilities": ("liabilities", "liability"),
}


def _balance_comparison(result: dict, st: dict) -> dict[int, dict]:
    """«مقارنة بالفترة السابقة» per balance-sheet face line — the balance-
    sheet twin of _income_comparison, with the SAME tie rules: the analysis
    must carry MORE THAN ONE period, and the latest captured values must tie
    the attached statements' face (1% tolerance) — the attached statements
    ARE the latest period or the line renders «—».

    Total assets/total liabilities/equity tie DIRECTLY to their metrics
    (assets/liabilities/equity). Line items tie through the shared pool:
    fixed_assets = assets − (cash + receivables + inventory), other (credit)
    = liabilities − payables, exactly as the BS builder composes them from
    the balance buckets. Kind drives judgment colour: assets/equity up =
    green, liabilities up = red (financing strain), mirroring
    build_yearly_comparison.
    Returns {line_index: {"pct", "kind"}}; empty dict = no column."""
    metrics = result.get("metrics") or {}
    bs = st.get("balance_sheet") or {}
    lines = ((bs.get("assets") or {}).get("lines") or []) + \
        ((bs.get("liabilities_equity") or {}).get("lines") or [])
    if not lines or not metrics:
        return {}

    def series(concept: str) -> list[float]:
        return [abs(float(v)) for v in (metrics.get(concept) or [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]

    def same(a: float, b: float) -> bool:
        return abs(a - b) <= max(1.0, abs(a) * 0.01)

    def ties_face(value: float, face_amount) -> bool:
        return (isinstance(face_amount, (int, float))
                and not isinstance(face_amount, bool)
                and same(value, abs(float(face_amount))))

    def prev_of(concept: str):
        vals = series(concept)
        if not vals:
            return None
        curr = vals[-1]
        for v in reversed(vals[:-1]):
            if v == 0 or same(v, curr):
                continue  # a re-stated duplicate or a TB artefact, not a period
            return curr, v
        return None

    comps = {c: prev_of(c) for c in (
        "assets", "liabilities", "equity",
        "cash", "receivables", "inventory", "payables",
    )}

    def compose(chain) -> tuple[float, float] | None:
        """Compose a pool subtotal exactly as the BS builder does: absent
        concepts contribute zero; a present-but-single-period concept blocks
        the composition (no honest previous for a component, no honest
        previous for the composition)."""
        curr = prev = 0.0
        for concept, sign in chain:
            if not series(concept):
                continue
            got = comps.get(concept)
            if not got:
                return None
            curr += sign * got[0]
            prev += sign * got[1]
        return curr, prev

    out: dict[int, dict] = {}
    for i, ln in enumerate(lines):
        spec = _BS_LINE_CONCEPTS.get(str(ln.get("en") or ""))
        if not spec:
            continue
        concept, kind = spec
        face_amount = ln.get("amount")
        if concept in comps:  # direct concept line
            got = comps[concept]
            if not got or not ties_face(got[0], face_amount):
                continue
            curr_mag, prev_mag = got[0], got[1]
        elif concept == "fixed_assets":
            got = compose((("assets", 1.0), ("cash", -1.0),
                           ("receivables", -1.0), ("inventory", -1.0)))
            if not got or got[1] <= 0 or not ties_face(got[0], face_amount):
                continue  # no positive residual pool → no honest comparison
            curr_mag, prev_mag = got[0], got[1]
        elif concept == "other_assets":
            got = compose((("assets", 1.0), ("cash", -1.0),
                           ("receivables", -1.0), ("inventory", -1.0)))
            if not got or got[0] >= 0 or not ties_face(got[0], face_amount):
                continue  # the negative (overshoot) side only
            curr_mag, prev_mag = abs(got[0]), abs(got[1])
        elif concept == "other_liab":
            got = compose((("liabilities", 1.0), ("payables", -1.0)))
            if not got or got[0] <= 0 or not ties_face(got[0], face_amount):
                continue
            curr_mag, prev_mag = got[0], got[1]
        else:  # totals (assets / liabilities) and equity: direct concept,
            # already covered above — kept for clarity
            got = comps.get(concept)
            if not got or not ties_face(got[0], face_amount):
                continue
            curr_mag, prev_mag = got[0], got[1]
        if prev_mag == 0:
            continue
        pct = (curr_mag - prev_mag) / prev_mag * 100
        out[i] = {"pct": round(pct, 1), "kind": kind}
    return out


def _same_ish(a: float, b: float) -> bool:
    """1%-tolerance tie (same contract as the comparison helpers)."""
    return abs(a - b) <= max(1.0, abs(a) * 0.01)


def _attach_metrics_statements(analysis_id: int) -> bool:
    """Comparison files WITHOUT a trial balance (multi-year income
    statements, English annual-report faces): the statements are composed
    from the captured multi-period metric series and attached to the row,
    so ``has_statements`` becomes honest for them too — reports, the Excel
    export and the statements endpoint all read one attached source.
    The row keeps ``has_tb=False`` (there is no trial balance); the dict
    is marked ``derived_from_metrics``. Single-period analyses cannot
    support the derivation and stay unattached. Returns True on attach."""
    from .statements import (build_statements_from_metrics,
                             extend_derived_statements_for_export)

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            return False
        try:
            result = json.loads(row.result_json)
        except Exception:
            return False
        try:
            derived = build_statements_from_metrics(
                result.get("metrics") or {},
                result.get("period_labels") or [],
            )
        except Exception:
            return False
        if not derived:
            return False
        row.statements_json = json.dumps(
            extend_derived_statements_for_export(derived),
            ensure_ascii=False,
        )
        db.commit()
    return True


def _try_attach_statements(analysis_id: int, table_rows: list) -> bool:
    """Auto-build statements and attach them to the analysis row: from a
    real, balanced trial balance when `table_rows` carries one, otherwise
    — comparison files without a TB — from the multi-period metric series.
    Returns True when statements were attached."""
    from .statements import build_statements, metrics_from_statements

    try:
        cand = build_statements(table_rows, standard="ifrs")
    except Exception:
        cand = None
    if cand is not None and _tb_acceptable(cand) \
            and not validate_statements(cand):
        # Deep coherence gate: the TB balancing alone once let pseudo-account
        # garbage through; the statements themselves must tie too.
        with SessionLocal() as db:
            r2 = db.get(Analysis, analysis_id)
            if not r2:
                return False
            r2.statements_json = json.dumps(cand, ensure_ascii=False)
            r2.has_tb = True
            # A REAL trial balance is the ground truth: the generic extractor
            # reads debit/credit columns as concept series and returns
            # systematically wrong figures (a NEGATIVE revenue, a fabricated
            # net profit that disagrees with the statements' own net) — so
            # the statements' values replace the capture UNCONDITIONALLY,
            # not only when the extractor found nothing. KPIs, ratios,
            # series and the «مقارنة بالفترة السابقة» column then all draw
            # from ONE source — the balanced statements the trial balance
            # built — and a single-period TB can never grow a fake second
            # period again.
            res2 = json.loads(r2.result_json)
            tb_metrics = metrics_from_statements(cand)
            res2["metrics"] = dict(tb_metrics)
            res2["original_metrics"] = {k: list(v) for k, v in tb_metrics.items()}
            res2["metrics"].pop("opex", None)
            clean_result(res2)
            res2 = recompute_result(res2)
            r2.result_json = json.dumps(res2, ensure_ascii=False)
            db.commit()
        return True
    # No acceptable trial balance → comparison statements from the metrics.
    return _attach_metrics_statements(analysis_id)


# ---------------------------------------------------------------------------
# BI-tool connectors (Excel · Power BI · Tableau · Google Looker · SQL · Python)
# ---------------------------------------------------------------------------


@app.get("/api/analyses/{analysis_id}/bi/{table}")
def bi_table(analysis_id: int, table: str, lang: str = "ar", fmt: str = "json",
             authorization: str | None = Header(default=None),
             auth_token: str | None = None):
    """Live BI connector: one tidy table — facts (every concept × period,
    forecast rows flagged is_forecast=1), growth (yearly values + YoY % +
    next-year forecast) or ratios — as JSON (default) or CSV (UTF-8 BOM) for
    Power BI's Web connector, Tableau, Looker Studio or pandas."""
    _require_paid(authorization, auth_token)
    if table not in BI_TABLES:
        raise HTTPException(404, f"unknown BI table: {table}")
    if lang not in ("ar", "en"):
        lang = "ar"
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    result = json.loads(row.result_json)
    rows, columns = build_table_rows(result, table, lang)
    if fmt == "csv":
        return Response(
            to_csv(rows, columns).encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":
                     f'attachment; filename="bi-{table}-{analysis_id}.csv"'},
        )
    return rows


@app.get("/api/analyses/{analysis_id}/bi-pack")
def bi_pack_download(analysis_id: int, lang: str = "ar",
                     authorization: str | None = Header(default=None),
                     auth_token: str | None = None):
    """Downloadable BI bundle (zip): tidy CSV + XLSX datasets, portable SQL
    schema + inserts, and a README with the connection steps for each tool
    (Excel, Power BI, Tableau, Google Looker, SQL, Python)."""
    _require_paid(authorization, auth_token)
    if lang not in ("ar", "en"):
        lang = "ar"
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    result = json.loads(row.result_json)
    entity = row.display_name or row.filename
    blob = build_bi_pack(analysis_id, entity, result, lang)
    return Response(
        blob,
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="bi-pack-{analysis_id}.zip"'},
    )


@app.post("/api/upload")
async def upload(
    files: list[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
    auth_token: str | None = None,
    x_upload_job_id: str | None = Header(default=None, alias="X-Upload-Job-Id"),
    file_kind: str = Form(default="statements"),
    analysis_mode: str = Form(default="auto"),
):
    """Upload one or more financial files at once; each is analysed and saved
    as its own analysis row. Auth failures abort the batch; a per-file
    problem is reported per item without aborting the rest. When a file
    carries a trial balance, the financial statements are built from it
    automatically."""
    # Any signed-in user may upload; downloads stay paywalled.
    from urllib.parse import unquote
    from .statements import build_statements

    token = unquote(authorization).removeprefix("Bearer ").strip() if authorization else (unquote(auth_token).strip() if auth_token else None)
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "سجّل الدخول أولاً لرفع الملفات")
    # Plan quota: free users get 5 uploads total; paid plans get their monthly
    # allowance (None = unlimited).
    from .auth import PLANS

    # plan quota = ANALYSES per month (CMRRS ladder): free 1 one-time,
    # pro 5/month, business 20/month; legacy plans keep their old allowance
    quota = PLANS.get(user.plan or "", {}).get("uploads") if user.subscription == "paid" else 1
    if user.subscription != "paid":
        quota = 1
    elif user.is_admin:
        quota = None  # platform admin rides an unlimited allowance
    elif user.plan in ("monthly", "yearly", "firm"):
        # grandfathered legacy plans: yearly ≈ business quota, monthly/firm
        # keep their old allowance until renewal migrates them to the new tiers
        quota = {"monthly": 15, "yearly": 20, "firm": None}.get(user.plan)
    remaining = None if quota is None else max(0, quota - (user.uploads_used or 0))
    if remaining is not None and remaining == 0:
            raise HTTPException(
                402,
                f"نفدت حصة التحليل ({quota}) — رقّ باقتك لتحليل المزيد",
            )

    # Live progress: the frontend mints an id per upload, sends it in the
    # X-Upload-Job-Id header and polls /api/upload/progress/{id} while this
    # request runs (a scanned batch takes ~20s per file) — the header is
    # authoritative so the slot exists BEFORE the response ever returns.
    # Upload-screen analysis routing: file_kind = what the user SAYS the
    # file is (statements / trial_balance / sales), analysis_mode = how to
    # read it (auto / force_trial_balance / financial_sheets). Sales files
    # always take the sales route; the analysis mode steers financial reads.
    file_kind_n = (file_kind or "statements").strip().lower()
    if file_kind_n not in ("statements", "trial_balance", "sales"):
        file_kind_n = "statements"
    analysis_mode_n = (analysis_mode or "auto").strip().lower()
    if analysis_mode_n not in ("auto", "force_trial_balance", "financial_sheets"):
        analysis_mode_n = "auto"
    job_id = (x_upload_job_id or "").strip()[:64] or uuid.uuid4().hex
    files_total = len(files)
    if files_total:
        _progress_for(job_id)  # pre-create the slot
    results = []
    files_done = 0
    for file in files:
        if remaining is not None and remaining <= 0:
            results.append({"filename": file.filename, "error": f"نفدت حصة التحليل ({quota})"})
            continue
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED:
            results.append({"filename": file.filename, "error": f"unsupported file type: {suffix or 'unknown'}"})
            continue

        data = await file.read()
        if len(data) > MAX_SIZE:
            results.append({"filename": file.filename, "error": "file too large (max 25 MB)"})
            continue

        saved = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
        saved.write_bytes(data)

        try:
            # Parse on a worker thread instead of the event loop: with the
            # loop free, /api/upload/progress/{id} stays live DURING the
            # (possibly slow) OCR — the whole point of the progress store.
            parsed = await asyncio.get_running_loop().run_in_executor(
                _UPLOAD_PARSE_POOL, parse_file, saved, _progress_for(job_id)
            )
            # Multi-entity workbooks (one statement per sheet — e.g. a
            # «التقرير عام 2024» workbook carrying an income statement per
            # company) are SPLIT: every financial sheet becomes its own
            # analysis so each company keeps its true numbers instead of
            # being mixed with the others.
            # Sheet splitting: one statement per sheet. The user's analysis
            # mode can pin the reading — «financial_sheets» forces the
            # financial split, otherwise keep the auto-detect behaviour.
            sheet_tables = _split_entity_sheets(parsed.get("tables") or [], suffix)
            split_mode = len(sheet_tables) >= 2
            if split_mode:
                sheet_entities = []
                rejected: list[tuple[str, str]] = []
                for t in sheet_tables:
                    res = analyze([t], [])
                    res["_ocr_used"] = bool(parsed.get("ocr_used"))
                    res["metrics"] = result_to_metrics(res)
                    clean_result(res)
                    res["original_metrics"] = res["metrics"]
                    # remembered so /reanalyze re-reads the SAME sheet
                    res["_sheet"] = t.get("name") or ""
                    # and the same declared routing (see the single-sheet path):
                    # the sales KIND is stamped only when the entity routes
                    # sales — a multi-sheet workbook declared «مبيعات» vents
                    # each sheet through the SALES extraction anyway, so the
                    # stamp keeps the reanalyze route loyal either way.
                    res["_file_kind"] = file_kind_n
                    res["_analysis_mode"] = analysis_mode_n
                    # quality gate per sheet: a corrupt sheet is refused
                    # while its healthy siblings still become analyses
                    gate = run_quality_gate(res)
                    if gate["fatal"]:
                        rejected.append((str(t.get("name") or "ورقة"), "; ".join(gate["messages"])))
                        continue
                    sheet_entities.append((res, t.get("rows") or []))
                if not sheet_entities:
                    saved.unlink(missing_ok=True)
                    detail = "; ".join(f"«{name}»: {msg}" for name, msg in rejected[:3])
                    results.append({
                        "filename": file.filename,
                        "error": f"رفض مدقق الجودة كل أوراق الملف — {detail}",
                    })
                    continue
                # the consolidated «الإجمالي» sheet (if any) is the GROUP's
                # own statements — align its stacked blocks to the companies'
                # chronology so its latest period equals the sum of the
                # companies just extracted (the upload ground truth)
                company_res = [
                    res for res, _ in sheet_entities
                    if not _ROLLUP_SHEET_RE.search(str(res.get("_sheet") or ""))
                ]
                if company_res:
                    for idx, (res, rows) in enumerate(sheet_entities):
                        if _ROLLUP_SHEET_RE.search(str(res.get("_sheet") or "")):
                            aligned = _align_rollup_chronology(res, rows, company_res)
                            # the chronology fix is an extraction correction,
                            # not a user edit — the as-extracted baseline
                            # moves with it (no spurious «معدّلة يدوياً»)
                            aligned["original_metrics"] = {
                                k: list(v) for k, v in aligned["metrics"].items()
                            }
                            aligned = recompute_result(aligned)
                            aligned["_ocr_used"] = res.get("_ocr_used", False)
                            clean_result(aligned)
                            sheet_entities[idx] = (aligned, rows)
            else:
                # SALES route: a sales-operations table (شهر/منطقة/مندوب/
                # مبيعات) is not financial data — the financial analyzer
                # misreads it and the quality gate would refuse it. Two ways
                # in: the upload-screen «مبيعات» kind, or the auto-detector
                # when every parsed table is sales-shaped (a financial sheet
                # in the same workbook stays financial). The mode guard
                # «financial_sheets» shuts the detector off deliberately.
                from .sales_analyzer import analyze_sales, detect_sales_table

                sales_records = None
                if file_kind_n == "sales":
                    # declared sales: route to the sales analyzer regardless
                    # of the header shapes (ordered month/region/rep headers
                    # may use plain «منطقة»/sales synonyms the detector misses)
                    sales_records = _sales_records_for_tables(
                        parsed["tables"] if parsed.get("tables") else []
                    ) or None
                    if sales_records is None:
                        results.append({
                            "filename": file.filename,
                            "error": "لم يُعثر على صفوف مبيعات صالحة (مبيعات رقمية + شهر/منطقة/مندوب) — تحقق من شكل الورقة",
                        })
                        saved.unlink(missing_ok=True)
                        continue
                elif analysis_mode_n != "financial_sheets" and parsed.get("tables"):
                    detected = [
                        recs for recs in (
                            detect_sales_table(t.get("rows") or [])
                            for t in parsed["tables"]
                        ) if recs
                    ]
                    # only when ALL content tables are sales grids (a
                    # financial sheet in the same workbook stays financial)
                    if len(detected) == len(parsed["tables"]):
                        sales_records = [r for recs in detected for r in recs]
                if sales_records:
                    result = {
                        "kpis": {}, "ratios": {}, "series": {}, "forecast": [],
                        "metrics": {},
                        "sales_analysis": analyze_sales(sales_records),
                        "kind": "sales",
                        "texts_found": len(parsed.get("texts") or []),
                        "analysed_at": _now(),
                    }
                    result["_ocr_used"] = bool(parsed.get("ocr_used"))
                    sales_sheet = parsed["tables"][0].get("name") if len(parsed["tables"]) == 1 else None
                    if sales_sheet:
                        result["_sheet"] = sales_sheet
                else:
                    result = analyze(parsed["tables"], parsed["texts"], mode=analysis_mode_n)
                    # remember the extraction path: the audit's W3 «suspect OCR
                    # numbers» warning only applies to OCR-read files
                    result["_ocr_used"] = bool(parsed.get("ocr_used"))
                    result["metrics"] = result_to_metrics(result)
                    clean_result(result)
                    result["original_metrics"] = result["metrics"]
                # freeze the user's upload-screen routing on the result: the
                # /reanalyze endpoint re-reads the SAME declared kind/mode
                # verbatim — re-analysis must never re-classify the file or
                # switch the reading mode behind the user's back.
                result["_file_kind"] = file_kind_n
                result["_analysis_mode"] = analysis_mode_n
        except Exception as exc:  # bad/corrupt file
            saved.unlink(missing_ok=True)
            results.append({"filename": file.filename, "error": f"failed to process file: {exc}"})
            continue

        def _insert_analysis(res: dict, display_name: str | None) -> int:
            with SessionLocal() as db:
                row = Analysis(
                    filename=file.filename or saved.name,
                    file_type=suffix,
                    size_bytes=len(data),
                    display_name=display_name,
                    result_json=json.dumps(res, ensure_ascii=False),
                    created_at=_now(),
                    original_path=str(saved),
                )
                db.add(row)
                db.commit()
                return row.id

        created_items: list = []
        if not split_mode:
            # quality gate: corrupt extractions are refused BEFORE any insert
            # (sales-kind results skip the financial checks entirely — their
            # «metrics» block is intentionally empty by design)
            is_sales = result.get("kind") == "sales"
            if is_sales:
                result["audit"] = {
                    "ok": True, "errors": [], "warnings": [], "repairs": [],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "sales",
                }
            else:
                gate = run_quality_gate(result)
            gate_fatal = False if is_sales else gate["fatal"]
            if gate_fatal:
                # DOC fallback: the OCR engine READ the file and extracted
                # real prose (this is content, not a read failure) — the
                # file is kept as a DOCUMENT analysis showing the extracted
                # text, with a loud «no financial statements» warning,
                # instead of refusing an upload the user cannot fix by
                # re-exporting. Corrupt reads (no OCR text either) stay
                # refused with the scanned-file hint.
                doc_text = (
                    texts_sample(parsed.get("texts") or [])
                    if parsed.get("ocr_used") else []
                )
                if not doc_text:
                    hint = ""
                    if suffix == ".pdf":
                        try:
                            import pdfplumber

                            with pdfplumber.open(str(saved)) as _pdf:
                                no_text = all(
                                    not (pg.extract_text() or "").strip()
                                    for pg in _pdf.pages[:3]
                                )
                            if no_text:
                                hint = ("يبدو الملف ممسوحًا ضوئيًا (صورة بلا طبقة نصية) وتعذر "
                                        "استخراج نص مقروء منه — أعد تصديره بنص أوضح أو ارفع نسخة Excel")
                        except Exception:
                            pass
                    saved.unlink(missing_ok=True)
                    results.append({
                        "filename": file.filename,
                        "error": "رفض مدقق الجودة هذا التحليل: "
                        + "; ".join(gate["messages"]) + (f" — {hint}" if hint else ""),
                    })
                    continue
                result = recompute_result(result)
                result["_ocr_used"] = True
                result["texts_sample"] = doc_text
                result["audit"] = {
                    "ok": False,
                    "errors": [],
                    "warnings": [{
                        "code": "D1", "severity": "warning",
                        "ar": "مستند بلا قوائم مالية — قُرئ ضوئيًا وعُرض نصه المستخرج بدل التحليل المالي؛ لا توجد أرقام قابلة للتحليل في هذا الملف",
                        "en": "Document without financial statements — OCR-read and kept as extracted text; no analysable figures in this file",
                    }],
                    "repairs": [],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "document",
                }
                doc_id = _insert_analysis(result, None)
                bump_analyses()
                created_items.append({
                    "id": doc_id,
                    "filename": file.filename or saved.name,
                    "result": result,
                    "has_statements": False,
                    "document_only": True,
                })
                with SessionLocal() as db:
                    u = db.get(User, user.id)
                    if u:
                        u.uploads_used = (u.uploads_used or 0) + 1
                        db.commit()
                results.append({
                    "id": doc_id,
                    "filename": file.filename or saved.name,
                    "document_only": True,
                })
                continue

        if split_mode:
            display_base = Path(file.filename or saved.name).stem
            for res, sheet_rows in sheet_entities:
                sheet_name = res.get("_sheet") or "ورقة"
                aid = _insert_analysis(res, f"{display_base} — {sheet_name}")
                has_stmts = _try_attach_statements(aid, sheet_rows)
                bump_analyses()
                created_items.append({
                    "id": aid,
                    "filename": file.filename or saved.name,
                    "display_name": f"{display_base} — {sheet_name}",
                    "result": res,
                    "has_statements": has_stmts,
                })
        else:
            with SessionLocal() as db:
                row = Analysis(
                    filename=file.filename or saved.name,
                    file_type=suffix,
                    size_bytes=len(data),
                    result_json=json.dumps(result, ensure_ascii=False),
                    created_at=_now(),
                    original_path=str(saved),
                )
                db.add(row)
                db.commit()
                analysis_id = row.id

            statements_attached = False
            # ANY parsed file type may carry a real trial balance (PDF/Word
            # exports from accounting suites do all the time) — the quality
            # gates inside _try_attach_statements (≥6 accounts, balanced,
            # statements coherence) decide, not the extension.
            tb_rows = [
                r
                for table in (parsed.get("tables") or [])
                for r in (table.get("rows") or [])
            ]
            if tb_rows:
                statements_attached = _try_attach_statements(analysis_id, tb_rows)

            bump_analyses()
            created_items.append({
                "id": analysis_id,
                "filename": row.filename,
                "result": result,
                "has_statements": statements_attached,
            })

        # count the ANALYSES against the plan quota — once per FILE, plus
        # one extra for each derived analysis when a workbook was split
        # (the CMRRS-style ladder counts analyses, not files)
        with SessionLocal() as db:
            u = db.get(User, user.id)
            if u:
                u.uploads_used = (u.uploads_used or 0) + 1 + max(0, len(created_items) - 1)
                db.commit()

        if remaining is not None:
            remaining -= 1
        files_done += 1
        results.extend(created_items)

    _progress_done(job_id, files_done, files_total)
    ok = [r for r in results if "id" in r]
    if not ok:
        # nothing succeeded — surface the first error as the request error
        first_error = next((r["error"] for r in results if "error" in r), "no files")
        raise HTTPException(400, first_error)
    return {"uploaded": results, "job_id": job_id}


@app.get("/api/upload/progress/{job_id}")
def upload_progress(job_id: str):
    """Live OCR/parse progress for a running /api/upload batch (the
    frontend polls this every second while it waits).{"stage": "done"}
    is terminal — the poller stops and clears its id."""
    slot = _UPLOAD_PROGRESS.get(job_id)
    if not slot:
        raise HTTPException(404, "no such upload job")
    return {"stage": str(slot.get("stage") or ""),
            "page": int(slot.get("page") or 0),
            "total": int(slot.get("total") or 0),
            "files_done": int(slot.get("files_done") or 0),
            "files_total": int(slot.get("files_total") or 0),
            "done": slot.get("stage") == "done"}


def _report_statements(row) -> dict | None:
    """Statements payload for the PDF/PPTX reports: the attached (trial-
    balance) statements when present, otherwise — for comparison files —
    the metrics-derived statements surfaced with the REAL-statements face
    so the reports' existing ``if statements:`` section renders without
    special-casing._reports carry the derived evidence (prev period values
    ride along on each line). None when the analysis has no statements
    data at all."""
    if row.statements_json:
        try:
            return json.loads(row.statements_json)
        except Exception:
            pass
    try:
        result = json.loads(row.result_json)
    except Exception:
        return None
    try:
        from .statements import build_statements_from_metrics, \
            extend_derived_statements_for_export

        derived = build_statements_from_metrics(
            result.get("metrics") or {},
            result.get("period_labels") or [],
        )
        if derived:
            return extend_derived_statements_for_export(derived)
    except Exception:
        return None
    return None


@app.get("/api/analyses/{analysis_id}/report")
def report(analysis_id: int, lang: str = "ar", authorization: str | None = Header(default=None), auth_token: str | None = None):
    user = _require_paid(authorization, auth_token)
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    if lang not in ("ar", "en"):
        lang = "ar"

    out = REPORTS / f"report_{analysis_id}_{lang}.pdf"
    if not out.exists():
        result = json.loads(row.result_json)
        result["_filename"] = row.display_name or row.filename
        from .scoring import compute_scenarios, compute_score

        try:
            build_report(
                _entity_name(row),
                result,
                out,
                lang,
                notes=row.notes,
                advisor=build_advisor(result, lang),
                statements=_report_statements(row),
                score=compute_score(result),
                scenarios=compute_scenarios(result),
                brief=build_executive_brief(result, lang),
                ratio_insights=build_ratio_insights(result, lang),
                consistency_checks=build_consistency_checks(result, lang),
                yearly_comparison=build_yearly_comparison(result, lang),
                key_findings=build_key_findings(result, lang),
                strategic_recs=build_strategic_recs(result, lang),
                period=_period_text(result, lang),
                band=_subscription_label(user, lang),
            )
        except UnsupportedGlyphError as exc:
            # a refused build never wrote a file — answer with a clear,
            # localised error instead of serving a PDF full of hollow boxes
            raise HTTPException(422, exc.message(lang)) from None

    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"financial-report-{analysis_id}-{lang}.pdf",
    )


@app.get("/api/analyses/{analysis_id}/sales-report")
def sales_report(analysis_id: int, lang: str = "ar", authorization: str | None = Header(default=None), auth_token: str | None = None):
    """PDF for a SALES-grid analysis (kind=="sales"): the sales dashboard
    (KPI cards, trend chart, regions/reps tables, period comparison,
    forecast and recommendations) in the platform's branded A4 style.
    Financial reports (the endpoint above) would render this payload
    empty — the sales analysis carries no statements/ratios by design."""
    user = _require_paid(authorization, auth_token)
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    if lang not in ("ar", "en"):
        lang = "ar"
    result = json.loads(row.result_json)
    if result.get("kind") != "sales":
        raise HTTPException(409, "not a sales analysis — use the financial report endpoint")
    sales = result.get("sales_analysis") or {}
    if not sales:
        raise HTTPException(422, "التحليل لا يحتوي بيانات مبيعات قابلة للتصدير")

    out = REPORTS / f"sales-report_{analysis_id}_{lang}.pdf"
    if not out.exists():
        from .report import build_sales_report

        try:
            build_sales_report(
                row.display_name or row.filename,
                sales,
                out,
                lang,
                band=_subscription_label(user, lang),
                notes=row.notes,
            )
        except UnsupportedGlyphError as exc:
            # a refused build never wrote a file — answer with a clear,
            # localised error instead of serving a PDF full of hollow boxes
            raise HTTPException(422, exc.message(lang)) from None

    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"sales-report-{analysis_id}-{lang}.pdf",
    )


@app.get("/api/analyses/{analysis_id}/dashboard")
def get_analytics_dashboard(analysis_id: int, lang: str = "ar"):
    """Analytics-dashboard payload (score gauge, expense mix, revenue
    composition, benchmark bullets) — the SAME data the deck's
    «لوحة المؤشرات التحليلية» and «النسب مقابل المعايير المرجعية»
    slides render, so the platform shows what its reports show."""
    from .dashboard_charts import dashboard_payload
    from .scoring import compute_score, health_radar

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    if lang not in ("ar", "en"):
        lang = "ar"
    result = json.loads(row.result_json)
    try:
        score = compute_score(result)
    except Exception:
        score = None
    payload = dashboard_payload(result, lang, score)
    payload["period_labels"] = result.get("period_labels") or payload.get("period_labels")
    # financial-health radar (مؤشر الصحة المالية): one polygon per period
    try:
        payload["health"] = health_radar(result)
    except Exception:
        payload["health"] = None
    return payload


@app.get("/api/analyses/{analysis_id}/advice")
def get_advice(analysis_id: int, lang: str = "ar"):
    """Recommendations + solutions + score + scenarios for the dashboard."""
    from .scoring import compute_scenarios, compute_score, health_radar

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    if lang not in ("ar", "en"):
        lang = "ar"
    result = json.loads(row.result_json)
    result["_filename"] = row.display_name or row.filename
    payload = build_advisor(result, lang)
    payload["score"] = compute_score(result)
    payload["health"] = health_radar(result)
    payload["scenarios"] = compute_scenarios(result)
    payload["brief"] = build_executive_brief(result, lang)
    payload["data_warnings"] = data_quality_warnings(result, lang)
    # suspect-OCR warning rides the same UI channel as data-quality ones
    oc = result.get("ocr_confidence") or {}
    if oc.get("suspect"):
        suspects = oc.get("suspect_concepts") or []
        if lang == "ar":
            from .hygiene import _AR_NAMES
            names = " و".join(_AR_NAMES.get(c, c) for c in suspects)
            payload["data_warnings"].insert(0,
                f"قُرئت الأرقام ضوئيًا (OCR) وقد تحتوي قيمًا مشكوكًا فيها في: {names} "
                "— راجع الأرقام أو ارفع نسخة نصية/Excel")
        else:
            from .hygiene import _EN_NAMES
            names = " & ".join(_EN_NAMES.get(c, c) for c in suspects)
            payload["data_warnings"].insert(0,
                f"Numbers were OCR-read and may carry suspect values in: {names} "
                "— review the figures or upload a text/Excel copy")
    payload["yearly_comparison"] = build_yearly_comparison(result, lang)
    payload["statements"] = (
        json.loads(row.statements_json) if row.statements_json else None
    )
    return payload


@app.post("/api/analyses/{analysis_id}/trial-balance")
async def upload_trial_balance(analysis_id: int, file: UploadFile = File(...), standard: str = "ifrs"):
    """Attach a trial balance (Excel) and build full financial statements.

    ``standard``: ifrs (default) or socpa — shown in statement titles/notes.
    """
    from .statements import build_statements

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        raise HTTPException(400, "trial balance must be an Excel file (.xlsx)")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "file too large (max 25 MB)")

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
        if not row:
            raise HTTPException(404, "analysis not found")

        saved = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
        saved.write_bytes(data)
        try:
            parsed = parse_file(saved)
            # flatten parsed tables into plain rows for the statements engine
            tb_rows = [
                row
                for table in (parsed.get("tables") or [])
                for row in (table.get("rows") or [])
            ]
            statements = build_statements(tb_rows, standard=standard)
        except Exception as exc:
            saved.unlink(missing_ok=True)
            raise HTTPException(400, f"failed to read trial balance: {exc}") from exc

        if not statements["trial_balance"]["accounts"]:
            saved.unlink(missing_ok=True)
            raise HTTPException(400, "no account rows detected in the trial balance")

        row.statements_json = json.dumps(statements, ensure_ascii=False)
        row.original_path = str(saved.absolute())
        row.has_tb = True

        # Derive KPIs/ratios from the statements themselves so the whole
        # dashboard reflects the trial balance.
        from .statements import metrics_from_statements

        result = json.loads(row.result_json)
        result["metrics"] = metrics_from_statements(statements)
        result.setdefault("original_metrics", dict(result["metrics"]))
        result["metrics"].pop("opex", None)
        clean_result(result)
        recomputed = recompute_result(result)
        row.result_json = json.dumps(recomputed, ensure_ascii=False)
        db.commit()

    bump_statements()
    _invalidate_cached_pdfs(analysis_id)
    return {"ok": True, "statements": statements}


@app.get("/api/analyses/{analysis_id}/statements")
def get_statements(analysis_id: int):
    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    return {
        "has_statements": bool(row.statements_json),
        "statements": json.loads(row.statements_json) if row.statements_json else None,
    }


@app.get("/api/stats/report")
def stats_report(lang: str = "ar", authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Cross-analysis statistics PDF (dashboard-styled). Admin-only."""
    _require_admin(authorization, auth_token)
    if lang not in ("ar", "en"):
        lang = "ar"
    with SessionLocal() as db:
        rows = db.query(Analysis).order_by(Analysis.id.asc()).all()

    analyses = []
    concepts: dict[str, dict] = {}
    for row in rows:
        result = json.loads(row.result_json)
        analyses.append({
            "id": row.id,
            "name": row.display_name or row.filename,
            "created_at": row.created_at,
            "edited": bool(result.get("edited_at")),
        })
        values: dict[str, float] = {}
        for concept, kpi in (result.get("kpis") or {}).items():
            value = kpi.get("value") if isinstance(kpi, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[concept] = float(value)
        for concept, s in (result.get("series") or {}).items():
            nums = [v for v in (s.get("values") or [])
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums:
                values[concept] = float(nums[-1])
        for concept, value in values.items():
            entry = concepts.setdefault(concept, {
                "label": ((result.get("kpis") or {}).get(concept) or {}).get("ar", concept),
                "label_en": ((result.get("kpis") or {}).get(concept) or {}).get("en", concept),
                "points": [],
            })
            entry["points"].append({
                "name": row.display_name or row.filename,
                "value": value,
            })

    for entry in concepts.values():
        points = entry.pop("points")
        entry["first"] = points[0]
        entry["last"] = points[-1]
        f, l = entry["first"]["value"], entry["last"]["value"]
        entry["change_pct"] = round((l - f) / abs(f) * 100, 1) if f else None
        entry["trend"] = (
            "up" if entry["change_pct"] and entry["change_pct"] > 0.05
            else "down" if entry["change_pct"] and entry["change_pct"] < -0.05
            else "flat"
        )

    payload = {
        "total": len(analyses),
        "analyses": analyses,
        "concepts": dict(sorted(concepts.items())),
    }
    out = REPORTS / f"stats_{lang}.pdf"
    if not out.exists():
        try:
            build_stats_report(payload, out, lang)
        except UnsupportedGlyphError as exc:
            raise HTTPException(422, exc.message(lang)) from None
    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"statistics-{lang}.pdf",
    )


# ---------------------------------------------------------------------------
# Comparison: side-by-side of two analyses + comparative PDF
# ---------------------------------------------------------------------------

def _load_pair(db, base_id: int, target_id: int):
    base_row = db.get(Analysis, base_id)
    target_row = db.get(Analysis, target_id)
    if not base_row or not target_row:
        raise HTTPException(404, "analysis not found")
    return base_row, target_row


@app.get("/api/compare-group")
def compare_group_endpoint(ids: str):
    """Side-by-side (revenue / gross margin / net profit) across N analyses,
    e.g. /api/compare-group?ids=13,14,15,16,17,18 — order is preserved."""
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be a comma-separated list of integers")
    if len(wanted) < 2:
        raise HTTPException(400, "pass at least two analysis ids")
    with SessionLocal() as db:
        rows = []
        for wid in dict.fromkeys(wanted):  # de-dupe, keep order
            row = db.get(Analysis, wid)
            if not row:
                raise HTTPException(404, f"analysis {wid} not found")
            rows.append(row)
        return compare_group(rows)


@app.get("/api/compare/{base_id}/{target_id}")
def compare_endpoint(base_id: int, target_id: int):
    if base_id == target_id:
        raise HTTPException(400, "cannot compare an analysis with itself")
    with SessionLocal() as db:
        base_row, target_row = _load_pair(db, base_id, target_id)
        return compare_analyses(base_row, target_row)


@app.get("/api/compare/{base_id}/{target_id}/report")
def compare_report_endpoint(base_id: int, target_id: int, lang: str = "ar", authorization: str | None = Header(default=None), auth_token: str | None = None):
    _require_paid(authorization, auth_token)
    if base_id == target_id:
        raise HTTPException(400, "cannot compare an analysis with itself")
    if lang not in ("ar", "en"):
        lang = "ar"

    with SessionLocal() as db:
        base_row, target_row = _load_pair(db, base_id, target_id)
        payload = compare_analyses(base_row, target_row)

    out = REPORTS / f"compare_{base_id}_vs_{target_id}_{lang}.pdf"
    if not out.exists():
        try:
            build_comparison_report(payload, out, lang)
        except UnsupportedGlyphError as exc:
            raise HTTPException(422, exc.message(lang)) from None

    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"comparison-{base_id}-vs-{target_id}-{lang}.pdf",
    )


@app.get("/api/stats")
def stats(authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Cross-analysis overview: latest value and trend per concept.
    Admin-only: cross-account aggregates are sensitive."""
    _require_admin(authorization, auth_token)
    from datetime import datetime as _dt

    def _parse(row):
        try:
            return _dt.fromisoformat(row.created_at)
        except (ValueError, TypeError):
            return None

    with SessionLocal() as db:
        rows = db.query(Analysis).order_by(Analysis.id.asc()).all()

    analyses = []
    concepts: dict[str, dict] = {}
    for row in rows:
        result = json.loads(row.result_json)
        when = _parse(row)
        analyses.append({
            "id": row.id,
            "name": row.display_name or row.filename,
            "created_at": row.created_at,
            "edited": bool(result.get("edited_at")),
        })
        values: dict[str, float] = {}
        for concept, kpi in (result.get("kpis") or {}).items():
            value = kpi.get("value") if isinstance(kpi, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[concept] = float(value)
        for concept, s in (result.get("series") or {}).items():
            nums = [v for v in (s.get("values") or [])
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums:
                values[concept] = float(nums[-1])
        for concept, value in values.items():
            entry = concepts.setdefault(concept, {
                "label": (result.get("kpis", {}).get(concept) or {}
                          .get("ar")) or concept,
                "label_en": (result.get("kpis", {}).get(concept) or {}
                             .get("en")) or concept,
                "points": [],
            })
            entry["points"].append({
                "id": row.id,
                "name": row.display_name or row.filename,
                "date": row.created_at,
                "_when": when,
                "value": value,
            })

    for entry in concepts.values():
        points = entry.pop("points")
        points.sort(key=lambda p: (p["_when"] is None, p["_when"]))
        entry["first"] = points[0]
        entry["last"] = points[-1]
        f, l = entry["first"]["value"], entry["last"]["value"]
        entry["change_pct"] = (
            round((l - f) / abs(f) * 100, 1) if f not in (None, 0) else None
        )
        entry["trend"] = (
            "up" if entry["change_pct"] and entry["change_pct"] > 0.05
            else "down" if entry["change_pct"] and entry["change_pct"] < -0.05
            else "flat"
        )
        for p in (entry["first"], entry["last"]):
            p.pop("_when", None)

    return {
        "total": len(analyses),
        "analyses": analyses,
        "concepts": dict(sorted(concepts.items(), key=lambda kv: kv[0])),
    }


# ---------------------------------------------------------------------------
# Demo data so the dashboard is not empty on first run
# ---------------------------------------------------------------------------

def _ratio_labels_entry(key: str) -> dict:
    """{"en", "ar"} من المصدر الموحد للتسميات — لبيانات الديمو والقيم المخزّنة."""
    from .ratio_labels import RATIO_LABELS
    return dict(RATIO_LABELS[key])


_DEMO_RESULT = {
    # mirrors the CMRRS reference report figures (شركة المثال للتجارة 2023-2024)
    # so the demo produces the same story: 12M -> 15M revenue, 15% net margin,
    # 2.00x liquidity, consistent statements.
    "kpis": {
        "revenue": {"value": 15000000, "en": "Revenue", "ar": "الإيرادات"},
        "net_profit": {"value": 2250000, "en": "Net Profit", "ar": "صافي الربح"},
        "assets": {"value": 25000000, "en": "Total Assets", "ar": "إجمالي الأصول"},
        "cash": {"value": 2500000, "en": "Cash", "ar": "النقدية"},
    },
    "ratios": {
        # تسميات الدينمو من المصدر الموحد ratio_labels — نفس نصوص المحلل
        "gross_margin": {"value": 30.0, **_ratio_labels_entry("gross_margin")},
        "net_margin": {"value": 15.0, **_ratio_labels_entry("net_margin")},
        "debt_ratio": {"value": 40.0, **_ratio_labels_entry("debt_ratio")},
        "debt_to_equity": {"value": 0.67, **_ratio_labels_entry("debt_to_equity")},
        "current_ratio": {"value": 2.0, **_ratio_labels_entry("current_ratio")},
        "quick_ratio": {"value": 1.38, **_ratio_labels_entry("quick_ratio")},
        "roa": {"value": 9.0, **_ratio_labels_entry("roa")},
        "roe": {"value": 15.0, **_ratio_labels_entry("roe")},
    },
    "metrics": {
        "revenue": [12000000, 15000000],
        "cogs": [8400000, 10500000],
        "opex": [1800000, 2250000],
        "net_profit": [1800000, 2250000],
        "assets": [22000000, 25000000],
        "liabilities": [9000000, 10000000],
        "equity": [13000000, 15000000],
        "current_assets": [14000000, 20000000],
        "inventory": [5500000, 7500000],
        "cash": [2200000, 2500000],
    },
    "series": {
        "revenue": {
            "values": [12000000, 15000000],
            "en": "Revenue",
            "ar": "الإيرادات",
        },
        "net_profit": {
            "values": [1800000, 2250000],
            "en": "Net Profit",
            "ar": "صافي الربح",
        },
    },
    "forecast": [
        {"concept": "revenue", "en": "Revenue", "ar": "الإيرادات", "change_pct": 25.0, "trend": "up"},
        {"concept": "net_profit", "en": "Net Profit", "ar": "صافي الربح", "change_pct": 25.0, "trend": "up"},
    ],
    "tables_found": 3,
    "texts_found": 120,
    "analysed_at": None,
}


@app.post("/api/demo")
def create_demo(authorization: str | None = Header(default=None), auth_token: str | None = None):
    """One-click demo analysis — counts against the caller's plan quota
    (the free tier has exactly ONE analysis, Pro/Business monthly quotas);
    anonymous visitors may try it once per browser session."""
    from urllib.parse import unquote

    token = (unquote(authorization).removeprefix("Bearer ").strip()
             if authorization else
             (unquote(auth_token).strip() if auth_token else None))
    user = user_from_token(token)
    if user:
        from .auth import PLANS

        quota = (PLANS.get(user.plan or "", {}).get("uploads")
                 if user.subscription == "paid" else 1)
        if user.is_admin:
            quota = None
        used = user.uploads_used or 0
        if quota is not None and used >= quota:
            raise HTTPException(
                402,
                f"نفدت حصة التحليل ({quota}) — رقّ باقتك لتحليل المزيد",
            )
    result = dict(_DEMO_RESULT)
    result["analysed_at"] = _now()
    result["metrics"] = result_to_metrics(result)
    clean_result(result)
    result["original_metrics"] = dict(result["metrics"])
    with SessionLocal() as db:
        row = Analysis(
            filename="demo-quarterly-report.xlsx",
            file_type=".xlsx",
            size_bytes=48213,
            result_json=json.dumps(result, ensure_ascii=False),
            created_at=_now(),
        )
        db.add(row)
        db.commit()
        bump_analyses()
        if user:
            with SessionLocal() as db:
                u = db.get(User, user.id)
                if u:
                    u.uploads_used = (u.uploads_used or 0) + 1
                    db.commit()
        return {"id": row.id, "filename": row.filename, "result": result}


# ---------------------------------------------------------------------------
# Logo asset
# ---------------------------------------------------------------------------


@app.get("/api/logo.svg")
def logo_svg():
    """Platform logo (SVG) — used by the UI and embeddable in exports."""
    return FileResponse(
        ROOT / "frontend" / "public" / "logo.svg",
        media_type="image/svg+xml",
    )


@app.get("/api/analyses/{analysis_id}/pptx")
def export_pptx(analysis_id: int, lang: str = "ar", authorization: str | None = Header(default=None), auth_token: str | None = None):
    """Professional PowerPoint export: branded cover, KPIs, charts,
    forecast, recommendations and full financial statements.
    SALES-kind analyses get the sales deck instead — a financial deck of
    a sales analysis renders zero-value statements slides.
    """
    user = _require_paid(authorization, auth_token)

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    if lang not in ("ar", "en"):
        lang = "ar"

    result = json.loads(row.result_json)
    result["_filename"] = row.display_name or row.filename

    # ---- sales deck branch -----------------------------------------------------
    if result.get("kind") == "sales":
        sales = result.get("sales_analysis") or {}
        if not sales:
            raise HTTPException(422, "التحليل لا يحتوي بيانات مبيعات قابلة للتصدير")
        from .pptx_report import build_sales_pptx_report

        out_s = REPORTS / f"pptx_sales_{analysis_id}_{lang}.pptx"
        if not out_s.exists():
            try:
                build_sales_pptx_report(
                    _entity_name(row),
                    sales,
                    out_s,
                    lang,
                    band=_subscription_label(user, lang),
                    notes=row.notes,
                )
            except UnsupportedGlyphError as exc:
                raise HTTPException(422, exc.message(lang)) from None
        return FileResponse(
            out_s,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"sales-deck-{analysis_id}-{lang}.pptx",
        )

    from .pptx_report import build_pptx_report

    advisor = build_advisor(result, lang)
    statements = (
        _report_statements(row)
    )
    from .scoring import compute_scenarios, compute_score

    out = REPORTS / f"pptx_{analysis_id}_{lang}.pptx"
    if not out.exists():
        try:
            build_pptx_report(
                _entity_name(row),
                result,
                out,
                lang,
                advisor=advisor,
                statements=statements,
                notes=row.notes,
                score=compute_score(result),
                scenarios=compute_scenarios(result),
                brief=build_executive_brief(result, lang),
                ratio_insights=build_ratio_insights(result, lang),
                yearly_comparison=build_yearly_comparison(result, lang),
                period=_period_text(result, lang),
                band=_subscription_label(user, lang),
            )
        except UnsupportedGlyphError as exc:
            # chart glyphs the matplotlib font cannot render refuse the
            # whole deck — never a slide full of hollow boxes
            raise HTTPException(422, exc.message(lang)) from None
    return FileResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"financial-deck-{analysis_id}-{lang}.pptx",
    )


# Serve the built React app (after `npm run build`) in production
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
