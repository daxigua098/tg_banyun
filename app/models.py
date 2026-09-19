"""Database models for the sequential Telegram mirroring MVP."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    """Created and updated timestamps shared by persisted entities."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class Source(TimestampMixin, Base):
    """A Telegram source chat or channel."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_input: Mapped[str] = mapped_column(String(512))
    normalized_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    tg_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    join_status: Mapped[str] = mapped_column(String(32), default="joined")
    sync_status: Mapped[str] = mapped_column(String(32), default="pending")
    last_synced_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    routes: Mapped[list[Route]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class Target(TimestampMixin, Base):
    """A destination Telegram chat or channel."""

    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_input: Mapped[str] = mapped_column(String(512))
    normalized_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    tg_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    routes: Mapped[list[Route]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
    )


class Route(TimestampMixin, Base):
    """A one-source-to-many-targets route binding."""

    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_route_source_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"),
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    source: Mapped[Source] = relationship(back_populates="routes")
    target: Mapped[Target] = relationship(back_populates="routes")


class DeliveryJob(TimestampMixin, Base):
    """One idempotent delivery attempt for a source message and target."""

    __tablename__ = "delivery_jobs"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_message_id",
            "target_id",
            name="uq_delivery_source_message_target",
        ),
        Index("ix_delivery_status_next_retry", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"),
        index=True,
    )
    source_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_message_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )
    target_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source: Mapped[Source] = relationship()
    target: Mapped[Target] = relationship()

class RecordTarget(TimestampMixin, Base):
    """A Telegram chat that receives human-readable delivery records."""

    __tablename__ = "record_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_input: Mapped[str] = mapped_column(String(512))
    normalized_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    tg_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class SourceRule(TimestampMixin, Base):
    """Per-source content filtering rules."""

    __tablename__ = "source_rules"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    allow_photo: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_video: Mapped[bool] = mapped_column(Boolean, default=True)
    keyword_whitelist: Mapped[str] = mapped_column(Text, default="[]")
    keyword_blacklist: Mapped[str] = mapped_column(Text, default="[]")
    sender_whitelist: Mapped[str] = mapped_column(Text, default="[]")
    sender_blacklist: Mapped[str] = mapped_column(Text, default="[]")
    skip_forwarded: Mapped[bool] = mapped_column(Boolean, default=False)
    post_only: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_only: Mapped[bool] = mapped_column(Boolean, default=False)
    search_monitor: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship()

class ControlCommand(TimestampMixin, Base):
    """Durable command executed by the single runtime process."""

    __tablename__ = "control_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

class AuditLog(Base):
    """Administrative and API action audit trail."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), default="anonymous", index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(512), index=True)
    status_code: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class WebUser(TimestampMixin, Base):
    """Web management user with a role."""

    __tablename__ = "web_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="viewer", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class WebSession(Base):
    """Server-side web login session for revocation and logout."""

    __tablename__ = "web_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class LoginHistory(Base):
    """Web login attempt history."""

    __tablename__ = "login_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )

class SystemSetting(Base):
    """Key-value runtime settings editable from the management dashboard."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
