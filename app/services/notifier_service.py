"""Administrator notifications sent through the management bot."""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.config import AlertConfig


class AdminNotifier:
    """Best-effort notification sender for configured Telegram administrators."""

    def __init__(
        self,
        bot_client: Any,
        admin_user_ids: list[int],
        config: AlertConfig,
    ) -> None:
        self.bot_client = bot_client
        self.admin_user_ids = admin_user_ids
        self.config = config

    async def send(self, text: str) -> None:
        """Send an alert to every configured administrator."""
        if not self.config.enabled:
            return
        for admin_id in self.admin_user_ids:
            try:
                await self.bot_client.send_message(admin_id, text)
            except Exception as exc:  # noqa: BLE001 - alerts are best effort
                logger.error(
                    "Failed to notify admin={} error={}: {}",
                    admin_id,
                    type(exc).__name__,
                    exc,
                )

    async def startup(self, detail: str) -> None:
        if self.config.notify_on_startup:
            await self.send(f"TG-Mirror-Bot 已启动\n{detail}")

    async def failure(self, detail: str) -> None:
        if self.config.notify_on_failure:
            await self.send(f"TG-Mirror-Bot 异常\n{detail}")

    async def backup(self, detail: str) -> None:
        if self.config.notify_on_backup:
            await self.send(f"TG-Mirror-Bot 自动备份\n{detail}")
