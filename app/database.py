"""Async database initialization and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
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


async def _migrate_delivery_jobs(connection: AsyncConnection) -> None:
    """Add album columns to databases created by older MVP versions."""
    columns = await connection.run_sync(
        lambda sync_connection: {
            column["name"]
            for column in inspect(sync_connection).get_columns("delivery_jobs")
        }
    )
    if "source_message_ids" not in columns:
        await connection.execute(
            text("ALTER TABLE delivery_jobs ADD COLUMN source_message_ids TEXT")
        )
    if "media_group_id" not in columns:
        await connection.execute(
            text("ALTER TABLE delivery_jobs ADD COLUMN media_group_id BIGINT")
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_delivery_jobs_media_group_id "
                "ON delivery_jobs (media_group_id)"
            )
        )


async def _migrate_display_names(connection: AsyncConnection) -> None:
    """Add custom display names to older source and target tables."""
    for table_name in ("sources", "targets"):
        columns = await connection.run_sync(
            lambda sync_connection, table=table_name: {
                column["name"]
                for column in inspect(sync_connection).get_columns(table)
            }
        )
        if "display_name" not in columns:
            await connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN display_name VARCHAR(255)")
            )


async def _migrate_source_rules(connection: AsyncConnection) -> None:
    """Add sender filtering columns to databases created by older MVP versions."""
    columns = await connection.run_sync(
        lambda sync_connection: {
            column["name"]
            for column in inspect(sync_connection).get_columns("source_rules")
        }
    )
    if "post_only" not in columns:
        await connection.execute(
            text(
                "ALTER TABLE source_rules "
                "ADD COLUMN post_only BOOLEAN NOT NULL DEFAULT 0"
            )
        )
    if "admin_only" not in columns:
        await connection.execute(
            text(
                "ALTER TABLE source_rules "
                "ADD COLUMN admin_only BOOLEAN NOT NULL DEFAULT 0"
            )
        )
    if "sender_whitelist" not in columns:
        await connection.execute(
            text(
                "ALTER TABLE source_rules "
                "ADD COLUMN sender_whitelist TEXT NOT NULL DEFAULT '[]'"
            )
        )
    if "sender_blacklist" not in columns:
        await connection.execute(
            text(
                "ALTER TABLE source_rules "
                "ADD COLUMN sender_blacklist TEXT NOT NULL DEFAULT '[]'"
            )
        )


async def init_database(config: AppConfig) -> None:
    """Create the database schema for the MVP."""
    engine = get_engine(config)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _migrate_delivery_jobs(connection)
        await _migrate_source_rules(connection)
        await _migrate_display_names(connection)


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
