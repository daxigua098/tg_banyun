from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services.user_service import (
    authenticate_web_user,
    create_web_user,
    get_web_user_by_username,
    update_web_user,
)


async def test_web_user_create_and_authenticate() -> None:
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        user = await create_web_user(
            session,
            username='operator1',
            password='secret123',
            role='operator',
        )
        assert authenticate_web_user(user, 'secret123') is True
        assert authenticate_web_user(user, 'wrong') is False

        await update_web_user(session, user.id, enabled=False)
        loaded = await get_web_user_by_username(session, 'operator1')
        assert loaded is not None
        assert authenticate_web_user(loaded, 'secret123') is False

    await engine.dispose()
