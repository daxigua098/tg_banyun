"""Management of Telegram chats that receive delivery records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient

from app.core.source_resolver import resolve_chat_input
from app.models import RecordTarget
from app.services.source_service import _entity_info, _resolve_entity


async def add_record_target(
    session: AsyncSession,
    client: TelegramClient,
    raw_input: str,
    *,
    join: bool = False,
) -> RecordTarget:
    """Resolve and persist a record receiving chat."""
    resolved = resolve_chat_input(raw_input)
    existing = await session.scalar(
        select(RecordTarget).where(RecordTarget.normalized_key == resolved.normalized_key)
    )
    if existing is not None:
        return existing

    entity = await _resolve_entity(client, resolved, join=join)
    tg_id, title, username, _ = _entity_info(entity)
    existing = await session.scalar(select(RecordTarget).where(RecordTarget.tg_id == tg_id))
    if existing is not None:
        return existing

    target = RecordTarget(
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


async def list_record_targets(session: AsyncSession) -> list[RecordTarget]:
    """List record receivers in deterministic order."""
    result = await session.scalars(
        select(RecordTarget).order_by(RecordTarget.id.asc())
    )
    return list(result)


async def set_record_target_enabled(
    session: AsyncSession,
    target_id: int,
    enabled: bool,
) -> RecordTarget:
    """Enable or disable a record receiver."""
    target = await session.get(RecordTarget, target_id)
    if target is None:
        raise ValueError(f"Record target {target_id} does not exist.")
    target.enabled = enabled
    await session.commit()
    await session.refresh(target)
    return target
