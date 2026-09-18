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
from app.core.runtime_lock import RuntimeLock
from app.core.transfer import SequentialTransferService
from app.database import dispose_database, get_session_factory, init_database
from app.models import DeliveryJob, Route, Source, Target
from app.services.history_service import HistorySyncService
from app.services.management_bot_service import ManagementBotService
from app.services.management_command_service import ManagementCommandService
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
        runtime = RuntimeService(
            client,
            session_factory,
            transfer,
            config,
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
    target_add = target_sub.add_parser("add", help="Add one or more targets")
    target_add.add_argument("inputs", nargs="+")
    target_sub.add_parser("list", help="List targets")

    route = subparsers.add_parser("route", help="Manage routes")
    route_sub = route.add_subparsers(dest="route_command", required=True)
    route_add = route_sub.add_parser("add", help="Bind a source to targets")
    route_add.add_argument("--source", type=int, required=True)
    route_add.add_argument("--target", dest="targets", type=int, nargs="+", required=True)
    route_sub.add_parser("list", help="List routes")

    sync_history = subparsers.add_parser("sync-history", help="Synchronize historical messages")
    sync_history_group = sync_history.add_mutually_exclusive_group(required=True)
    sync_history_group.add_argument("--all", action="store_true")
    sync_history_group.add_argument("--source", type=int)
    sync_history.add_argument("--limit", type=int, default=None)

    subparsers.add_parser("run", help="Run userbot and management bot if enabled")
    subparsers.add_parser("bot", help="Run only the management bot")
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
    elif args.command == "sync-history":
        await command_sync_history(args)
    elif args.command == "run":
        await command_run(args)
    elif args.command == "bot":
        await command_bot(args)
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
