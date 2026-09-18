"""Telethon client construction and login helpers."""

from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from app.config import PROJECT_ROOT, AppConfig


def _session_path(session_name: str) -> Path:
    path = Path(session_name)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def create_telegram_client(config: AppConfig) -> TelegramClient:
    """Create a Telethon userbot client from validated application configuration."""
    config.telegram.validate_credentials()
    if config.telegram.proxy:
        raise NotImplementedError(
            "Proxy support is intentionally deferred from the first MVP skeleton."
        )

    return TelegramClient(
        session=str(_session_path(config.telegram.session_name)),
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )


def create_management_bot_client(config: AppConfig) -> TelegramClient:
    """Create a Telethon bot client for the management interface."""
    config.telegram.validate_credentials()
    config.management_bot.validate_ready()
    if config.telegram.proxy:
        raise NotImplementedError(
            "Proxy support is intentionally deferred from the first MVP skeleton."
        )

    return TelegramClient(
        session=str(_session_path(config.management_bot.session_name)),
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )


async def start_client(client: TelegramClient, config: AppConfig) -> TelegramClient:
    """Start the userbot and complete the interactive login when necessary."""
    await client.start(phone=config.telegram.phone)
    return client


async def start_management_bot_client(
    client: TelegramClient,
    config: AppConfig,
) -> TelegramClient:
    """Start the management bot using its BotFather token."""
    await client.start(bot_token=config.management_bot.token)
    return client
