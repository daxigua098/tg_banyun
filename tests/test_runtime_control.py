from __future__ import annotations

from app.core.runtime_control import is_runtime_paused, read_runtime_control, set_runtime_paused


def test_runtime_control_round_trip(tmp_path) -> None:
    path = tmp_path / "runtime_control.json"
    assert is_runtime_paused(path) is False

    set_runtime_paused(path, True)
    assert is_runtime_paused(path) is True
    assert read_runtime_control(path)["paused"] is True

    set_runtime_paused(path, False)
    assert is_runtime_paused(path) is False
