from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import AppConfig
from app.services.control_command_service import COMMAND_SYNC
from app.services.runtime_service import RuntimeService


def test_runtime_service_initializes_album_filter() -> None:
    service = RuntimeService(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        AppConfig(),
    )
    assert service._album_filter is not None


async def test_runtime_sync_command_passes_fuzzy_keywords() -> None:
    captured: dict[str, object] = {}

    class FakeHistory:
        async def sync_source(
            self,
            source_id: int,
            *,
            limit: int,
            fuzzy_keywords: list[str] | None = None,
            recent: bool = False,
        ) -> int:
            captured["source_id"] = source_id
            captured["limit"] = limit
            captured["fuzzy_keywords"] = fuzzy_keywords
            captured["recent"] = recent
            return 7

    class FakeTransfer:
        async def process_pending(self) -> None:
            raise AssertionError("sync command must leave delivery to the runtime worker")

    service = RuntimeService(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        FakeTransfer(),  # type: ignore[arg-type]
        AppConfig(),
    )
    service.history = FakeHistory()  # type: ignore[assignment]
    command = SimpleNamespace(
        command_type=COMMAND_SYNC,
        payload=json.dumps({"source_id": 5, "limit": 30, "keywords": ["AI", " 主播 "]}),
    )

    result = await service._execute_control_command(command)  # type: ignore[arg-type]

    assert result == {"source_id": 5, "inspected": 7}
    assert captured == {
        "source_id": 5,
        "limit": 30,
        "fuzzy_keywords": ["AI", "主播"],
        "recent": True,
    }
