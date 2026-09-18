from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import calculate_progress_percent, create_app
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
    assert authorized.json()['authenticated'] is True
    assert authorized.json()['role'] == 'super_admin'

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


def test_sync_command_includes_fuzzy_keywords(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    captured: dict[str, object] = {}

    class StubCommand:
        id = 123
        status = "pending"

    async def fake_enqueue_control_command(session, command_type, payload):
        captured["session"] = session
        captured["command_type"] = command_type
        captured["payload"] = payload
        return StubCommand()

    monkeypatch.setattr(api_main, "enqueue_control_command", fake_enqueue_control_command)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/control/sync",
            json={"source_id": 1, "limit": 30, "keywords": ["AI", "主播"]},
        )

    assert response.status_code == 200
    assert response.json() == {"id": 123, "status": "pending"}
    assert captured["command_type"] == "sync"
    assert captured["payload"] == {
        "source_id": 1,
        "limit": 30,
        "keywords": ["AI", "主播"],
        "recent": True,
    }

def test_control_commands_include_delivery_progress(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    command = SimpleNamespace(
        id=55,
        command_type="sync",
        status="success",
        payload='{"source_id": 999}',
        result='{"source_id": 999, "inspected": 0}',
        error=None,
        created_at=datetime.now(UTC),
        processed_at=datetime.now(UTC),
    )

    async def fake_list_control_commands(session, limit=50):
        return [command]

    monkeypatch.setattr(api_main, "list_control_commands", fake_list_control_commands)

    with TestClient(create_app()) as client:
        response = client.get("/api/control/commands")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == 55
    assert item["progress"] == {
        "total": 0,
        "completed": 0,
        "success": 0,
        "failed": 0,
        "pending": 0,
        "percent": 100,
    }


def test_sync_progress_uses_completed_jobs_not_command_status() -> None:
    assert calculate_progress_percent(total=130, completed=1) == 0
    assert calculate_progress_percent(total=130, completed=65) == 50
    assert calculate_progress_percent(total=130, completed=130) == 100
    assert calculate_progress_percent(total=0, completed=0) == 100
