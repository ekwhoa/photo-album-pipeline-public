"""
Database setup for the FastAPI backend.
Provides SQLAlchemy engine/session utilities for SQLite.
"""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


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


def get_session():
    """FastAPI dependency-style session generator."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
