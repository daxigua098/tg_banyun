"""Per-source content rule management."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceRule

RULE_FIELDS = {
    "photo": "allow_photo",
    "video": "allow_video",
    "whitelist": "keyword_whitelist",
    "blacklist": "keyword_blacklist",
    "forwarded": "skip_forwarded",
}


async def get_source_rule(session: AsyncSession, source_id: int) -> SourceRule:
    """Return the configured rule, creating defaults when absent."""
    rule = await session.get(SourceRule, source_id)
    if rule is not None:
        return rule
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError(f"源 {source_id} 不存在。")
    rule = SourceRule(source_id=source_id)
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def list_source_rules(session: AsyncSession) -> list[tuple[Source, SourceRule]]:
    """List all sources with their effective rules."""
    sources = list(await session.scalars(select(Source).order_by(Source.id.asc())))
    results: list[tuple[Source, SourceRule]] = []
    for source in sources:
        rule = await get_source_rule(session, source.id)
        results.append((source, rule))
    return results


async def set_source_rule(
    session: AsyncSession,
    source_id: int,
    field: str,
    value: str,
) -> SourceRule:
    """Update one source rule field from a management-bot value."""
    normalized_field = field.lower()
    column = RULE_FIELDS.get(normalized_field)
    if column is None:
        raise ValueError("可用字段：photo、video、whitelist、blacklist、forwarded。")

    rule = await get_source_rule(session, source_id)
    if column in {"allow_photo", "allow_video"}:
        setattr(rule, column, _parse_toggle(value))
    elif column == "skip_forwarded":
        if value.lower() not in {"skip", "allow"}:
            raise ValueError("forwarded 只能设置为 skip 或 allow。")
        rule.skip_forwarded = value.lower() == "skip"
    else:
        keywords = [item.strip() for item in value.split(",") if item.strip()]
        setattr(rule, column, json.dumps(keywords, ensure_ascii=False))

    await session.commit()
    await session.refresh(rule)
    return rule


def _parse_toggle(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"on", "yes", "true", "1", "开"}:
        return True
    if lowered in {"off", "no", "false", "0", "关"}:
        return False
    raise ValueError("开关值只能使用 on/off。")


def load_keywords(value: str) -> list[str]:
    """Load a keyword list from its JSON storage."""
    try:
        items = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in items] if isinstance(items, list) else []
