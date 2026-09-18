"""Audit trail persistence and queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write_audit_log(
    session: AsyncSession,
    *,
    username: str,
    method: str,
    path: str,
    status_code: int,
    ip_address: str | None,
) -> AuditLog:
    """Persist one audit record."""
    log = AuditLog(
        username=username,
        method=method,
        path=path,
        status_code=status_code,
        ip_address=ip_address,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def list_audit_logs(session: AsyncSession, limit: int = 100) -> list[AuditLog]:
    """Return recent audit records newest first."""
    return list(
        await session.scalars(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        )
    )
