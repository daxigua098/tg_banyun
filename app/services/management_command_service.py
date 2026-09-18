"""Commands handled by the Telegram management bot."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import AppConfig
from app.core.heartbeat import is_process_running, read_runtime_status
from app.core.runtime_control import is_runtime_paused, set_runtime_paused
from app.core.transfer import SequentialTransferService
from app.models import DeliveryJob, Route, Source, Target
from app.services.history_service import HistorySyncService
from app.services.record_service import add_record_target, list_record_targets
from app.services.rule_service import (
    get_source_rule,
    list_source_rules,
    load_keywords,
    set_source_rule,
)
from app.services.source_service import (
    add_route,
    add_source,
    add_target,
    delete_route,
    list_routes,
    list_sources,
    list_targets,
    set_source_enabled,
    set_target_enabled,
)

HELP_TEXT = """TG-Mirror-Bot 管理菜单

控制面板
/menu  打开中文按钮控制面板

状态与统计
/status  运行状态
/stats  投递统计
/jobs [状态] [数量]  最近任务

配置查看
/sources  搬运源
/targets  接收目标
/routes  路由关系
/rules  查看每源过滤规则

运行控制
/pause  暂停搬运
/resume  恢复搬运
/retry_failed [任务ID]  重试失败

输入 /help all 查看完整菜单。
"""

FULL_HELP_TEXT = """TG-Mirror-Bot 完整菜单

控制面板
/menu  打开中文按钮控制面板

状态与统计
/status  查看运行状态
/stats  查看投递统计
/jobs [状态] [数量]  查看最近任务

源、目标与路由
/sources  查看搬运源
/targets  查看接收目标
/routes  查看路由关系
/sync <源ID|all> [数量]  同步历史消息

运行控制
/pause  暂停搬运
/resume  恢复搬运
/retry_failed [任务ID]  重试失败任务

添加与开关
/source_add [--join] <频道/群组> [...]
/target_add <频道/群组> [...]
/source_enable <源ID> [...]
/source_disable <源ID> [...]
/target_enable <目标ID> [...]
/target_disable <目标ID> [...]
/route_add <源ID> <目标ID> [...]
/route_delete <源ID> <目标ID>

每源过滤规则
/rules  查看全部规则
/rule <源ID>  查看单个规则
/rule_set <源ID> <字段> <值>
字段：
photo on/off、video on/off、forwarded skip/allow、post on/off、admin on/off
whitelist 词1,词2、blacklist 词1,词2

记录接收群
/record_add [--join] <群组> [...]
/records  查看记录接收群

/help  查看精简菜单
"""


class ManagementCommandService:
    """Execute management commands against the same database and userbot session."""

    def __init__(
        self,
        user_client: Any,
        session_factory: async_sessionmaker[AsyncSession],
        transfer: SequentialTransferService,
        config: AppConfig,
        operation_lock: asyncio.Lock | None = None,
    ) -> None:
        self.user_client = user_client
        self.session_factory = session_factory
        self.transfer = transfer
        self.config = config
        self.operation_lock = operation_lock
        self.history = HistorySyncService(
            user_client,
            session_factory,
            transfer,
            config,
            operation_lock=operation_lock,
        )

    @asynccontextmanager
    async def _operation_context(self) -> AsyncIterator[None]:
        if self.operation_lock is None:
            yield
            return
        async with self.operation_lock:
            yield

    async def handle(self, text: str) -> str:
        """Parse and execute one command, returning a Telegram-safe response."""
        command, args = self._parse(text)
        if command in {"start", "help"}:
            if args and args[0].lower() == "all":
                return FULL_HELP_TEXT.strip()
            return HELP_TEXT.strip()
        if command == "status":
            return await self._status()
        if command == "sources":
            return await self._sources()
        if command == "targets":
            return await self._targets()
        if command == "routes":
            return await self._routes()
        if command == "records":
            return await self._records()
        if command == "stats":
            return await self._stats()
        if command == "rules":
            return await self._rules()
        if command == "rule":
            return await self._rule(args)
        if command == "rule_set":
            return await self._rule_set(args)
        if command == "jobs":
            return await self._jobs(args)
        if command == "pause":
            return await self._pause()
        if command == "resume":
            return await self._resume()
        if command == "sync":
            return await self._sync(args)
        if command == "retry_failed":
            return await self._retry_failed(args)
        if command == "source_add":
            return await self._source_add(args)
        if command == "target_add":
            return await self._target_add(args)
        if command == "source_enable":
            return await self._set_source_enabled(args, True)
        if command == "source_disable":
            return await self._set_source_enabled(args, False)
        if command == "target_enable":
            return await self._set_target_enabled(args, True)
        if command == "target_disable":
            return await self._set_target_enabled(args, False)
        if command == "route_add":
            return await self._route_add(args)
        if command == "route_delete":
            return await self._route_delete(args)
        if command == "record_add":
            return await self._record_add(args)
        return f"未知命令：/{command}\n\n{HELP_TEXT.strip()}"

    @staticmethod
    def _parse(text: str) -> tuple[str, list[str]]:
        parts = text.strip().split()
        if not parts:
            return "", []
        command = parts[0].split("@", maxsplit=1)[0].removeprefix("/").lower()
        return command, parts[1:]

    async def _status(self) -> str:
        async with self.session_factory() as session:
            source_total = await self._count(session, Source)
            source_enabled = await self._count_enabled(session, Source)
            target_total = await self._count(session, Target)
            target_enabled = await self._count_enabled(session, Target)
            route_total = await self._count(session, Route)
            jobs = await self._job_counts(session)
        connected = self.user_client.is_connected()
        heartbeat = read_runtime_status(
            self.config.project_root / "data" / "runtime_status.json"
        )
        if heartbeat is None:
            runtime_state = "未启动"
        elif heartbeat.get("status") != "running":
            runtime_state = str(heartbeat.get("status"))
        else:
            pid = int(heartbeat.get("pid") or 0)
            runtime_state = "运行中" if is_process_running(pid) else "心跳过期"
        paused = is_runtime_paused(
            self.config.project_root / "data" / "runtime_control.json"
        )
        lines = [
            "TG-Mirror-Bot 状态",
            f"运行状态：{runtime_state}",
            f"搬运状态：{'已暂停' if paused else '运行中'}",
            f"最近备份：{(heartbeat or {}).get('last_backup_at') or '未记录'}",
            f"Userbot：{'已连接' if connected else '未连接'}",
            f"源：总 {source_total} / 启用 {source_enabled}",
            f"目标：总 {target_total} / 启用 {target_enabled}",
            f"路由：{route_total}",
            "任务：" + self._format_counts(jobs),
        ]
        return "\n".join(lines)

    async def _sources(self) -> str:
        async with self.session_factory() as session:
            sources = await list_sources(session)
        if not sources:
            return "尚未配置任何源。"
        lines = ["源列表（ID / 状态 / 同步 / 最新消息 / 名称）"]
        for source in sources[:50]:
            lines.append(
                f"{source.id} / {'启用' if source.enabled else '禁用'} / "
                f"{source.sync_status} / {source.last_synced_message_id} / "
                f"{source.title or source.raw_input}"
            )
        if len(sources) > 50:
            lines.append(f"... 仅显示前 50 个，共 {len(sources)} 个")
        return "\n".join(lines)

    async def _targets(self) -> str:
        async with self.session_factory() as session:
            targets = await list_targets(session)
        if not targets:
            return "尚未配置任何目标。"
        lines = ["目标列表（ID / 状态 / 名称）"]
        for target in targets[:50]:
            lines.append(
                f"{target.id} / {'启用' if target.enabled else '禁用'} / "
                f"{target.title or target.raw_input}"
            )
        if len(targets) > 50:
            lines.append(f"... 仅显示前 50 个，共 {len(targets)} 个")
        return "\n".join(lines)

    async def _routes(self) -> str:
        async with self.session_factory() as session:
            routes = await list_routes(session)
            sources = {item.id: item for item in await list_sources(session)}
            targets = {item.id: item for item in await list_targets(session)}
        if not routes:
            return "尚未配置任何路由。"
        lines = ["路由列表（源ID -> 目标ID）"]
        for route in routes[:50]:
            source = sources.get(route.source_id)
            target = targets.get(route.target_id)
            source_name = source.title if source else str(route.source_id)
            target_name = target.title if target else str(route.target_id)
            lines.append(
                f"{route.source_id} -> {route.target_id} / "
                f"{source_name} -> {target_name} / "
                f"{'启用' if route.enabled else '禁用'}"
            )
        if len(routes) > 50:
            lines.append(f"... 仅显示前 50 条，共 {len(routes)} 条")
        return "\n".join(lines)

    async def _records(self) -> str:
        async with self.session_factory() as session:
            record_targets = await list_record_targets(session)
        if not record_targets:
            return "尚未配置搬运记录接收群。"
        lines = ["搬运记录接收群（ID / 状态 / 名称）"]
        for record_target in record_targets:
            lines.append(
                f"{record_target.id} / "
                f"{'启用' if record_target.enabled else '禁用'} / "
                f"{record_target.title or record_target.raw_input}"
            )
        return "\n".join(lines)

    async def _record_add(self, args: list[str]) -> str:
        if not args:
            raise ValueError("用法：/record_add [--join] <群组> [...]")
        join = "--join" in args
        inputs = [item for item in args if item != "--join"]
        if not inputs:
            raise ValueError("请至少提供一个记录接收群。")
        async with self._operation_context():
            async with self.session_factory() as session:
                results = []
                for raw_input in inputs:
                    record_target = await add_record_target(
                        session,
                        self.user_client,
                        raw_input,
                        join=join,
                    )
                    results.append(
                        f"[{record_target.id}] "
                        f"{record_target.title or record_target.raw_input}"
                    )
        return "记录接收群已添加：\n" + "\n".join(results)

    async def _pause(self) -> str:
        set_runtime_paused(
            self.config.project_root / "data" / "runtime_control.json",
            True,
        )
        return "搬运已暂停。新消息仍会持久化到待处理队列。"

    async def _resume(self) -> str:
        set_runtime_paused(
            self.config.project_root / "data" / "runtime_control.json",
            False,
        )
        return "搬运已恢复。"

    async def _rules(self) -> str:
        async with self.session_factory() as session:
            rules = await list_source_rules(session)
        if not rules:
            return "尚未配置任何源。"
        lines = ["每源过滤规则"]
        for source, rule in rules:
            whitelist = ",".join(load_keywords(rule.keyword_whitelist)) or "-"
            blacklist = ",".join(load_keywords(rule.keyword_blacklist)) or "-"
            lines.append(
                f"源 {source.id} {source.title or source.raw_input}\n"
                f"图片={'开' if rule.allow_photo else '关'} "
                f"视频={'开' if rule.allow_video else '关'} "
                f"转发={'跳过' if rule.skip_forwarded else '允许'} "
                f"仅频道={'是' if rule.post_only else '否'} "
                f"仅管理={'是' if rule.admin_only else '否'}\n"
                f"白名单={whitelist} 黑名单={blacklist}"
            )
        return "\n\n".join(lines)

    async def _rule(self, args: list[str]) -> str:
        if len(args) != 1:
            raise ValueError("用法：/rule <源ID>")
        source_id = self._parse_id(args[0], "源ID")
        async with self.session_factory() as session:
            rule = await get_source_rule(session, source_id)
        return (
            f"源 {source_id} 过滤规则\n"
            f"图片：{'开启' if rule.allow_photo else '关闭'}\n"
            f"视频：{'开启' if rule.allow_video else '关闭'}\n"
            f"转发消息：{'跳过' if rule.skip_forwarded else '允许'}\n"
            f"仅频道帖子：{'是' if rule.post_only else '否'}\n"
            f"仅管理员：{'是' if rule.admin_only else '否'}\n"
            f"关键词白名单：{','.join(load_keywords(rule.keyword_whitelist)) or '无'}\n"
            f"关键词黑名单：{','.join(load_keywords(rule.keyword_blacklist)) or '无'}"
        )

    async def _rule_set(self, args: list[str]) -> str:
        if len(args) < 3:
            raise ValueError("用法：/rule_set <源ID> <字段> <值>")
        source_id = self._parse_id(args[0], "源ID")
        field = args[1]
        value = " ".join(args[2:])
        async with self.session_factory() as session:
            rule = await set_source_rule(session, source_id, field, value)
        return (
            f"源 {source_id} 规则已更新\n"
            f"图片={'开' if rule.allow_photo else '关'} "
            f"视频={'开' if rule.allow_video else '关'} "
            f"转发={'跳过' if rule.skip_forwarded else '允许'} "
            f"仅频道={'是' if rule.post_only else '否'} "
            f"仅管理={'是' if rule.admin_only else '否'}\n"
            f"白名单={','.join(load_keywords(rule.keyword_whitelist)) or '-'} "
            f"黑名单={','.join(load_keywords(rule.keyword_blacklist)) or '-'}"
        )

    async def _stats(self) -> str:
        stats = await self.transfer.stats()
        if not stats:
            return "尚无投递任务。"
        return "投递统计\n" + self._format_counts(stats)

    async def _jobs(self, args: list[str]) -> str:
        status = args[0] if args else None
        if status not in {None, "pending", "processing", "retrying", "success", "failed"}:
            raise ValueError("任务状态必须是 pending/processing/retrying/success/failed。")
        limit = self._parse_limit(args[1] if len(args) > 1 else None, default=10)
        async with self.session_factory() as session:
            statement = select(DeliveryJob).order_by(DeliveryJob.id.desc()).limit(limit)
            if status:
                statement = statement.where(DeliveryJob.status == status)
            jobs = list(await session.scalars(statement))
        if not jobs:
            return "没有符合条件的任务。"
        lines = [f"最近任务（{status or '全部'}）"]
        for job in jobs:
            error = f" / {job.last_error[:100]}" if job.last_error else ""
            lines.append(
                f"[{job.id}] {job.source_id}:{job.source_message_id} -> "
                f"{job.target_id} / {job.status} / 尝试 {job.attempt_count}{error}"
            )
        return "\n".join(lines)

    async def _sync(self, args: list[str]) -> str:
        if not args:
            raise ValueError("用法：/sync <源ID|all> [数量]")
        target = args[0].lower()
        limit = self._parse_limit(args[1] if len(args) > 1 else None, default=None)
        if target == "all":
            results = await self.history.sync_all(limit=limit)
            summary = ", ".join(f"{source_id}:{count}" for source_id, count in results.items())
            processed = await self.transfer.process_pending()
            return f"历史同步完成：{summary or '没有启用的源'}；处理任务 {processed} 个。"
        source_id = self._parse_id(target, "源ID")
        inspected = await self.history.sync_source(source_id, limit=limit)
        processed = await self.transfer.process_pending()
        return f"源 {source_id} 同步完成，检查 {inspected} 条；处理任务 {processed} 个。"

    async def _retry_failed(self, args: list[str]) -> str:
        async with self.session_factory() as session:
            statement = update(DeliveryJob).where(DeliveryJob.status == "failed")
            if args:
                statement = statement.where(DeliveryJob.id == self._parse_id(args[0], "任务ID"))
            result = await session.execute(
                statement.values(
                    status="pending",
                    attempt_count=0,
                    next_retry_at=None,
                    last_error=None,
                )
            )
            await session.commit()
            return f"已将 {result.rowcount or 0} 个失败任务重新加入队列。"

    async def _source_add(self, args: list[str]) -> str:
        if not args:
            raise ValueError("用法：/source_add [--join] <频道/群组> [...]")
        join = "--join" in args
        inputs = [item for item in args if item != "--join"]
        if not inputs:
            raise ValueError("请至少提供一个频道或群组。")
        async with self._operation_context():
            async with self.session_factory() as session:
                results = []
                for raw_input in inputs:
                    try:
                        source = await add_source(
                            session,
                            self.user_client,
                            raw_input,
                            join=join,
                        )
                    except ValueError as exc:
                        raise ValueError(f"{raw_input}：{exc}") from exc
                    results.append(f"[{source.id}] {source.title or raw_input}")
        return "源已添加：\n" + "\n".join(results)

    async def _target_add(self, args: list[str]) -> str:
        if not args:
            raise ValueError("用法：/target_add <频道/群组> [...]")
        async with self._operation_context():
            async with self.session_factory() as session:
                results = []
                for raw_input in args:
                    try:
                        target = await add_target(session, self.user_client, raw_input)
                    except ValueError as exc:
                        raise ValueError(f"{raw_input}：{exc}") from exc
                    results.append(f"[{target.id}] {target.title or raw_input}")
        return "目标已添加：\n" + "\n".join(results)

    async def _set_source_enabled(self, args: list[str], enabled: bool) -> str:
        if not args:
            raise ValueError("请至少提供一个源ID。")
        async with self.session_factory() as session:
            changed = []
            for raw_id in args:
                source = await set_source_enabled(session, self._parse_id(raw_id, "源ID"), enabled)
                changed.append(f"[{source.id}] {source.title or source.raw_input}")
        state = "启用" if enabled else "禁用"
        return f"已{state}源：\n" + "\n".join(changed)

    async def _set_target_enabled(self, args: list[str], enabled: bool) -> str:
        if not args:
            raise ValueError("请至少提供一个目标ID。")
        async with self.session_factory() as session:
            changed = []
            for raw_id in args:
                target = await set_target_enabled(
                    session,
                    self._parse_id(raw_id, "目标ID"),
                    enabled,
                )
                changed.append(f"[{target.id}] {target.title or target.raw_input}")
        state = "启用" if enabled else "禁用"
        return f"已{state}目标：\n" + "\n".join(changed)

    async def _route_add(self, args: list[str]) -> str:
        if len(args) < 2:
            raise ValueError("用法：/route_add <源ID> <目标ID> [...]")
        source_id = self._parse_id(args[0], "源ID")
        async with self.session_factory() as session:
            routes = []
            for raw_target_id in args[1:]:
                route = await add_route(
                    session,
                    source_id,
                    self._parse_id(raw_target_id, "目标ID"),
                )
                routes.append(f"[{route.id}] {route.source_id} -> {route.target_id}")
        return "路由已添加：\n" + "\n".join(routes)

    async def _route_delete(self, args: list[str]) -> str:
        if len(args) != 2:
            raise ValueError("用法：/route_delete <源ID> <目标ID>")
        source_id = self._parse_id(args[0], "源ID")
        target_id = self._parse_id(args[1], "目标ID")
        async with self.session_factory() as session:
            removed = await delete_route(session, source_id, target_id)
        return "路由已删除。" if removed else "未找到对应路由。"

    @staticmethod
    def _parse_id(value: str, label: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{label}必须是整数。") from exc
        if parsed <= 0:
            raise ValueError(f"{label}必须是正整数。")
        return parsed

    @staticmethod
    def _parse_limit(value: str | None, *, default: int | None) -> int | None:
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError("数量必须是整数。") from exc
        if parsed <= 0 or parsed > 500:
            raise ValueError("数量必须在 1 到 500 之间。")
        return parsed

    @staticmethod
    async def _count(session: AsyncSession, model: type[Any]) -> int:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)

    @staticmethod
    async def _count_enabled(session: AsyncSession, model: type[Any]) -> int:
        return int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.enabled.is_(True))
            )
            or 0
        )

    @staticmethod
    async def _job_counts(session: AsyncSession) -> dict[str, int]:
        rows = await session.execute(
            select(DeliveryJob.status, func.count(DeliveryJob.id)).group_by(DeliveryJob.status)
        )
        return {str(status): int(count) for status, count in rows.all()}

    @staticmethod
    def _format_counts(counts: dict[str, int]) -> str:
        if not counts:
            return "0"
        return ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))


def truncate_response(text: str, limit: int = 3800) -> str:
    """Keep Telegram responses below the message size limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


