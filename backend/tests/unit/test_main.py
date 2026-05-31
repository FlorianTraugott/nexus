"""Tests for the application factory and health endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_exposes_title() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Nexus AI"


def test_docs_available() -> None:
    response = client.get("/docs")
    assert response.status_code == 200
