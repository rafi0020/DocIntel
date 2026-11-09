from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(_settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# RQ forks a child process per job; never share pooled connections across a fork.
os.register_at_fork(after_in_child=lambda: engine.dispose(close=False))


def init_db() -> None:
    """Create the pgvector extension and all tables (idempotent)."""
    from . import models  # noqa: F401  (register mappers)

    # API and worker containers start together: serialise schema creation.
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(724001)"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        Base.metadata.create_all(conn)
        # create_all never alters existing tables: add columns introduced after the first release.
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by_id uuid REFERENCES users(id) ON DELETE SET NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_uploaded_by_id ON documents (uploaded_by_id)"))


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
