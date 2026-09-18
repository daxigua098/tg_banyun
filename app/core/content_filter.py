"""Content-type filters applied before messages enter the delivery queue."""

from __future__ import annotations

from typing import Any, Literal

from app.config import ContentFilterConfig

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
