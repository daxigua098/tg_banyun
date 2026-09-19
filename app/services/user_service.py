"""Web user management for role-based access."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, verify_password
from app.models import WebUser
from app.services.session_service import revoke_all_web_sessions

VALID_ROLES = {"super_admin", "operator", "viewer"}


async def list_web_users(session: AsyncSession) -> list[WebUser]:
    return list(await session.scalars(select(WebUser).order_by(WebUser.id.asc())))


async def get_web_user(session: AsyncSession, user_id: int) -> WebUser | None:
    return await session.get(WebUser, user_id)


async def get_web_user_by_username(session: AsyncSession, username: str) -> WebUser | None:
    return await session.scalar(select(WebUser).where(WebUser.username == username))


async def create_web_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: str,
) -> WebUser:
    username = username.strip()
    if not username or not password:
        raise ValueError("用户名和密码不能为空。")
    if role not in VALID_ROLES:
        raise ValueError(f"角色必须是：{', '.join(sorted(VALID_ROLES))}")
    if await get_web_user_by_username(session, username) is not None:
        raise ValueError("用户名已存在。")
    user = WebUser(
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_web_user(
    session: AsyncSession,
    user_id: int,
    *,
    role: str | None = None,
    enabled: bool | None = None,
    password: str | None = None,
) -> WebUser:
    user = await session.get(WebUser, user_id)
    if user is None:
        raise ValueError("用户不存在。")
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError(f"角色必须是：{', '.join(sorted(VALID_ROLES))}")
        user.role = role
    if enabled is not None:
        user.enabled = enabled
    if password:
        user.password_hash = hash_password(password)
    if enabled is False:
        await revoke_all_web_sessions(session, user.username)
    if password:
        await revoke_all_web_sessions(session, user.username)
    await session.commit()
    await session.refresh(user)
    return user


def authenticate_web_user(user: WebUser, password: str) -> bool:
    return user.enabled and verify_password(password, user.password_hash)


async def delete_web_user(
    session: AsyncSession,
    user_id: int,
    *,
    current_username: str | None = None,
) -> WebUser:
    """Delete a web user after protecting the active and final super admin."""
    user = await session.get(WebUser, user_id)
    if user is None:
        raise ValueError("用户不存在。")
    if current_username and user.username == current_username:
        raise ValueError("不能删除当前登录用户。")
    if user.role == "super_admin":
        super_admin_count = int(
            await session.scalar(
                select(func.count())
                .select_from(WebUser)
                .where(WebUser.role == "super_admin")
            )
            or 0
        )
        if super_admin_count <= 1:
            raise ValueError("至少需要保留一个超级管理员。")
    await revoke_all_web_sessions(session, user.username)
    await session.delete(user)
    await session.commit()
    return user
