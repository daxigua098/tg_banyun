"""Sequential historical message synchronization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient

from app.config import AppConfig
from app.core.transfer import SequentialTransferService
from app.models import Source


class HistorySyncService:
    """Fetch source history one source at a time and enqueue delivery jobs."""

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
        self.operation_lock = operation_lock

    @asynccontextmanager
    async def _operation_context(self) -> AsyncIterator[None]:
        if self.operation_lock is None:
            yield
            return
        async with self.operation_lock:
            yield

    async def sync_all(self, *, limit: int | None = None) -> dict[int, int]:
        """Synchronize all enabled sources in deterministic order."""
        async with self.session_factory() as session:
            sources = list(
                await session.scalars(
                    select(Source)
                    .where(Source.enabled.is_(True))
                    .order_by(Source.priority.asc(), Source.id.asc())
                )
            )

        results: dict[int, int] = {}
        for source in sources:
            results[source.id] = await self.sync_source(source.id, limit=limit)
        return results

    async def sync_source(self, source_id: int, *, limit: int | None = None) -> int:
        """Synchronize one source and return the number of inspected messages."""
        limit = limit or self.config.history.default_limit
        if self.config.history.order != "old_to_new":
            raise ValueError("MVP history synchronization only supports old_to_new ordering.")

        async with self.session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:
                raise ValueError(f"Source {source_id} does not exist.")
            entity = source.tg_id or source.raw_input
            watermark = source.last_synced_message_id
            source.sync_status = "syncing"
            source.error_message = None
            await session.commit()

        inspected = 0
        try:
            async with self._operation_context():
                async for message in self.client.iter_messages(
                    entity,
                    min_id=watermark,
                    reverse=True,
                    limit=limit,
                ):
                    if self.config.history.skip_pinned and getattr(message, "pinned", False):
                        continue

                    await self.transfer.enqueue_message(source_id, int(message.id))
                    inspected += 1

                    async with self.session_factory() as session:
                        current = await session.get(Source, source_id)
                        if current is None:
                            continue
                        current.last_synced_message_id = max(
                            current.last_synced_message_id,
                            int(message.id),
                        )
                        current.last_sync_at = datetime.now(UTC)
                        current.sync_status = "ready"
                        await session.commit()
        except Exception as exc:  # noqa: BLE001 - keep source loop alive
            async with self.session_factory() as session:
                current = await session.get(Source, source_id)
                if current is not None:
                    current.sync_status = "error"
                    current.error_message = f"{type(exc).__name__}: {exc}"[:2000]
                    await session.commit()
            logger.exception("History synchronization failed for source={}", source_id)
            raise

        logger.info(
            "History synchronization completed source={} inspected={}",
            source_id,
            inspected,
        )
        return inspected
