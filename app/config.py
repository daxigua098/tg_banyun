"""Application configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "config.yaml"


class AppMetaConfig(BaseModel):
    """General application metadata."""

    name: str = "tg-mirror-bot"
    environment: str = "development"
    timezone: str = "Asia/Shanghai"


class DatabaseConfig(BaseModel):
    """Database connection settings."""

    url: str = "sqlite+aiosqlite:///./data/app.db"
    echo: bool = False


class TelegramConfig(BaseModel):
    """Telegram userbot settings."""

    api_id: int = 0
    api_hash: str = ""
    phone: str = ""
    session_name: str = "data/sessions/default"
    proxy: str | None = None

    def validate_credentials(self) -> None:
        """Raise a readable error when Telegram credentials are incomplete."""
        if not self.api_id or not self.api_hash or not self.phone:
            raise ValueError(
                "Telegram credentials are incomplete. Configure TG_API_ID, "
                "TG_API_HASH and TG_PHONE in .env."
            )


class ManagementBotConfig(BaseModel):
    """Telegram management bot settings."""

    enabled: bool = False
    token: str = ""
    admin_user_ids: list[int] = Field(default_factory=list)
    session_name: str = "data/sessions/management_bot"

    def validate_ready(self) -> None:
        """Validate all settings required to start the management bot."""
        if not self.enabled:
            return
        if not self.token:
            raise ValueError(
                "Management bot is enabled but TG_BOT_TOKEN is empty."
            )
        if not self.admin_user_ids:
            raise ValueError(
                "Management bot is enabled but TG_ADMIN_IDS is empty."
            )


class TransferConfig(BaseModel):
    """Message transfer behavior."""

    mode: Literal["copy", "forward"] = "copy"
    sequential: bool = True
    delay_seconds: float = Field(default=1.0, ge=0)
    max_attempts: int = Field(default=5, ge=1)
    retry_base_seconds: int = Field(default=5, ge=1)
    worker_concurrency: int = Field(default=1, ge=1, le=1)

    @field_validator("sequential")
    @classmethod
    def require_sequential(cls, value: bool) -> bool:
        """The MVP deliberately supports one globally sequential worker."""
        if not value:
            raise ValueError("MVP requires transfer.sequential=true")
        return value


class HistoryConfig(BaseModel):
    """Historical message synchronization behavior."""

    enabled: bool = True
    default_limit: int = Field(default=500, ge=1)
    order: Literal["old_to_new", "new_to_old"] = "old_to_new"
    skip_pinned: bool = True


class ContentFilterConfig(BaseModel):
    """Content-type filtering applied before message delivery."""

    media_only: bool = False
    allow_photo: bool = True
    allow_video: bool = True


class BackupConfig(BaseModel):
    """Automatic backup scheduling and retention."""

    enabled: bool = True
    interval_hours: int = Field(default=24, ge=1)
    retention_count: int = Field(default=7, ge=1)
    directory: str = "backups"


class AlertConfig(BaseModel):
    """Admin notification settings."""

    enabled: bool = True
    notify_on_startup: bool = True
    notify_on_failure: bool = True
    notify_on_backup: bool = True


class WebConfig(BaseModel):
    """FastAPI management API settings."""

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    api_token: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    session_secret: str = ""
    session_hours: int = Field(default=24, ge=1)
    max_login_failures: int = Field(default=5, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )


class LoggingConfig(BaseModel):
    """Logging settings."""

    level: str = "INFO"
    file: str = "logs/app.log"


class AppConfig(BaseModel):
    """Root application configuration."""

    app: AppMetaConfig = Field(default_factory=AppMetaConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    management_bot: ManagementBotConfig = Field(default_factory=ManagementBotConfig)
    transfer: TransferConfig = Field(default_factory=TransferConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    content_filter: ContentFilterConfig = Field(default_factory=ContentFilterConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @property
    def project_root(self) -> Path:
        """Return the repository root."""
        return PROJECT_ROOT


def _resolve_config_path(config_path: str | Path | None) -> Path:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _parse_admin_ids(value: str | list[int] | tuple[int, ...]) -> list[int]:
    if isinstance(value, str):
        return [int(item.strip()) for item in value.split(",") if item.strip()]
    return [int(item) for item in value]


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load YAML configuration and overlay secrets from environment variables."""
    load_dotenv(PROJECT_ROOT / ".env")
    path = _resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    telegram = raw.setdefault("telegram", {})
    database = raw.setdefault("database", {})
    management_bot = raw.setdefault("management_bot", {})
    web = raw.setdefault("web", {})

    telegram["api_id"] = int(os.getenv("TG_API_ID", telegram.get("api_id", 0)) or 0)
    telegram["api_hash"] = os.getenv("TG_API_HASH", telegram.get("api_hash", ""))
    telegram["phone"] = os.getenv("TG_PHONE", telegram.get("phone", ""))
    database["url"] = os.getenv(
        "DATABASE_URL",
        database.get("url", "sqlite+aiosqlite:///./data/app.db"),
    )

    management_bot["token"] = os.getenv(
        "TG_BOT_TOKEN",
        management_bot.get("token", ""),
    )
    management_bot["session_name"] = os.getenv(
        "TG_BOT_SESSION_NAME",
        management_bot.get("session_name", "data/sessions/management_bot"),
    )
    if os.getenv("TG_ADMIN_IDS"):
        management_bot["admin_user_ids"] = _parse_admin_ids(os.environ["TG_ADMIN_IDS"])
    web["api_token"] = os.getenv("ADMIN_API_TOKEN", web.get("api_token", ""))
    web["admin_username"] = os.getenv("ADMIN_USERNAME", web.get("admin_username", "admin"))
    web["admin_password"] = os.getenv("ADMIN_PASSWORD", web.get("admin_password", ""))
    web["session_secret"] = os.getenv("ADMIN_SESSION_SECRET", web.get("session_secret", ""))

    return AppConfig.model_validate(raw)
