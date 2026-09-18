"""Administrator and channel-post checks for group messages."""

from __future__ import annotations

from typing import Any


async def is_admin_or_channel_post(
    client: Any,
    entity: Any,
    message: Any,
) -> bool:
    """Return whether a message is a channel post or was sent by an admin."""
    if bool(getattr(message, "post", False)):
        return True

    sender_id = getattr(message, "sender_id", None)
    if sender_id is None:
        return False

    try:
        permissions = await client.get_permissions(entity, sender_id)
    except Exception:  # noqa: BLE001 - inaccessible permissions should not leak content
        return False
    return bool(
        getattr(permissions, "is_admin", False)
        or getattr(permissions, "is_creator", False)
    )
