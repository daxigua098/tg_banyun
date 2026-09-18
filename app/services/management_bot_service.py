"""Telegram management bot event handling."""

from __future__ import annotations

from typing import Any

from loguru import logger
from telethon import events
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault

from app.config import AppConfig
from app.services.management_command_service import (
    ManagementCommandService,
    truncate_response,
)

BOT_COMMANDS = (
    BotCommand("status", "查看运行状态"),
    BotCommand("sources", "查看搬运源"),
    BotCommand("targets", "查看接收目标"),
    BotCommand("routes", "查看源到目标路由"),
    BotCommand("stats", "查看投递统计"),
    BotCommand("jobs", "查看最近投递任务"),
    BotCommand("pause", "暂停搬运"),
    BotCommand("resume", "恢复搬运"),
    BotCommand("retry_failed", "重试失败任务"),
    BotCommand("source_add", "添加搬运源"),
    BotCommand("target_add", "添加接收目标"),
    BotCommand("source_enable", "启用搬运源"),
    BotCommand("source_disable", "停用搬运源"),
    BotCommand("target_enable", "启用接收目标"),
    BotCommand("target_disable", "停用接收目标"),
    BotCommand("route_add", "建立搬运路由"),
    BotCommand("route_delete", "删除搬运路由"),
    BotCommand("record_add", "添加记录接收群"),
    BotCommand("records", "查看记录接收群"),
    BotCommand("sync", "同步历史消息"),
    BotCommand("help", "查看中文帮助"),
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
            await self._register_commands()
            await self.bot_client.run_until_disconnected()
        finally:
            self.bot_client.remove_event_handler(self._handle_message, self._message_filter)

    async def _register_commands(self) -> None:
        try:
            await self.bot_client(
                SetBotCommandsRequest(
                    scope=BotCommandScopeDefault(),
                    lang_code="",
                    commands=list(BOT_COMMANDS),
                )
            )
            logger.info("Management bot command menu updated in Chinese")
        except Exception:  # noqa: BLE001 - menu setup must not stop command handling
            logger.exception("Failed to register management bot commands")

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
