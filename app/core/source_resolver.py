"""Normalize Telegram source and target inputs without network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ResolutionKind = Literal["username", "invite", "chat_id"]

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_INVITE_RE = re.compile(r"^[A-Za-z0-9_-]{16,}$")
_PRIVATE_LINK_RE = re.compile(r"^c/(?P<internal_id>\d+)(?:/\d+)?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ResolvedChat:
    """A normalized Telegram chat reference."""

    raw: str
    kind: ResolutionKind
    value: str
    normalized_key: str
    is_private: bool


def _strip_known_prefix(value: str) -> str:
    value = value.strip()
    for prefix in ("https://", "http://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break

    lowered = value.lower()
    for telegram_host in ("t.me/", "telegram.me/", "www.t.me/"):
        if lowered.startswith(telegram_host):
            return value[len(telegram_host) :].strip("/")
    return value


def resolve_chat_input(raw_input: str) -> ResolvedChat:
    """Parse a Telegram username, invite link, private link, or chat ID."""
    raw = raw_input.strip()
    if not raw:
        raise ValueError("Telegram chat input cannot be empty.")

    if re.fullmatch(r"-?\d+", raw):
        chat_id = int(raw)
        return ResolvedChat(
            raw=raw_input,
            kind="chat_id",
            value=str(chat_id),
            normalized_key=f"chat_id:{chat_id}",
            is_private=chat_id < 0,
        )

    value = _strip_known_prefix(raw)
    lowered = value.lower()

    private_match = _PRIVATE_LINK_RE.fullmatch(value)
    if private_match:
        internal_id = int(private_match.group("internal_id"))
        chat_id = int(f"-100{internal_id}")
        return ResolvedChat(
            raw=raw_input,
            kind="chat_id",
            value=str(chat_id),
            normalized_key=f"chat_id:{chat_id}",
            is_private=True,
        )

    if lowered.startswith(("+", "joinchat/", "join/")):
        invite_hash = value.split("/", maxsplit=1)[-1].removeprefix("+")
        if not _INVITE_RE.fullmatch(invite_hash):
            raise ValueError(f"Invalid Telegram invite link: {raw_input}")
        return ResolvedChat(
            raw=raw_input,
            kind="invite",
            value=invite_hash,
            normalized_key=f"invite:{invite_hash}",
            is_private=True,
        )

    username = value.removeprefix("@").strip("/")
    if _USERNAME_RE.fullmatch(username):
        normalized = username.lower()
        return ResolvedChat(
            raw=raw_input,
            kind="username",
            value=username,
            normalized_key=f"username:{normalized}",
            is_private=False,
        )

    raise ValueError(
        "Unsupported Telegram chat input. Use @username, t.me/username, "
        "t.me/+invite, t.me/c/..., or a numeric chat ID."
    )
