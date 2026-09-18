from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import ContentFilterConfig
from app.core.content_filter import should_transfer_for_source
from app.models import Base, Source, SourceRule
from app.services.rule_service import load_keywords, set_source_rule


async def _build_factory() -> tuple[async_sessionmaker, object]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory, engine


async def test_source_rule_update_and_keyword_filter() -> None:
    session_factory, engine = await _build_factory()
    async with session_factory() as session:
        session.add(
            Source(
                raw_input="@source",
                normalized_key="username:source",
                tg_id=100,
                title="Source",
            )
        )
        await session.commit()
        rule = await set_source_rule(session, 1, "whitelist", "猫,狗")
        assert load_keywords(rule.keyword_whitelist) == ["猫", "狗"]
        await set_source_rule(session, 1, "blacklist", "广告")
        await set_source_rule(session, 1, "forwarded", "skip")

    photo = SimpleNamespace(
        photo=object(),
        video=None,
        media=None,
        raw_text="可爱猫咪",
        forward=None,
        fwd_from=None,
    )
    blocked = SimpleNamespace(
        photo=object(),
        video=None,
        media=None,
        raw_text="猫咪广告",
        forward=None,
        fwd_from=None,
    )
    forwarded = SimpleNamespace(
        photo=object(),
        video=None,
        media=None,
        raw_text="猫咪",
        forward=object(),
        fwd_from=None,
    )
    assert should_transfer_for_source(photo, ContentFilterConfig(media_only=True), rule) is True
    assert should_transfer_for_source(blocked, ContentFilterConfig(media_only=True), rule) is False
    assert (
        should_transfer_for_source(forwarded, ContentFilterConfig(media_only=True), rule)
        is False
    )
    await engine.dispose()


def test_post_only_rule_rejects_group_messages() -> None:
    rule = SourceRule(source_id=1, post_only=True, allow_photo=True, allow_video=True)
    group_message = SimpleNamespace(
        photo=object(),
        video=None,
        media=None,
        raw_text="",
        forward=None,
        fwd_from=None,
        post=False,
    )
    channel_post = SimpleNamespace(
        photo=object(),
        video=None,
        media=None,
        raw_text="",
        forward=None,
        fwd_from=None,
        post=True,
    )
    config = ContentFilterConfig(media_only=True)

    assert should_transfer_for_source(group_message, config, rule) is False
    assert should_transfer_for_source(channel_post, config, rule) is True

