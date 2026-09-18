"""Telethon client construction and login helpers."""

from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from app.config import PROJECT_ROOT, AppConfig


def create_telegram_client(config: AppConfig) -> TelegramClient:
    """Create a Telethon client from validated application configuration."""
    config.telegram.validate_credentials()
    session_path = Path(config.telegram.session_name)
    if not session_path.is_absolute():
        session_path = PROJECT_ROOT / session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)

    if config.telegram.proxy:
        raise NotImplementedError(
            "Proxy support is intentionally deferred from the first MVP skeleton."
        )

    return TelegramClient(
        session=str(session_path),
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )


async def start_client(client: TelegramClient, config: AppConfig) -> TelegramClient:
    """Start the userbot and complete the interactive login when necessary."""
    await client.start(phone=config.telegram.phone)
    return client
