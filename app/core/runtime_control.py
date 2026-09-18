"""Persistent pause/resume state shared by CLI, bot and runtime."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


def read_runtime_control(path: Path) -> dict[str, Any]:
    """Read runtime control state, defaulting to running."""
    if not path.exists():
        return {"paused": False, "stop_requested": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"paused": False, "stop_requested": False}
    if not isinstance(payload, dict):
        return {"paused": False, "stop_requested": False}
    payload["paused"] = bool(payload.get("paused", False))
    payload["stop_requested"] = bool(payload.get("stop_requested", False))
    return payload


def is_runtime_paused(path: Path) -> bool:
    """Return whether delivery processing is paused."""
    return bool(read_runtime_control(path).get("paused"))


def is_runtime_stopped(path: Path) -> bool:
    """Return whether delivery processing has been stopped."""
    return bool(read_runtime_control(path).get("stop_requested"))


def _write_runtime_control(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
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


def set_runtime_paused(path: Path, paused: bool) -> dict[str, Any]:
    """Persist pause/resume state without losing the stop flag."""
    current = read_runtime_control(path)
    payload = {
        "paused": paused,
        "stop_requested": bool(current.get("stop_requested", False)),
    }
    return _write_runtime_control(path, payload)


def set_runtime_stop_requested(path: Path, stopped: bool) -> dict[str, Any]:
    """Persist the stop flag without losing pause state."""
    current = read_runtime_control(path)
    payload = {
        "paused": bool(current.get("paused", False)),
        "stop_requested": stopped,
    }
    return _write_runtime_control(path, payload)


