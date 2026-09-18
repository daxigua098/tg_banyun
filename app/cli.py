"""Command-line interface for the sequential Telegram mirroring MVP."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import PROJECT_ROOT, AppConfig, load_config
from app.core.client import (
    create_management_bot_client,
    create_telegram_client,
    start_client,
    start_management_bot_client,
)
from app.core.heartbeat import is_process_running, read_runtime_status
from app.core.runtime_control import is_runtime_paused, set_runtime_paused
from app.core.runtime_lock import RuntimeLock
from app.core.transfer import SequentialTransferService
from app.database import dispose_database, get_session_factory, init_database
from app.models import DeliveryJob, Route, Source, Target
from app.services.backup_service import BackupError, create_backup, restore_backup
from app.services.history_service import HistorySyncService
from app.services.management_bot_service import ManagementBotService
from app.services.management_command_service import ManagementCommandService
from app.services.record_service import (
    add_record_target,
    list_record_targets,
    set_record_target_enabled,
)
from app.services.runtime_service import RuntimeService
from app.services.source_service import (
    add_route,
    add_source,
    add_target,
    list_routes,
    list_sources,
    list_targets,
)


def _configure_logging(config: AppConfig) -> None:
    logger.remove()
    logger.add(sys.stderr, level=config.logging.level.upper())
    log_path = Path(config.logging.file)
    if not log_path.is_absolute():
        log_path = PROJECT_ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_path,
        level=config.logging.level.upper(),
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
    )


async def _prepare(config_path: str | None) -> tuple[AppConfig, async_sessionmaker[AsyncSession]]:
    config = load_config(config_path)
    _configure_logging(config)
    await init_database(config)
    return config, get_session_factory()


def _print_source(source: Source) -> None:
    print(
        f"{source.id:>4}  {source.sync_status:<10} "
        f"last={source.last_synced_message_id:<8} {source.title or source.raw_input}"
    )


def _print_target(target: Target) -> None:
    print(f"{target.id:>4}  enabled={str(target.enabled):<5} {target.title or target.raw_input}")


def _print_route(route: Route, source: Source | None, target: Target | None) -> None:
    source_name = source.title if source else str(route.source_id)
    target_name = target.title if target else str(route.target_id)
    print(f"{route.id:>4}  {route.source_id} -> {route.target_id}  {source_name} -> {target_name}")


async def _with_client(
    config: AppConfig,
    command: Callable[[Any], Awaitable[None]],
) -> None:
    client = create_telegram_client(config)
    try:
        await start_client(client, config)
        await command(client)
    finally:
        if client.is_connected():
            await client.disconnect()


async def _start_management_bot(
    config: AppConfig,
    user_client: Any,
    session_factory: async_sessionmaker[AsyncSession],
    transfer: SequentialTransferService,
    operation_lock: asyncio.Lock,
) -> tuple[Any, ManagementBotService]:
    bot_client = create_management_bot_client(config)
    try:
        await start_management_bot_client(bot_client, config)
        bot_me = await bot_client.get_me()
        logger.info(
            "Management bot connected id={} username={}",
            bot_me.id,
            getattr(bot_me, "username", None),
        )
    except Exception:
        if bot_client.is_connected():
            await bot_client.disconnect()
        raise

    command_service = ManagementCommandService(
        user_client,
        session_factory,
        transfer,
        config,
        operation_lock=operation_lock,
    )
    return bot_client, ManagementBotService(bot_client, command_service, config)


async def command_init_db(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    _configure_logging(config)
    await init_database(config)
    print(f"Database initialized: {config.database.url}")


def command_check_config(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if config.management_bot.enabled:
        config.management_bot.validate_ready()
    print(f"Config OK: {config.app.name} ({config.app.environment})")
    print(f"Transfer mode: {config.transfer.mode}")
    print(f"Sequential worker: {config.transfer.sequential}")
    print(f"Worker concurrency: {config.transfer.worker_concurrency}")
    print(f"Management bot enabled: {config.management_bot.enabled}")


async def command_login(args: argparse.Namespace) -> None:
    config, _ = await _prepare(args.config)

    async def run(client: Any) -> None:
        me = await client.get_me()
        print(f"Logged in as: {getattr(me, 'username', None) or me.id} (id={me.id})")

    await _with_client(config, run)


async def command_source_add(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)

    async def run(client: Any) -> None:
        async with session_factory() as session:
            for raw_input in args.inputs:
                source = await add_source(session, client, raw_input, join=args.join)
                print(
                    f"Source [{source.id}] {source.title}: "
                    f"last_synced_message_id={source.last_synced_message_id}"
                )

    await _with_client(config, run)


async def command_source_list(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        sources = await list_sources(session)
    if not sources:
        print("No sources configured.")
        return
    for source in sources:
        _print_source(source)


async def command_target_add(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)

    async def run(client: Any) -> None:
        async with session_factory() as session:
            for raw_input in args.inputs:
                target = await add_target(session, client, raw_input)
                print(f"Target [{target.id}] {target.title}")

    await _with_client(config, run)


async def command_target_list(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        targets = await list_targets(session)
    if not targets:
        print("No targets configured.")
        return
    for target in targets:
        _print_target(target)


async def command_record_add(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)

    async def run(client: Any) -> None:
        async with session_factory() as session:
            for raw_input in args.inputs:
                record_target = await add_record_target(
                    session,
                    client,
                    raw_input,
                    join=args.join,
                )
                print(f"Record target [{record_target.id}] {record_target.title}")

    await _with_client(config, run)


async def command_record_list(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        record_targets = await list_record_targets(session)
    if not record_targets:
        print("No record targets configured.")
        return
    for record_target in record_targets:
        print(
            f"{record_target.id:>4}  enabled={str(record_target.enabled):<5} "
            f"{record_target.title or record_target.raw_input}"
        )


async def command_record_set_enabled(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        target = await set_record_target_enabled(
            session,
            args.target_id,
            args.enabled,
        )
    state = "enabled" if target.enabled else "disabled"
    print(f"Record target [{target.id}] is now {state}.")


async def command_route_add(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        routes = []
        for target_id in args.targets:
            routes.append(await add_route(session, args.source, target_id))
    for route in routes:
        print(f"Route [{route.id}] {route.source_id} -> {route.target_id}")


async def command_route_list(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        routes = await list_routes(session)
        source_map = {source.id: source for source in await list_sources(session)}
        target_map = {target.id: target for target in await list_targets(session)}
    if not routes:
        print("No routes configured.")
        return
    for route in routes:
        _print_route(route, source_map.get(route.source_id), target_map.get(route.target_id))


async def command_sync_history(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)

    async def run(client: Any) -> None:
        operation_lock = asyncio.Lock()
        transfer = SequentialTransferService(
            client,
            session_factory,
            config,
            operation_lock=operation_lock,
        )
        history = HistorySyncService(
            client,
            session_factory,
            transfer,
            config,
            operation_lock=operation_lock,
        )
        if args.all:
            results = await history.sync_all(limit=args.limit)
            for source_id, inspected in results.items():
                print(f"Source {source_id}: inspected {inspected} message(s)")
        else:
            inspected = await history.sync_source(args.source, limit=args.limit)
            print(f"Source {args.source}: inspected {inspected} message(s)")
        processed = await transfer.process_pending()
        print(f"Processed {processed} delivery job(s).")

    with RuntimeLock(config.project_root / "data" / "runtime.lock"):
        await _with_client(config, run)


async def command_run(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)

    async def run(client: Any) -> None:
        operation_lock = asyncio.Lock()
        transfer = SequentialTransferService(
            client,
            session_factory,
            config,
            operation_lock=operation_lock,
        )
        runtime_config = config
        if args.skip_history:
            runtime_config = config.model_copy(
                update={
                    "history": config.history.model_copy(update={"enabled": False})
                }
            )
        runtime = RuntimeService(
            client,
            session_factory,
            transfer,
            runtime_config,
            operation_lock=operation_lock,
        )

        tasks = [asyncio.create_task(runtime.run(), name="userbot-runtime")]
        bot_client: Any | None = None
        if config.management_bot.enabled:
            bot_client, bot_service = await _start_management_bot(
                config,
                client,
                session_factory,
                transfer,
                operation_lock,
            )
            tasks.append(
                asyncio.create_task(bot_service.run(), name="management-bot-runtime")
            )

        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if bot_client is not None and bot_client.is_connected():
                await bot_client.disconnect()

    with RuntimeLock(config.project_root / "data" / "runtime.lock"):
        await _with_client(config, run)


async def command_bot(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)
    if not config.management_bot.enabled:
        raise ValueError("Management bot is disabled. Set management_bot.enabled=true.")

    async def run(client: Any) -> None:
        operation_lock = asyncio.Lock()
        transfer = SequentialTransferService(
            client,
            session_factory,
            config,
            operation_lock=operation_lock,
        )
        bot_client, bot_service = await _start_management_bot(
            config,
            client,
            session_factory,
            transfer,
            operation_lock,
        )
        try:
            await bot_service.run()
        finally:
            if bot_client.is_connected():
                await bot_client.disconnect()

    with RuntimeLock(config.project_root / "data" / "runtime.lock"):
        await _with_client(config, run)


async def command_pause(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    set_runtime_paused(config.project_root / "data" / "runtime_control.json", True)
    print("Runtime paused. New jobs will remain queued.")


async def command_resume(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    set_runtime_paused(config.project_root / "data" / "runtime_control.json", False)
    print("Runtime resumed.")


async def command_backup(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    archive = create_backup(config.project_root, output_dir=args.output)
    print(f"Backup created: {archive}")


async def command_restore(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    try:
        restored = restore_backup(
            config.project_root,
            Path(args.archive),
            yes=args.yes,
        )
    except BackupError as exc:
        raise ValueError(str(exc)) from exc
    print("Restored: " + ", ".join(restored))


async def command_status(args: argparse.Namespace) -> None:
    config, session_factory = await _prepare(args.config)
    heartbeat = read_runtime_status(config.project_root / "data" / "runtime_status.json")

    if heartbeat is None:
        state = "not_started"
    elif heartbeat.get("status") != "running":
        state = str(heartbeat.get("status") or "unknown")
    else:
        pid = int(heartbeat.get("pid") or 0)
        state = "running" if is_process_running(pid) else "stale"

    async with session_factory() as session:
        source_total = int(await session.scalar(select(func.count()).select_from(Source)) or 0)
        target_total = int(await session.scalar(select(func.count()).select_from(Target)) or 0)
        route_total = int(await session.scalar(select(func.count()).select_from(Route)) or 0)
        job_rows = await session.execute(
            select(DeliveryJob.status, func.count(DeliveryJob.id)).group_by(DeliveryJob.status)
        )
        jobs = {str(status): int(count) for status, count in job_rows.all()}

    paused = is_runtime_paused(config.project_root / "data" / "runtime_control.json")
    print(f"Runtime state: {state}")
    print(f"Paused: {paused}")
    if heartbeat:
        print(f"PID: {heartbeat.get('pid')}")
        print(f"Started at: {heartbeat.get('started_at')}")
        print(f"Heartbeat at: {heartbeat.get('heartbeat_at')}")
        print(f"Queue size: {heartbeat.get('queue_size', 0)}")
        print(f"Last backup: {heartbeat.get('last_backup_at') or 'not recorded'}")
    print(f"Sources: {source_total}")
    print(f"Targets: {target_total}")
    print(f"Routes: {route_total}")
    print("Jobs: " + (", ".join(f"{key}={value}" for key, value in sorted(jobs.items())) or "0"))


async def command_stats(args: argparse.Namespace) -> None:
    _, session_factory = await _prepare(args.config)
    async with session_factory() as session:
        rows = await session.execute(
            select(DeliveryJob.status, func.count(DeliveryJob.id)).group_by(DeliveryJob.status)
        )
        stats = {str(status): int(count) for status, count in rows.all()}

    if not stats:
        print("No delivery jobs yet.")
        return
    for status, count in sorted(stats.items()):
        print(f"{status:<12} {count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="Sequential Telegram mirror bot")
    parser.add_argument("--config", help="Path to config.yaml", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create database tables")
    subparsers.add_parser("check-config", help="Validate configuration")
    subparsers.add_parser("login", help="Login and save the Telegram session")

    source = subparsers.add_parser("source", help="Manage sources")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    source_add = source_sub.add_parser("add", help="Add one or more sources")
    source_add.add_argument("inputs", nargs="+")
    source_add.add_argument(
        "--join",
        action="store_true",
        help="Join public/invite sources if needed",
    )
    source_sub.add_parser("list", help="List sources")

    target = subparsers.add_parser("target", help="Manage targets")
    target_sub = target.add_subparsers(dest="target_command", required=True)
    target_add = target_sub.add_parser(
        "add",
        help="Add targets; private invite links must already be joined",
    )
    target_add.add_argument("inputs", nargs="+")
    target_sub.add_parser("list", help="List targets")

    route = subparsers.add_parser("route", help="Manage routes")
    route_sub = route.add_subparsers(dest="route_command", required=True)
    route_add = route_sub.add_parser("add", help="Bind a source to targets")
    route_add.add_argument("--source", type=int, required=True)
    route_add.add_argument("--target", dest="targets", type=int, nargs="+", required=True)
    route_sub.add_parser("list", help="List routes")

    record = subparsers.add_parser("record", help="Manage delivery record receivers")
    record_sub = record.add_subparsers(dest="record_command", required=True)
    record_add = record_sub.add_parser("add", help="Add record receiving chats")
    record_add.add_argument("inputs", nargs="+")
    record_add.add_argument(
        "--join",
        action="store_true",
        help="Join public/private chats before adding them",
    )
    record_sub.add_parser("list", help="List record receiving chats")
    record_enable = record_sub.add_parser("enable", help="Enable a record receiver")
    record_enable.add_argument("target_id", type=int)
    record_enable.set_defaults(enabled=True)
    record_disable = record_sub.add_parser("disable", help="Disable a record receiver")
    record_disable.add_argument("target_id", type=int)
    record_disable.set_defaults(enabled=False)

    sync_history = subparsers.add_parser("sync-history", help="Synchronize historical messages")
    sync_history_group = sync_history.add_mutually_exclusive_group(required=True)
    sync_history_group.add_argument("--all", action="store_true")
    sync_history_group.add_argument("--source", type=int)
    sync_history.add_argument("--limit", type=int, default=None)

    run = subparsers.add_parser("run", help="Run userbot and management bot if enabled")
    run.add_argument(
        "--skip-history",
        action="store_true",
        help="Do not run automatic history catch-up at startup",
    )
    subparsers.add_parser("bot", help="Run only the management bot")
    backup = subparsers.add_parser("backup", help="Create a backup archive")
    backup.add_argument("--output", type=Path, default=None)
    restore = subparsers.add_parser("restore", help="Restore from a backup archive")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--yes", action="store_true", help="Confirm overwrite")
    subparsers.add_parser("pause", help="Pause delivery processing")
    subparsers.add_parser("resume", help="Resume delivery processing")
    subparsers.add_parser("status", help="Show runtime and database status")
    subparsers.add_parser("stats", help="Show delivery statistics")
    return parser


async def _dispatch(args: argparse.Namespace) -> None:
    if args.command == "init-db":
        await command_init_db(args)
    elif args.command == "check-config":
        command_check_config(args)
    elif args.command == "login":
        await command_login(args)
    elif args.command == "source":
        if args.source_command == "add":
            await command_source_add(args)
        else:
            await command_source_list(args)
    elif args.command == "target":
        if args.target_command == "add":
            await command_target_add(args)
        else:
            await command_target_list(args)
    elif args.command == "route":
        if args.route_command == "add":
            await command_route_add(args)
        else:
            await command_route_list(args)
    elif args.command == "record":
        if args.record_command == "add":
            await command_record_add(args)
        elif args.record_command == "list":
            await command_record_list(args)
        else:
            await command_record_set_enabled(args)
    elif args.command == "sync-history":
        await command_sync_history(args)
    elif args.command == "run":
        await command_run(args)
    elif args.command == "bot":
        await command_bot(args)
    elif args.command == "pause":
        await command_pause(args)
    elif args.command == "resume":
        await command_resume(args)
    elif args.command == "status":
        await command_status(args)
    elif args.command == "backup":
        await command_backup(args)
    elif args.command == "restore":
        await command_restore(args)
    elif args.command == "stats":
        await command_stats(args)


async def _run_cli(args: argparse.Namespace) -> None:
    try:
        await _dispatch(args)
    finally:
        await dispose_database()


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(_run_cli(args))
        return 0
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI should show a concise error
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
