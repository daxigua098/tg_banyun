"""Admin username/password and signed session token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.config import WebConfig


def create_session_token(config: WebConfig, username: str) -> tuple[str, int]:
    """Create a signed expiring session token."""
    expires_at = int(time.time()) + config.session_hours * 3600
    payload = json.dumps(
        {"sub": username, "exp": expires_at},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(
        config.session_secret.encode("utf-8"),
        encoded,
        hashlib.sha256,
    ).digest()
    token = encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
    return token.decode("ascii"), expires_at


def verify_session_token(config: WebConfig, token: str) -> dict[str, Any] | None:
    """Verify a signed session token and return its payload."""
    if not config.session_secret:
        return None
    try:
        encoded, signature = token.encode("ascii").rsplit(b".", maxsplit=1)
    except (ValueError, UnicodeEncodeError):
        return None

    expected = hmac.new(
        config.session_secret.encode("utf-8"),
        encoded,
        hashlib.sha256,
    ).digest()
    supplied = base64.urlsafe_b64decode(signature + b"=" * (-len(signature) % 4))
    if not hmac.compare_digest(expected, supplied):
        return None

    payload_bytes = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("exp") or 0) < int(time.time()):
        return None
    return payload
