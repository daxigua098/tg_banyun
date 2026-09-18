"""Durable commands executed by the Telegram runtime process."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ControlCommand

COMMAND_ADD_SOURCE = "add_source"
COMMAND_ADD_TARGET = "add_target"
COMMAND_SYNC = "sync"
COMMAND_NOTIFY_ADMINS = "notify_admins"
COMMAND_MANUAL_POST = "manual_post"


async def enqueue_control_command(
    session: AsyncSession,
    command_type: str,
    payload: dict[str, Any],
) -> ControlCommand:
    """Persist one command for the runtime process."""
    supported_commands = {
        COMMAND_ADD_SOURCE,
        COMMAND_ADD_TARGET,
        COMMAND_SYNC,
        COMMAND_NOTIFY_ADMINS,
    }
    if command_type not in supported_commands:
        raise ValueError(f"不支持的控制命令：{command_type}")
    command = ControlCommand(
        command_type=command_type,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    session.add(command)
    await session.commit()
    await session.refresh(command)
    return command


async def list_control_commands(
    session: AsyncSession,
    limit: int = 50,
) -> list[ControlCommand]:
    """Return recent commands newest first."""
    return list(
        await session.scalars(
            select(ControlCommand).order_by(ControlCommand.id.desc()).limit(limit)
        )
    )


def load_command_payload(command: ControlCommand) -> dict[str, Any]:
    """Load command payload JSON with a safe fallback."""
    try:
        payload = json.loads(command.payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}

