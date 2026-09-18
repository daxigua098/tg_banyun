from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services.session_service import (
    create_web_session,
    is_web_session_valid,
    revoke_web_session,
)


async def test_web_session_can_be_revoked() -> None:
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    token = 'session-token'
    expires_at = int(time.time()) + 3600
    async with factory() as session:
        await create_web_session(
            session,
            token=token,
            username='admin',
            role='super_admin',
            expires_at=expires_at,
        )
        assert await is_web_session_valid(session, token) is True

        await revoke_web_session(session, token)
        assert await is_web_session_valid(session, token) is False

    await engine.dispose()
