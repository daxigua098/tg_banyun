"""Login attempt history persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginHistory


async def record_login_attempt(
    session: AsyncSession,
    *,
    username: str,
    ip_address: str | None,
    user_agent: str | None,
    success: bool,
    reason: str | None = None,
) -> LoginHistory:
    item = LoginHistory(
        username=username,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        reason=reason,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def list_login_history(session: AsyncSession, limit: int = 100) -> list[LoginHistory]:
    return list(
        await session.scalars(
            select(LoginHistory).order_by(LoginHistory.id.desc()).limit(limit)
        )
    )

async def is_login_rate_limited(
    session: AsyncSession,
    *,
    username: str,
    ip_address: str | None,
    max_failures: int,
    window_minutes: int,
) -> bool:
    """Return whether recent failed attempts exceed the configured limit."""
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)
    count = await session.scalar(
        select(func.count())
        .select_from(LoginHistory)
        .where(
            LoginHistory.username == username,
            LoginHistory.ip_address == ip_address,
            LoginHistory.success.is_(False),
            LoginHistory.created_at >= since,
        )
    )
    return int(count or 0) >= max_failures


async def has_successful_login(
    session: AsyncSession,
    *,
    username: str,
    ip_address: str | None,
) -> bool:
    """Return whether this username and IP pair logged in successfully before."""
    item = await session.scalar(
        select(LoginHistory.id)
        .where(
            LoginHistory.username == username,
            LoginHistory.ip_address == ip_address,
            LoginHistory.success.is_(True),
        )
        .limit(1)
    )
    return item is not None
