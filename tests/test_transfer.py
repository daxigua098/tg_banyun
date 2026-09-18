from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from telethon.errors import MessageIdInvalidError

from app.config import AppConfig, TransferConfig
from app.core.message_batch import MessageBatch
from app.core.transfer import SequentialTransferService
from app.models import Base, DeliveryJob, RecordTarget, Route, Source, Target


class FakeTelegramClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int | tuple[int, ...]]] = []
        self.messages: list[tuple[int, str]] = []
        self.albums: list[bool] = []

    async def send_message(self, entity: int, text: str) -> None:
        self.messages.append((int(entity), text))

    async def forward_messages(
        self,
        *,
        entity: int,
        messages: int | list[int],
        from_peer: int,
        drop_author: bool,
        as_album: bool,
    ) -> SimpleNamespace:
        message_key: int | tuple[int, ...]
        if isinstance(messages, list):
            message_key = tuple(int(item) for item in messages)
        else:
            message_key = int(messages)
        self.calls.append((int(entity), message_key))
        self.albums.append(as_album)
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

async def test_concurrent_process_pending_calls_do_not_duplicate_delivery() -> None:
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
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=201,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        session.add(Route(source_id=source.id, target_id=target.id))
        await session.commit()
        source_id = source.id

    service = SequentialTransferService(fake_client, session_factory, config)
    await service.enqueue_message(source_id, 88)

    await asyncio.gather(service.process_pending(), service.process_pending())

    assert fake_client.calls == [(201, 88)]
    await engine.dispose()


class InvalidMessageClient:
    async def forward_messages(self, **kwargs: object) -> None:
        raise MessageIdInvalidError(request=None)


async def test_invalid_source_message_is_not_retried() -> None:
    session_factory, engine = await _build_factory()
    config = AppConfig(transfer=TransferConfig(delay_seconds=0, max_attempts=5))

    async with session_factory() as session:
        source = Source(
            raw_input="@source",
            normalized_key="username:source",
            tg_id=100,
            title="Source",
        )
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=201,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        session.add(Route(source_id=source.id, target_id=target.id))
        await session.commit()
        source_id = source.id

    service = SequentialTransferService(InvalidMessageClient(), session_factory, config)
    await service.enqueue_message(source_id, 1)
    await service.process_pending()

    async with session_factory() as session:
        job = await session.scalar(select(DeliveryJob))
        assert job is not None
        assert job.status == "failed"
        assert job.attempt_count == 1
        assert job.next_retry_at is None

    await engine.dispose()


async def test_successful_delivery_sends_record_message() -> None:
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
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=201,
            title="Target",
        )
        record_target = RecordTarget(
            raw_input="@records",
            normalized_key="username:records",
            tg_id=301,
            title="Records",
        )
        session.add_all([source, target, record_target])
        await session.commit()
        session.add(Route(source_id=source.id, target_id=target.id))
        await session.commit()
        source_id = source.id

    service = SequentialTransferService(fake_client, session_factory, config)
    await service.enqueue_message(source_id, 99)
    await service.process_pending()

    assert fake_client.calls == [(201, 99)]
    assert len(fake_client.messages) == 1
    record_entity, text = fake_client.messages[0]
    assert record_entity == 301
    assert "搬运记录" in text
    assert "状态：成功" in text
    assert "源消息：99" in text

    await engine.dispose()


async def test_album_batch_is_forwarded_as_one_album() -> None:
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
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=201,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        session.add(Route(source_id=source.id, target_id=target.id))
        await session.commit()
        source_id = source.id

    service = SequentialTransferService(fake_client, session_factory, config)
    await service.enqueue_batch(
        source_id,
        MessageBatch(message_ids=(10, 11), media_group_id=555),
    )
    await service.process_pending()

    assert fake_client.calls == [(201, (10, 11))]
    assert fake_client.albums == [True]

    async with session_factory() as session:
        job = await session.scalar(select(DeliveryJob))
        assert job is not None
        assert job.source_message_id == 10
        assert job.source_message_ids == "[10, 11]"
        assert job.media_group_id == 555

    await engine.dispose()

class FakeNotifier:
    def __init__(self) -> None:
        self.failures: list[str] = []

    async def failure(self, detail: str) -> None:
        self.failures.append(detail)


async def test_permanent_delivery_failure_notifies_admin() -> None:
    session_factory, engine = await _build_factory()
    config = AppConfig(transfer=TransferConfig(delay_seconds=0, max_attempts=1))

    async with session_factory() as session:
        source = Source(
            raw_input="@source",
            normalized_key="username:source",
            tg_id=100,
            title="Source",
        )
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=201,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        session.add(Route(source_id=source.id, target_id=target.id))
        await session.commit()
        source_id = source.id

    notifier = FakeNotifier()
    service = SequentialTransferService(
        InvalidMessageClient(),
        session_factory,
        config,
        notifier=notifier,
    )
    await service.enqueue_message(source_id, 1)
    await service.process_pending()

    assert len(notifier.failures) == 1
    assert "投递永久失败" in notifier.failures[0]
    await engine.dispose()


async def test_process_pending_stops_before_next_job_when_requested() -> None:
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
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=201,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        session.add(Route(source_id=source.id, target_id=target.id))
        await session.commit()
        source_id = source.id

    service = SequentialTransferService(fake_client, session_factory, config)
    await service.enqueue_message(source_id, 1)
    await service.enqueue_message(source_id, 2)
    processed = await service.process_pending(
        should_stop=lambda: len(fake_client.calls) >= 1,
    )

    assert processed == 1
    assert fake_client.calls == [(201, 1)]
    async with session_factory() as session:
        jobs = list(
            await session.scalars(select(DeliveryJob).order_by(DeliveryJob.id.asc()))
        )
    assert [job.status for job in jobs] == ["success", "pending"]

    await engine.dispose()
