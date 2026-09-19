from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services.user_service import (
    authenticate_web_user,
    create_web_user,
    delete_web_user,
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


async def test_delete_web_user_protects_current_and_last_super_admin() -> None:
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        admin = await create_web_user(
            session,
            username='admin1',
            password='secret123',
            role='super_admin',
        )
        operator = await create_web_user(
            session,
            username='operator1',
            password='secret123',
            role='operator',
        )
        try:
            await delete_web_user(session, admin.id, current_username='admin1')
        except ValueError as exc:
            assert '当前登录用户' in str(exc)
        else:
            raise AssertionError('current user deletion should fail')

        try:
            await delete_web_user(session, admin.id, current_username='other')
        except ValueError as exc:
            assert '至少需要保留一个超级管理员' in str(exc)
        else:
            raise AssertionError('last super admin deletion should fail')

        deleted = await delete_web_user(session, operator.id)
        assert deleted.username == 'operator1'

    await engine.dispose()
