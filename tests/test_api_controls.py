"""Tests for POST /api/v1/controls/* endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis


def _client(r: MagicMock, api_key: str = "") -> TestClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    with patch("api.auth.settings") as ms:
        ms.api_key = api_key
        return TestClient(app, raise_server_exceptions=False)


class TestKillEndpoint:
    def test_missing_key_returns_401(self) -> None:
        r = MagicMock()
        with patch("api.auth.settings") as ms:
            ms.api_key = "set"
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/v1/controls/kill")
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self) -> None:
        r = MagicMock()
        with patch("api.auth.settings") as ms:
            ms.api_key = "correct"
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/controls/kill", headers={"X-API-Key": "wrong"}
            )
        assert resp.status_code == 403

    def test_no_server_key_configured_returns_403(self) -> None:
        r = MagicMock()
        with patch("api.auth.settings") as ms:
            ms.api_key = ""
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/controls/kill", headers={"X-API-Key": "anything"}
            )
        assert resp.status_code == 403

    def test_valid_key_triggers_kill_switch(self) -> None:
        r = MagicMock()
        with (
            patch("api.auth.settings") as ms,
            patch("api.routers.controls.KillSwitchManager") as mk,
        ):
            ms.api_key = "secret"
            mk.return_value.trigger_tier2.return_value = MagicMock()
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/controls/kill", headers={"X-API-Key": "secret"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["action"] == "kill"

    def test_kill_switch_error_returns_failure(self) -> None:
        r = MagicMock()
        with (
            patch("api.auth.settings") as ms,
            patch("api.routers.controls.KillSwitchManager") as mk,
        ):
            ms.api_key = "s"
            mk.return_value.trigger_tier2.side_effect = RuntimeError("boom")
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/controls/kill", headers={"X-API-Key": "s"}
            )
        body = resp.json()
        assert body["success"] is False


class TestPauseEndpoint:
    def test_missing_key_returns_401(self) -> None:
        r = MagicMock()
        with patch("api.auth.settings") as ms:
            ms.api_key = "set"
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/v1/controls/pause")
        assert resp.status_code == 401

    def test_valid_key_sets_pause_flag(self) -> None:
        r = MagicMock()
        r.set.return_value = True
        with patch("api.auth.settings") as ms:
            ms.api_key = "k"
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/controls/pause", headers={"X-API-Key": "k"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["action"] == "pause"
        r.set.assert_called_once_with("system:status:paused", "1")


class TestResumeEndpoint:
    def test_missing_key_returns_401(self) -> None:
        r = MagicMock()
        with patch("api.auth.settings") as ms:
            ms.api_key = "set"
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/v1/controls/resume")
        assert resp.status_code == 401

    def test_valid_key_clears_pause_flag(self) -> None:
        r = MagicMock()
        r.delete.return_value = 1
        with patch("api.auth.settings") as ms:
            ms.api_key = "k"
            app = create_app()
            app.dependency_overrides[get_redis] = lambda: r
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/controls/resume", headers={"X-API-Key": "k"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["action"] == "resume"
        r.delete.assert_called_once_with("system:status:paused")
