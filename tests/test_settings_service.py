from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import SyncBehaviorConfig
from app.models import Base
from app.services.settings_service import get_sync_behavior, set_sync_behavior


async def test_sync_behavior_settings_round_trip() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        defaults = SyncBehaviorConfig()
        assert await get_sync_behavior(session, defaults) == defaults
        saved = await set_sync_behavior(
            session,
            SyncBehaviorConfig(edits=True, deletes=True),
        )
        loaded = await get_sync_behavior(session, defaults)

    assert saved.edits is True
    assert saved.deletes is True
    assert loaded == saved
    await engine.dispose()
