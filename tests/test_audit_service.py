from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services.audit_service import list_audit_logs, write_audit_log


async def test_audit_log_write_and_list() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await write_audit_log(
            session,
            username="admin",
            method="POST",
            path="/api/pause",
            status_code=200,
            ip_address="127.0.0.1",
        )
        logs = await list_audit_logs(session)

    assert len(logs) == 1
    assert logs[0].username == "admin"
    assert logs[0].path == "/api/pause"
    await engine.dispose()
