"""Administrative operations for durable delivery and control jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ControlCommand, DeliveryJob


async def cancel_pending_jobs(session: AsyncSession) -> int:
    """Cancel jobs and control commands that have not started processing yet."""
    result = await session.execute(
        update(DeliveryJob)
        .where(DeliveryJob.status.in_(("pending", "retrying")))
        .values(
            status="cancelled",
            last_error="管理员停止全部任务",
            next_retry_at=None,
        )
    )
    await session.execute(
        update(ControlCommand)
        .where(ControlCommand.status == "pending")
        .values(
            status="cancelled",
            error="管理员停止全部任务",
            processed_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return int(result.rowcount or 0)
