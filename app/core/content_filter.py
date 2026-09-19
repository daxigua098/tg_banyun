"""Content-type filters applied before messages enter the delivery queue."""

from __future__ import annotations

from typing import Any, Literal

from app.config import ContentFilterConfig
from app.services.rule_service import load_keywords, load_sender_ids

MediaKind = Literal["photo", "video"]


def detect_media_kind(message: Any) -> MediaKind | None:
    """Return photo/video when a Telegram message contains transferable visual media."""
    if getattr(message, "photo", None) is not None:
        return "photo"
    if getattr(message, "video", None) is not None:
        return "video"

    media = getattr(message, "media", None)
    document = getattr(media, "document", None)
    mime_type = str(getattr(document, "mime_type", "") or "").lower()
    if mime_type.startswith("image/"):
        return "photo"
    if mime_type.startswith("video/"):
        return "video"
    return None


def should_transfer_message(message: Any, config: ContentFilterConfig) -> bool:
    """Apply the configured media-only policy to one Telegram message."""
    if not config.media_only:
        return True

    media_kind = detect_media_kind(message)
    if media_kind == "photo":
        return config.allow_photo
    if media_kind == "video":
        return config.allow_video
    return False


def should_transfer_for_source(
    message: Any,
    config: ContentFilterConfig,
    rule: Any,
) -> bool:
    """Apply global media settings and one source's keyword/forwarding rules."""
    if not should_transfer_message(message, config):
        return False

    media_kind = detect_media_kind(message)
    if media_kind == "photo" and not bool(rule.allow_photo):
        return False
    if media_kind == "video" and not bool(rule.allow_video):
        return False
    if bool(rule.post_only) and not bool(getattr(message, "post", False)):
        return False

    sender_id = getattr(message, "sender_id", None)
    sender_whitelist = load_sender_ids(rule.sender_whitelist)
    sender_blacklist = load_sender_ids(rule.sender_blacklist)
    if sender_whitelist and sender_id not in sender_whitelist:
        return False
    if sender_blacklist and sender_id in sender_blacklist:
        return False

    text = str(getattr(message, "raw_text", "") or "").casefold()
    whitelist = [keyword.casefold() for keyword in load_keywords(rule.keyword_whitelist)]
    blacklist = [keyword.casefold() for keyword in load_keywords(rule.keyword_blacklist)]
    if whitelist and not any(keyword in text for keyword in whitelist):
        return False
    if blacklist and any(keyword in text for keyword in blacklist):
        return False

    if bool(rule.skip_forwarded) and (
        getattr(message, "forward", None) is not None
        or getattr(message, "fwd_from", None) is not None
    ):
        return False
    return True
