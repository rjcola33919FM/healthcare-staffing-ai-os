"""
Database engine — async SQLAlchemy setup with connection pooling.
Provides get_db() FastAPI dependency and create_all() for startup.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .models import Base

logger = logging.getLogger(__name__)

# Build from env or settings
def _db_url() -> str:
    """Prefer DATABASE_URL env var; fall back to component parts."""
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # asyncpg requires postgresql+asyncpg:// scheme
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    user     = os.environ.get("POSTGRES_USER", "staffing_user")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host     = os.environ.get("POSTGRES_HOST", "localhost")
    port     = os.environ.get("POSTGRES_PORT", "5432")
    dbname   = os.environ.get("POSTGRES_DB", "healthcare_staffing")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = _db_url()
        _engine = create_async_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
        )
        logger.info("[DB] Engine created: %s", url.split("@")[-1])  # hide credentials
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def create_all() -> None:
    """Create all tables if they don't exist. Call once at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[DB] Schema synced (create_all).")


async def dispose() -> None:
    """Dispose connection pool — call at shutdown."""
    if _engine:
        await _engine.dispose()
        logger.info("[DB] Engine disposed.")


# ── FastAPI dependency ─────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields an async database session.
    Usage: session: AsyncSession = Depends(get_db)
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
