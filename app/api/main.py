"""FastAPI management API for the Telegram mirror bot."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PROJECT_ROOT, AdditionalConfig, AppConfig, load_config
from app.core.auth import create_session_token, verify_session_token
from app.core.heartbeat import is_process_running, read_runtime_status
from app.core.runtime_control import is_runtime_paused, set_runtime_paused
from app.database import dispose_database, get_session_factory, init_database
from app.models import DeliveryJob, Route, Source, Target
from app.services.audit_service import list_audit_logs, write_audit_log
from app.services.control_command_service import (
    COMMAND_ADD_SOURCE,
    COMMAND_ADD_TARGET,
    COMMAND_SYNC,
    enqueue_control_command,
    list_control_commands,
)
from app.services.login_history_service import (
    list_login_history,
    record_login_attempt,
)
from app.services.rule_service import (
    list_source_rules,
    load_keywords,
    load_sender_ids,
    replace_source_rule,
)
from app.services.session_service import (
    create_web_session,
    is_web_session_valid,
    revoke_all_web_sessions,
    revoke_web_session,
)
from app.services.settings_service import (
    get_additional_settings,
    set_additional_settings,
)
from app.services.upload_service import UploadError, save_additional_image
from app.services.user_service import (
    authenticate_web_user,
    create_web_user,
    get_web_user,
    get_web_user_by_username,
    list_web_users,
    update_web_user,
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


class AdditionalSettingsUpdate(BaseModel):
    enabled: bool = False
    text: str = ""
    image_paths: list[str] = Field(default_factory=list)
    image_caption: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class AddSourceCommand(BaseModel):
    name: str = ""
    input: str
    join: bool = False


class AddTargetCommand(BaseModel):
    name: str = ""
    input: str


class SyncCommand(BaseModel):
    source_id: int | str
    limit: int = Field(default=100, ge=1, le=5000)


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


class WebUserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class WebUserUpdate(BaseModel):
    role: str | None = None
    enabled: bool | None = None
    password: str | None = None


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

    def authenticated_identity(request: Request) -> dict[str, str] | None:
        authorization = request.headers.get("authorization", "")
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        web = request.app.state.config.web
        if web.api_token and hmac.compare_digest(supplied, web.api_token):
            return {"username": "api-token", "role": "super_admin"}
        payload = verify_session_token(web, supplied) if supplied else None
        if not payload:
            return None
        return {
            "username": str(payload.get("sub")),
            "role": str(payload.get("role") or "viewer"),
        }

    def authenticated_username(request: Request) -> str:
        identity = authenticated_identity(request)
        return identity["username"] if identity else "anonymous"

    @app.middleware("http")
    async def audit_middleware(request: Request, call_next: Any) -> Any:
        identity = authenticated_identity(request)
        if identity is not None and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.url.path.startswith("/api/") and identity["role"] == "viewer":
                return JSONResponse(status_code=403, content={"detail": "只读用户无权执行此操作"})
            if request.url.path.startswith("/api/users") and identity["role"] != "super_admin":
                return JSONResponse(status_code=403, content={"detail": "仅超级管理员可管理用户"})
        response = await call_next(request)
        is_write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if is_write and request.url.path.startswith("/api/"):
            try:
                factory = get_session_factory()
                async with factory() as session:
                    await write_audit_log(
                        session,
                        username=authenticated_username(request),
                        method=request.method,
                        path=request.url.path,
                        status_code=response.status_code,
                        ip_address=request.client.host if request.client else None,
                    )
            except Exception:  # noqa: BLE001 - auditing must not break responses
                pass
        return response

    async def require_auth(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        web = request.app.state.config.web
        supplied = (
            authorization.removeprefix("Bearer ").strip()
            if authorization and authorization.startswith("Bearer ")
            else ""
        )
        if web.api_token and hmac.compare_digest(supplied, web.api_token):
            request.state.identity = {"username": "api-token", "role": "super_admin"}
            return
        payload = verify_session_token(web, supplied) if supplied else None
        if payload is not None:
            factory = get_session_factory()
            async with factory() as session:
                valid_session = await is_web_session_valid(session, supplied)
            if valid_session:
                request.state.identity = {
                    "username": str(payload.get("sub")),
                    "role": str(payload.get("role") or "viewer"),
                }
                return
        if not web.api_token and not web.admin_password:
            return
        raise HTTPException(status_code=401, detail="未授权")

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        factory = get_session_factory()
        async with factory() as session:
            yield session

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "time": datetime.now(UTC).isoformat(timespec="seconds")}

    @app.post("/api/auth/login")
    async def login(
        payload: LoginRequest,
        request: Request,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        web = request.app.state.config.web
        username = web.admin_username
        role = "super_admin"
        valid = False
        if web.admin_password:
            valid = hmac.compare_digest(
                payload.username,
                web.admin_username,
            ) and hmac.compare_digest(
                payload.password,
                web.admin_password,
            )
        if not valid:
            user = await get_web_user_by_username(session, payload.username)
            if user is not None and authenticate_web_user(user, payload.password):
                username = user.username
                role = user.role
                valid = True
        if not valid:
            await record_login_attempt(
                session,
                username=payload.username,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=False,
                reason="用户名或密码错误",
            )
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        await record_login_attempt(
            session,
            username=username,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
        token, expires_at = create_session_token(web, username, role=role)
        await create_web_session(
            session,
            token=token,
            username=username,
            role=role,
            expires_at=expires_at,
        )
        return {
            "token": token,
            "expires_at": expires_at,
            "username": username,
            "role": role,
        }

    @app.get("/api/auth/check", dependencies=[Depends(require_auth)])
    async def auth_check(request: Request) -> dict[str, Any]:
        identity = getattr(request.state, "identity", {})
        return {
            "authenticated": True,
            "username": identity.get("username"),
            "role": identity.get("role"),
        }

    @app.post("/api/auth/logout", dependencies=[Depends(require_auth)])
    async def logout(
        request: Request,
        authorization: str = Header(default=""),
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, bool]:
        token = authorization.removeprefix("Bearer ").strip()
        if token:
            await revoke_web_session(session, token)
        return {"logged_out": True}

    @app.patch("/api/auth/password", dependencies=[Depends(require_auth)])
    async def change_password(
        request: Request,
        payload: PasswordChange,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, bool]:
        identity = getattr(request.state, "identity", {})
        username = str(identity.get("username") or "")
        user = await get_web_user_by_username(session, username)
        if user is None:
            raise HTTPException(
                status_code=400,
                detail="内置管理员密码保存在 .env 中，不能通过网页修改。",
            )
        if not authenticate_web_user(user, payload.current_password):
            raise HTTPException(status_code=400, detail="当前密码错误")
        if len(payload.new_password) < 8:
            raise HTTPException(status_code=400, detail="新密码至少需要 8 位")
        await update_web_user(session, user.id, password=payload.new_password)
        return {"changed": True}

    @app.post("/api/auth/logout-all", dependencies=[Depends(require_auth)])
    async def logout_all(
        request: Request,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        identity = getattr(request.state, "identity", {})
        username = str(identity.get("username") or "")
        if not username or username == "api-token":
            return {"username": username, "revoked": 0}
        count = await revoke_all_web_sessions(session, username)
        return {"username": username, "revoked": count}

    @app.post("/api/settings/additional/upload", dependencies=[Depends(require_auth)])
    async def upload_additional_image(
        file: UploadFile = File(...),
    ) -> dict[str, str]:
        content = await file.read()
        try:
            path = save_additional_image(
                PROJECT_ROOT,
                file.filename,
                content,
            )
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": path}

    @app.get("/api/settings/additional", dependencies=[Depends(require_auth)])
    async def additional_settings(
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        settings = await get_additional_settings(session, config.additional)
        return settings.model_dump()

    @app.put("/api/settings/additional", dependencies=[Depends(require_auth)])
    async def update_additional_settings(
        payload: AdditionalSettingsUpdate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        settings = await set_additional_settings(
            session,
            AdditionalConfig.model_validate(payload.model_dump()),
        )
        return settings.model_dump()

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
                "display_name": item.display_name,
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
                "display_name": item.display_name,
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

    @app.post("/api/control/add-source", dependencies=[Depends(require_auth)])
    async def command_add_source(
        payload: AddSourceCommand,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        command = await enqueue_control_command(
            session,
            COMMAND_ADD_SOURCE,
            {"name": payload.name, "input": payload.input, "join": payload.join},
        )
        return {"id": command.id, "status": command.status}

    @app.post("/api/control/add-target", dependencies=[Depends(require_auth)])
    async def command_add_target(
        payload: AddTargetCommand,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        command = await enqueue_control_command(
            session,
            COMMAND_ADD_TARGET,
            {"name": payload.name, "input": payload.input},
        )
        return {"id": command.id, "status": command.status}

    @app.post("/api/control/sync", dependencies=[Depends(require_auth)])
    async def command_sync(
        payload: SyncCommand,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        source_value: int | str = payload.source_id
        if isinstance(source_value, str) and source_value != "all":
            try:
                source_value = int(source_value)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="source_id 必须是数字或 all") from exc
        command = await enqueue_control_command(
            session,
            COMMAND_SYNC,
            {"source_id": source_value, "limit": payload.limit},
        )
        return {"id": command.id, "status": command.status}

    @app.get("/api/users", dependencies=[Depends(require_auth)])
    async def users(
        session: AsyncSession = Depends(session_dependency),
    ) -> list[dict[str, Any]]:
        rows = await list_web_users(session)
        return [
            {
                "id": item.id,
                "username": item.username,
                "role": item.role,
                "enabled": item.enabled,
                "created_at": item.created_at,
            }
            for item in rows
        ]

    @app.post("/api/users", dependencies=[Depends(require_auth)])
    async def create_user(
        payload: WebUserCreate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        try:
            user = await create_web_user(
                session,
                username=payload.username,
                password=payload.password,
                role=payload.role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "enabled": user.enabled,
        }

    @app.patch("/api/users/{user_id}", dependencies=[Depends(require_auth)])
    async def update_user(
        user_id: int,
        payload: WebUserUpdate,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        try:
            user = await update_web_user(
                session,
                user_id,
                role=payload.role,
                enabled=payload.enabled,
                password=payload.password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "enabled": user.enabled,
        }

    @app.post("/api/users/{user_id}/revoke-sessions", dependencies=[Depends(require_auth)])
    async def revoke_user_sessions(
        user_id: int,
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        user = await get_web_user(session, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        count = await revoke_all_web_sessions(session, user.username)
        return {"username": user.username, "revoked": count}

    @app.get("/api/login-history", dependencies=[Depends(require_auth)])
    async def login_history(
        limit: int = Query(default=100, ge=1, le=500),
        session: AsyncSession = Depends(session_dependency),
    ) -> list[dict[str, Any]]:
        rows = await list_login_history(session, limit=limit)
        return [
            {
                "id": item.id,
                "username": item.username,
                "ip_address": item.ip_address,
                "user_agent": item.user_agent,
                "success": item.success,
                "reason": item.reason,
                "created_at": item.created_at,
            }
            for item in rows
        ]

    @app.get("/api/audit", dependencies=[Depends(require_auth)])
    async def audit_logs(
        limit: int = Query(default=100, ge=1, le=500),
        session: AsyncSession = Depends(session_dependency),
    ) -> list[dict[str, Any]]:
        rows = await list_audit_logs(session, limit=limit)
        return [
            {
                "id": item.id,
                "username": item.username,
                "method": item.method,
                "path": item.path,
                "status_code": item.status_code,
                "ip_address": item.ip_address,
                "created_at": item.created_at,
            }
            for item in rows
        ]

    @app.get("/api/control/commands", dependencies=[Depends(require_auth)])
    async def control_commands(
        limit: int = Query(default=50, ge=1, le=500),
        session: AsyncSession = Depends(session_dependency),
    ) -> list[dict[str, Any]]:
        rows = await list_control_commands(session, limit=limit)
        return [
            {
                "id": item.id,
                "command_type": item.command_type,
                "status": item.status,
                "result": item.result,
                "error": item.error,
                "created_at": item.created_at,
                "processed_at": item.processed_at,
            }
            for item in rows
        ]

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
