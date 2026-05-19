"""
database.py — SQLAlchemy Database Engine & Session Management
=============================================================
Sets up the SQLAlchemy connection to SQLite (or any other database
configured via DATABASE_URL). Provides:

  - Base          : Declarative base class that all ORM models inherit from
  - engine        : The SQLAlchemy engine (manages the connection pool)
  - SessionLocal  : A session factory used to create per-request DB sessions
  - get_db()      : FastAPI dependency that yields a session and closes it
  - init_database(): Called at app startup — creates tables and runs migrations

SQLite note: `check_same_thread=False` is required because FastAPI/uvicorn
can handle a request across multiple threads; SQLite's default single-thread
check would raise an error without this flag.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings


# ---------------------------------------------------------------------------
# Declarative Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    Every model (e.g. ExpenseReport, PolicyDocument) inherits from this class.
    SQLAlchemy uses Base.metadata to track all registered tables so it can
    create or migrate them in init_database().
    """
    pass


# ---------------------------------------------------------------------------
# Database Engine
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    # SQLite only: allow the same connection to be used across threads.
    # This is safe here because we use per-request sessions (see get_db).
    connect_args={"check_same_thread": False},
)

# ---------------------------------------------------------------------------
# Session Factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    autocommit=False,   # Never auto-commit — we commit explicitly after writes
    autoflush=False,    # Don't auto-flush — gives us control over when SQL runs
    bind=engine,        # Use the engine created above
)


# ---------------------------------------------------------------------------
# FastAPI DB Dependency
# ---------------------------------------------------------------------------

def get_db():
    """
    FastAPI dependency that provides a database session per request.

    Usage in a route:
        @app.get("/example")
        def my_route(db: Session = Depends(get_db)):
            ...

    The `yield` makes this a generator-based dependency. FastAPI ensures
    the `finally` block runs after the response is sent, even if an
    exception occurred, so the session is always closed — preventing
    connection leaks.
    """
    db = SessionLocal()
    try:
        yield db          # Provide the session to the route handler
    finally:
        db.close()        # Always close the session when the request is done


# ---------------------------------------------------------------------------
# Database Initialization & Migrations
# ---------------------------------------------------------------------------

def init_database():
    """
    Create all database tables and apply schema migrations.

    Called once at application startup (in main.py's @app.on_event("startup")).

    Steps:
      1. Import models so SQLAlchemy registers them with Base.metadata
         (the `# noqa` suppresses the "unused import" linter warning).
      2. Base.metadata.create_all() creates any tables that don't exist yet.
         It is idempotent — safe to call even if tables already exist.
      3. _run_migrations() adds new columns to existing tables without
         dropping any data (ALTER TABLE ... ADD COLUMN).
    """
    import models  # noqa: F401 — registers ORM classes with Base.metadata
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """
    Apply incremental schema changes to existing tables.

    SQLAlchemy's create_all() only creates missing tables — it does NOT
    add new columns to tables that already exist. This function handles
    that by running raw ALTER TABLE statements.

    Each statement is wrapped in try/except so that:
      - If the column already exists, the database raises an error which
        we silently ignore (it's safe — the column is already there).
      - If the column is new, it gets added successfully.

    This is a simple migration strategy suitable for SQLite + small teams.
    For production use, consider Alembic for proper versioned migrations.
    """
    migrations = [
        # Added in v2: allows users to specify org-specific policy caps
        "ALTER TABLE expense_reports ADD COLUMN policy_overrides_json JSON",
        # Added in v2: tracks whether manager review is pending or complete
        "ALTER TABLE expense_reports ADD COLUMN review_status VARCHAR(50)",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(__import__("sqlalchemy").text(sql))
                conn.commit()
            except Exception:
                # Column already exists — safe to ignore
                pass
