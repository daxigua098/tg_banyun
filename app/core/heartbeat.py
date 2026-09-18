"""Runtime heartbeat persistence for status monitoring and supervision."""

from __future__ import annotations

import ctypes
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


def _windows_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
    except (AttributeError, OSError):
        return False
    if handle:
        kernel32.CloseHandle(handle)
        return True
    # ERROR_ACCESS_DENIED means the process exists but belongs to another user.
    return ctypes.get_last_error() == 5


def is_process_running(pid: int) -> bool:
    """Return whether a local PID appears to still exist."""
    if os.name == "nt":
        return _windows_process_running(pid)

    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
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
