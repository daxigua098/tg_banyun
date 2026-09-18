from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import AppConfig, ContentFilterConfig, HistoryConfig, TransferConfig
from app.models import Base, Source
from app.services.history_service import HistorySyncService


class FakeHistoryClient:
    async def iter_messages(self, entity: object, **kwargs: object):
        yield SimpleNamespace(id=1, action=object(), pinned=False)
        yield SimpleNamespace(id=2, action=None, pinned=False)
        yield SimpleNamespace(id=3, action=None, pinned=True)
        yield SimpleNamespace(id=4, action=None, pinned=False)
        yield SimpleNamespace(id=5, action=None, pinned=False)


class FakeTransfer:
    def __init__(self) -> None:
        self.enqueued: list[tuple[int, tuple[int, ...]]] = []

    async def enqueue_batch(self, source_id: int, batch: object) -> list[int]:
        self.enqueued.append((source_id, batch.message_ids))
        return [len(self.enqueued)]


async def _build_factory() -> tuple[async_sessionmaker, object]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory, engine


async def test_history_skips_service_and_pinned_messages() -> None:
    session_factory, engine = await _build_factory()
    config = AppConfig(
        history=HistoryConfig(default_limit=2, skip_pinned=True),
        transfer=TransferConfig(delay_seconds=0),
    )
    transfer = FakeTransfer()

    async with session_factory() as session:
        session.add(
            Source(
                raw_input="@source",
                normalized_key="username:source",
                tg_id=100,
                title="Source",
            )
        )
        await session.commit()

    service = HistorySyncService(
        FakeHistoryClient(),  # type: ignore[arg-type]
        session_factory,
        transfer,  # type: ignore[arg-type]
        config,
    )
    inspected = await service.sync_source(1, limit=2)

    assert inspected == 2
    assert transfer.enqueued == [(1, (2,)), (1, (4,))]

    async with session_factory() as session:
        source = await session.get(Source, 1)
        assert source is not None
        assert source.last_synced_message_id == 4
        assert source.sync_status == "ready"

    await engine.dispose()

class FakeMediaHistoryClient:
    async def iter_messages(self, entity: object, **kwargs: object):
        yield SimpleNamespace(id=1, action=None, pinned=False, photo=None, video=None, media=None)
        yield SimpleNamespace(
            id=2,
            action=None,
            pinned=False,
            photo=object(),
            video=None,
            media=None,
        )
        yield SimpleNamespace(
            id=3,
            action=None,
            pinned=False,
            photo=None,
            video=object(),
            media=None,
        )
        yield SimpleNamespace(
            id=4,
            action=object(),
            pinned=False,
            photo=None,
            video=None,
            media=None,
        )


async def test_history_media_only_mode_skips_text() -> None:
    session_factory, engine = await _build_factory()
    config = AppConfig(
        history=HistoryConfig(default_limit=2, skip_pinned=True),
        content_filter=ContentFilterConfig(media_only=True),
        transfer=TransferConfig(delay_seconds=0),
    )
    transfer = FakeTransfer()

    async with session_factory() as session:
        session.add(
            Source(
                raw_input="@media_source",
                normalized_key="username:media_source",
                tg_id=101,
                title="Media Source",
            )
        )
        await session.commit()

    service = HistorySyncService(
        FakeMediaHistoryClient(),  # type: ignore[arg-type]
        session_factory,
        transfer,  # type: ignore[arg-type]
        config,
    )
    inspected = await service.sync_source(1, limit=2)

    assert inspected == 2
    assert transfer.enqueued == [(1, (2,)), (1, (3,))]
    await engine.dispose()


class FakeAlbumHistoryClient:
    async def iter_messages(self, entity: object, **kwargs: object):
        yield SimpleNamespace(
            id=10,
            action=None,
            pinned=False,
            photo=object(),
            video=None,
            media=None,
            grouped_id=555,
        )
        yield SimpleNamespace(
            id=11,
            action=None,
            pinned=False,
            photo=object(),
            video=None,
            media=None,
            grouped_id=555,
        )
        yield SimpleNamespace(
            id=12,
            action=None,
            pinned=False,
            photo=None,
            video=object(),
            media=None,
            grouped_id=None,
        )


async def test_history_groups_album_messages_into_one_batch() -> None:
    session_factory, engine = await _build_factory()
    config = AppConfig(
        history=HistoryConfig(default_limit=2, skip_pinned=True),
        content_filter=ContentFilterConfig(media_only=True),
        transfer=TransferConfig(delay_seconds=0),
    )
    transfer = FakeTransfer()

    async with session_factory() as session:
        session.add(
            Source(
                raw_input="@album_source",
                normalized_key="username:album_source",
                tg_id=102,
                title="Album Source",
            )
        )
        await session.commit()

    service = HistorySyncService(
        FakeAlbumHistoryClient(),  # type: ignore[arg-type]
        session_factory,
        transfer,  # type: ignore[arg-type]
        config,
    )
    inspected = await service.sync_source(1, limit=2)

    assert inspected == 2
    assert transfer.enqueued == [(1, (10, 11)), (1, (12,))]
    await engine.dispose()
