"""Async database initialization and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import PROJECT_ROOT, AppConfig
from app.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_parent(url: str) -> None:
    """Create the parent directory for a relative SQLite database file."""
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return

    raw_path = url.removeprefix(prefix)
    if raw_path == ":memory:" or raw_path.startswith("file:"):
        return

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(config: AppConfig | None = None) -> AsyncEngine:
    """Return the process-wide database engine."""
    global _engine
    if _engine is None:
        if config is None:
            raise RuntimeError("Database engine is not initialized.")
        _ensure_sqlite_parent(config.database.url)
        _engine = create_async_engine(
            config.database.url,
            echo=config.database.echo,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory(config: AppConfig | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(config)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def init_database(config: AppConfig) -> None:
    """Create the database schema for the MVP."""
    engine = get_engine(config)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield an async database session with rollback-on-error behavior."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_database() -> None:
    """Dispose the database engine, mainly for tests and shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
