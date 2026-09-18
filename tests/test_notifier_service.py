from __future__ import annotations

from app.config import AlertConfig
from app.services.notifier_service import AdminNotifier


class FakeBotClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, user_id: int, text: str) -> None:
        self.messages.append((user_id, text))


async def test_admin_notifier_sends_enabled_alerts() -> None:
    client = FakeBotClient()
    notifier = AdminNotifier(client, [42, 43], AlertConfig())

    await notifier.startup("ready")
    await notifier.failure("failed")
    await notifier.backup("backup.zip")

    assert len(client.messages) == 6
    assert client.messages[0] == (42, "TG-Mirror-Bot 已启动\nready")
    assert "异常" in client.messages[2][1]
    assert "自动备份" in client.messages[4][1]


async def test_admin_notifier_can_be_disabled() -> None:
    client = FakeBotClient()
    notifier = AdminNotifier(client, [42], AlertConfig(enabled=False))

    await notifier.failure("failed")

    assert client.messages == []
