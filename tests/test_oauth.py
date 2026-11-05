"""Real OAuth ID-token verification (Google / Apple).

The provider JWKS is fetched over HTTPS in production; here it is injected
with a locally generated RSA keypair so the whole cryptographic path —
signature, exp, iss, aud, kid rotation — is exercised offline.
"""

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import oauth

KID = "test-key"


def _b64u(n: int) -> str:
    return base64.urlsafe_b64encode(
        n.to_bytes((n.bit_length() + 7) // 8, "big")
    ).decode().rstrip("=")


@pytest.fixture()
def keys(monkeypatch):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nums = priv.public_key().public_numbers()
    jwk = {
        "kid": KID, "kty": "RSA", "alg": "RS256", "use": "sig",
        "n": _b64u(nums.n), "e": _b64u(nums.e),
    }
    monkeypatch.setattr(oauth, "_jwks_cache", {
        "google": (time.time(), [jwk]),
        "apple": (time.time(), [jwk]),
    })
    return priv


def _token(priv, claims, kid=KID):
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": kid})


def _google_claims(aud, email="g.user@gmail.com", verified=True, **over):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com", "aud": aud, "sub": "12345",
        "email": email, "email_verified": verified, "name": "G User",
        "exp": now + 600, "iat": now,
    }
    claims.update(over)
    return claims


class TestSocialConfig:
    def test_disabled_without_env(self, client, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("APPLE_CLIENT_ID", raising=False)
        res = client.get("/api/auth/social-config").json()
        assert res["google"] == {"enabled": False, "client_id": None}
        assert res["apple"]["enabled"] is False

    def test_enabled_with_env(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        monkeypatch.setenv("APPLE_CLIENT_ID", "com.example.web")
        res = client.get("/api/auth/social-config").json()
        assert res["google"]["enabled"] is True
        assert res["google"]["client_id"] == "my-app.apps.googleusercontent.com"
        assert res["apple"]["client_id"] == "com.example.web"


class TestGoogleVerification:
    def test_valid_credential_signs_in(self, client, keys, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        token = _token(keys, _google_claims("my-app.apps.googleusercontent.com"))
        res = client.post(
            "/api/auth/social/google",
            json={"credential": token, "lang": "ar"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["token"]
        assert body["user"]["email"] == "g.user@gmail.com"
        assert body["user"]["subscription"] == "free"

    def test_wrong_audience_rejected(self, client, keys, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        token = _token(keys, _google_claims("someone-else.apps.googleusercontent.com"))
        res = client.post("/api/auth/social/google", json={"credential": token})
        assert res.status_code == 400
        assert "لا يخص هذا التطبيق" in res.json()["detail"]

    def test_expired_token_rejected(self, client, keys, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        token = _token(keys, _google_claims(
            "my-app.apps.googleusercontent.com", exp=int(time.time()) - 100))
        res = client.post("/api/auth/social/google", json={"credential": token})
        assert res.status_code == 401

    def test_bad_signature_rejected(self, client, keys, monkeypatch):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        token = _token(other, _google_claims("my-app.apps.googleusercontent.com"))
        res = client.post("/api/auth/social/google", json={"credential": token})
        assert res.status_code == 400

    def test_unverified_email_rejected(self, client, keys, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        token = _token(keys, _google_claims(
            "my-app.apps.googleusercontent.com", verified=False))
        res = client.post("/api/auth/social/google", json={"credential": token})
        assert res.status_code == 400

    def test_garbage_token_rejected(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-app.apps.googleusercontent.com")
        res = client.post("/api/auth/social/google", json={"credential": "junk"})
        assert res.status_code == 400

    def test_unconfigured_provider_returns_503(self, client, keys, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        token = _token(keys, _google_claims("my-app.apps.googleusercontent.com"))
        res = client.post("/api/auth/social/google", json={"credential": token})
        assert res.status_code == 503


class TestAppleVerification:
    def test_valid_id_token_signs_in(self, client, keys, monkeypatch):
        monkeypatch.setenv("APPLE_CLIENT_ID", "com.example.web")
        now = int(time.time())
        token = _token(keys, {
            "iss": "https://appleid.apple.com", "aud": "com.example.web",
            "sub": "001234.abc.5678", "email": "u@privaterelay.appleid.com",
            "exp": now + 600, "iat": now,
            "name": {"firstName": "سارة", "lastName": "الأعمال"},
        })
        res = client.post("/api/auth/social/apple", json={"id_token": token})
        assert res.status_code == 200
        body = res.json()
        assert body["user"]["email"] == "u@privaterelay.appleid.com"
        # Apple's split name arrives joined through social_auth
        assert body["token"]

    def test_wrong_issuer_rejected(self, client, keys, monkeypatch):
        monkeypatch.setenv("APPLE_CLIENT_ID", "com.example.web")
        now = int(time.time())
        token = _token(keys, {
            "iss": "https://evil.example", "aud": "com.example.web",
            "sub": "x", "email": "u@privaterelay.appleid.com",
            "exp": now + 600, "iat": now,
        })
        res = client.post("/api/auth/social/apple", json={"id_token": token})
        assert res.status_code == 400

    def test_unconfigured_apple_returns_503(self, client, keys, monkeypatch):
        monkeypatch.delenv("APPLE_CLIENT_ID", raising=False)
        now = int(time.time())
        token = _token(keys, {
            "iss": "https://appleid.apple.com", "aud": "com.example.web",
            "sub": "x", "email": "u@x.com", "exp": now + 600, "iat": now,
        })
        res = client.post("/api/auth/social/apple", json={"id_token": token})
        assert res.status_code == 503
