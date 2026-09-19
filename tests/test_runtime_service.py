from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import AppConfig
from app.models import Base, Source, Target
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


async def test_runtime_access_check_reports_source_and_target_permissions() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        source = Source(
            raw_input="@source",
            normalized_key="username:source",
            tg_id=100,
            title="Source",
        )
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=200,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        source_id = source.id
        target_id = target.id

    class FakeAccessClient:
        async def get_me(self):
            return SimpleNamespace(id=1)

        async def get_messages(self, entity, limit):
            return []

        async def get_permissions(self, entity, me):
            return SimpleNamespace(
                is_admin=False,
                is_creator=False,
                send_messages=True,
                post_messages=False,
            )

    service = RuntimeService(
        FakeAccessClient(),  # type: ignore[arg-type]
        session_factory,
        SimpleNamespace(),  # type: ignore[arg-type]
        AppConfig(),
        operation_lock=None,
    )
    result = await service._check_access(
        {"source_ids": [source_id], "target_ids": [target_id]}
    )

    assert result == {
        "results": [
            {
                "kind": "source",
                "id": source_id,
                "name": "Source",
                "ok": True,
                "message": "可以读取消息",
            },
            {
                "kind": "target",
                "id": target_id,
                "name": "Target",
                "ok": True,
                "message": "可以发送/发帖",
            },
        ]
    }
    await engine.dispose()
