"""Message batch representation for single posts and Telegram albums."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MessageBatch:
    """One logical source post, optionally containing multiple album messages."""

    message_ids: tuple[int, ...]
    media_group_id: int | None = None

    def __post_init__(self) -> None:
        if not self.message_ids:
            raise ValueError("MessageBatch requires at least one message ID.")
        normalized = tuple(dict.fromkeys(int(message_id) for message_id in self.message_ids))
        if len(normalized) != len(self.message_ids):
            raise ValueError("MessageBatch contains duplicate message IDs.")
        object.__setattr__(self, "message_ids", normalized)

    @property
    def primary_message_id(self) -> int:
        """Return the stable database key for the batch."""
        return min(self.message_ids)

    @property
    def max_message_id(self) -> int:
        """Return the highest Telegram message ID in the batch."""
        return max(self.message_ids)

    @property
    def is_album(self) -> bool:
        """Return whether this batch contains more than one message."""
        return len(self.message_ids) > 1

    @classmethod
    def from_messages(cls, messages: Iterable[Any]) -> MessageBatch:
        """Build a batch while preserving Telegram's message order."""
        items = list(messages)
        if not items:
            raise ValueError("Cannot build a MessageBatch from an empty message list.")
        grouped_id = next(
            (
                int(message.grouped_id)
                for message in items
                if getattr(message, "grouped_id", None) is not None
            ),
            None,
        )
        return cls(
            message_ids=tuple(int(message.id) for message in items),
            media_group_id=grouped_id,
        )
