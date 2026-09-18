from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Route, Source, Target
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

async def test_add_source_joins_private_invite(monkeypatch) -> None:
    session_factory, engine = await _build_factory()
    monkeypatch.setattr(
        source_service,
        "_entity_info",
        lambda entity: (888, "Private Source", None, True),
    )

    class JoinClient(FakeClient):
        async def __call__(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(chats=[SimpleNamespace(id=888)])

    async with session_factory() as session:
        source = await source_service.add_source(
            session,
            JoinClient(),
            "https://t.me/+HpdR8GSmvThlZDc1",
            join=True,
        )

    assert source.tg_id == 888
    assert source.title == "Private Source"
    await engine.dispose()


async def test_add_routes_bulk_builds_cartesian_pairs_and_skips_duplicates() -> None:
    session_factory, engine = await _build_factory()
    async with session_factory() as session:
        sources = [
            Source(raw_input="@one", normalized_key="username:one", tg_id=1, title="One"),
            Source(raw_input="@two", normalized_key="username:two", tg_id=2, title="Two"),
        ]
        targets = [
            Target(raw_input="@x", normalized_key="username:x", tg_id=11, title="X"),
            Target(raw_input="@y", normalized_key="username:y", tg_id=12, title="Y"),
        ]
        session.add_all([*sources, *targets])
        await session.commit()
        source_ids = [source.id for source in sources]
        target_ids = [target.id for target in targets]
        session.add(Route(source_id=source_ids[0], target_id=target_ids[0]))
        await session.commit()

        created, skipped = await source_service.add_routes_bulk(
            session,
            source_ids,
            target_ids,
        )
        assert len(created) == 3
        assert sorted(skipped) == [(source_ids[0], target_ids[0])]

        created_again, skipped_again = await source_service.add_routes_bulk(
            session,
            source_ids,
            target_ids,
        )

    assert created_again == []
    assert sorted(skipped_again) == [
        (source_ids[0], target_ids[0]),
        (source_ids[0], target_ids[1]),
        (source_ids[1], target_ids[0]),
        (source_ids[1], target_ids[1]),
    ]
    await engine.dispose()
