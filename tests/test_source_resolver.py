from __future__ import annotations

import pytest

from app.core.source_resolver import resolve_chat_input


@pytest.mark.parametrize(
    ("raw", "kind", "value", "normalized_key"),
    [
        ("@Example_Channel", "username", "Example_Channel", "username:example_channel"),
        ("https://t.me/Example_Channel", "username", "Example_Channel", "username:example_channel"),
        (
            "https://t.me/Example_Channel/123",
            "username",
            "Example_Channel",
            "username:example_channel",
        ),
        ("t.me/porna91com/1", "username", "porna91com", "username:porna91com"),
        (
            "[https://t.me/Example_Channel](https://t.me/Example_Channel)",
            "username",
            "Example_Channel",
            "username:example_channel",
        ),
        (
            "<https://t.me/Example_Channel/123?single>",
            "username",
            "Example_Channel",
            "username:example_channel",
        ),
        (
            "tg://resolve?domain=Example_Channel&post=123",
            "username",
            "Example_Channel",
            "username:example_channel",
        ),
        ("-1001234567890", "chat_id", "-1001234567890", "chat_id:-1001234567890"),
        ("123456789", "chat_id", "123456789", "chat_id:123456789"),
        (
            "https://t.me/c/123456789/44",
            "chat_id",
            "-100123456789",
            "chat_id:-100123456789",
        ),
    ],
)
def test_resolve_chat_input(
    raw: str,
    kind: str,
    value: str,
    normalized_key: str,
) -> None:
    resolved = resolve_chat_input(raw)
    assert resolved.kind == kind
    assert resolved.value == value
    assert resolved.normalized_key == normalized_key


def test_resolve_invite_link() -> None:
    resolved = resolve_chat_input("https://t.me/+AbCdEfGhIjKlMnOpQrStUv")
    assert resolved.kind == "invite"
    assert resolved.is_private is True
    assert resolved.normalized_key.startswith("invite:")


def test_reject_invalid_input() -> None:
    with pytest.raises(ValueError, match="普通网站"):
        resolve_chat_input("https://example.com")



