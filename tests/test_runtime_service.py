from __future__ import annotations

from types import SimpleNamespace

from app.config import AppConfig
from app.services.runtime_service import RuntimeService


def test_runtime_service_initializes_album_filter() -> None:
    service = RuntimeService(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        AppConfig(),
    )
    assert service._album_filter is not None
