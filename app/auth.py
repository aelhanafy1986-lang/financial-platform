"""Authentication: register + email activation code + login sessions.

Email delivery uses SMTP when SMTP_HOST is configured; otherwise the code is
printed to the server log (and returned in dev mode) so local use still works.
Passwords are hashed with PBKDF2-SHA256 via hashlib (no extra dependency).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from . import database as _db
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# password hashing (PBKDF2-SHA256, 200k iterations; fewer under tests)
# ---------------------------------------------------------------------------
import os

# Tests may lower the work factor — hashing dominates their wall time.
_PBKDF2_ITERATIONS = 2_000 if os.environ.get("FIN_TEST_MODE") == "1" else 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return secrets.compare_digest(check.hex(), digest)


# ---------------------------------------------------------------------------
# email delivery
# ---------------------------------------------------------------------------

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "noreply@sfp.local")


def send_code_email(to: str, code: str, lang: str = "ar") -> bool:
    """Send the activation code via SMTP when configured.

    Returns True when the email was actually sent; False means dev mode
    (the code is surfaced in the API response / server log instead).
    """
    subject = (
        "كود تفعيل حسابك — المنصة المالية الذكية"
        if lang == "ar"
        else "Your activation code — Smart Financial Platform"
    )
    body = (
        f"مرحباً،\n\nكود التفعيل الخاص بك هو: {code}\n\n"
        "أدخل هذا الكود في صفحة التسجيل لتفعيل حسابك.\n\n— المنصة المالية الذكية"
        if lang == "ar"
        else f"Hello,\n\nYour activation code is: {code}\n\n"
        "Enter it on the sign-up page to activate your account.\n\n— Smart Financial Platform"
    )
    if not SMTP_HOST:
        print(f"[AUTH] dev mode: activation code for {to}: {code}")
        return False

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=ctx)
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        return True
    except Exception as exc:
        print(f"[AUTH] SMTP send failed ({exc}); code for {to}: {code}")
        return False


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# ---------------------------------------------------------------------------
# registration / activation / login
# ---------------------------------------------------------------------------

class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def register_user(full_name: str, email: str, country: str | None,
                  username: str, password: str, lang: str = "ar") -> dict:
    if len(password) < 6:
        raise AuthError(
            "كلمة المرور يجب ألا تقل عن 6 أحرف" if lang == "ar" else "Password must be at least 6 characters"
        )
    with _db.SessionLocal() as db:
        email_n = email.strip().lower()
        username_n = username.strip().lower()
        if db.query(_db.User).filter(_db.User.email == email_n).first():
            raise AuthError(
                "البريد الإلكتروني مسجل مسبقاً" if lang == "ar" else "Email already registered", 409
            )
        if db.query(_db.User).filter(_db.User.username == username_n).first():
            raise AuthError(
                "اسم المستخدم محجوز" if lang == "ar" else "Username taken", 409
            )
        code = _generate_code()
        user = _db.User(
            full_name=full_name.strip(),
            email=email_n,
            country=(country or "").strip() or None,
            username=username_n,
            password_hash=hash_password(password),
            status="pending",
            activation_code=code,
            subscription="free",
            created_at=_now(),
        )
        db.add(user)
        db.commit()
        sent = send_code_email(email_n, code, lang)
        return {
            "user_id": user.id,
            "email_sent": sent,
            # In dev mode (no SMTP configured) the code is returned so the
            # local platform remains usable end-to-end.
            "dev_code": None if sent else code,
        }


def activate_user(email: str, code: str, lang: str = "ar") -> _db.User:
    with _db.SessionLocal() as db:
        user = db.query(_db.User).filter(_db.User.email == email.strip().lower()).first()
        bad = "كود غير صحيح" if lang == "ar" else "Invalid code"
        if not user or not user.activation_code:
            raise AuthError(bad, 400)
        if user.status == "active":
            raise AuthError(
                "الحساب مفعّل مسبقاً" if lang == "ar" else "Account already active", 409
            )
        if not secrets.compare_digest(user.activation_code, code.strip()):
            raise AuthError(bad, 400)
        user.status = "active"
        user.activation_code = None
        db.commit()
        return user


def login_user(username: str, password: str, lang: str = "ar") -> dict:
    with _db.SessionLocal() as db:
        user = db.query(_db.User).filter(_db.User.username == username.strip().lower()).first()
        invalid = "اسم المستخدم أو كلمة المرور غير صحيحة" if lang == "ar" else "Invalid username or password"
        if not user or not verify_password(password, user.password_hash):
            raise AuthError(invalid, 401)
        if user.status != "active":
            raise AuthError(
                "الحساب غير مفعّل — أدخل كود التفعيل المرسل لإيميلك"
                if lang == "ar" else
                "Account not activated — enter the code sent to your email",
                403,
            )
        token = secrets.token_hex(32)
        db.add(_db.Session(token=token, user_id=user.id, created_at=_now()))
        user.last_login = _now()
        db.commit()
        # same public shape as /me so the client (e.g. the social-account
        # badge) sees provider/status right after signing in, not only on
        # the next refresh
        return {"token": token, "user": user_payload(user)}


# Social sign-in providers (Google / Apple). Like the card charge, the
# exchange is SIMULATED locally: the provider email is trusted and the
# account is created or matched without a password. Verify the real
# provider ID-token before exposing this to the public internet.
_SOCIAL_PROVIDERS = ("google", "apple")


def social_auth(provider: str, email: str, full_name: str | None,
                lang: str = "ar") -> dict:
    """Sign up / in through a social provider — one endpoint for both:
    an existing email logs in, a new email auto-registers an ACTIVE
    passwordless account (the provider is trusted for verification)."""
    provider_n = (provider or "").strip().lower()
    if provider_n not in _SOCIAL_PROVIDERS:
        raise AuthError(
            "مزوّد الدخول غير مدعوم" if lang == "ar" else "Unsupported provider", 400
        )
    email_n = (email or "").strip().lower()
    if "@" not in email_n or "." not in email_n.split("@")[-1]:
        raise AuthError(
            "بريد إلكتروني غير صالح" if lang == "ar" else "Invalid email address", 400
        )
    with _db.SessionLocal() as db:
        user = db.query(_db.User).filter(_db.User.email == email_n).first()
        if not user:
            # derive a unique username from the email's local part
            base = email_n.split("@")[0].replace(".", "_")[:24] or "user"
            username, n = base, 1
            while db.query(_db.User).filter(_db.User.username == username).first():
                n += 1
                username = f"{base}{n}"
            user = _db.User(
                full_name=(full_name or "").strip() or base,
                email=email_n,
                country=None,
                username=username,
                # passwordless account: random unusable hash keeps password
                # login closed for social-only users
                password_hash=hash_password(secrets.token_hex(16)),
                status="active",
                activation_code=None,
                subscription="free",
                provider=provider_n,
                created_at=_now(),
            )
            db.add(user)
            db.commit()
        else:
            changed = False
            if user.status != "active":
                # a pending email-code account verified through the provider
                user.status = "active"
                user.activation_code = None
                changed = True
            if getattr(user, "provider", None) != provider_n:
                user.provider = provider_n
                changed = True
            if changed:
                db.commit()
        token = secrets.token_hex(32)
        db.add(_db.Session(token=token, user_id=user.id, created_at=_now()))
        user.last_login = _now()
        db.commit()
        # same public shape as /me so the client (e.g. the social-account
        # badge) sees provider/status right after signing in, not only on
        # the next refresh
        return {"token": token, "user": user_payload(user)}


def user_payload(user: _db.User) -> dict:
    """Public shape of a user row (used by /me and admin endpoints)."""
    # current payment method: the masked card of the user's last charge
    # (surfaces in the «سجل المدفوعات» header without a second request).
    masked_card: str | None = None
    try:
        with _db.SessionLocal() as db:
            last = (
                db.query(_db.Payment)
                .filter(_db.Payment.user_id == user.id)
                .order_by(_db.Payment.id.desc())
                .first()
            )
            masked_card = last.masked_card if last else None
    except Exception:
        masked_card = None  # ledger unavailable — /me still loads
    return {
        "id": user.id,
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "country": user.country,
        "subscription": user.subscription,
        "plan": user.plan,
        "provider": user.provider,
        "is_admin": bool(user.is_admin),
        "status": user.status,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "uploads_used": user.uploads_used or 0,
        "plan_expires": user.plan_expires,
        "masked_card": masked_card,
    }


def list_users() -> list[dict]:
    """All registered users, newest first (admin only)."""
    with _db.SessionLocal() as db:
        users = db.query(_db.User).order_by(_db.User.id.desc()).all()
        return [user_payload(u) for u in users]


def set_user_subscription(target_id: int, subscription: str, plan: str | None,
                          lang: str = "ar") -> dict:
    """Admin override of another user's subscription/plan."""
    if subscription not in ("free", "paid"):
        raise AuthError("قيمة اشتراك غير صالحة" if lang == "ar" else "Invalid subscription")
    if plan is not None and plan not in PLANS:
        raise AuthError("باقة غير معروفة" if lang == "ar" else "Unknown plan")
    with _db.SessionLocal() as db:
        user = db.get(_db.User, target_id)
        if not user:
            raise AuthError("مستخدم غير موجود" if lang == "ar" else "User not found", 404)
        user.subscription = subscription
        user.plan = plan if subscription == "paid" else None
        if subscription == "free":
            user.plan_expires = None
            user.uploads_used = 0
        db.commit()
        return user_payload(user)


def set_user_active(target_id: int, active: bool, lang: str = "ar") -> dict:
    """Admin enable/disable of another user's account."""
    with _db.SessionLocal() as db:
        user = db.get(_db.User, target_id)
        if not user:
            raise AuthError("مستخدم غير موجود" if lang == "ar" else "User not found", 404)
        if user.is_admin:
            raise AuthError(
                "لا يمكن تعطيل حساب المدير" if lang == "ar" else "Cannot disable the admin account"
            )
        user.status = "active" if active else "disabled"
        db.commit()
        return user_payload(user)


def user_from_token(token: str | None) -> _db.User | None:
    if not token:
        return None
    with _db.SessionLocal() as db:
        session = db.get(_db.Session, token)
        if not session:
            return None
        return db.get(_db.User, session.user_id)


def logout(token: str) -> None:
    with _db.SessionLocal() as db:
        session = db.get(_db.Session, token)
        if session:
            db.delete(session)
            db.commit()


# Subscription plans: key -> (months, analyses per month, ar name, en name).
# analyses=None means unlimited. Quota ladder mirrors the CMRRS pricing page:
# free = ONE analysis (one-time), Pro = 5/month, Business = 20/month.
PLANS: dict[str, dict] = {
    "pro": {"months": 1, "uploads": 5, "price": 50.0,
            "ar": "برو", "en": "Pro"},
    "business": {"months": 1, "uploads": 20, "price": 100.0,
                 "ar": "الأعمال", "en": "Business"},
}


def plan_list() -> list[dict]:
    return [{"key": k, **v} for k, v in PLANS.items()]


# ---------------------------------------------------------------------------
# platform administrator
# ---------------------------------------------------------------------------

ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@finplatform.local"
ADMIN_DEFAULT_PASSWORD = "Admin@2026"


def ensure_admin() -> None:
    """Create the built-in admin account on first start (idempotent).

    Username ``admin`` / password ``Admin@2026`` — fully active with the
    unlimited Business plan. Change the password after first login.
    """
    with _db.SessionLocal() as db:
        user = db.query(_db.User).filter(_db.User.username == ADMIN_USERNAME).first()
        if not user:
            user = _db.User(
                full_name="مدير المنصة",
                email=ADMIN_EMAIL,
                country=None,
                username=ADMIN_USERNAME,
                password_hash=hash_password(ADMIN_DEFAULT_PASSWORD),
                status="active",
                activation_code=None,
                subscription="paid",
                plan="business",
                is_admin=True,
                created_at=_now(),
            )
            db.add(user)
            db.commit()
        elif not user.is_admin:
            user.is_admin = True
            db.commit()


def activate_subscription(token: str, card_number: str, holder: str,
                          expiry: str, cvv: str, lang: str = "ar",
                          plan: str = "pro") -> dict:
    """Activate a paid plan after a (simulated) card charge."""
    if not token:
        raise AuthError("سجّل الدخول أولاً" if lang == "ar" else "Login required", 401)
    digits = (card_number or "").replace(" ", "")
    if not (digits.isdigit() and 12 <= len(digits) <= 19):
        raise AuthError(
            "رقم البطاقة غير صالح" if lang == "ar" else "Invalid card number"
        )
    if not (holder or "").strip():
        raise AuthError(
            "اسم حامل البطاقة مطلوب" if lang == "ar" else "Card holder required"
        )
    parts = (expiry or "").split("/")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise AuthError(
            "تاريخ الانتهاء يجب أن يكون MM/YY" if lang == "ar" else "Expiry must be MM/YY"
        )
    if not (cvv or "").strip().isdigit() or len(cvv.strip()) < 3:
        raise AuthError("CVV غير صالح" if lang == "ar" else "Invalid CVV")

    if plan not in PLANS:
        raise AuthError("باقة غير معروفة" if lang == "ar" else "Unknown plan")
    chosen = PLANS[plan]

    with _db.SessionLocal() as db:
        session = db.get(_db.Session, token)
        if not session:
            raise AuthError("جلسة غير صالحة" if lang == "ar" else "Invalid session", 401)
        user = db.get(_db.User, session.user_id)
        if not user:
            raise AuthError("مستخدم غير موجود" if lang == "ar" else "User not found", 404)
        # NOTE: simulation only — no real charge is performed. Replace with a
        # payment-gateway integration before production use.
        user.subscription = "paid"
        user.plan = plan
        user.uploads_used = 0
        # expiry from now (extend when renewing before expiry)
        from datetime import datetime, timedelta

        base = datetime.now(timezone.utc)
        if user.plan_expires:
            try:
                prev = datetime.fromisoformat(user.plan_expires)
                if prev > base:
                    base = prev
            except ValueError:
                pass
        user.plan_expires = (base + timedelta(days=30 * chosen["months"])).isoformat()
        masked = f"**** **** **** {digits[-4:]}"
        # ledger row for the «سجل المدفوعات» screen (payments table)
        from .database import Payment

        db.add(Payment(
            user_id=user.id,
            plan=plan,
            amount=float(chosen.get("price", 0.0)),
            currency="USD",
            masked_card=masked,
            status="paid",
            invoice_no=f"INV-{user.id}-{int(datetime.now(timezone.utc).timestamp())}",
            paid_at=datetime.now(timezone.utc).isoformat(),
        ))
        db.commit()
        return {
            "subscription": user.subscription,
            "plan": user.plan,
            "plan_expires": user.plan_expires,
            "masked_card": masked,
        }


def list_payments(user_id: int) -> list[dict]:
    """Payment history for the «سجل المدفوعات» screen, newest first."""
    from .database import Payment

    with _db.SessionLocal() as db:
        rows = (
            db.query(Payment)
            .filter(Payment.user_id == user_id)
            .order_by(Payment.id.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "plan": r.plan,
                "amount": r.amount,
                "currency": r.currency,
                "masked_card": r.masked_card,
                "status": r.status,
                "invoice_no": r.invoice_no,
                "paid_at": r.paid_at,
            }
            for r in rows
        ]
