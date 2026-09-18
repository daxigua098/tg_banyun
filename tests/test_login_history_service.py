from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services.login_history_service import list_login_history, record_login_attempt


async def test_login_history_records_success_and_failure() -> None:
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        await record_login_attempt(
            session,
            username='admin',
            ip_address='127.0.0.1',
            user_agent='test-agent',
            success=False,
            reason='bad password',
        )
        await record_login_attempt(
            session,
            username='admin',
            ip_address='127.0.0.1',
            user_agent='test-agent',
            success=True,
        )
        rows = await list_login_history(session)

    assert len(rows) == 2
    assert rows[0].success is True
    assert rows[1].reason == 'bad password'
    await engine.dispose()
