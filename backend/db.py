"""
Database setup for the FastAPI backend.
Provides SQLAlchemy engine/session utilities for SQLite.
"""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import text


DB_PATH = Path(__file__).resolve().parent / "app.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False allows usage across FastAPI threads
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    """Create tables if they don't exist."""
    from repositories import models  # noqa: F401  Ensures models are registered

    Base.metadata.create_all(bind=engine)
    _ensure_photobook_spec_column()


def get_session():
    """FastAPI dependency-style session generator."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _ensure_photobook_spec_column() -> None:
    """
    Lightweight schema bump for SQLite: add photobook_spec_v1 column if missing.
    Avoids full migration tooling while keeping existing data.
    """
    try:
        with engine.begin() as conn:
            cols = conn.execute(text("PRAGMA table_info(books)")).fetchall()
            col_names = {row[1] for row in cols}
            if "photobook_spec_v1" not in col_names:
                conn.execute(text("ALTER TABLE books ADD COLUMN photobook_spec_v1 JSON"))
    except Exception:
        # Best-effort; if this fails we still want the app to start, but API will continue to error.
        pass
