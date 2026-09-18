"""Persistent pause/resume state shared by CLI, bot and runtime."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


def read_runtime_control(path: Path) -> dict[str, Any]:
    """Read runtime control state, defaulting to unpaused."""
    if not path.exists():
        return {"paused": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"paused": False}
    if not isinstance(payload, dict):
        return {"paused": False}
    payload["paused"] = bool(payload.get("paused", False))
    return payload


def is_runtime_paused(path: Path) -> bool:
    """Return whether delivery processing is paused."""
    return bool(read_runtime_control(path).get("paused"))


def set_runtime_paused(path: Path, paused: bool) -> dict[str, Any]:
    """Persist pause/resume state atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "paused": paused,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        logger.exception("Failed to write runtime control state: {}", path)
    return payload


