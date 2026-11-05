"""المساعد الذكي — AI chat assistant backed by Google Gemini.

The client (AssistantPage.tsx) posts a message plus recent history to
``/api/assistant/chat``; this module assembles the user's real platform
context (account, plan, analyses) into a system prompt and calls the
Gemini ``generateContent`` REST API.

API-key discovery (first match wins, checked per request):
  1. env ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` / ``AI_API_KEY``
  2. file  ``<project root>/ai_key.txt``
  3. file  ``<project root>/app/ai_key.txt``
The key file is re-read whenever its mtime changes, so the user can paste
a free key from aistudio.google.com while the server is running — no
restart needed. The key itself never leaves this module (only the model
endpoint receives it).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
KEY_FILES = [ROOT / "ai_key.txt", ROOT / "app" / "ai_key.txt"]
# Preferred model first; later entries are fallbacks. gemini-flash-latest
# and gemini-pro-latest are evergreen aliases — always the latest models,
# so a Google retirement never breaks the assistant again (older pinned
# versions such as gemini-2.x/3.x now 404 for new keys).
# Override the first entry via the GEMINI_MODEL env var.
# Primary = flash quality; lite first-fallback has a wider free-tier
# request quota (20 RPM flash vs 60 RPM lite-ish) and pro-last stays as
# the paid-tier option. Override the primary via the GEMINI_MODEL env var.
_MODELS = [
    os.environ.get("GEMINI_MODEL") or "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest",
]
_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_key_lock = threading.Lock()
_key_cache: dict = {"path": None, "mtime": None, "key": None}


def _read_key() -> tuple[str | None, Path | None]:
    """Return (key, source_file_or_None); env vars take priority."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AI_API_KEY"):
        val = (os.environ.get(var) or "").strip()
        if val:
            return val, None
    with _key_lock:
        for path in KEY_FILES:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if (
                _key_cache["path"] == str(path)
                and _key_cache["mtime"] == mtime
                and _key_cache["key"]
            ):
                return _key_cache["key"], path
            try:
                raw = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            # tolerate a pasted "key": "AIza..." line or stray quotes
            raw = raw.split(":", 1)[-1].strip().strip('"').strip("'").strip()
            if raw:
                _key_cache.update(path=str(path), mtime=mtime, key=raw)
                return raw, path
    return None, KEY_FILES[0]


# ---------------------------------------------------------------------------
# platform context injected into the system prompt
# ---------------------------------------------------------------------------

def build_user_context(user: dict) -> str:
    """Compact bilingual context block: the signed-in account, its plan and
    the platform's stored analyses (real numbers the assistant may quote)."""
    lines = ["سياق المستخدم (بيانات حقيقية من قاعدة بيانات المنصة):"]
    lines.append(f"- الحساب: {user.get('full_name') or user.get('username')}")
    if user.get("subscription") == "paid":
        plan = user.get("plan") or ""
        plan_name = {"pro": "برو", "business": "الأعمال"}.get(plan, plan)
        expires = str(user.get("plan_expires") or "")[:10] or "غير محدد"
        lines.append(
            f"- الاشتراك: مدفوع — باقة {plan_name}، تنتهي في {expires}"
        )
    else:
        lines.append("- الاشتراك: مجاني (تحليل واحد لمرة واحدة)")
    lines.append(f"- عدد التحليلات المستخدمة في الفترة الحالية: {user.get('uploads_used', 0)}")

    try:
        from .database import Analysis, SessionLocal

        with SessionLocal() as db:
            rows = db.query(Analysis).order_by(Analysis.id.desc()).limit(8).all()
        if not rows:
            lines.append("- لا توجد تحليلات محفوظة بعد (سجل التحليلات فارغ).")
        else:
            lines.append(f"- التحليلات المحفوظة: {len(rows)} (الأحدث أولًا):")
            for r in rows:
                name = r.display_name or r.filename
                info = [f"«{name}» ({(r.file_type or '').lstrip('.')}, {str(r.created_at)[:10]})"]
                try:
                    res = json.loads(r.result_json or "{}")
                    kpis = res.get("kpis") or {}
                    vals = []
                    for key, k in list(kpis.items())[:5]:
                        if isinstance(k, dict) and k.get("value") is not None:
                            try:
                                num = f"{float(k['value']):,.0f}"
                            except (TypeError, ValueError):
                                continue
                            vals.append(f"{k.get('ar') or key}: {num}")
                    if vals:
                        info.append("القيم: " + "؛ ".join(vals))
                    ratios = res.get("ratios") or {}
                    rts = []
                    for key, v in list(ratios.items())[:4]:
                        if isinstance(v, dict) and v.get("value") is not None:
                            rts.append(f"{v.get('ar') or key}: {v.get('value')}")
                    if rts:
                        info.append("النسب: " + "؛ ".join(rts))
                    audit = res.get("audit") or {}
                    if audit.get("errors"):
                        info.append(f"مدقق الجودة: {len(audit['errors'])} أخطاء")
                    elif audit:
                        info.append("مدقق الجودة: سليم")
                except Exception:
                    pass  # metadata row only
                lines.append("  * " + " — ".join(info))
    except Exception:
        lines.append("- تعذّر جلب التحليلات الآن.")
    return "\n".join(lines)


def _sales_slowdown_diagnosis(sa: dict) -> str | None:
    """Mirror of the dashboard's root-cause block (frontend SalesAnalysis).
    Detects a month-over-month growth decline streak on the total series,
    then scans the region/rep matrices for entities reproducing the same
    streak — the steepest growth slide names the likely culprit. Returns
    a single Arabic context line, or None when no slowdown fires (3+
    consecutive declines, matching the dashboard's default threshold)."""
    monthly = sa.get("monthly") or []
    gs = [m.get("growth") for m in monthly if isinstance(m, dict) and m.get("growth") is not None]
    if len(gs) < 2:
        return None
    streak = 0
    for i in range(len(gs) - 1, 0, -1):
        if gs[i] < gs[i - 1]:
            streak += 1
        else:
            break
    if streak < 3:
        return None
    months = [m.get("month") for m in monthly if isinstance(m, dict)]
    win = months[-(streak + 1):]
    negative = gs[-1] < 0

    cands: list[tuple[str, str, float, float]] = []  # (label, name, from, to)
    for kind, matrix_key in (("منطقة", "by_region_months"), ("مندوب", "by_rep_months")):
        matrix = sa.get(matrix_key) or {}
        for name, mm in matrix.items():
            if not isinstance(mm, dict):
                continue
            es = [float((mm.get(mo) or {}).get("sales") or 0) for mo in months]
            egs: list[float] = []
            for i in range(1, len(es)):
                egs.append(round((es[i] - es[i - 1]) / es[i - 1] * 1000) / 10 if es[i - 1] > 0 else 0.0)
            if len(egs) < streak:
                continue
            est = 0
            for i in range(len(egs) - 1, 0, -1):
                if egs[i] < egs[i - 1]:
                    est += 1
                else:
                    break
            if est < streak:
                continue
            if not any((mm.get(mo) or {}).get("transactions") for mo in win):
                continue
            cands.append((kind, name, egs[len(egs) - 1 - est], egs[-1]))
    cands.sort(key=lambda c: c[3] - c[2])
    # python<3.12 cannot nest quotes inside an f-string expression — keep the
    # trailing note in a variable instead
    neg_note = " — آخر شهر سالب" if negative else ""

    if cands:
        kind, name, g_from, g_to = cands[0]
        return (
            f"- تنبيه تباطؤ المبيعات: نمو آخر {streak} أشهر متتالية يتراجع "
            f"({gs[len(gs) - 1 - streak]}% → {gs[-1]}%{neg_note}) "
            f"عبر النافذة {' → '.join(win)}. التشخيص الأكثر ترجيحًا: {kind} «{name}» "
            f"— نموه الشهري تراجع من {g_from}% إلى {g_to}%؛ راجع حساباته/حملاته أولًا."
        )
    return (
        f"- تنبيه تباطؤ المبيعات: نمو آخر {streak} أشهر متتالية يتراجع "
        f"({gs[len(gs) - 1 - streak]}% → {gs[-1]}%{neg_note}) "
        f"عبر النافذة {' → '.join(win)}. لا توجد منطقة أو مندوب واحد مسؤول واضح "
        "— الانخفاض موزّع؛ راجع العوامل العامة (الموسمية، الأسعار، الحملات)."
    )


def build_analysis_context(analysis_id: int) -> str | None:
    """Rich context block for ONE analysis — the «المساعد الذكي» may quote
    these real numbers verbatim when the user scopes the chat to it.
    Returns None when the analysis does not exist (caller raises 404)."""
    import json as _json

    from .database import Analysis, SessionLocal

    with SessionLocal() as db:
        row = db.get(Analysis, analysis_id)
    if not row:
        return None
    name = row.display_name or row.filename
    lines = [
        "التحليل المحدد للمحادثة (أجب من هذه الأرقام فقط، واقتبسها كما هي):",
        f"- الاسم: «{name}» ({(row.file_type or '').lstrip('.')}) — أُنشئ في {str(row.created_at)[:10]}",
    ]
    try:
        res = _json.loads(row.result_json or "{}")
        labels = [p for p in (res.get("period_labels") or []) if isinstance(p, str) and p.strip()]
        n_periods = labels[-1] if labels else str(max(
            (len(v) for v in (res.get("metrics") or {}).values()), default=0
        ))
        if labels:
            lines.append(f"- الفترات (الأقدم → الأحدث): {' - '.join(labels)}")
        kpis = res.get("kpis") or {}
        if kpis:
            kv = []
            for key, k in kpis.items():
                if isinstance(k, dict) and k.get("value") is not None:
                    try:
                        kv.append(f"{k.get('ar') or key}: {float(k['value']):,.0f}")
                    except (TypeError, ValueError):
                        pass
            lines.append("- المؤشرات: " + "؛ ".join(kv))
        ratios = res.get("ratios") or {}
        if ratios:
            rv = []
            for key, v in ratios.items():
                if isinstance(v, dict) and v.get("value") is not None:
                    rv.append(f"{v.get('ar') or key}: {v.get('value')}")
            lines.append("- النسب: " + "؛ ".join(rv))
        series = res.get("series") or {}
        if series:
            lines.append(f"- عدد الفترات: {n_periods}")
            sv = []
            for key, s in list(series.items())[:6]:
                if isinstance(s, dict) and s.get("values"):
                    label = s.get("ar") or key
                    vals = ", ".join(str(v) for v in s["values"][:6])
                    sv.append(f"{label}: [{vals}]")
            if sv:
                lines.append("- سلاسل القيم (الأقدم → الأحدث): " + "؛ ".join(sv))
        forecast = res.get("forecast") or []
        if forecast:
            fv = []
            for f in forecast[:6]:
                if isinstance(f, dict):
                    fv.append(
                        f"{f.get('ar') or f.get('concept')}: {f.get('change_pct')}% "
                        f"({f.get('trend')})"
                    )
            lines.append("- التنبؤ المرتقب: " + "؛ ".join(fv))
        audit = res.get("audit") or {}
        if audit:
            verdict = (
                f"{len(audit.get('errors') or [])} أخطاء و{len(audit.get('warnings') or [])} "
                "تنبيهات من مدقق الجودة"
                if (audit.get("errors") or audit.get("warnings"))
                else "سليم بلا ملاحظات (شارة مدقق)"
            )
            lines.append(f"- مدقق الجودة: {verdict}")
        # sales dashboards: inject the slowdown root-cause diagnosis so the
        # assistant answers «من سبب التباطؤ؟» with the same culprit the UI names
        sa = res.get("sales_analysis") or {}
        if sa.get("monthly"):
            try:
                diag = _sales_slowdown_diagnosis(sa)
                if diag:
                    lines.append(diag)
            except Exception:
                pass
        if row.notes:
            notes = str(row.notes).strip().replace("\n", " | ")[:400]
            lines.append(f"- ملاحظات المستخدم على التحليل: {notes}")
        if row.statements_json:
            try:
                st = _json.loads(row.statements_json)
                tb = st.get("trial_balance") or {}
                if tb:
                    lines.append(
                        "- ميزان المراجعة المرفق: "
                        f"مدين {tb.get('total_debit', 0):,.0f} / دائن {tb.get('total_credit', 0):,.0f}"
                        + (" (متوازن)" if tb.get("balanced") else " (غير متوازن!)"
                           if tb.get("balanced") is not None else "")
                )
                bs = st.get("balance_sheet") or {}
                inc = st.get("income_statement") or {}
                if bs.get("total") is not None:
                    lines.append(f"- إجمالي الميزانية العمومية: {float(bs['total']):,.0f}")
                if bs.get("difference") is not None:
                    lines.append(f"- فرق التوازن: {float(bs['difference']):,.0f}")
                lines.append("- ملاحظة: القوائم المالية المتكاملة مبنية من ميزان المراجعة وهي متاحة في بطاقة التحليل.")
            except Exception:
                pass
    except Exception:
        lines.append("- (تعذّر قراءة تفاصيل النتيجة المحفوظة — اعتمد الاسم والتواريخ فقط)")
    return "\n".join(lines)


def _system_prompt(lang: str) -> str:
    from .knowledge import build_knowledge_context

    knowledge = build_knowledge_context()
    return (
        "أنت «المساعد الذكي» داخل منصة SFP لتحليل الملفات المالية — منصة عربية "
        "تقرأ الملفات المحاسبية وتُخرج قوائم مالية ونسبًا وتقارير.\n"
        "دورك: مساعد مالي ودليل استخدام للمنصة.\n"
        + knowledge
        + "\n"
        "- أجب بنفس لغة سؤال المستخدم (العربية هي الغالب)، وبالإنجليزية إن سُئلت بها.\n"
        "- الإجابة موجزة وواضحة (٢–٦ جمل)، ونقاط قصيرة عند التعداد.\n"
        "- استعن بـ«سياق المستخدم» المرفق: بياناته وباقته وتحليلاته الفعلية؛ "
        "اقتبس أرقامه الحقيقية حين يسأل عنها.\n"
        "- عند شرح مؤشر مالي: ما هو، كيف يُقرأ، وما القيمة الجيدة تقريبًا.\n"
        "- لا تخترع أرقامًا غير موجودة في السياق؛ إن غاب الرقم فقل إنه غير متوفر.\n"
        "- لا تقدّم توصيات استثمارية ملزمة؛ ذكّر بإيجاز أن القرار النهائي للمحاسب المختص.\n"
        "- عند السؤال عن المنصة اشرح ميزاتها: رفع الملف المالي، سجل التحليلات مع "
        "تقارير PDF/PPTX/Excel، مقارنة التقارير، نماذج التقارير حسب الباقة، سجل "
        "المدفوعات والفواتير، والباقات: برو (5 تحليلات شهريًا بـ50$) والأعمال "
        "(20 تحليلًا شهريًا بـ100$).\n"
        f"- لغة الواجهة الحالية للمستخدم: {lang}.\n"
    )


# ---------------------------------------------------------------------------
# user-facing failure messages (bilingual, shown inside the chat bubble)
# ---------------------------------------------------------------------------

def _no_key_message(lang: str) -> str:
    if lang == "en":
        return (
            "🔑 Hi! I'm the platform AI assistant, powered by Google Gemini.\n"
            "No API key is configured yet. Create a free key at "
            "aistudio.google.com/apikey, paste it into:\n"
            f"{KEY_FILES[0]}\n"
            "then send your message again — no restart needed."
        )
    return (
        "🔑 مرحبًا! أنا المساعد الذكي في المنصة، وأعمل بمحرك Google Gemini.\n"
        "لم يتم ضبط مفتاح Gemini بعد.\n"
        "أنشئ مفتاحًا مجانيًا من aistudio.google.com/apikey ثم ضعه كاملًا في الملف:\n"
        f"{KEY_FILES[0]}\n"
        "وأعد إرسال رسالتك — سأعمل فورًا دون الحاجة لإعادة تشغيل المنصة."
    )


def _bad_key_message(lang: str) -> str:
    if lang == "en":
        return (
            "🔑 The configured Gemini key looks invalid — make sure it was copied "
            "in full from aistudio.google.com into the key file, then try again."
        )
    return (
        "🔑 المفتاح المضبوط للمساعد الذكي غير صالح — تأكد من نسخه كاملًا من "
        "Google AI Studio في ملف المفتاح، ثم أعد المحاولة."
    )


def _rate_limit_message(lang: str) -> str:
    if lang == "en":
        return "⏳ Temporary Gemini free-tier limit reached — wait a minute and try again."
    return "⏳ وصلنا الحد المؤقت للاستخدام المجاني لـ Gemini — انتظر دقيقة ثم أعد المحاولة."


def _blocked_message(lang: str) -> str:
    if lang == "en":
        return "I can't answer that request under Gemini's safety policy."
    return "لا أستطيع الإجابة على هذا الطلب وفق سياسات الاستخدام الآمن لـ Gemini."


def _api_fail_message(lang: str, detail: str) -> str:
    short = (detail or "unknown error")[:180]
    if lang == "en":
        return (
            f"⚠️ Couldn't reach Gemini right now ({short}). Check the internet "
            "connection and try again."
        )
    return f"⚠️ تعذّر الاتصال بخدمة Gemini الآن ({short}). تأكد من اتصال الإنترنت وأعد المحاولة."


# ---------------------------------------------------------------------------
# persisted conversation (per user, survives page reloads)
# ---------------------------------------------------------------------------

# Cap of the stored history per user (newest kept) — SQLite only, but a
# bound keeps the DB and the Gemini context modest.
_MAX_SAVED_TURNS = 100


def _save_turn(user_id: int, role: str, content: str) -> None:
    """Persist one chat turn and prune beyond the newest _MAX_SAVED_TURNS."""
    from datetime import datetime, timezone

    from .database import AssistantMessage, SessionLocal

    try:
        with SessionLocal() as db:
            db.add(AssistantMessage(
                user_id=user_id,
                role=role,
                content=content,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            db.commit()
            extra = (
                db.query(AssistantMessage.id)
                .filter(AssistantMessage.user_id == user_id)
                .order_by(AssistantMessage.id.desc())
                .offset(_MAX_SAVED_TURNS)
                .all()
            )
            if extra:
                ids = [row[0] for row in extra]
                db.query(AssistantMessage).filter(
                    AssistantMessage.id.in_(ids)
                ).delete(synchronize_session=False)
                db.commit()
    except Exception:
        pass  # history is an enhancement — a chat turn must never 500


def read_history(user_id: int) -> list[dict]:
    """Stored conversation of one user, oldest first (resumed live)."""
    from .database import AssistantMessage, SessionLocal

    try:
        with SessionLocal() as db:
            rows = (
                db.query(AssistantMessage)
                .filter(AssistantMessage.user_id == user_id)
                .order_by(AssistantMessage.id.asc())
                .all()
            )
            return [
                {"role": r.role if r.role in ("user", "assistant") else "user",
                 "content": r.content or ""}
                for r in rows
            ]
    except Exception:
        return []  # table not ready / db hiccup — start a fresh chat


def clear_history(user_id: int) -> int:
    """Delete one user's stored conversation; returns the removed count."""
    from .database import AssistantMessage, SessionLocal

    with SessionLocal() as db:
        n = (
            db.query(AssistantMessage)
            .filter(AssistantMessage.user_id == user_id)
            .delete(synchronize_session=False)
        )
        db.commit()
        return n


# ---------------------------------------------------------------------------
# the Gemini call
# ---------------------------------------------------------------------------

def _gemini_error(resp: requests.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("error", {}).get("message") or resp.text[:200])
    except (ValueError, AttributeError):
        return resp.text[:200]


def assistant_reply(
    message: str,
    history: list[dict] | None,
    context: str,
    lang: str = "ar",
) -> tuple[str, str | None]:
    """One chat turn. Returns ``(reply, error)`` — ``error`` is ``None`` on
    a real model answer, ``"no_key"`` when unconfigured, or a short code for
    failures (the reply itself always carries a friendly user-facing text)."""
    key, _src = _read_key()
    if not key:
        return _no_key_message(lang), "no_key"

    contents: list[dict] = []
    for turn in (history or [])[-10:]:
        text = str((turn or {}).get("content") or "").strip()[:2000]
        if not text:
            continue
        role = "model" if (turn or {}).get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": message.strip()[:4000]}]})

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        _system_prompt(lang)
                        + "\n\n"
                        + (context.strip() or "")
                    )
                }
            ]
        },
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1200},
    }

    last_err = ""
    import time as _time

    for i, model in enumerate(_MODELS):
        # Transient overload (503 high demand) is retried on the SAME model
        # before falling to the next entry — falling through to Pro on a
        # flash overload just burns the Pro quota (often zero on free tier).
        for attempt in range(3 if i == 0 else 1):
            try:
                resp = requests.post(
                    _API_URL.format(model=model),
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=45,
                )
            except requests.RequestException as exc:
                last_err = str(exc)
                break
            if resp.status_code == 200:
                break  # success — leave the retry loop
            if resp.status_code == 503 and attempt < 2:
                _time.sleep(15 * (attempt + 1))
                continue  # overloaded right now — same model, back off
            break  # other failures go to the model-chain logic below
        if resp.status_code == 404:
            last_err = f"model {model} not found"
            continue  # retired/unavailable model — try the next one
        if resp.status_code in (400, 401, 403):
            detail = _gemini_error(resp)
            low = detail.lower()
            if "api key not valid" in low or "api_key_invalid" in low:
                return _bad_key_message(lang), "invalid_key"
            if "model" in low and i < len(_MODELS) - 1:
                last_err = detail
                continue  # unknown-model flavour of a 400 — try next model
            last_err = detail
            continue
        if resp.status_code == 429:
            # Quota/gate refusal on THIS model — a lighter/next model in the
            # chain usually still has its own quota (lite is wider on the
            # free tier). Report the limit only when every model refused.
            last_err = f"{model}: {_gemini_error(resp)[:160]}"
            continue
        if resp.status_code != 200:
            last_err = f"HTTP {resp.status_code}: {_gemini_error(resp)}"
            continue
        try:
            data = resp.json()
            candidates = data.get("candidates") or [{}]
            parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text, None
            block = (data.get("promptFeedback") or {}).get("blockReason")
            if block:
                return _blocked_message(lang), str(block)
            last_err = "empty response"
        except (ValueError, AttributeError, IndexError, KeyError) as exc:
            last_err = f"bad payload: {exc}"
    # every model in the chain failed — distinguish quota vs transient
    if "429" in last_err or "quota" in last_err.lower():
        return _rate_limit_message(lang), "rate_limited"
    return _api_fail_message(lang, last_err), "api_error"
