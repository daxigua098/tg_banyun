"""FastAPI management API for the Telegram mirror bot."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PROJECT_ROOT, AppConfig, load_config
from app.core.heartbeat import is_process_running, read_runtime_status
from app.core.runtime_control import is_runtime_paused, set_runtime_paused
from app.database import dispose_database, get_session_factory, init_database
from app.models import DeliveryJob, Route, Source, Target
from app.services.rule_service import (
    list_source_rules,
    load_keywords,
    load_sender_ids,
    replace_source_rule,
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = load_config()
    app.state.config = config
    await init_database(config)
    try:
        yield
    finally:
        await dispose_database()


class EnabledUpdate(BaseModel):
    enabled: bool


class RouteCreate(BaseModel):
    source_id: int = Field(gt=0)
    target_id: int = Field(gt=0)


class RuleUpdate(BaseModel):
    allow_photo: bool = True
    allow_video: bool = True
    post_only: bool = False
    admin_only: bool = False
    skip_forwarded: bool = False
    keyword_whitelist: list[str] = Field(default_factory=list)
    keyword_blacklist: list[str] = Field(default_factory=list)
    sender_whitelist: list[int] = Field(default_factory=list)
    sender_blacklist: list[int] = Field(default_factory=list)


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="TG-Mirror-Bot Management API",
        version="0.1.0",
        lifespan=_lifespan,
    )
    config = load_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.web.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def require_auth(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        token = request.app.state.config.web.api_token
        if token and authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="未授权")

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        factory = get_session_factory()
        async with factory() as session:
            yield session

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "time": datetime.now(UTC).isoformat(timespec="seconds")}

    @app.get("/api/status", dependencies=[Depends(require_auth)])
    async def status(session: AsyncSession = Depends(session_dependency)) -> dict[str, Any]:
        config: AppConfig = app.state.config
        heartbeat = read_runtime_status(
            config.project_root / "data" / "runtime_status.json"
        )
        state = "not_started"
        if heartbeat is not None:
            if heartbeat.get("status") != "running":
                state = str(heartbeat.get("status"))
            else:
                pid = int(heartbeat.get("pid") or 0)
                state = "running" if is_process_running(pid) else "stale"
        job_rows = await session.execute(
            select(DeliveryJob.status, func.count(DeliveryJob.id)).group_by(DeliveryJob.status)
        )
        return {
            "runtime": state,
            "paused": is_runtime_paused(
                config.project_root / "data" / "runtime_control.json"
            ),
            "heartbeat": heartbeat,
            "jobs": {str(status): int(count) for status, count in job_rows.all()},
            "source_count": int(
                await session.scalar(select(func.count()).select_from(Source)) or 0
            ),
            "target_count": int(
                await session.scalar(select(func.count()).select_from(Target)) or 0
            ),
            "route_count": int(
                await session.scalar(select(func.count()).select_from(Route)) or 0
            ),
        }

    @app.get("/api/sources", dependencies=[Depends(require_auth)])
    async def sources(session: AsyncSession = Depends(session_dependency)) -> list[dict[str, Any]]:
        rows = list(await session.scalars(select(Source).order_by(Source.id)))
        return [
            {
                "id": item.id,
                "title": item.title,
                "username": item.username,
                "enabled": item.enabled,
                "sync_status": item.sync_status,
                "last_synced_message_id": item.last_synced_message_id,
                "last_sync_at": item.last_sync_at,
            }
            for item in rows
        ]

    @app.get("/api/targets", dependencies=[Depends(require_auth)])
    async def targets(session: AsyncSession = Depends(session_dependency)) -> list[dict[str, Any]]:
        rows = list(await session.scalars(select(Target).order_by(Target.id)))
        return [
            {
                "id": item.id,
                "title": item.title,
                "username": item.username,
                "enabled": item.enabled,
            }
            for item in rows
        ]

    @app.patch("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
    async def update_source(
        source_id: int,
        payload: EnabledUpdate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        source = await session.get(Source, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="源不存在")
        source.enabled = payload.enabled
        await session.commit()
        return {"id": source.id, "enabled": source.enabled}

    @app.patch("/api/targets/{target_id}", dependencies=[Depends(require_auth)])
    async def update_target(
        target_id: int,
        payload: EnabledUpdate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        target = await session.get(Target, target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="目标不存在")
        target.enabled = payload.enabled
        await session.commit()
        return {"id": target.id, "enabled": target.enabled}

    @app.post("/api/routes", dependencies=[Depends(require_auth)])
    async def create_route(
        payload: RouteCreate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        source = await session.get(Source, payload.source_id)
        target = await session.get(Target, payload.target_id)
        if source is None or target is None:
            raise HTTPException(status_code=404, detail="源或目标不存在")
        route = await session.scalar(
            select(Route).where(
                Route.source_id == payload.source_id,
                Route.target_id == payload.target_id,
            )
        )
        if route is None:
            route = Route(
                source_id=payload.source_id,
                target_id=payload.target_id,
            )
            session.add(route)
            await session.commit()
            await session.refresh(route)
        return {
            "id": route.id,
            "source_id": route.source_id,
            "target_id": route.target_id,
            "enabled": route.enabled,
        }

    @app.delete("/api/routes/{route_id}", dependencies=[Depends(require_auth)])
    async def remove_route(
        route_id: int,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, bool]:
        route = await session.get(Route, route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="路由不存在")
        await session.delete(route)
        await session.commit()
        return {"deleted": True}

    @app.put("/api/rules/{source_id}", dependencies=[Depends(require_auth)])
    async def update_rule(
        source_id: int,
        payload: RuleUpdate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        rule = await replace_source_rule(
            session,
            source_id,
            allow_photo=payload.allow_photo,
            allow_video=payload.allow_video,
            post_only=payload.post_only,
            admin_only=payload.admin_only,
            skip_forwarded=payload.skip_forwarded,
            keyword_whitelist=payload.keyword_whitelist,
            keyword_blacklist=payload.keyword_blacklist,
            sender_whitelist=payload.sender_whitelist,
            sender_blacklist=payload.sender_blacklist,
        )
        return {
            "source_id": source_id,
            "allow_photo": rule.allow_photo,
            "allow_video": rule.allow_video,
            "post_only": rule.post_only,
            "admin_only": rule.admin_only,
            "skip_forwarded": rule.skip_forwarded,
            "keyword_whitelist": payload.keyword_whitelist,
            "keyword_blacklist": payload.keyword_blacklist,
            "sender_whitelist": payload.sender_whitelist,
            "sender_blacklist": payload.sender_blacklist,
        }

    @app.get("/api/routes", dependencies=[Depends(require_auth)])
    async def routes(session: AsyncSession = Depends(session_dependency)) -> list[dict[str, Any]]:
        rows = list(await session.scalars(select(Route).order_by(Route.id)))
        return [
            {
                "id": item.id,
                "source_id": item.source_id,
                "target_id": item.target_id,
                "enabled": item.enabled,
            }
            for item in rows
        ]

    @app.get("/api/rules", dependencies=[Depends(require_auth)])
    async def rules(session: AsyncSession = Depends(session_dependency)) -> list[dict[str, Any]]:
        rows = await list_source_rules(session)
        return [
            {
                "source_id": source.id,
                "source_title": source.title,
                "allow_photo": rule.allow_photo,
                "allow_video": rule.allow_video,
                "post_only": rule.post_only,
                "admin_only": rule.admin_only,
                "skip_forwarded": rule.skip_forwarded,
                "keyword_whitelist": load_keywords(rule.keyword_whitelist),
                "keyword_blacklist": load_keywords(rule.keyword_blacklist),
                "sender_whitelist": load_sender_ids(rule.sender_whitelist),
                "sender_blacklist": load_sender_ids(rule.sender_blacklist),
            }
            for source, rule in rows
        ]

    @app.get("/api/jobs", dependencies=[Depends(require_auth)])
    async def jobs(
        status_filter: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=500),
        session: AsyncSession = Depends(session_dependency),
    ) -> list[dict[str, Any]]:
        statement = select(DeliveryJob).order_by(DeliveryJob.id.desc()).limit(limit)
        if status_filter:
            statement = statement.where(DeliveryJob.status == status_filter)
        rows = list(await session.scalars(statement))
        return [
            {
                "id": item.id,
                "source_id": item.source_id,
                "target_id": item.target_id,
                "source_message_id": item.source_message_id,
                "status": item.status,
                "attempt_count": item.attempt_count,
                "last_error": item.last_error,
                "target_message_id": item.target_message_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in rows
        ]

    @app.post("/api/pause", dependencies=[Depends(require_auth)])
    async def pause() -> dict[str, bool]:
        config: AppConfig = app.state.config
        set_runtime_paused(config.project_root / "data" / "runtime_control.json", True)
        return {"paused": True}

    @app.post("/api/resume", dependencies=[Depends(require_auth)])
    async def resume() -> dict[str, bool]:
        config: AppConfig = app.state.config
        set_runtime_paused(config.project_root / "data" / "runtime_control.json", False)
        return {"paused": False}

    @app.post("/api/retry-failed", dependencies=[Depends(require_auth)])
    async def retry_failed(
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, int]:
        from sqlalchemy import update

        result = await session.execute(
            update(DeliveryJob)
            .where(DeliveryJob.status == "failed")
            .values(
                status="pending",
                attempt_count=0,
                next_retry_at=None,
                last_error=None,
            )
        )
        await session.commit()
        return {"retried": result.rowcount or 0}

    frontend_dist = PROJECT_ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
