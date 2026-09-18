"""Runtime orchestration for history synchronization and realtime listening."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, events

from app.config import AppConfig
from app.core.content_filter import should_transfer_message
from app.core.heartbeat import HeartbeatWriter
from app.core.message_batch import MessageBatch
from app.core.transfer import SequentialTransferService
from app.models import Route, Source, Target
from app.services.history_service import HistorySyncService


class RuntimeService:
    """Run one realtime event consumer and synchronize sources sequentially."""

    def __init__(
        self,
        client: TelegramClient,
        session_factory: async_sessionmaker[AsyncSession],
        transfer: SequentialTransferService,
        config: AppConfig,
        operation_lock: asyncio.Lock | None = None,
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.transfer = transfer
        self.config = config
        self.history = HistorySyncService(
            client,
            session_factory,
            transfer,
            config,
            operation_lock=operation_lock,
        )
        self.queue: asyncio.Queue[tuple[int, MessageBatch] | None] = asyncio.Queue()
        self.heartbeat = HeartbeatWriter(config.project_root / "data" / "runtime_status.json")
        self._new_message_filter = events.NewMessage(
            incoming=True,
            func=self._is_non_album,
        )
        self._album_filter = events.Album()

    @staticmethod
    def _is_non_album(event: events.NewMessage.Event) -> bool:
        return getattr(event.message, "grouped_id", None) is None

    async def run(self) -> None:
        """Catch up history sequentially, then start the realtime worker."""
        recovered = await self.transfer.recover_interrupted_jobs()
        if recovered:
            logger.info("Recovered {} interrupted delivery jobs", recovered)

        self.client.add_event_handler(self._on_new_message, self._new_message_filter)
        self.client.add_event_handler(self._on_album, self._album_filter)
        worker: asyncio.Task[None] | None = None
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="runtime-heartbeat",
        )

        try:
            await self.transfer.process_pending()
            await self._sync_history_sequentially()

            worker = asyncio.create_task(
                self._consume_queue(),
                name="sequential-transfer-worker",
            )
            logger.info("Realtime listener is running; all transfers use one sequential worker")
            await self.client.run_until_disconnected()
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            if worker is not None:
                await self.queue.put(None)
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            self.client.remove_event_handler(self._on_new_message, self._new_message_filter)
            self.client.remove_event_handler(self._on_album, self._album_filter)
            await self._write_heartbeat("stopped")

    async def _heartbeat_loop(self) -> None:
        while True:
            await self._write_heartbeat("running")
            await asyncio.sleep(5)

    async def _write_heartbeat(self, status: str) -> None:
        try:
            async with self.session_factory() as session:
                source_count = int(
                    await session.scalar(select(func.count()).select_from(Source)) or 0
                )
                target_count = int(
                    await session.scalar(select(func.count()).select_from(Target)) or 0
                )
                route_count = int(
                    await session.scalar(select(func.count()).select_from(Route)) or 0
                )
        except Exception:  # noqa: BLE001 - monitoring must not stop the runtime
            logger.exception("Failed to collect runtime status")
            source_count = target_count = route_count = 0

        self.heartbeat.write(
            status=status,
            source_count=source_count,
            target_count=target_count,
            route_count=route_count,
            queue_size=self.queue.qsize(),
        )

    async def _sync_history_sequentially(self) -> None:
        if not self.config.history.enabled:
            return

        async with self.session_factory() as session:
            source_ids = list(
                await session.scalars(
                    select(Source.id)
                    .where(Source.enabled.is_(True))
                    .order_by(Source.priority.asc(), Source.id.asc())
                )
            )

        for source_id in source_ids:
            await self.history.sync_source(source_id)
            await self.transfer.process_pending()

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            return
        if not should_transfer_message(event.message, self.config.content_filter):
            return
        source_id = await self._source_id_for_chat(int(chat_id))
        if source_id is not None:
            batch = MessageBatch.from_messages([event.message])
            await self.queue.put((source_id, batch))

    async def _on_album(self, event: events.Album.Event) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            return
        messages = [
            message
            for message in event.messages
            if should_transfer_message(message, self.config.content_filter)
        ]
        if not messages:
            return
        source_id = await self._source_id_for_chat(int(chat_id))
        if source_id is not None:
            await self.queue.put((source_id, MessageBatch.from_messages(messages)))

    async def _source_id_for_chat(self, chat_id: int) -> int | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(Source.id).where(
                    Source.tg_id == chat_id,
                    Source.enabled.is_(True),
                )
            )

    async def _consume_queue(self) -> None:
        while True:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                await self.transfer.process_pending()
                continue

            try:
                if item is None:
                    return
                source_id, batch = item
                await self.transfer.enqueue_batch(source_id, batch)
                async with self.session_factory() as session:
                    source = await session.get(Source, source_id)
                    if source is not None:
                        source.last_synced_message_id = max(
                            source.last_synced_message_id,
                            batch.max_message_id,
                        )
                        await session.commit()
                await self.transfer.process_pending()
            finally:
                self.queue.task_done()

