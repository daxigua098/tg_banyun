"""Server-side web session persistence and revocation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WebSession


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


async def create_web_session(
    session: AsyncSession,
    *,
    token: str,
    username: str,
    role: str,
    expires_at: int,
) -> WebSession:
    record = WebSession(
        token_hash=hash_session_token(token),
        username=username,
        role=role,
        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
    )
    session.add(record)
    await session.commit()
    return record


async def is_web_session_valid(session: AsyncSession, token: str) -> bool:
    record = await session.get(WebSession, hash_session_token(token))
    if record is None or record.revoked:
        return False
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC)


async def revoke_web_session(session: AsyncSession, token: str) -> bool:
    record = await session.get(WebSession, hash_session_token(token))
    if record is None:
        return False
    record.revoked = True
    await session.commit()
    return True
