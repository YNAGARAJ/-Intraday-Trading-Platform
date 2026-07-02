"""Tests for GET /health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


class TestHealthEndpoint:
    def test_returns_200(self) -> None:
        assert _client().get("/health").status_code == 200

    def test_returns_ok(self) -> None:
        assert _client().get("/health").json()["status"] == "ok"

    def test_no_auth_required(self) -> None:
        # Even with no API key header the health check succeeds.
        resp = _client().get("/health")
        assert resp.status_code == 200

    def test_content_type_json(self) -> None:
        resp = _client().get("/health")
        assert "application/json" in resp.headers["content-type"]
