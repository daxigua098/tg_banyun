"""Source, target and route management services."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient, utils
from telethon.errors import UserAlreadyParticipantError

from app.core.source_resolver import ResolvedChat, resolve_chat_input
from app.models import Route, Source, Target


def _entity_info(entity: Any) -> tuple[int, str | None, str | None, bool]:
    """Return a stable marked Telegram ID and display metadata."""
    tg_id = int(utils.get_peer_id(entity))
    username = getattr(entity, "username", None)
    title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
    is_private = username is None
    return tg_id, title, username, is_private


async def _resolve_entity(
    client: TelegramClient,
    resolved: ResolvedChat,
    *,
    join: bool,
) -> Any:
    if resolved.kind == "invite":
        invite = resolved.value
        if not join:
            raise ValueError(
                "Private invite links require --join so the userbot can join the chat first."
            )
        try:
            result = await client.join_chat(f"https://t.me/+{invite}")
            return result if hasattr(result, "id") else await client.get_entity(f"https://t.me/+{invite}")
        except UserAlreadyParticipantError:
            return await client.get_entity(f"https://t.me/+{invite}")

    entity = await client.get_entity(resolved.value)
    if join:
        try:
            await client.join_chat(entity)
        except UserAlreadyParticipantError:
            pass
    return entity


async def add_source(
    session: AsyncSession,
    client: TelegramClient,
    raw_input: str,
    *,
    join: bool = False,
) -> Source:
    """Resolve and persist one Telegram source."""
    resolved = resolve_chat_input(raw_input)
    existing = await session.scalar(
        select(Source).where(Source.normalized_key == resolved.normalized_key)
    )
    if existing is not None:
        return existing

    entity = await _resolve_entity(client, resolved, join=join)
    tg_id, title, username, is_private = _entity_info(entity)
    existing = await session.scalar(select(Source).where(Source.tg_id == tg_id))
    if existing is not None:
        return existing

    source = Source(
        raw_input=raw_input,
        normalized_key=resolved.normalized_key,
        tg_id=tg_id,
        username=username,
        title=title or str(tg_id),
        is_private=is_private,
        join_status="joined",
        sync_status="pending",
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def add_target(
    session: AsyncSession,
    client: TelegramClient,
    raw_input: str,
) -> Target:
    """Resolve and persist one Telegram target."""
    resolved = resolve_chat_input(raw_input)
    if resolved.kind == "invite":
        raise ValueError("Targets cannot be added through private invite links in this MVP.")

    existing = await session.scalar(
        select(Target).where(Target.normalized_key == resolved.normalized_key)
    )
    if existing is not None:
        return existing

    entity = await client.get_entity(resolved.value)
    tg_id, title, username, _ = _entity_info(entity)
    existing = await session.scalar(select(Target).where(Target.tg_id == tg_id))
    if existing is not None:
        return existing

    target = Target(
        raw_input=raw_input,
        normalized_key=resolved.normalized_key,
        tg_id=tg_id,
        username=username,
        title=title or str(tg_id),
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return target


async def add_route(
    session: AsyncSession,
    source_id: int,
    target_id: int,
) -> Route:
    """Create an idempotent source-to-target route."""
    source = await session.get(Source, source_id)
    target = await session.get(Target, target_id)
    if source is None:
        raise ValueError(f"Source {source_id} does not exist.")
    if target is None:
        raise ValueError(f"Target {target_id} does not exist.")

    existing = await session.scalar(
        select(Route).where(Route.source_id == source_id, Route.target_id == target_id)
    )
    if existing is not None:
        return existing

    route = Route(source_id=source_id, target_id=target_id)
    session.add(route)
    await session.commit()
    await session.refresh(route)
    return route


async def list_sources(session: AsyncSession) -> list[Source]:
    """List sources in deterministic processing order."""
    result = await session.scalars(
        select(Source).order_by(Source.priority.asc(), Source.id.asc())
    )
    return list(result)


async def list_targets(session: AsyncSession) -> list[Target]:
    """List targets in deterministic order."""
    result = await session.scalars(select(Target).order_by(Target.id.asc()))
    return list(result)


async def list_routes(session: AsyncSession) -> list[Route]:
    """List route bindings."""
    result = await session.scalars(select(Route).order_by(Route.source_id.asc(), Route.id.asc()))
    return list(result)
