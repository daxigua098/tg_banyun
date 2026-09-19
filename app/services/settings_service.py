"""Runtime-editable system settings."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AdditionalConfig, SyncBehaviorConfig
from app.models import SystemSetting

ADDITIONAL_SETTINGS_KEY = "additional_content"
SYNC_BEHAVIOR_KEY = "sync_behavior"


async def get_additional_settings(
    session: AsyncSession,
    defaults: AdditionalConfig,
) -> AdditionalConfig:
    row = await session.get(SystemSetting, ADDITIONAL_SETTINGS_KEY)
    if row is None:
        return defaults
    try:
        data = json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    merged = defaults.model_dump()
    merged.update(data)
    try:
        return AdditionalConfig.model_validate(merged)
    except ValueError:
        return defaults


async def set_additional_settings(
    session: AsyncSession,
    settings: AdditionalConfig,
) -> AdditionalConfig:
    data = settings.model_dump()
    row = await session.get(SystemSetting, ADDITIONAL_SETTINGS_KEY)
    encoded = json.dumps(data, ensure_ascii=False)
    if row is None:
        row = SystemSetting(key=ADDITIONAL_SETTINGS_KEY, value=encoded)
        session.add(row)
    else:
        row.value = encoded
    await session.commit()
    return settings


async def get_sync_behavior(
    session: AsyncSession,
    defaults: SyncBehaviorConfig,
) -> SyncBehaviorConfig:
    row = await session.get(SystemSetting, SYNC_BEHAVIOR_KEY)
    if row is None:
        return defaults
    try:
        data = json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    merged = defaults.model_dump()
    merged.update(data)
    try:
        return SyncBehaviorConfig.model_validate(merged)
    except ValueError:
        return defaults


async def set_sync_behavior(
    session: AsyncSession,
    settings: SyncBehaviorConfig,
) -> SyncBehaviorConfig:
    row = await session.get(SystemSetting, SYNC_BEHAVIOR_KEY)
    encoded = json.dumps(settings.model_dump(), ensure_ascii=False)
    if row is None:
        row = SystemSetting(key=SYNC_BEHAVIOR_KEY, value=encoded)
        session.add(row)
    else:
        row.value = encoded
    await session.commit()
    return settings
