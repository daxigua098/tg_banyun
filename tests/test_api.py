from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import create_app
from app.config import load_config


def test_api_health_and_sources(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)
    with TestClient(create_app()) as client:
        health = client.get("/health")
        sources = client.get("/api/sources")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert sources.status_code == 200
    assert isinstance(sources.json(), list)

def test_control_command_list(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)
    with TestClient(create_app()) as client:
        response = client.get("/api/control/commands")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_token_authentication(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = 'test-token'
    monkeypatch.setattr(api_main, 'load_config', lambda: config)

    with TestClient(create_app()) as client:
        unauthorized = client.get('/api/auth/check')
        authorized = client.get(
            '/api/auth/check',
            headers={'Authorization': 'Bearer test-token'},
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json() == {'authenticated': True}

def test_api_username_password_login(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ''
    config.web.admin_username = 'admin'
    config.web.admin_password = 'password'
    config.web.session_secret = 'session-secret'
    monkeypatch.setattr(api_main, 'load_config', lambda: config)

    with TestClient(create_app()) as client:
        login = client.post(
            '/api/auth/login',
            json={'username': 'admin', 'password': 'password'},
        )
        token = login.json()['token']
        check = client.get(
            '/api/auth/check',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert login.status_code == 200
    assert check.status_code == 200

def test_viewer_role_cannot_execute_write_actions(monkeypatch) -> None:
    from app.core.auth import create_session_token

    config = load_config()
    config.web.api_token = ''
    config.web.admin_password = ''
    config.web.session_secret = 'session-secret'
    monkeypatch.setattr(api_main, 'load_config', lambda: config)
    token, _ = create_session_token(config.web, 'viewer1', role='viewer')

    with TestClient(create_app()) as client:
        response = client.post(
            '/api/pause',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert response.status_code == 403
