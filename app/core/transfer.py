"""Durable, globally sequential Telegram message delivery."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient
from telethon.errors import FloodWaitError, MessageIdInvalidError

from app.config import AppConfig
from app.core.message_batch import MessageBatch
from app.models import DeliveryJob, RecordTarget, Route, Source, Target
from app.services.notifier_service import AdminNotifier
from app.services.settings_service import get_additional_settings


@asynccontextmanager
async def _null_async_context():
    yield


class SequentialTransferService:
    """Create and execute delivery jobs with one worker consumer."""

    def __init__(
        self,
        client: TelegramClient,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
        operation_lock: asyncio.Lock | None = None,
        notifier: AdminNotifier | None = None,
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.config = config
        self.operation_lock = operation_lock
        self.notifier = notifier
        self._worker_lock = asyncio.Lock()

    async def recover_interrupted_jobs(self) -> int:
        """Reset jobs interrupted by a previous process shutdown."""
        async with self.session_factory() as session:
            jobs = list(
                await session.scalars(
                    select(DeliveryJob).where(DeliveryJob.status == "processing")
                )
            )
            for job in jobs:
                job.status = "pending"
                job.last_error = "Recovered after interrupted processing."
            await session.commit()
            return len(jobs)

    async def enqueue_message(self, source_id: int, source_message_id: int) -> list[int]:
        """Create a single-message batch for backwards-compatible callers."""
        return await self.enqueue_batch(
            source_id,
            MessageBatch(message_ids=(source_message_id,)),
        )

    async def enqueue_batch(self, source_id: int, batch: MessageBatch) -> list[int]:
        """Create missing jobs for every enabled target routed from a source."""
        async with self.session_factory() as session:
            target_ids = list(
                await session.scalars(
                    select(Route.target_id)
                    .join(Target, Target.id == Route.target_id)
                    .where(
                        Route.source_id == source_id,
                        Route.enabled.is_(True),
                        Target.enabled.is_(True),
                    )
                    .order_by(Route.target_id.asc())
                )
            )
            if not target_ids:
                return []

            existing = set(
                await session.scalars(
                    select(DeliveryJob.target_id).where(
                        DeliveryJob.source_id == source_id,
                        DeliveryJob.source_message_id == batch.primary_message_id,
                        DeliveryJob.target_id.in_(target_ids),
                    )
                )
            )

            new_jobs: list[DeliveryJob] = []
            for target_id in target_ids:
                if target_id in existing:
                    continue
                job = DeliveryJob(
                    source_id=source_id,
                    target_id=target_id,
                    source_message_id=batch.primary_message_id,
                    source_message_ids=json.dumps(batch.message_ids),
                    media_group_id=batch.media_group_id,
                    status="pending",
                    max_attempts=self.config.transfer.max_attempts,
                )
                session.add(job)
                new_jobs.append(job)

            await session.commit()
            for job in new_jobs:
                await session.refresh(job)
            return [job.id for job in new_jobs]

    async def process_pending(self, *, wait_for_retry: bool = False) -> int:
        """Process eligible jobs sequentially, one at a time."""
        async with self._worker_lock:
            return await self._process_pending_locked(wait_for_retry=wait_for_retry)

    async def _process_pending_locked(self, *, wait_for_retry: bool) -> int:
        processed = 0
        while True:
            job_id = await self._next_ready_job_id()
            if job_id is None:
                if not wait_for_retry:
                    break
                delay = await self._seconds_until_next_retry()
                if delay is None:
                    break
                await asyncio.sleep(min(delay, 60.0))
                continue

            await self._process_job(job_id)
            processed += 1
            if self.config.transfer.delay_seconds:
                await asyncio.sleep(self.config.transfer.delay_seconds)
        return processed

    async def _next_ready_job_id(self) -> int | None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            statement = (
                select(DeliveryJob.id)
                .where(
                    DeliveryJob.status.in_(("pending", "retrying")),
                    (DeliveryJob.next_retry_at.is_(None)) | (DeliveryJob.next_retry_at <= now),
                )
                .order_by(DeliveryJob.id.asc())
                .limit(1)
            )
            return await session.scalar(statement)

    async def _seconds_until_next_retry(self) -> float | None:
        async with self.session_factory() as session:
            next_retry = await session.scalar(
                select(func.min(DeliveryJob.next_retry_at)).where(
                    DeliveryJob.status == "retrying"
                )
            )
        if next_retry is None:
            return None
        if next_retry.tzinfo is None:
            next_retry = next_retry.replace(tzinfo=UTC)
        return max((next_retry - datetime.now(UTC)).total_seconds(), 0.0)

    async def _process_job(self, job_id: int) -> None:
        async with self.session_factory() as session:
            job = await session.get(DeliveryJob, job_id)
            if job is None or job.status not in {"pending", "retrying"}:
                return

            source = await session.get(Source, job.source_id)
            target = await session.get(Target, job.target_id)
            if source is None or target is None:
                job.status = "failed"
                job.last_error = "Source or target row no longer exists."
                await session.commit()
                return

            batch = self._batch_from_job(job)
            job.status = "processing"
            job.attempt_count += 1
            await session.commit()

            try:
                result = await self._forward_message(source, target, batch)
                try:
                    await self._apply_additional_content(target, result)
                except Exception as exc:  # noqa: BLE001 - post already sent
                    logger.error(
                        "Additional content failed target={} error={}: {}",
                        target.id,
                        type(exc).__name__,
                        exc,
                    )
                job.status = "success"
                job.last_error = None
                job.next_retry_at = None
                job.sent_at = datetime.now(UTC)
                job.target_message_id = self._result_message_id(result)
                await session.commit()
                await self._send_delivery_record(source, target, job)
                logger.info(
                    "Delivered source={} messages={} target={} as message={}",
                    source.id,
                    batch.message_ids,
                    target.id,
                    job.target_message_id,
                )
            except FloodWaitError as exc:
                job.status = "retrying"
                job.last_error = f"FloodWait: {exc.seconds}s"
                job.next_retry_at = datetime.now(UTC) + timedelta(seconds=exc.seconds)
                await session.commit()
                await self._send_delivery_record(source, target, job)
                logger.warning(
                    "Telegram FloodWait for source={} messages={} target={}: {}s",
                    source.id,
                    batch.message_ids,
                    target.id,
                    exc.seconds,
                )
            except MessageIdInvalidError as exc:
                job.status = "failed"
                job.next_retry_at = None
                job.last_error = f"MessageIdInvalid: {exc}"[:2000]
                await session.commit()
                await self._send_delivery_record(source, target, job)
                logger.warning(
                    "Skipping invalid Telegram messages source={} messages={} target={}",
                    source.id,
                    batch.message_ids,
                    target.id,
                )
                if self.notifier is not None:
                    await self.notifier.failure(
                        "投递永久失败\n"
                        f"源：{source.title or source.raw_input} (ID {source.id})\n"
                        f"消息：{', '.join(str(item) for item in batch.message_ids)}\n"
                        f"目标：{target.title or target.raw_input} (ID {target.id})\n"
                        f"错误：{job.last_error}"
                    )
            except Exception as exc:  # noqa: BLE001 - job failures must not stop the worker
                message = f"{type(exc).__name__}: {exc}"[:2000]
                if job.attempt_count >= job.max_attempts:
                    job.status = "failed"
                    job.next_retry_at = None
                else:
                    job.status = "retrying"
                    delay = self.config.transfer.retry_base_seconds * (
                        2 ** max(job.attempt_count - 1, 0)
                    )
                    job.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
                job.last_error = message
                await session.commit()
                await self._send_delivery_record(source, target, job)
                logger.error(
                    "Delivery failed source={} messages={} target={} attempt={}/{} error={}",
                    source.id,
                    batch.message_ids,
                    target.id,
                    job.attempt_count,
                    job.max_attempts,
                    message,
                )
                logger.opt(exception=True).debug(
                    "Delivery exception details source={} messages={} target={}",
                    source.id,
                    batch.message_ids,
                    target.id,
                )
                if job.status == "failed" and self.notifier is not None:
                    await self.notifier.failure(
                        "投递永久失败\n"
                        f"源：{source.title or source.raw_input} (ID {source.id})\n"
                        f"消息：{', '.join(str(item) for item in batch.message_ids)}\n"
                        f"目标：{target.title or target.raw_input} (ID {target.id})\n"
                        f"错误：{message}"
                    )

    @staticmethod
    def _batch_from_job(job: DeliveryJob) -> MessageBatch:
        if job.source_message_ids:
            try:
                message_ids = tuple(int(item) for item in json.loads(job.source_message_ids))
            except (TypeError, ValueError, json.JSONDecodeError):
                message_ids = (job.source_message_id,)
        else:
            message_ids = (job.source_message_id,)
        return MessageBatch(
            message_ids=message_ids,
            media_group_id=job.media_group_id,
        )

    @staticmethod
    def format_delivery_record(source: Source, target: Target, job: DeliveryJob) -> str:
        """Build a human-readable delivery record."""
        status_names = {
            "retrying": "等待重试",
            "success": "成功",
            "failed": "失败",
        }
        status = status_names.get(job.status, job.status)
        target_message = job.target_message_id or "-"
        error = job.last_error or "-"
        batch = SequentialTransferService._batch_from_job(job)
        message_ids = ", ".join(str(item) for item in batch.message_ids)
        return (
            "搬运记录\n"
            f"状态：{status}\n"
            f"源：{source.title or source.raw_input} (ID {source.id})\n"
            f"源消息：{message_ids}\n"
            f"目标：{target.title or target.raw_input} (ID {target.id})\n"
            f"目标消息：{target_message}\n"
            f"尝试：{job.attempt_count}/{job.max_attempts}\n"
            f"错误：{error}"
        )

    async def _send_delivery_record(
        self,
        source: Source,
        target: Target,
        job: DeliveryJob,
    ) -> None:
        async with self.session_factory() as session:
            record_targets = list(
                await session.scalars(
                    select(RecordTarget)
                    .where(RecordTarget.enabled.is_(True))
                    .order_by(RecordTarget.id.asc())
                )
            )
        if not record_targets:
            return

        text = self.format_delivery_record(source, target, job)
        for record_target in record_targets:
            record_entity = record_target.tg_id or record_target.raw_input
            try:
                if self.operation_lock is None:
                    await self.client.send_message(record_entity, text)
                else:
                    async with self.operation_lock:
                        await self.client.send_message(record_entity, text)
            except Exception as exc:  # noqa: BLE001 - records must not break delivery
                logger.error(
                    "Failed to send delivery record target={} error={}: {}",
                    record_target.id,
                    type(exc).__name__,
                    exc,
                )

    async def _apply_additional_content(self, target: Target, result: Any) -> None:
        async with self.session_factory() as session:
            settings = await get_additional_settings(session, self.config.additional)
        if not settings.enabled:
            return

        target_entity = target.tg_id or target.raw_input
        target_message = self._first_result_message(result)
        if settings.text and target_message is not None:
            original = target_message.raw_text or ""
            new_text = f"{original}\n\n{settings.text}".strip()
            async with self.operation_lock if self.operation_lock else _null_async_context():
                await self.client.edit_message(
                    target_entity,
                    target_message.id,
                    new_text,
                    link_preview=False,
                )

        for raw_path in settings.image_paths:
            image_path = Path(raw_path)
            if not image_path.is_absolute():
                image_path = self.config.project_root / image_path
            if not image_path.exists():
                logger.warning("Additional image not found: {}", image_path)
                continue
            async with self.operation_lock if self.operation_lock else _null_async_context():
                await self.client.send_file(
                    target_entity,
                    str(image_path),
                    caption=settings.image_caption or None,
                )

    @staticmethod
    def _first_result_message(result: Any) -> Any | None:
        if hasattr(result, "id"):
            return result
        if isinstance(result, Iterable):
            return next(iter(result), None)
        return None

    async def _forward_message(
        self,
        source: Source,
        target: Target,
        batch: MessageBatch,
    ) -> Any:
        source_entity = source.tg_id or source.raw_input
        target_entity = target.tg_id or target.raw_input
        if self.operation_lock is None:
            return await self._call_forward(source_entity, target_entity, batch)

        async with self.operation_lock:
            return await self._call_forward(source_entity, target_entity, batch)

    async def _call_forward(
        self,
        source_entity: int | str,
        target_entity: int | str,
        batch: MessageBatch,
    ) -> Any:
        messages: int | list[int]
        if batch.is_album:
            messages = list(batch.message_ids)
        else:
            messages = batch.message_ids[0]
        return await self.client.forward_messages(
            entity=target_entity,
            messages=messages,
            from_peer=source_entity,
            drop_author=self.config.transfer.mode == "copy",
            as_album=batch.is_album,
        )

    @staticmethod
    def _result_message_id(result: Any) -> int | None:
        if isinstance(result, Iterable) and not hasattr(result, "id"):
            first = next(iter(result), None)
            return getattr(first, "id", None)
        return getattr(result, "id", None)

    async def stats(self) -> dict[str, int]:
        """Return delivery counts grouped by status."""
        async with self.session_factory() as session:
            rows = await session.execute(
                select(DeliveryJob.status, func.count(DeliveryJob.id)).group_by(DeliveryJob.status)
            )
            return {str(status): int(count) for status, count in rows.all()}
