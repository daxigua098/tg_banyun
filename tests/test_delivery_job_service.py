from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, ControlCommand, DeliveryJob, Source, Target
from app.services.delivery_job_service import cancel_pending_jobs


async def test_cancel_pending_jobs_marks_only_waiting_jobs_cancelled() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        source = Source(
            raw_input="@source",
            normalized_key="username:source",
            tg_id=100,
            title="Source",
        )
        target = Target(
            raw_input="@target",
            normalized_key="username:target",
            tg_id=200,
            title="Target",
        )
        session.add_all([source, target])
        await session.commit()
        session.add_all(
            [
                DeliveryJob(
                    source_id=source.id,
                    target_id=target.id,
                    source_message_id=1,
                    status="pending",
                ),
                DeliveryJob(
                    source_id=source.id,
                    target_id=target.id,
                    source_message_id=2,
                    status="retrying",
                ),
                DeliveryJob(
                    source_id=source.id,
                    target_id=target.id,
                    source_message_id=3,
                    status="success",
                ),
                ControlCommand(
                    command_type="sync",
                    status="pending",
                    payload="{}",
                ),
                ControlCommand(
                    command_type="sync",
                    status="success",
                    payload="{}",
                ),
            ]
        )
        await session.commit()

        cancelled = await cancel_pending_jobs(session)

    async with session_factory() as session:
        jobs = list(
            await session.scalars(select(DeliveryJob).order_by(DeliveryJob.id.asc()))
        )
        commands = list(
            await session.scalars(select(ControlCommand).order_by(ControlCommand.id.asc()))
        )

    assert cancelled == 2
    assert [job.status for job in jobs] == ["cancelled", "cancelled", "success"]
    assert [command.status for command in commands] == ["cancelled", "success"]
    await engine.dispose()
