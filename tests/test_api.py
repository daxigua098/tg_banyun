from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import create_app
from app.config import load_config


def test_api_health_and_sources(monkeypatch) -> None:
    config = load_config()
    config.web.api_token = ""
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
