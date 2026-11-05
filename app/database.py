from pathlib import Path

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "financial.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))
    # Optional user-defined name shown instead of the filename.
    display_name: Mapped[str | None] = mapped_column(String(200))
    # Free-text user notes that can be added/edited after the analysis.
    notes: Mapped[str | None] = mapped_column(Text)
    # Server-side path of the originally uploaded file (for re-download).
    original_path: Mapped[str | None] = mapped_column(String(512))
    # Full financial statements built from an attached trial balance (JSON).
    statements_json: Mapped[str | None] = mapped_column(Text)
    # True when a trial balance was attached to this analysis.
    has_tb: Mapped[bool] = mapped_column(Boolean, default=False)


class SiteStat(Base):
    """Single-row counter table for the public site statistics page."""

    __tablename__ = "site_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Platform activity counters.
    visits: Mapped[int] = mapped_column(Integer, default=0)
    analyses_count: Mapped[int] = mapped_column(Integer, default=0)
    statements_count: Mapped[int] = mapped_column(Integer, default=0)
    # ISO timestamps.
    last_visit: Mapped[str | None] = mapped_column(String(32))
    since: Mapped[str] = mapped_column(String(32))


class User(Base):
    """Registered platform user (email-code activation, card subscription)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    country: Mapped[str | None] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # pending | active
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Email verification code (sent to the user's inbox).
    activation_code: Mapped[str | None] = mapped_column(String(10))
    # paid | free
    subscription: Mapped[str] = mapped_column(String(20), default="free")
    # google | apple — social sign-in origin (None = password account)
    provider: Mapped[str | None] = mapped_column(String(20))
    # platform administrator (manages users/plans, sees all data)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # plan key: monthly | yearly | business | firm (null = legacy paid)
    plan: Mapped[str | None] = mapped_column(String(30))
    # ISO date when the paid plan expires (yearly/business/firm renew it).
    plan_expires: Mapped[str | None] = mapped_column(String(32))
    # uploads used this billing period (quota enforcement for plans)
    uploads_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))
    last_login: Mapped[str | None] = mapped_column(String(32))


class Session(Base):
    """Simple bearer-token session per login."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(32))


class Payment(Base):
    """One (simulated) subscription charge — feeds the «سجل المدفوعات»
    screen: every successful /api/subscription/activate writes a row here
    with the masked card, the chosen plan and its price at charge time."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    plan: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    # USD, captured from PLANS at activation time
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    masked_card: Mapped[str] = mapped_column(String(30))
    # paid | refunded (kept for future refund flows)
    status: Mapped[str] = mapped_column(String(20), default="paid")
    invoice_no: Mapped[str] = mapped_column(String(30))
    paid_at: Mapped[str] = mapped_column(String(32))


class AssistantMessage(Base):
    """One turn of the «المساعد الذكي» chat, persisted per user so the
    conversation resumes after closing/reloading the page. Order = id."""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # user | assistant
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))


def get_site_stats(db) -> SiteStat:
    """Return the singleton counter row, creating it on first use."""
    row = db.query(SiteStat).first()
    if not row:
        row = SiteStat(
            visits=0,
            analyses_count=0,
            statements_count=0,
            last_visit=None,
            since=datetime.now(timezone.utc).isoformat(),
        )
        db.add(row)
        db.commit()
    return row


def bump_visits() -> None:
    """Count one site visit (called by the frontend on first load)."""
    with SessionLocal() as db:
        row = get_site_stats(db)
        row.visits = (row.visits or 0) + 1
        row.last_visit = datetime.now(timezone.utc).isoformat()
        db.commit()


def bump_analyses() -> None:
    with SessionLocal() as db:
        row = get_site_stats(db)
        row.analyses_count = (row.analyses_count or 0) + 1
        db.commit()


def bump_statements() -> None:
    with SessionLocal() as db:
        row = get_site_stats(db)
        row.statements_count = (row.statements_count or 0) + 1
        db.commit()


# Columns added after the first release: ALTER TABLE for databases created
# before they existed. Safe to run on every start-up.
_MIGRATIONS = [
    ("display_name", "ALTER TABLE analyses ADD COLUMN display_name VARCHAR(200)"),
    ("notes", "ALTER TABLE analyses ADD COLUMN notes TEXT"),
    ("original_path", "ALTER TABLE analyses ADD COLUMN original_path VARCHAR(512)"),
    ("statements_json", "ALTER TABLE analyses ADD COLUMN statements_json TEXT"),
    ("has_tb", "ALTER TABLE analyses ADD COLUMN has_tb BOOLEAN DEFAULT 0"),
    ("is_admin", "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"),
    ("plan", "ALTER TABLE users ADD COLUMN plan VARCHAR(30)"),
    ("plan_expires", "ALTER TABLE users ADD COLUMN plan_expires VARCHAR(32)"),
    ("uploads_used", "ALTER TABLE users ADD COLUMN uploads_used INTEGER DEFAULT 0"),
    ("provider", "ALTER TABLE users ADD COLUMN provider VARCHAR(20)"),
    ("amount", "ALTER TABLE payments ADD COLUMN amount FLOAT DEFAULT 0"),
    ("currency", "ALTER TABLE payments ADD COLUMN currency VARCHAR(8) DEFAULT 'USD'"),
    ("masked_card", "ALTER TABLE payments ADD COLUMN masked_card VARCHAR(30)"),
    ("status", "ALTER TABLE payments ADD COLUMN status VARCHAR(20) DEFAULT 'paid'"),
    ("invoice_no", "ALTER TABLE payments ADD COLUMN invoice_no VARCHAR(30)"),
]


def _migrate(conn) -> None:
    from sqlalchemy import inspect, text

    for table in ("analyses", "users"):
        existing = {c["name"] for c in inspect(conn).get_columns(table)}
        for column, ddl in _MIGRATIONS:
            if ddl.startswith(f"ALTER TABLE {table}") and column not in existing:
                conn.execute(text(ddl))


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        _migrate(conn)
    # Ensure the singleton counter row exists.
    with SessionLocal() as db:
        get_site_stats(db)


def _sync_counters() -> None:
    """Align analyses/statements counters with the actual rows once per
    startup, so pre-existing data is reflected (visits are never reset)."""
    with SessionLocal() as db:
        row = get_site_stats(db)
        row.analyses_count = db.query(Analysis).count()
        row.statements_count = (
            db.query(Analysis).filter(Analysis.has_tb.is_(True)).count()
        )
        db.commit()
