"""Smoke test for the Part 1 placeholder app.

Proves that the test harness, FastAPI app, and HTTP client all work together.
Replaced with real endpoint tests once Part 2 introduces the app factory.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_responds() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Nexus AI" in response.json()["message"]
