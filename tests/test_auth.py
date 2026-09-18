from __future__ import annotations

from app.config import WebConfig
from app.core.auth import create_session_token, verify_session_token


def test_session_token_round_trip() -> None:
    config = WebConfig(admin_username='admin', session_secret='secret', session_hours=1)
    token, expires_at = create_session_token(config, 'admin')

    payload = verify_session_token(config, token)

    assert payload is not None
    assert payload['sub'] == 'admin'
    assert payload['exp'] == expires_at


def test_session_token_rejects_wrong_secret() -> None:
    token, _ = create_session_token(
        WebConfig(session_secret='secret', session_hours=1),
        'admin',
    )
    assert verify_session_token(WebConfig(session_secret='other'), token) is None
