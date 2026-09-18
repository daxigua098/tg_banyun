"""Normalize Telegram source and target inputs without network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

ResolutionKind = Literal["username", "invite", "chat_id"]

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_INVITE_RE = re.compile(r"^[A-Za-z0-9_-]{16,}$")
_PRIVATE_LINK_RE = re.compile(r"^c/(?P<internal_id>\d+)(?:/\d+)?$", re.IGNORECASE)
_PUBLIC_MESSAGE_LINK_RE = re.compile(
    r"^(?P<username>[A-Za-z][A-Za-z0-9_]{4,31})/\d+$"
)
_MARKDOWN_LINK_RE = re.compile(r"^\[[^\]]+\]\((?P<url>https?://[^)]+)\)$")
_ZERO_WIDTH_CHARS = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


@dataclass(frozen=True, slots=True)
class ResolvedChat:
    """A normalized Telegram chat reference."""

    raw: str
    kind: ResolutionKind
    value: str
    normalized_key: str
    is_private: bool


def _clean_raw_input(raw_input: str) -> str:
    value = raw_input.strip().translate(_ZERO_WIDTH_CHARS)
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    markdown_match = _MARKDOWN_LINK_RE.fullmatch(value)
    if markdown_match:
        value = markdown_match.group("url")
    return value


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


def _resolved_username(raw_input: str, username: str) -> ResolvedChat:
    normalized = username.lower()
    return ResolvedChat(
        raw=raw_input,
        kind="username",
        value=username,
        normalized_key=f"username:{normalized}",
        is_private=False,
    )


def _resolve_tg_url(raw_input: str, value: str) -> ResolvedChat | None:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    query = parse_qs(parsed.query)

    if host == "resolve" and query.get("domain"):
        username = query["domain"][0].removeprefix("@")
        if _USERNAME_RE.fullmatch(username):
            return _resolved_username(raw_input, username)

    if host == "join" and query.get("invite"):
        invite_hash = query["invite"][0]
        if _INVITE_RE.fullmatch(invite_hash):
            return ResolvedChat(
                raw=raw_input,
                kind="invite",
                value=invite_hash,
                normalized_key=f"invite:{invite_hash}",
                is_private=True,
            )
    return None


def resolve_chat_input(raw_input: str) -> ResolvedChat:
    """Parse a Telegram username, invite link, private link, or chat ID."""
    raw = _clean_raw_input(raw_input)
    if not raw:
        raise ValueError("Telegram 链接不能为空。")

    if raw.lower().startswith("tg://"):
        resolved = _resolve_tg_url(raw_input, raw)
        if resolved is not None:
            return resolved

    if re.fullmatch(r"-?\d+", raw):
        chat_id = int(raw)
        return ResolvedChat(
            raw=raw_input,
            kind="chat_id",
            value=str(chat_id),
            normalized_key=f"chat_id:{chat_id}",
            is_private=chat_id < 0,
        )

    if raw.lower().startswith(("http://", "https://")):
        host = (urlparse(raw).hostname or "").lower()
        if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
            raise ValueError(
                f"“{raw}”是普通网站链接，不是 Telegram 频道或群组，不能作为搬运源或目标。"
            )

    value = _strip_known_prefix(raw).split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]
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
            raise ValueError(f"私有邀请链接格式不正确：{raw_input}")
        return ResolvedChat(
            raw=raw_input,
            kind="invite",
            value=invite_hash,
            normalized_key=f"invite:{invite_hash}",
            is_private=True,
        )

    public_message_match = _PUBLIC_MESSAGE_LINK_RE.fullmatch(value)
    if public_message_match:
        return _resolved_username(raw_input, public_message_match.group("username"))

    username = value.removeprefix("@").strip("/")
    if _USERNAME_RE.fullmatch(username):
        return _resolved_username(raw_input, username)

    raise ValueError(
        "不支持的 Telegram 链接格式。请发送公开频道链接、消息链接、"
        "私有邀请链接、@用户名或数字 chat ID。"
    )

