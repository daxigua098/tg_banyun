from __future__ import annotations

import pytest

from app.core.runtime_lock import RuntimeLock, RuntimeLockError


def test_runtime_lock_rejects_second_owner(tmp_path) -> None:
    path = tmp_path / "runtime.lock"

    with RuntimeLock(path):
        with pytest.raises(RuntimeLockError):
            with RuntimeLock(path):
                pass

    with RuntimeLock(path):
        pass
