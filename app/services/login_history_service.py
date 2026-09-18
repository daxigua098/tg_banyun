"""Login attempt history persistence."""

from __future__ import annotations

from sqlalchemy import select
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
