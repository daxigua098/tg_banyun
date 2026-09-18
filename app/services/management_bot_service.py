"""Telegram management bot event handling."""

from __future__ import annotations

from typing import Any

from loguru import logger
from telethon import events

from app.config import AppConfig
from app.services.management_command_service import (
    ManagementCommandService,
    truncate_response,
)


class ManagementBotService:
    """Authorize admins and forward commands to the command service."""

    def __init__(
        self,
        bot_client: Any,
        command_service: ManagementCommandService,
        config: AppConfig,
    ) -> None:
        self.bot_client = bot_client
        self.command_service = command_service
        self.admin_user_ids = set(config.management_bot.admin_user_ids)
        self._message_filter = events.NewMessage(incoming=True)

    def is_admin(self, sender_id: int | None) -> bool:
        """Return whether a Telegram sender is authorized."""
        return sender_id is not None and int(sender_id) in self.admin_user_ids

    async def run(self) -> None:
        """Run the management bot until its Telegram connection closes."""
        self.bot_client.add_event_handler(self._handle_message, self._message_filter)
        try:
            await self.bot_client.run_until_disconnected()
        finally:
            self.bot_client.remove_event_handler(self._handle_message, self._message_filter)

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        if not event.is_private:
            return
        if not self.is_admin(event.sender_id):
            await event.respond("无权限使用此管理 Bot。")
            return

        text = (event.raw_text or "").strip()
        if not text.startswith("/"):
            return

        try:
            response = await self.command_service.handle(text)
        except ValueError as exc:
            response = f"参数错误：{exc}"
        except Exception:  # noqa: BLE001 - bot must keep serving other commands
            logger.exception("Management command failed: {}", text)
            response = "命令执行失败，请查看服务日志。"

        await event.respond(truncate_response(response))
