from __future__ import annotations

from types import SimpleNamespace

from app.config import ContentFilterConfig
from app.core.content_filter import detect_media_kind, should_transfer_message


def test_detects_photo_and_video() -> None:
    photo = SimpleNamespace(photo=object(), video=None, media=None)
    video = SimpleNamespace(photo=None, video=object(), media=None)
    assert detect_media_kind(photo) == "photo"
    assert detect_media_kind(video) == "video"


def test_detects_media_documents_by_mime_type() -> None:
    image = SimpleNamespace(
        photo=None,
        video=None,
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/jpeg")),
    )
    video = SimpleNamespace(
        photo=None,
        video=None,
        media=SimpleNamespace(document=SimpleNamespace(mime_type="video/mp4")),
    )
    assert detect_media_kind(image) == "photo"
    assert detect_media_kind(video) == "video"


def test_media_only_filter_rejects_text_and_web_preview() -> None:
    config = ContentFilterConfig(media_only=True)
    text = SimpleNamespace(photo=None, video=None, media=None)
    web_preview = SimpleNamespace(
        photo=None,
        video=None,
        media=SimpleNamespace(document=None),
    )
    photo = SimpleNamespace(photo=object(), video=None, media=None)
    video = SimpleNamespace(photo=None, video=object(), media=None)

    assert should_transfer_message(text, config) is False
    assert should_transfer_message(web_preview, config) is False
    assert should_transfer_message(photo, config) is True
    assert should_transfer_message(video, config) is True


def test_media_filter_can_be_disabled() -> None:
    message = SimpleNamespace(photo=None, video=None, media=None)
    assert should_transfer_message(message, ContentFilterConfig(media_only=False)) is True
