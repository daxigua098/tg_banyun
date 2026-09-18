"""Runtime-editable system settings."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AdditionalConfig
from app.models import SystemSetting

ADDITIONAL_SETTINGS_KEY = "additional_content"


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
