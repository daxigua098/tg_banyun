from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import AppConfig, TransferConfig
from app.core.transfer import SequentialTransferService
from app.models import Base, DeliveryJob, Route, Source, Target


class FakeTelegramClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def forward_messages(
        self,
        *,
        entity: int,
        messages: int,
        from_peer: int,
        drop_author: bool,
    ) -> SimpleNamespace:
        self.calls.append((int(entity), int(messages)))
        return SimpleNamespace(id=10_000 + len(self.calls))


async def _build_factory() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory, engine


async def test_one_source_delivers_to_targets_in_order() -> None:
    session_factory, engine = await _build_factory()
    fake_client = FakeTelegramClient()
    config = AppConfig(transfer=TransferConfig(delay_seconds=0))

    async with session_factory() as session:
        source = Source(
            raw_input="@source",
            normalized_key="username:source",
            tg_id=100,
            title="Source",
        )
        target_one = Target(
            raw_input="@target_one",
            normalized_key="username:target_one",
            tg_id=201,
            title="Target 1",
        )
        target_two = Target(
            raw_input="@target_two",
            normalized_key="username:target_two",
            tg_id=202,
            title="Target 2",
        )
        session.add_all([source, target_one, target_two])
        await session.commit()
        session.add_all(
            [
                Route(source_id=source.id, target_id=target_one.id),
                Route(source_id=source.id, target_id=target_two.id),
            ]
        )
        await session.commit()
        source_id = source.id

    service = SequentialTransferService(fake_client, session_factory, config)
    job_ids = await service.enqueue_message(source_id, 77)
    processed = await service.process_pending()

    assert len(job_ids) == 2
    assert processed == 2
    assert fake_client.calls == [(201, 77), (202, 77)]

    async with session_factory() as session:
        jobs = list(await session.scalars(select(DeliveryJob).order_by(DeliveryJob.id)))
        assert [job.status for job in jobs] == ["success", "success"]

    await engine.dispose()
