"""Runtime heartbeat persistence for status monitoring and supervision."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


def read_runtime_status(path: Path) -> dict[str, Any] | None:
    """Read the latest runtime heartbeat, returning None when unavailable."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def is_process_running(pid: int) -> bool:
    """Return whether a local PID appears to still exist."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class HeartbeatWriter:
    """Write runtime status atomically for CLI and management bot readers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, *, status: str, **extra: Any) -> dict[str, Any]:
        """Persist one heartbeat and return the written payload."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        existing = read_runtime_status(self.path) or {}
        payload = {
            **existing,
            **extra,
            "status": status,
            "pid": os.getpid(),
            "heartbeat_at": now,
        }
        if status == "running" and not payload.get("started_at"):
            payload["started_at"] = now
        if status in {"stopped", "error"}:
            payload["stopped_at"] = now

        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError:
            logger.exception("Failed to write runtime heartbeat: {}", self.path)
        return payload
