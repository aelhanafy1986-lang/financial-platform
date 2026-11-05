"""Tests for the built-in admin account and admin endpoints."""

from app.auth import ADMIN_DEFAULT_PASSWORD, ADMIN_USERNAME


class TestAdminAccount:
    def test_builtin_admin_login(self, client):
        res = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_DEFAULT_PASSWORD, "lang": "ar"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["user"]["is_admin"] is True
        assert body["user"]["subscription"] == "paid"
        assert body["token"]

    def test_regular_user_is_not_admin(self, client):
        # `tester` is created (active, free) by the client fixture.
        res = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "secret123", "lang": "ar"},
        )
        assert res.json()["user"]["is_admin"] is False


class TestAdminEndpoints:
    def _admin_headers(self, client):
        token = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_DEFAULT_PASSWORD, "lang": "ar"},
        ).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_users_list_requires_admin(self, client):
        assert client.get("/api/admin/users").status_code == 401
        # logged-in non-admin is rejected with 403
        login = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "secret123", "lang": "ar"},
        ).json()
        res = client.get(
            "/api/admin/users", headers={"Authorization": f"Bearer {login['token']}"}
        )
        assert res.status_code == 403

    def test_admin_lists_users(self, client):
        res = client.get("/api/admin/users", headers=self._admin_headers(client))
        assert res.status_code == 200
        users = res.json()["users"]
        names = {u["username"] for u in users}
        assert ADMIN_USERNAME in names and "tester" in names

    def test_grant_and_revoke_subscription(self, client):
        headers = self._admin_headers(client)
        target = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "secret123", "lang": "ar"},
        ).json()["user"]["id"]

        grant = client.patch(
            f"/api/admin/users/{target}/subscription",
            json={"subscription": "paid", "plan": "business"},
            headers=headers,
        )
        assert grant.status_code == 200
        assert grant.json()["subscription"] == "paid"
        assert grant.json()["plan"] == "business"

        revoke = client.patch(
            f"/api/admin/users/{target}/subscription",
            json={"subscription": "free"},
            headers=headers,
        )
        assert revoke.status_code == 200
        assert revoke.json()["subscription"] == "free"

    def test_disable_and_enable_user(self, client):
        headers = self._admin_headers(client)
        target = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "secret123", "lang": "ar"},
        ).json()["user"]["id"]

        off = client.patch(
            f"/api/admin/users/{target}/status",
            json={"active": False},
            headers=headers,
        )
        assert off.status_code == 200
        assert off.json()["status"] == "disabled"

        # disabled user cannot log in
        blocked = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "secret123", "lang": "ar"},
        )
        assert blocked.status_code == 403

        on = client.patch(
            f"/api/admin/users/{target}/status",
            json={"active": True},
            headers=headers,
        )
        assert on.status_code == 200
        assert on.json()["status"] == "active"

    def test_admin_account_protected_from_disable(self, client):
        admin_id = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_DEFAULT_PASSWORD, "lang": "ar"},
        ).json()["user"]["id"]
        res = client.patch(
            f"/api/admin/users/{admin_id}/status",
            json={"active": False},
            headers=self._admin_headers(client),
        )
        assert res.status_code == 400
