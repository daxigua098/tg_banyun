"""Sequential historical message synchronization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient

from app.config import AppConfig
from app.core.content_filter import should_transfer_for_source
from app.core.message_batch import MessageBatch
from app.core.sender_filter import is_admin_or_channel_post
from app.core.transfer import SequentialTransferService
from app.models import Source
from app.services.rule_service import get_source_rule


class HistorySyncService:
    """Fetch source history one source at a time and enqueue delivery batches."""

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

    async def sync_all(
        self,
        *,
        limit: int | None = None,
        fuzzy_keywords: list[str] | None = None,
        recent: bool = False,
    ) -> dict[int, int]:
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
            results[source.id] = await self.sync_source(
                source.id,
                limit=limit,
                fuzzy_keywords=fuzzy_keywords,
                recent=recent,
            )
        return results

    async def sync_source(
        self,
        source_id: int,
        *,
        limit: int | None = None,
        fuzzy_keywords: list[str] | None = None,
        recent: bool = False,
    ) -> int:
        """Synchronize eligible messages and return the number of new batches.

        Incremental mode continues after the source watermark. Manual immediate
        transfers use recent mode to inspect a recent history window, while the
        database-backed deduplication still prevents already copied posts from
        being enqueued again.
        """
        limit = limit or self.config.history.default_limit
        if self.config.history.order != "old_to_new":
            raise ValueError("MVP history synchronization only supports old_to_new ordering.")

        async with self.session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:
                raise ValueError(f"Source {source_id} does not exist.")
            entity = source.tg_id or source.raw_input
            watermark = source.last_synced_message_id
            rule = await get_source_rule(session, source_id)
            source.sync_status = "syncing"
            source.error_message = None
            await session.commit()

        try:
            async with self._operation_context():
                if recent:
                    inspected = await self._sync_recent_locked(
                        source_id,
                        entity,
                        limit=limit,
                        fuzzy_keywords=fuzzy_keywords,
                        rule=rule,
                    )
                else:
                    inspected = await self._sync_incremental_locked(
                        source_id,
                        entity,
                        watermark=watermark,
                        limit=limit,
                        fuzzy_keywords=fuzzy_keywords,
                        rule=rule,
                    )
        except Exception as exc:  # noqa: BLE001 - keep source loop alive
            async with self.session_factory() as session:
                current = await session.get(Source, source_id)
                if current is not None:
                    current.sync_status = "error"
                    current.error_message = f"{type(exc).__name__}: {exc}"[:2000]
                    await session.commit()
            logger.exception("History synchronization failed for source={}", source_id)
            raise

        async with self.session_factory() as session:
            current = await session.get(Source, source_id)
            if current is not None:
                current.sync_status = "ready"
                current.last_sync_at = datetime.now(UTC)
                await session.commit()

        logger.info(
            "History synchronization completed source={} enqueued={} mode={}",
            source_id,
            inspected,
            "recent" if recent else "incremental",
        )
        return inspected

    async def _message_is_eligible(
        self,
        entity: object,
        source_id: int,
        message: object,
        rule: object,
        fuzzy_keywords: list[str] | None,
    ) -> bool:
        message_id = int(getattr(message, "id", 0))
        if self.config.history.skip_pinned and getattr(message, "pinned", False):
            return False
        if getattr(message, "action", None) is not None:
            logger.debug(
                "Skipping Telegram service message source={} message={}",
                source_id,
                message_id,
            )
            return False
        if not should_transfer_for_source(message, self.config.content_filter, rule):
            logger.debug(
                "Skipping filtered message source={} message={}",
                source_id,
                message_id,
            )
            return False
        if bool(getattr(rule, "search_monitor", False)):
            if not str(getattr(message, "raw_text", "") or "").strip():
                return False
            sender = await message.get_sender() if hasattr(message, "get_sender") else None
            if sender is not None and bool(getattr(sender, "bot", False)):
                logger.debug(
                    "Skipping bot message source={} message={}",
                    source_id,
                    message_id,
                )
                return False
        if fuzzy_keywords:
            text = str(getattr(message, "raw_text", "") or "").casefold()
            normalized_keywords = [item.casefold() for item in fuzzy_keywords]
            if not any(keyword in text for keyword in normalized_keywords):
                logger.debug(
                    "Skipping fuzzy-filtered message source={} message={}",
                    source_id,
                    message_id,
                )
                return False
        if rule.admin_only and not await is_admin_or_channel_post(self.client, entity, message):
            logger.debug(
                "Skipping non-admin message source={} message={}",
                source_id,
                message_id,
            )
            return False
        return True

    async def _sync_incremental_locked(
        self,
        source_id: int,
        entity: object,
        *,
        watermark: int,
        limit: int,
        fuzzy_keywords: list[str] | None,
        rule: object,
    ) -> int:
        inspected = 0
        pending_messages: list[Any] = []
        pending_group_id: int | None = None

        async def flush_pending() -> bool:
            nonlocal inspected, pending_group_id
            if not pending_messages:
                return False
            batch = MessageBatch.from_messages(pending_messages)
            await self.transfer.enqueue_batch(source_id, batch)
            inspected += 1
            await self._advance_watermark(source_id, batch.max_message_id)
            pending_messages.clear()
            pending_group_id = None
            return inspected >= limit

        async for message in self.client.iter_messages(
            entity,
            min_id=watermark,
            reverse=True,
        ):
            message_id = int(message.id)
            grouped_id = getattr(message, "grouped_id", None)
            grouped_id = int(grouped_id) if grouped_id is not None else None

            if not await self._message_is_eligible(
                entity,
                source_id,
                message,
                rule,
                fuzzy_keywords,
            ):
                if await flush_pending():
                    break
                await self._advance_watermark(source_id, message_id)
                continue

            if pending_messages and grouped_id is not None and grouped_id == pending_group_id:
                pending_messages.append(message)
                continue

            if await flush_pending():
                break

            pending_messages.append(message)
            pending_group_id = grouped_id

            if grouped_id is None and await flush_pending():
                break

        if inspected < limit:
            await flush_pending()
        return inspected

    async def _sync_recent_locked(
        self,
        source_id: int,
        entity: object,
        *,
        limit: int,
        fuzzy_keywords: list[str] | None,
        rule: object,
    ) -> int:
        # Inspect a bounded recent window so manual transfers remain responsive.
        scan_limit = max(limit * 50, 5000)
        candidate_batches: list[MessageBatch] = []
        pending_messages: list[Any] = []
        pending_group_id: int | None = None
        max_seen_message_id = 0

        def flush_candidate() -> bool:
            nonlocal pending_group_id
            if not pending_messages:
                return False
            candidate_batches.append(MessageBatch.from_messages(pending_messages))
            pending_messages.clear()
            pending_group_id = None
            return len(candidate_batches) >= limit

        async for message in self.client.iter_messages(entity, limit=scan_limit):
            max_seen_message_id = max(max_seen_message_id, int(message.id))
            grouped_id = getattr(message, "grouped_id", None)
            grouped_id = int(grouped_id) if grouped_id is not None else None

            if not await self._message_is_eligible(
                entity,
                source_id,
                message,
                rule,
                fuzzy_keywords,
            ):
                continue

            if pending_messages and grouped_id is not None and grouped_id == pending_group_id:
                pending_messages.append(message)
                continue

            if flush_candidate():
                break

            pending_messages.append(message)
            pending_group_id = grouped_id

            if grouped_id is None and flush_candidate():
                break

        if len(candidate_batches) < limit:
            flush_candidate()

        candidate_batches.reverse()
        enqueued = 0
        for batch in candidate_batches:
            job_ids = await self.transfer.enqueue_batch(source_id, batch)
            if job_ids:
                enqueued += 1

        if max_seen_message_id:
            await self._advance_watermark(source_id, max_seen_message_id)
        return enqueued

    async def _advance_watermark(self, source_id: int, message_id: int) -> None:
        async with self.session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:
                return
            source.last_synced_message_id = max(source.last_synced_message_id, message_id)
            source.last_sync_at = datetime.now(UTC)
            await session.commit()



