"""Real OAuth ID-token verification for Google / Apple sign-in.

The frontend obtains an ID token from the provider (Google Identity
Services / Sign in with Apple JS) and posts it to
/api/auth/social/google|apple. This module verifies the token
cryptographically — RS256 signature against the provider's published JWKS,
issuer, audience (client id) and expiry — BEFORE any account is touched.

Configuration (environment variables):
    GOOGLE_CLIENT_ID    OAuth 2.0 Web client id  → enables real Google sign-in
    APPLE_CLIENT_ID     Services ID (aud claim)  → enables real Apple sign-in

When an id is not configured the endpoints answer 503 and the UI keeps the
local simulated buttons (the platform stays usable fully offline).
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import requests

from .auth import AuthError

_GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
_APPLE_JWKS = "https://appleid.apple.com/auth/keys"
_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_APPLE_ISSUER = "https://appleid.apple.com"

_CACHE_TTL = 3600  # seconds between JWKS refreshes
_jwks_cache: dict[str, tuple[float, list[dict]]] = {}


def _provider_config(provider: str) -> str:
    """Return the configured audience (client id) for the provider."""
    import os
    env_key = "GOOGLE_CLIENT_ID" if provider == "google" else "APPLE_CLIENT_ID"
    client_id = (os.environ.get(env_key) or "").strip()
    if not client_id:
        raise AuthError(
            f"الدخول عبر {provider.title()} غير مُهيأ على هذا الخادم"
            if provider == "google" else
            "الدخول عبر Apple غير مُهيأ على هذا الخادم",
            503,
        )
    return client_id


def _fetch_jwks(provider: str) -> list[dict]:
    """Fetch + cache the provider's published signing keys (per process)."""
    now = time.time()
    cached = _jwks_cache.get(provider)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    url = _GOOGLE_JWKS if provider == "google" else _APPLE_JWKS
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        keys = resp.json().get("keys") or []
    except Exception as exc:  # network down / provider outage
        raise AuthError(
            "تعذّر التحقق من الدخول الاجتماعي الآن — حاول مجددًا"
            if provider == "google" else
            "تعذّر التحقق من دخول Apple الآن — حاول مجددًا",
            502,
        ) from exc
    if not keys:
        raise AuthError("مفاتيح التحقق غير متاحة", 502)
    _jwks_cache[provider] = (now, keys)
    return keys


def _verify_id_token(provider: str, token: str, audience: str,
                     issuers: tuple[str, ...]) -> dict[str, Any]:
    """Cryptographic verification: signature, exp, iss, aud."""
    try:
        headers = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("توكن دخول غير صالح", 400) from exc
    kid = headers.get("kid")
    if not kid:
        raise AuthError("توكن دخول غير صالح", 400)
    key = next((k for k in _fetch_jwks(provider) if k.get("kid") == kid), None)
    if key is None:
        # key rotation: refresh the cache once before giving up
        _jwks_cache.pop(provider, None)
        key = next((k for k in _fetch_jwks(provider) if k.get("kid") == kid), None)
    if key is None:
        raise AuthError("توكن دخول غير صالح", 400)
    try:
        # PyJWT ≥2.15 needs an algorithm key object, not a raw JWK dict
        claims = jwt.decode(
            token,
            key=jwt.PyJWK(key).key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuers,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.InvalidAudienceError as exc:
        raise AuthError("توكن الدخول لا يخص هذا التطبيق", 400) from exc
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(
            "انتهت صلاحية جلسة المزوّد — أعد تسجيل الدخول", 401
        ) from exc
    except jwt.PyJWTError as exc:
        raise AuthError("توكن دخول غير صالح", 400) from exc
    return claims


def verify_google_id_token(credential: str) -> dict[str, Any]:
    """Verify a Google Identity Services ID token → {email, name, sub}."""
    claims = _verify_id_token(
        "google", credential, _provider_config("google"), _GOOGLE_ISSUERS
    )
    email = (claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified", False):
        raise AuthError(
            "حساب Google غير مؤكد البريد — استخدم بريدًا مُتحقّقًا منه", 400
        )
    return {
        "email": email,
        "name": (claims.get("name") or "").strip(),
        "sub": claims.get("sub") or "",
    }


def verify_apple_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Sign-in-with-Apple ID token → {email, name, sub}.

    Apple sends the user's name ONLY on the very first authorization; later
    logins carry the email alone, so name is optional here.
    """
    claims = _verify_id_token(
        "apple", id_token, _provider_config("apple"), (_APPLE_ISSUER,)
    )
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise AuthError(
            "لم يُرسل Apple بريدًا لهذا الحساب", 400
        )
    name = ""
    if isinstance(claims.get("name"), dict):
        name_parts = claims["name"]
        name = " ".join(
            p for p in (name_parts.get("firstName"), name_parts.get("lastName"))
            if p
        ).strip()
    return {"email": email, "name": name, "sub": claims.get("sub") or ""}
