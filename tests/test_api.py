from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app


def test_api_health_and_sources() -> None:
    with TestClient(create_app()) as client:
        health = client.get("/health")
        sources = client.get("/api/sources")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert sources.status_code == 200
    assert isinstance(sources.json(), list)
