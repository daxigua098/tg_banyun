from __future__ import annotations

from app.core.runtime_control import (
    is_runtime_paused,
    is_runtime_stopped,
    read_runtime_control,
    set_runtime_paused,
    set_runtime_stop_requested,
)


def test_runtime_control_round_trip(tmp_path) -> None:
    path = tmp_path / "runtime_control.json"
    assert is_runtime_paused(path) is False

    set_runtime_paused(path, True)
    assert is_runtime_paused(path) is True
    assert read_runtime_control(path)["paused"] is True

    set_runtime_paused(path, False)
    assert is_runtime_paused(path) is False


def test_runtime_stop_flag_is_preserved_by_pause_and_resume(tmp_path) -> None:
    path = tmp_path / "runtime_control.json"

    set_runtime_stop_requested(path, True)
    assert is_runtime_stopped(path) is True

    set_runtime_paused(path, True)
    state = read_runtime_control(path)
    assert state["paused"] is True
    assert state["stop_requested"] is True

    set_runtime_stop_requested(path, False)
    assert is_runtime_stopped(path) is False
    assert is_runtime_paused(path) is True
