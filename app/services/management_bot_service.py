"""Telegram management bot event handling and button control panel."""

from __future__ import annotations

from typing import Any

from loguru import logger
from telethon import Button, events
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault

from app.config import AppConfig
from app.services.management_command_service import (
    ManagementCommandService,
    truncate_response,
)

BOT_COMMANDS = (
    BotCommand("menu", "打开按钮控制面板"),
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

MENU_TEXT = """TG-Mirror-Bot 控制面板

请直接点击下方按钮操作，不需要记命令。
所有操作仅在管理员账号中生效。"""

BUTTON_COMMANDS = {
    "status": "/status",
    "stats": "/stats",
    "routes": "/routes",
    "jobs_failed": "/jobs failed 20",
    "retry_failed": "/retry_failed",
    "pause": "/pause",
    "resume": "/resume",
    "help": "/help all",
}


class ManagementBotService:
    """Authorize admins and provide command and button interfaces."""

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
        self._callback_filter = events.CallbackQuery()

    def is_admin(self, sender_id: int | None) -> bool:
        """Return whether a Telegram sender is authorized."""
        return sender_id is not None and int(sender_id) in self.admin_user_ids

    async def run(self) -> None:
        """Run the management bot until its Telegram connection closes."""
        self.bot_client.add_event_handler(self._handle_message, self._message_filter)
        self.bot_client.add_event_handler(self._handle_callback, self._callback_filter)
        try:
            await self._register_commands()
            await self.bot_client.run_until_disconnected()
        finally:
            self.bot_client.remove_event_handler(self._handle_message, self._message_filter)
            self.bot_client.remove_event_handler(self._handle_callback, self._callback_filter)

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

    @staticmethod
    def _main_menu_buttons() -> list[list[Button]]:
        return [
            [
                Button.inline("运行状态", b"status"),
                Button.inline("投递统计", b"stats"),
            ],
            [
                Button.inline("搬运源", b"sources"),
                Button.inline("接收目标", b"targets"),
            ],
            [
                Button.inline("路由关系", b"routes"),
                Button.inline("失败任务", b"jobs_failed"),
            ],
            [
                Button.inline("暂停搬运", b"pause"),
                Button.inline("恢复搬运", b"resume"),
            ],
            [
                Button.inline("重试失败", b"retry_failed"),
                Button.inline("使用帮助", b"help"),
            ],
        ]

    @staticmethod
    def _result_buttons() -> list[list[Button]]:
        return [[Button.inline("返回主菜单", b"menu")]]

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        if not event.is_private:
            return
        if not self.is_admin(event.sender_id):
            await event.respond("无权限使用此管理 Bot。")
            return

        text = (event.raw_text or "").strip()
        if not text.startswith("/"):
            return
        command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()

        if command in {"/start", "/menu"}:
            await event.respond(MENU_TEXT, buttons=self._main_menu_buttons())
            return

        try:
            response = await self.command_service.handle(text)
        except ValueError as exc:
            response = f"参数错误：{exc}"
        except Exception:  # noqa: BLE001 - bot must keep serving other commands
            logger.exception("Management command failed: {}", text)
            response = "命令执行失败，请查看服务日志。"

        await event.respond(truncate_response(response))

    async def _handle_callback(self, event: events.CallbackQuery.Event) -> None:
        if not self.is_admin(event.sender_id):
            await event.answer("无权限操作。", alert=True)
            return

        action = (event.data or b"").decode(errors="ignore")
        if action == "menu":
            await event.answer()
            await self._edit_or_send(event, MENU_TEXT, self._main_menu_buttons())
            return

        try:
            response = await self._callback_response(action)
        except ValueError as exc:
            response = f"参数错误：{exc}"
        except Exception:  # noqa: BLE001 - callback errors must not stop the bot
            logger.exception("Management callback failed: {}", action)
            response = "操作失败，请查看服务日志。"

        await event.answer("已更新")
        await self._edit_or_send(event, truncate_response(response), self._result_buttons())

    async def _callback_response(self, action: str) -> str:
        if action == "sources":
            response = await self.command_service.handle("/sources")
            return (
                f"{response}\n\n"
                "添加源：发送 /source_add <链接>\n"
                "私有链接：/source_add --join <链接>"
            )
        if action == "targets":
            response = await self.command_service.handle("/targets")
            return f"{response}\n\n添加目标：发送 /target_add <链接>"
        command = BUTTON_COMMANDS.get(action)
        if command is None:
            return "未识别的操作，请返回主菜单重试。"
        return await self.command_service.handle(command)

    async def _edit_or_send(
        self,
        event: events.CallbackQuery.Event,
        text: str,
        buttons: list[list[Button]],
    ) -> None:
        try:
            await event.edit(text, buttons=buttons)
        except Exception:  # noqa: BLE001 - old callback messages may not be editable
            await event.respond(text, buttons=buttons)

