"""Shared pytest fixtures for the API tests."""

import os
import sys
from pathlib import Path

# Lower PBKDF2 work factor for the whole test session (hashing dominates
# fixture wall time on loaded machines).
os.environ.setdefault("FIN_TEST_MODE", "1")

import pytest

# pytest 9 creates a cosmetic "-current" symlink next to every numbered tmp
# directory it makes. On this machine (project living under Downloads), the
# symlink_to call stalls for tens of seconds per tmp dir — an AV/filter-driver
# interaction — even though pytest swallows the eventual failure. The link is
# best-effort eye-candy only (see _force_symlink's docstring), so disable it
# for the whole test session; tmp_path itself is unaffected.
import _pytest.pathlib as _pytest_pathlib

_pytest_pathlib._force_symlink = lambda *args, **kwargs: None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh app instance with database/uploads/reports redirected to tmp_path."""
    from fastapi.testclient import TestClient

    import app.database as database
    import app.main as main_module

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db", raising=False)
    monkeypatch.setattr(main_module, "UPLOADS", tmp_path / "uploads", raising=False)
    monkeypatch.setattr(main_module, "REPORTS", tmp_path / "reports", raising=False)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "reports").mkdir()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    database.engine = engine
    database.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(main_module, "SessionLocal", database.SessionLocal, raising=False)
    database.Base.metadata.create_all(engine)

    # main.py's module-level ensure_admin() ran against the real DB at import
    # time — create the admin account in THIS test database too.
    from app.auth import ensure_admin
    ensure_admin()

    c = TestClient(main_module.app)

    # Register + activate + subscribe a test user, then expose the bearer
    # token as `c.auth_headers` — downloads are subscription-gated.
    c.post(
        "/api/auth/register",
        json={
            "full_name": "Test User", "email": "t@x.com", "country": "",
            "username": "tester", "password": "secret123", "lang": "ar",
        },
    )
    with database.SessionLocal() as db:
        user = db.query(database.User).filter(database.User.username == "tester").first()
        user.status = "active"
        db.commit()
    login = c.post(
        "/api/auth/login",
        json={"username": "tester", "password": "secret123", "lang": "ar"},
    ).json()
    c.auth_token = login["token"]
    c.auth_headers = {"Authorization": f"Bearer {c.auth_token}"}
    c.post(
        "/api/subscription/activate",
        json={
            "card_number": "4242424242424242", "holder": "Test User",
            "expiry": "12/28", "cvv": "123", "lang": "ar",
        },
        headers=c.auth_headers,
    )

    # Admin login for admin-only endpoints (stats, user management).
    c.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Admin@2026", "lang": "ar"},
    )
    with database.SessionLocal() as db:
        from app.auth import ADMIN_USERNAME

        admin = (
            db.query(database.User)
            .filter(database.User.username == ADMIN_USERNAME)
            .first()
        )
        admin_token = (
            db.query(database.Session)
            .filter(database.Session.user_id == admin.id)
            .order_by(database.Session.created_at.desc())
            .first()
        )
    # The Session model lives in app.database; grab the newest admin session.
    c.admin_token = admin_token.token if admin_token else None
    c.admin_headers = {"Authorization": f"Bearer {c.admin_token}"}

    return c
