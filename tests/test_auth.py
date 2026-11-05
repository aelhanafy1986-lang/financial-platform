"""Tests for authentication: register + email code + login + subscription."""

from app.auth import AuthError, hash_password, verify_password
from app.database import User


class TestPasswordHashing:
    def test_roundtrip(self):
        stored = hash_password("secret123")
        assert verify_password("secret123", stored)
        assert not verify_password("wrong", stored)


class TestRegisterFlow:
    def _register(self, client, username="alice", email="a@x.com"):
        return client.post(
            "/api/auth/register",
            json={
                "full_name": "Alice",
                "email": email,
                "country": "Yemen",
                "username": username,
                "password": "secret123",
                "lang": "ar",
            },
        )

    def test_register_returns_dev_code(self, client):
        res = self._register(client)
        assert res.status_code == 200
        body = res.json()
        assert body["email_sent"] is False  # no SMTP in tests
        assert body["dev_code"] and len(body["dev_code"]) == 6
        assert body["user_id"] > 0

    def test_duplicate_email_and_username_rejected(self, client):
        assert self._register(client).status_code == 200
        res2 = self._register(client, email="other@x.com")
        assert res2.status_code == 409
        res3 = self._register(client, username="bob")
        assert res3.status_code == 409

    def test_activate_and_login(self, client):
        body = self._register(client).json()
        code = body["dev_code"]
        res = client.post(
            "/api/auth/activate",
            json={"email": "a@x.com", "code": code, "lang": "ar"},
        )
        assert res.status_code == 200
        login = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "secret123", "lang": "ar"},
        )
        assert login.status_code == 200
        payload = login.json()
        assert payload["user"]["username"] == "alice"
        assert payload["user"]["subscription"] == "free"
        assert payload["token"]
        assert payload["user"]["last_login"]

    def test_wrong_code_rejected(self, client):
        self._register(client)
        res = client.post(
            "/api/auth/activate",
            json={"email": "a@x.com", "code": "000000", "lang": "ar"},
        )
        assert res.status_code == 400

    def test_login_before_activation_403(self, client):
        self._register(client)
        res = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "secret123", "lang": "ar"},
        )
        assert res.status_code == 403


class TestQuotaLadder:
    """CMRRS quota ladder: free = ONE analysis (one-time), Pro = 5/month,
    Business = 20/month — counted per ANALYSIS and charged by /api/demo and
    /api/upload alike."""

    def _login(self, client, username, email):
        client.post(
            "/api/auth/register",
            json={
                "full_name": "Quota", "email": email, "country": "",
                "username": username, "password": "secret123", "lang": "ar",
            },
        )
        import app.database as database

        with database.SessionLocal() as db:
            user = db.query(User).filter(User.username == username).first()
            user.status = "active"
            db.commit()
        return client.post(
            "/api/auth/login",
            json={"username": username, "password": "secret123", "lang": "ar"},
        ).json()

    def _activate(self, client, headers, plan):
        return client.post(
            "/api/subscription/activate",
            json={"card_number": "4242 4242 4242 4242", "holder": "Q",
                  "expiry": "12/28", "cvv": "123", "plan": plan, "lang": "ar"},
            headers=headers,
        )

    def test_free_gets_exactly_one_analysis(self, client):
        session = self._login(client, "qfree", "qf@x.com")
        h = {"Authorization": f"Bearer {session['token']}"}
        first = client.post("/api/demo", headers=h)
        assert first.status_code == 200
        second = client.post("/api/demo", headers=h)
        assert second.status_code == 402
        assert "حصة التحليل" in second.json()["detail"]

    def test_anonymous_demo_unchanged(self, client):
        assert client.post("/api/demo").status_code == 200

    def test_pro_quota_is_five(self, client):
        session = self._login(client, "qpro", "qp@x.com")
        h = {"Authorization": f"Bearer {session['token']}"}
        assert self._activate(client, h, "pro").status_code == 200
        for i in range(5):
            assert client.post("/api/demo", headers=h).status_code == 200, f"#{i}"
        assert client.post("/api/demo", headers=h).status_code == 402

    def test_business_quota_is_twenty(self, client):
        session = self._login(client, "qbiz", "qb@x.com")
        h = {"Authorization": f"Bearer {session['token']}"}
        assert self._activate(client, h, "business").status_code == 200
        for i in range(20):
            assert client.post("/api/demo", headers=h).status_code == 200, f"#{i}"
        assert client.post("/api/demo", headers=h).status_code == 402


class TestSocialAuth:
    """Google/Apple sign-up & sign-in — simulated locally: the provider
    email is trusted, accounts are created ACTIVE and passwordless."""

    def _social(self, client, email, provider="google", full_name=None):
        return client.post(
            "/api/auth/social",
            json={"provider": provider, "email": email,
                  "full_name": full_name, "lang": "ar"},
        )

    def test_social_signup_creates_active_passwordless_account(self, client):
        res = self._social(client, "soc.guy@gmail.com", full_name="سوشيال")
        assert res.status_code == 200
        body = res.json()
        assert body["token"]
        assert body["user"]["subscription"] == "free"
        assert body["user"]["email"] == "soc.guy@gmail.com"
        me = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"}
        ).json()
        assert me["status"] == "active"
        assert me["provider"] == "google"
        # password login is closed for social-only accounts
        pw = client.post(
            "/api/auth/login",
            json={"username": me["username"], "password": "secret123", "lang": "ar"},
        )
        assert pw.status_code == 401

    def test_social_login_returns_same_account(self, client):
        first = self._social(client, "same@x.com", provider="google").json()
        second = self._social(client, "same@x.com", provider="apple").json()
        assert second["user"]["id"] == first["user"]["id"]
        assert second["user"]["email"] == "same@x.com"

    def test_social_activates_pending_account(self, client):
        client.post(
            "/api/auth/register",
            json={"full_name": "P", "email": "pending@x.com", "country": "",
                  "username": "pnd", "password": "secret123", "lang": "ar"},
        )
        res = self._social(client, "pending@x.com", provider="apple")
        assert res.status_code == 200
        me = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {res.json()['token']}"},
        ).json()
        assert me["status"] == "active"

    def test_social_invalid_provider_and_email_rejected(self, client):
        bad = self._social(client, "a@x.com", provider="twitter")
        assert bad.status_code == 400
        badmail = self._social(client, "not-an-email", provider="google")
        assert badmail.status_code == 400


class TestPaywall:
    def _login(self, client):
        client.post(
            "/api/auth/register",
            json={
                "full_name": "Bob", "email": "b@x.com", "country": "",
                "username": "bob", "password": "secret123", "lang": "ar",
            },
        )
        import app.database as database

        with database.SessionLocal() as db:
            user = db.query(User).filter(User.username == "bob").first()
            user.status = "active"
            db.commit()
        return client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "secret123", "lang": "ar"},
        ).json()

    def test_download_requires_login(self, client):
        client.post("/api/demo")
        res = client.get("/api/analyses/1/report?lang=ar")
        assert res.status_code == 401

    def test_download_requires_paid_subscription(self, client):
        session = self._login(client)
        client.post("/api/demo")
        token = session["token"]
        res = client.get(
            "/api/analyses/1/report?lang=ar",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 402

    def test_card_activation_unlocks_downloads(self, client):
        session = self._login(client)
        token = session["token"]
        pay = client.post(
            "/api/subscription/activate",
            json={
                "card_number": "4242 4242 4242 4242",
                "holder": "Bob",
                "expiry": "12/28",
                "cvv": "123",
                "lang": "ar",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pay.status_code == 200
        assert pay.json()["subscription"] == "paid"
        assert pay.json()["masked_card"].endswith("4242")

        client.post("/api/demo")
        res = client.get(
            "/api/analyses/1/export?lang=ar",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    def test_bad_card_rejected(self, client):
        session = self._login(client)
        res = client.post(
            "/api/subscription/activate",
            json={
                "card_number": "abc",
                "holder": "Bob",
                "expiry": "12/28",
                "cvv": "123",
                "lang": "ar",
            },
            headers={"Authorization": f"Bearer {session['token']}"},
        )
        assert res.status_code == 400

    def test_query_param_token_accepted(self, client):
        session = self._login(client)
        client.post("/api/demo")
        client.post(
            "/api/subscription/activate",
            json={
                "card_number": "4242424242424242",
                "holder": "Bob",
                "expiry": "12/28",
                "cvv": "123",
                "lang": "ar",
            },
            headers={"Authorization": f"Bearer {session['token']}"},
        )
        from urllib.parse import quote

        res = client.get(
            f"/api/analyses/1/export?lang=ar&auth_token={quote('Bearer ' + session['token'])}"
        )
        assert res.status_code == 200
