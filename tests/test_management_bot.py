from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import AppConfig, ManagementBotConfig, TransferConfig
from app.core.transfer import SequentialTransferService
from app.models import Base, DeliveryJob, Route, Source, Target
from app.services import management_command_service as command_module
from app.services.management_bot_service import BOT_COMMANDS, ManagementBotService
from app.services.management_command_service import ManagementCommandService


class FakeUserClient:
    def is_connected(self) -> bool:
        return True

    async def forward_messages(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(id=1)


class FakeBotClient:
    pass


class FakeEvent:
    def __init__(self, *, sender_id: int, text: str) -> None:
        self.is_private = True
        self.sender_id = sender_id
        self.raw_text = text
        self.responses: list[str] = []

    async def respond(self, text: str) -> None:
        self.responses.append(text)


async def _build_factory() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory, engine


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> None:
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
        session.add(Route(source_id=source.id, target_id=target.id))
        session.add(
            DeliveryJob(
                source_id=source.id,
                target_id=target.id,
                source_message_id=77,
                status="failed",
                attempt_count=5,
                max_attempts=5,
                last_error="Forbidden",
            )
        )
        await session.commit()


async def test_management_commands_update_and_report_state() -> None:
    session_factory, engine = await _build_factory()
    await _seed(session_factory)
    config = AppConfig(
        management_bot=ManagementBotConfig(enabled=True, admin_user_ids=[42]),
        transfer=TransferConfig(delay_seconds=0),
    )
    user_client = FakeUserClient()
    transfer = SequentialTransferService(user_client, session_factory, config)
    service = ManagementCommandService(user_client, session_factory, transfer, config)

    status = await service.handle("/status")
    assert "源：总 1 / 启用 1" in status
    assert "failed=1" in status

    disabled = await service.handle("/source_disable 1")
    assert "已禁用源" in disabled

    retry = await service.handle("/retry_failed")
    assert "1 个失败任务" in retry

    async with session_factory() as session:
        job = await session.scalar(select(DeliveryJob))
        source = await session.get(Source, 1)
        assert job is not None
        assert job.status == "pending"
        assert job.attempt_count == 0
        assert source is not None
        assert source.enabled is False

    await engine.dispose()


async def test_management_bot_enforces_admin_permissions(monkeypatch) -> None:
    monkeypatch.setattr(
        command_module,
        "read_runtime_status",
        lambda path: {"status": "running", "pid": 12345},
    )
    monkeypatch.setattr(command_module, "is_process_running", lambda pid: True)
    session_factory, engine = await _build_factory()
    config = AppConfig(
        management_bot=ManagementBotConfig(enabled=True, admin_user_ids=[42]),
        transfer=TransferConfig(delay_seconds=0),
    )
    user_client = FakeUserClient()
    transfer = SequentialTransferService(user_client, session_factory, config)
    command_service = ManagementCommandService(user_client, session_factory, transfer, config)
    bot_service = ManagementBotService(FakeBotClient(), command_service, config)

    denied = FakeEvent(sender_id=99, text="/status")
    await bot_service._handle_message(denied)
    assert denied.responses == ["无权限使用此管理 Bot。"]

    allowed = FakeEvent(sender_id=42, text="/status")
    await bot_service._handle_message(allowed)
    assert allowed.responses
    assert "TG-Mirror-Bot 状态" in allowed.responses[0]
    assert "运行状态：运行中" in allowed.responses[0]

    await engine.dispose()



def test_management_bot_command_menu_is_chinese() -> None:
    descriptions = {command.command: command.description for command in BOT_COMMANDS}
    assert descriptions["status"] == "查看运行状态"
    assert descriptions["pause"] == "暂停搬运"
    assert descriptions["retry_failed"] == "重试失败任务"
