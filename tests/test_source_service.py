from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services import source_service


class FakeClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def get_entity(self, value: str) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return SimpleNamespace(id=999, value=value)


async def _build_factory() -> tuple[async_sessionmaker, object]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory, engine


async def test_add_target_accepts_joined_private_invite(monkeypatch) -> None:
    session_factory, engine = await _build_factory()
    monkeypatch.setattr(
        source_service,
        "_entity_info",
        lambda entity: (999, "Private Target", None, True),
    )

    async with session_factory() as session:
        target = await source_service.add_target(
            session,
            FakeClient(),
            "https://t.me/+HpdR8GSmvThlZDc1",
        )

    assert target.tg_id == 999
    assert target.title == "Private Target"
    await engine.dispose()


async def test_add_target_rejects_unjoined_private_invite(monkeypatch) -> None:
    session_factory, engine = await _build_factory()
    monkeypatch.setattr(
        source_service,
        "_entity_info",
        lambda entity: (999, "Private Target", None, True),
    )

    with pytest.raises(ValueError, match="could not resolve"):
        async with session_factory() as session:
            await source_service.add_target(
                session,
                FakeClient(error=ValueError("not found")),
                "https://t.me/+HpdR8GSmvThlZDc1",
            )

    await engine.dispose()
