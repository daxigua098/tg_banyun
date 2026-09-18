"""Durable, globally sequential Telegram message delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.config import AppConfig
from app.models import DeliveryJob, Route, Source, Target


class SequentialTransferService:
    """Create and execute delivery jobs with one worker consumer."""

    def __init__(
        self,
        client: TelegramClient,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
        operation_lock: asyncio.Lock | None = None,
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.config = config
        self.operation_lock = operation_lock
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
                        DeliveryJob.source_message_id == source_message_id,
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
                    source_message_id=source_message_id,
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

            job.status = "processing"
            job.attempt_count += 1
            await session.commit()

            try:
                result = await self._forward_message(source, target, job.source_message_id)
                job.status = "success"
                job.last_error = None
                job.next_retry_at = None
                job.sent_at = datetime.now(UTC)
                job.target_message_id = self._result_message_id(result)
                await session.commit()
                logger.info(
                    "Delivered source={} message={} target={} as message={}",
                    source.id,
                    job.source_message_id,
                    target.id,
                    job.target_message_id,
                )
            except FloodWaitError as exc:
                job.status = "retrying"
                job.last_error = f"FloodWait: {exc.seconds}s"
                job.next_retry_at = datetime.now(UTC) + timedelta(seconds=exc.seconds)
                await session.commit()
                logger.warning(
                    "Telegram FloodWait for source={} message={} target={}: {}s",
                    source.id,
                    job.source_message_id,
                    target.id,
                    exc.seconds,
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
                logger.exception(
                    "Delivery failed source={} message={} target={} attempt={}/{}",
                    source.id,
                    job.source_message_id,
                    target.id,
                    job.attempt_count,
                    job.max_attempts,
                )

    async def _forward_message(self, source: Source, target: Target, message_id: int) -> Any:
        source_entity = source.tg_id or source.raw_input
        target_entity = target.tg_id or target.raw_input
        if self.operation_lock is None:
            return await self._call_forward(source_entity, target_entity, message_id)

        async with self.operation_lock:
            return await self._call_forward(source_entity, target_entity, message_id)

    async def _call_forward(
        self,
        source_entity: int | str,
        target_entity: int | str,
        message_id: int,
    ) -> Any:
        return await self.client.forward_messages(
            entity=target_entity,
            messages=message_id,
            from_peer=source_entity,
            drop_author=self.config.transfer.mode == "copy",
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
