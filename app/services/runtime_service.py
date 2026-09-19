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
from app.core.runtime_control import is_runtime_paused, is_runtime_stopped
from app.core.sender_filter import is_admin_or_channel_post
from app.core.transfer import SequentialTransferService
from app.models import ControlCommand, DeliveryJob, Route, Source, Target
from app.services.backup_service import (
    create_backup,
    is_backup_due,
    latest_backup,
    prune_backups,
)
from app.services.control_command_service import (
    COMMAND_ADD_SOURCE,
    COMMAND_ADD_TARGET,
    COMMAND_CHECK_ACCESS,
    COMMAND_MANUAL_POST,
    COMMAND_NOTIFY_ADMINS,
    COMMAND_SYNC,
    load_command_payload,
)
from app.services.delivery_job_service import cancel_pending_jobs
from app.services.history_service import HistorySyncService
from app.services.notifier_service import AdminNotifier
from app.services.rule_service import get_source_rule
from app.services.settings_service import get_additional_settings, get_sync_behavior
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
        self.operation_lock = operation_lock
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
        self._edited_filter = events.MessageEdited()
        self._deleted_filter = events.MessageDeleted()

    def _transfer_should_stop(self) -> bool:
        return is_runtime_paused(self.control_path) or is_runtime_stopped(self.control_path)

    async def _process_transfer_queue(self) -> None:
        if self._transfer_should_stop():
            return
        await self.transfer.process_pending(should_stop=self._transfer_should_stop)

    async def _cancel_waiting_work(self) -> None:
        async with self.session_factory() as session:
            await cancel_pending_jobs(session)

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
        self.client.add_event_handler(self._on_message_edited, self._edited_filter)
        self.client.add_event_handler(self._on_message_deleted, self._deleted_filter)
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
            await self._process_transfer_queue()
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
            self.client.remove_event_handler(self._on_message_edited, self._edited_filter)
            self.client.remove_event_handler(self._on_message_deleted, self._deleted_filter)
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
            await self._process_transfer_queue()

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            return
        if self._transfer_should_stop():
            return
        source_id = await self._source_id_for_chat(int(chat_id))
        if source_id is not None and await self._message_allowed(source_id, event.message):
            batch = MessageBatch.from_messages([event.message])
            await self.queue.put((source_id, batch))

    async def _on_album(self, event: events.Album.Event) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            return
        if self._transfer_should_stop():
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

    async def _on_message_edited(self, event: events.MessageEdited.Event) -> None:
        async with self.session_factory() as session:
            settings = await get_sync_behavior(session, self.config.sync)
        if not settings.edits:
            return
        chat_id = event.chat_id
        if chat_id is None:
            return
        source_id = await self._source_id_for_chat(int(chat_id))
        if source_id is None:
            return
        jobs = await self._successful_jobs_for_source_message(source_id, int(event.message.id))
        if not jobs:
            return
        async with self.session_factory() as session:
            additional = await get_additional_settings(session, self.config.additional)
        text = str(getattr(event.message, "raw_text", "") or "")
        if additional.enabled and additional.text:
            text = f"{text}\n\n{additional.text}".strip()
        for job in jobs:
            async with self.session_factory() as session:
                target = await session.get(Target, job.target_id)
            if target is None or job.target_message_id is None:
                continue
            entity = target.tg_id or target.raw_input
            try:
                if self.operation_lock is None:
                    await self.client.edit_message(
                        entity,
                        job.target_message_id,
                        text,
                        link_preview=False,
                    )
                else:
                    async with self.operation_lock:
                        await self.client.edit_message(
                            entity,
                            job.target_message_id,
                            text,
                            link_preview=False,
                        )
                logger.info(
                    "Synchronized edit source={} message={} target={} target_message={}",
                    source_id,
                    event.message.id,
                    target.id,
                    job.target_message_id,
                )
            except Exception as exc:  # noqa: BLE001 - one target failure must not stop others
                logger.warning(
                    "Edit sync failed source={} message={} target={} error={}",
                    source_id,
                    event.message.id,
                    target.id,
                    exc,
                )

    async def _on_message_deleted(self, event: events.MessageDeleted.Event) -> None:
        async with self.session_factory() as session:
            settings = await get_sync_behavior(session, self.config.sync)
        if not settings.deletes:
            return
        source_id = None
        if event.chat_id is not None:
            source_id = await self._source_id_for_chat(int(event.chat_id))
        for message_id in [int(item) for item in event.deleted_ids]:
            jobs = await self._successful_jobs_for_source_message(source_id, message_id)
            for job in jobs:
                async with self.session_factory() as session:
                    target = await session.get(Target, job.target_id)
                if target is None or job.target_message_id is None:
                    continue
                entity = target.tg_id or target.raw_input
                try:
                    if self.operation_lock is None:
                        await self.client.delete_messages(entity, [job.target_message_id])
                    else:
                        async with self.operation_lock:
                            await self.client.delete_messages(entity, [job.target_message_id])
                    logger.info(
                        "Synchronized delete source={} message={} target={} target_message={}",
                        source_id,
                        message_id,
                        target.id,
                        job.target_message_id,
                    )
                except Exception as exc:  # noqa: BLE001 - one target failure must not stop others
                    logger.warning(
                        "Delete sync failed source={} message={} target={} error={}",
                        source_id,
                        message_id,
                        target.id,
                        exc,
                    )

    async def _successful_jobs_for_source_message(
        self,
        source_id: int | None,
        message_id: int,
    ) -> list[DeliveryJob]:
        async with self.session_factory() as session:
            statement = select(DeliveryJob).where(
                DeliveryJob.status == "success",
                DeliveryJob.target_message_id.is_not(None),
            )
            if source_id is not None:
                statement = statement.where(DeliveryJob.source_id == source_id)
            rows = list(await session.scalars(statement))
        matched: list[DeliveryJob] = []
        for job in rows:
            try:
                message_ids = json.loads(job.source_message_ids or "[]")
            except (TypeError, json.JSONDecodeError):
                message_ids = [job.source_message_id]
            if message_id in message_ids or message_id == job.source_message_id:
                matched.append(job)
        return matched

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
        if command.command_type == COMMAND_MANUAL_POST:
            target_ids = [int(item) for item in payload.get("target_ids") or []]
            text = str(payload.get("text") or "")
            image_path = str(payload.get("image_path") or "")
            if not target_ids:
                raise ValueError("手动发帖至少需要一个目标。")
            if not text and not image_path:
                raise ValueError("手动发帖需要文字或图片。")
            sent: list[dict[str, int]] = []
            for target_id in target_ids:
                async with self.session_factory() as session:
                    target = await session.get(Target, target_id)
                if target is None or not target.enabled:
                    continue
                entity = target.tg_id or target.raw_input
                async with self.operation_lock:
                    if image_path:
                        path = Path(image_path)
                        if not path.is_absolute():
                            path = self.config.project_root / path
                        if not path.exists():
                            raise ValueError(f"帖子图片不存在：{image_path}")
                        result = await self.client.send_file(
                            entity,
                            str(path),
                            caption=text or None,
                        )
                    else:
                        result = await self.client.send_message(entity, text)
                sent.append({"target_id": target_id, "message_id": int(getattr(result, "id", 0))})
            return {"sent": sent}
        if command.command_type == COMMAND_CHECK_ACCESS:
            return await self._check_access(payload)
        if command.command_type == COMMAND_NOTIFY_ADMINS:
            text = str(payload.get("text") or "TG-Mirror-Bot 异常通知")
            if self.notifier is not None:
                await self.notifier.send(text)
            return {"notified": self.notifier is not None}
        if command.command_type == COMMAND_SYNC:
            source_value = payload.get("source_id", "all")
            limit = int(payload.get("limit") or self.config.history.default_limit)
            raw_keywords = payload.get("keywords")
            fuzzy_keywords = (
                [str(item).strip() for item in raw_keywords if str(item).strip()]
                if isinstance(raw_keywords, list)
                else []
            )
            recent = bool(payload.get("recent", True))
            if source_value == "all":
                results = await self.history.sync_all(
                    limit=limit,
                    fuzzy_keywords=fuzzy_keywords or None,
                    recent=recent,
                )
                return {"results": results}
            inspected = await self.history.sync_source(
                int(source_value),
                limit=limit,
                fuzzy_keywords=fuzzy_keywords or None,
                recent=recent,
            )
            return {"source_id": int(source_value), "inspected": inspected}
        raise ValueError(f"不支持的控制命令：{command.command_type}")

    async def _check_access(self, payload: dict[str, Any]) -> dict[str, Any]:
        me = await self.client.get_me()
        results: list[dict[str, Any]] = []

        for source_id in [int(item) for item in payload.get("source_ids") or []]:
            async with self.session_factory() as session:
                source = await session.get(Source, source_id)
            if source is None:
                results.append(
                    {
                        "kind": "source",
                        "id": source_id,
                        "name": f"源 {source_id}",
                        "ok": False,
                        "message": "搬运源不存在",
                    }
                )
                continue
            entity = source.tg_id or source.raw_input
            try:
                if self.operation_lock is None:
                    await self.client.get_messages(entity, limit=1)
                else:
                    async with self.operation_lock:
                        await self.client.get_messages(entity, limit=1)
            except Exception as exc:  # noqa: BLE001 - report Telegram access failures
                results.append(
                    {
                        "kind": "source",
                        "id": source_id,
                        "name": source.display_name or source.title or source.raw_input,
                        "ok": False,
                        "message": f"无法读取消息：{type(exc).__name__}: {exc}",
                    }
                )
            else:
                results.append(
                    {
                        "kind": "source",
                        "id": source_id,
                        "name": source.display_name or source.title or source.raw_input,
                        "ok": True,
                        "message": "可以读取消息",
                    }
                )

        for target_id in [int(item) for item in payload.get("target_ids") or []]:
            async with self.session_factory() as session:
                target = await session.get(Target, target_id)
            if target is None:
                results.append(
                    {
                        "kind": "target",
                        "id": target_id,
                        "name": f"目标 {target_id}",
                        "ok": False,
                        "message": "接收目标不存在",
                    }
                )
                continue
            entity = target.tg_id or target.raw_input
            try:
                if self.operation_lock is None:
                    permissions = await self.client.get_permissions(entity, me)
                else:
                    async with self.operation_lock:
                        permissions = await self.client.get_permissions(entity, me)
                can_send = bool(
                    getattr(permissions, "is_admin", False)
                    or getattr(permissions, "is_creator", False)
                    or getattr(permissions, "send_messages", False)
                    or getattr(permissions, "post_messages", False)
                )
            except Exception as exc:  # noqa: BLE001 - report Telegram permission failures
                results.append(
                    {
                        "kind": "target",
                        "id": target_id,
                        "name": target.display_name or target.title or target.raw_input,
                        "ok": False,
                        "message": f"无法检查发送权限：{type(exc).__name__}: {exc}",
                    }
                )
            else:
                results.append(
                    {
                        "kind": "target",
                        "id": target_id,
                        "name": target.display_name or target.title or target.raw_input,
                        "ok": can_send,
                        "message": (
                            "可以发送/发帖"
                            if can_send
                            else "没有发送或发帖权限（可能被禁言或不是频道管理员）"
                        ),
                    }
                )

        return {"results": results}

    async def _consume_queue(self) -> None:
        while True:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                if is_runtime_stopped(self.control_path):
                    await self._cancel_waiting_work()
                    continue
                await self._process_control_command_once()
                await self._process_transfer_queue()
                continue

            try:
                if item is None:
                    return
                if is_runtime_stopped(self.control_path):
                    continue
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
                await self._process_control_command_once()
                if is_runtime_stopped(self.control_path):
                    await self._cancel_waiting_work()
                    continue
                await self._process_transfer_queue()
            finally:
                self.queue.task_done()




