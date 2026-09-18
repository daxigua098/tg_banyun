from __future__ import annotations

import os

from app.core.heartbeat import HeartbeatWriter, is_process_running, read_runtime_status


def test_heartbeat_round_trip(tmp_path) -> None:
    path = tmp_path / "runtime_status.json"
    writer = HeartbeatWriter(path)

    payload = writer.write(status="running", source_count=2)

    assert payload["status"] == "running"
    assert payload["source_count"] == 2
    status = read_runtime_status(path)
    assert status is not None
    assert status["pid"] == os.getpid()
    assert status["started_at"] == status["heartbeat_at"]


def test_heartbeat_stopped_status(tmp_path) -> None:
    path = tmp_path / "runtime_status.json"
    writer = HeartbeatWriter(path)
    writer.write(status="running")
    stopped = writer.write(status="stopped")

    assert stopped["status"] == "stopped"
    assert "stopped_at" in stopped


def test_process_running_check() -> None:
    assert is_process_running(os.getpid()) is True
    assert is_process_running(2_147_483_647) is False
