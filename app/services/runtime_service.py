"""Runtime orchestration for history synchronization and realtime listening."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, events

from app.config import AppConfig
from app.core.transfer import SequentialTransferService
from app.models import Source
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
        self.queue: asyncio.Queue[tuple[int, int] | None] = asyncio.Queue()
        self._new_message_filter = events.NewMessage(incoming=True)

    async def run(self) -> None:
        """Catch up history sequentially, then start the realtime worker."""
        recovered = await self.transfer.recover_interrupted_jobs()
        if recovered:
            logger.info("Recovered {} interrupted delivery jobs", recovered)

        self.client.add_event_handler(self._on_new_message, self._new_message_filter)
        worker: asyncio.Task[None] | None = None

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
            if worker is not None:
                await self.queue.put(None)
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            self.client.remove_event_handler(self._on_new_message, self._new_message_filter)

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
        async with self.session_factory() as session:
            source_id = await session.scalar(
                select(Source.id).where(
                    Source.tg_id == int(chat_id),
                    Source.enabled.is_(True),
                )
            )
        if source_id is not None:
            await self.queue.put((int(source_id), int(event.message.id)))

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
                source_id, message_id = item
                await self.transfer.enqueue_message(source_id, message_id)
                async with self.session_factory() as session:
                    source = await session.get(Source, source_id)
                    if source is not None:
                        source.last_synced_message_id = max(
                            source.last_synced_message_id,
                            message_id,
                        )
                        await session.commit()
                await self.transfer.process_pending()
            finally:
                self.queue.task_done()
