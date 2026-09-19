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


def test_stop_endpoint_requests_runtime_stop_and_cancels_waiting_jobs(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)
    calls: dict[str, object] = {}

    async def fake_cancel_pending_jobs(session):
        calls["cancelled_session"] = session
        return 7

    def fake_set_stop(path, stopped):
        calls["stop"] = (path, stopped)

    def fake_set_paused(path, paused):
        calls["paused"] = (path, paused)

    monkeypatch.setattr(api_main, "cancel_pending_jobs", fake_cancel_pending_jobs)
    monkeypatch.setattr(api_main, "set_runtime_stop_requested", fake_set_stop)
    monkeypatch.setattr(api_main, "set_runtime_paused", fake_set_paused)

    with TestClient(create_app()) as client:
        response = client.post("/api/stop")

    assert response.status_code == 200
    assert response.json()["stopped"] is True
    assert response.json()["cancelled"] == 7
    assert calls["stop"] == (config.project_root / "data" / "runtime_control.json", True)
    assert calls["paused"] == (config.project_root / "data" / "runtime_control.json", True)


def test_frontend_index_is_not_cached(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"


def test_batch_route_endpoint_returns_created_and_skipped_counts(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)
    captured: dict[str, object] = {}

    async def fake_add_routes_bulk(session, source_ids, target_ids):
        captured["source_ids"] = source_ids
        captured["target_ids"] = target_ids
        return (
            [
                SimpleNamespace(id=1, source_id=10, target_id=20, enabled=True),
                SimpleNamespace(id=2, source_id=10, target_id=21, enabled=True),
            ],
            [(11, 20)],
        )

    monkeypatch.setattr(api_main, "add_routes_bulk", fake_add_routes_bulk)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/routes/batch",
            json={"source_ids": [10, 11], "target_ids": [20, 21]},
        )

    assert response.status_code == 200
    assert captured == {"source_ids": [10, 11], "target_ids": [20, 21]}
    assert response.json()["created_count"] == 2
    assert response.json()["skipped_count"] == 1
    assert response.json()["skipped"] == [{"source_id": 11, "target_id": 20}]


def test_access_check_endpoint_enqueues_permission_command(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)
    captured: dict[str, object] = {}

    class StubCommand:
        id = 321
        status = "pending"

    async def fake_enqueue_control_command(session, command_type, payload):
        captured["command_type"] = command_type
        captured["payload"] = payload
        return StubCommand()

    monkeypatch.setattr(api_main, "enqueue_control_command", fake_enqueue_control_command)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/access/check",
            json={"source_ids": [1, 2], "target_ids": [9]},
        )

    assert response.status_code == 200
    assert response.json() == {"id": 321, "status": "pending"}
    assert captured == {
        "command_type": "check_access",
        "payload": {"source_ids": [1, 2], "target_ids": [9]},
    }


def test_sync_behavior_settings_endpoint_round_trip(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    async def fake_get_sync_behavior(session, defaults):
        return defaults

    async def fake_set_sync_behavior(session, settings):
        return settings

    monkeypatch.setattr(api_main, "get_sync_behavior", fake_get_sync_behavior)
    monkeypatch.setattr(api_main, "set_sync_behavior", fake_set_sync_behavior)

    with TestClient(create_app()) as client:
        current = client.get("/api/settings/sync")
        updated = client.put(
            "/api/settings/sync",
            json={"edits": True, "deletes": True},
        )

    assert current.status_code == 200
    assert current.json() == {"edits": False, "deletes": False}
    assert updated.status_code == 200
    assert updated.json() == {"edits": True, "deletes": True}


def test_delete_source_endpoint_returns_cleanup_counts(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    async def fake_delete_source(session, source_id):
        assert source_id == 7
        return {"routes": 2, "jobs": 9, "rules": 1}

    monkeypatch.setattr(api_main, "delete_source", fake_delete_source)

    with TestClient(create_app()) as client:
        response = client.delete("/api/sources/7")

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "deleted": True,
        "routes": 2,
        "jobs": 9,
        "rules": 1,
    }


def test_update_route_endpoint_changes_pair(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
    config.web.admin_password = ""
    config.web.session_secret = ""
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    async def fake_update_route(session, route_id, source_id, target_id):
        assert (route_id, source_id, target_id) == (5, 2, 9)
        return SimpleNamespace(
            id=route_id,
            source_id=source_id,
            target_id=target_id,
            enabled=True,
        )

    monkeypatch.setattr(api_main, "update_route", fake_update_route)

    with TestClient(create_app()) as client:
        response = client.put(
            "/api/routes/5",
            json={"source_id": 2, "target_id": 9},
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": 5,
        "source_id": 2,
        "target_id": 9,
        "enabled": True,
    }


def test_delete_user_endpoint_revokes_and_returns_user(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = "test-token"
    monkeypatch.setattr(api_main, "load_config", lambda: config)

    async def fake_delete_web_user(session, user_id, current_username=None):
        assert (user_id, current_username) == (8, "api-token")
        return SimpleNamespace(id=8, username="operator8")

    monkeypatch.setattr(api_main, "delete_web_user", fake_delete_web_user)

    with TestClient(create_app()) as client:
        response = client.delete(
            "/api/users/8",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": 8,
        "username": "operator8",
        "deleted": True,
    }
