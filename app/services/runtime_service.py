"""Runtime orchestration for history synchronization and realtime listening."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, events

from app.config import AppConfig
from app.core.content_filter import should_transfer_for_source
from app.core.heartbeat import HeartbeatWriter
from app.core.message_batch import MessageBatch
from app.core.runtime_control import is_runtime_paused
from app.core.sender_filter import is_admin_or_channel_post
from app.core.transfer import SequentialTransferService
from app.models import ControlCommand, Route, Source, Target
from app.services.backup_service import (
    create_backup,
    is_backup_due,
    latest_backup,
    prune_backups,
)
from app.services.control_command_service import (
    COMMAND_ADD_SOURCE,
    COMMAND_ADD_TARGET,
    COMMAND_NOTIFY_ADMINS,
    COMMAND_SYNC,
    load_command_payload,
)
from app.services.history_service import HistorySyncService
from app.services.notifier_service import AdminNotifier
from app.services.rule_service import get_source_rule
from app.services.source_service import add_source, add_target


class RuntimeService:
    """Run one realtime event consumer and synchronize sources sequentially."""

    def __init__(
        self,
        client: TelegramClient,
        session_factory: async_sessionmaker[AsyncSession],
        transfer: SequentialTransferService,
        config: AppConfig,
        operation_lock: asyncio.Lock | None = None,
        notifier: AdminNotifier | None = None,
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.transfer = transfer
        self.config = config
        self.notifier = notifier
        self.history = HistorySyncService(
            client,
            session_factory,
            transfer,
            config,
            operation_lock=operation_lock,
        )
        self.queue: asyncio.Queue[tuple[int, MessageBatch] | None] = asyncio.Queue()
        self.heartbeat = HeartbeatWriter(config.project_root / "data" / "runtime_status.json")
        self.control_path = config.project_root / "data" / "runtime_control.json"
        backup_dir = Path(config.backup.directory)
        if not backup_dir.is_absolute():
            backup_dir = config.project_root / backup_dir
        self.backup_dir = backup_dir
        self.last_backup_at: str | None = None
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
        backup_task = asyncio.create_task(
            self._backup_loop(),
            name="automatic-backup",
        )

        try:
            if not is_runtime_paused(self.control_path):
                await self.transfer.process_pending()
            await self._sync_history_sequentially()

            worker = asyncio.create_task(
                self._consume_queue(),
                name="sequential-transfer-worker",
            )
            if self.notifier is not None:
                await self.notifier.startup(
                    "实时监听已启动，历史补发和自动备份均已就绪。"
                )
            logger.info("Realtime listener is running; all transfers use one sequential worker")
            await self.client.run_until_disconnected()
        finally:
            heartbeat_task.cancel()
            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            with suppress(asyncio.CancelledError):
                await backup_task
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
            paused=is_runtime_paused(self.control_path),
            last_backup_at=self.last_backup_at,
        )

    async def _backup_loop(self) -> None:
        while True:
            await self._run_backup_if_due()
            await asyncio.sleep(300)

    async def _run_backup_if_due(self) -> None:
        if not self.config.backup.enabled:
            return
        if not is_backup_due(self.backup_dir, self.config.backup.interval_hours):
            latest = latest_backup(self.backup_dir)
            if latest is not None:
                self.last_backup_at = datetime.fromtimestamp(
                    latest.stat().st_mtime,
                    tz=UTC,
                ).isoformat(timespec="seconds")
            return

        archive = await asyncio.to_thread(
            create_backup,
            self.config.project_root,
            self.backup_dir,
        )
        removed = await asyncio.to_thread(
            prune_backups,
            self.backup_dir,
            self.config.backup.retention_count,
        )
        self.last_backup_at = datetime.fromtimestamp(
            archive.stat().st_mtime,
            tz=UTC,
        ).isoformat(timespec="seconds")
        logger.info(
            "Automatic backup created={} removed_old={}",
            archive,
            removed,
        )
        if self.notifier is not None:
            await self.notifier.backup(
                f"备份文件：{archive.name}\n清理旧备份：{removed} 份"
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
            try:
                await self.history.sync_source(source_id)
            except Exception as exc:  # noqa: BLE001 - continue other sources
                if self.notifier is not None:
                    await self.notifier.failure(
                        f"源同步失败\n源 ID：{source_id}\n"
                        f"错误：{type(exc).__name__}: {exc}"
                    )
                continue
            if not is_runtime_paused(self.control_path):
                await self.transfer.process_pending()

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            return
        source_id = await self._source_id_for_chat(int(chat_id))
        if source_id is not None and await self._message_allowed(source_id, event.message):
            batch = MessageBatch.from_messages([event.message])
            await self.queue.put((source_id, batch))

    async def _on_album(self, event: events.Album.Event) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            return
        source_id = await self._source_id_for_chat(int(chat_id))
        if source_id is None:
            return
        messages = []
        for message in event.messages:
            if await self._message_allowed(source_id, message):
                messages.append(message)
        if messages:
            await self.queue.put((source_id, MessageBatch.from_messages(messages)))

    async def _source_id_for_chat(self, chat_id: int) -> int | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(Source.id).where(
                    Source.tg_id == chat_id,
                    Source.enabled.is_(True),
                )
            )

    async def _message_allowed(self, source_id: int, message: object) -> bool:
        async with self.session_factory() as session:
            source = await session.get(Source, source_id)
            rule = await get_source_rule(session, source_id)
        if source is None:
            return False
        if not should_transfer_for_source(message, self.config.content_filter, rule):
            return False
        if rule.admin_only:
            entity = source.tg_id or source.raw_input
            return await is_admin_or_channel_post(self.client, entity, message)
        return True

    async def _process_control_command_once(self) -> bool:
        async with self.session_factory() as session:
            command = await session.scalar(
                select(ControlCommand)
                .where(ControlCommand.status == "pending")
                .order_by(ControlCommand.id.asc())
                .limit(1)
            )
            if command is None:
                return False
            command.status = "processing"
            await session.commit()

        try:
            result = await self._execute_control_command(command)
            async with self.session_factory() as session:
                current = await session.get(ControlCommand, command.id)
                if current is not None:
                    current.status = "success"
                    current.result = json.dumps(result, ensure_ascii=False)
                    current.error = None
                    current.processed_at = datetime.now(UTC)
                    await session.commit()
            logger.info("Control command completed id={} type={}", command.id, command.command_type)
        except Exception as exc:  # noqa: BLE001 - command failures must not stop runtime
            async with self.session_factory() as session:
                current = await session.get(ControlCommand, command.id)
                if current is not None:
                    current.status = "failed"
                    current.error = f"{type(exc).__name__}: {exc}"[:2000]
                    current.processed_at = datetime.now(UTC)
                    await session.commit()
            logger.exception("Control command failed id={}", command.id)
        return True

    async def _execute_control_command(self, command: ControlCommand) -> dict[str, Any]:
        payload = load_command_payload(command)
        if command.command_type == COMMAND_ADD_SOURCE:
            async with self.operation_lock:
                async with self.session_factory() as session:
                    source = await add_source(
                        session,
                        self.client,
                        str(payload.get("input", "")),
                        join=bool(payload.get("join", False)),
                        display_name=str(payload.get("name") or "") or None,
                    )
            return {"source_id": source.id, "title": source.title}
        if command.command_type == COMMAND_ADD_TARGET:
            async with self.operation_lock:
                async with self.session_factory() as session:
                    target = await add_target(
                        session,
                        self.client,
                        str(payload.get("input", "")),
                        display_name=str(payload.get("name") or "") or None,
                    )
            return {"target_id": target.id, "title": target.title}
        if command.command_type == COMMAND_NOTIFY_ADMINS:
            text = str(payload.get("text") or "TG-Mirror-Bot 异常通知")
            if self.notifier is not None:
                await self.notifier.send(text)
            return {"notified": self.notifier is not None}
        if command.command_type == COMMAND_SYNC:
            source_value = payload.get("source_id", "all")
            limit = int(payload.get("limit") or self.config.history.default_limit)
            if source_value == "all":
                results = await self.history.sync_all(limit=limit)
                return {"results": results}
            inspected = await self.history.sync_source(int(source_value), limit=limit)
            if not is_runtime_paused(self.control_path):
                await self.transfer.process_pending()
            return {"source_id": int(source_value), "inspected": inspected}
        raise ValueError(f"不支持的控制命令：{command.command_type}")

    async def _consume_queue(self) -> None:
        while True:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                if not is_runtime_paused(self.control_path):
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
                if not is_runtime_paused(self.control_path):
                    await self.transfer.process_pending()
            finally:
                self.queue.task_done()

