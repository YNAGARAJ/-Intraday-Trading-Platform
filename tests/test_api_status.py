"""Tests for GET /api/v1/status endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis


def _mock_redis(
    *,
    halted: bool = False,
    paused: bool = False,
    degraded: bool = False,
    state: dict[str, object] | None = None,
) -> MagicMock:
    r = MagicMock()

    def _get(key: str) -> str | None:
        mapping = {
            "system:status:halted": "1" if halted else None,
            "system:status:paused": "1" if paused else None,
            "system:status:degraded": "1" if degraded else None,
            "orchestrator:state": json.dumps(state or {}),
        }
        return mapping.get(key)

    r.get.side_effect = _get
    return r


def _client(r: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    return TestClient(app, raise_server_exceptions=False)


class TestStatusEndpoint:
    def test_returns_200(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/status").status_code == 200

    def test_default_not_halted(self) -> None:
        body = _client(_mock_redis()).get("/api/v1/status").json()
        assert body["is_halted"] is False

    def test_halted_key_sets_is_halted(self) -> None:
        body = _client(_mock_redis(halted=True)).get("/api/v1/status").json()
        assert body["is_halted"] is True

    def test_paused_key_sets_is_paused(self) -> None:
        body = _client(_mock_redis(paused=True)).get("/api/v1/status").json()
        assert body["is_paused"] is True

    def test_degraded_key_sets_is_degraded(self) -> None:
        body = _client(_mock_redis(degraded=True)).get("/api/v1/status").json()
        assert body["is_degraded"] is True

    def test_kill_switch_active_from_state(self) -> None:
        state: dict[str, object] = {"kill_switch_active": True}
        body = _client(_mock_redis(state=state)).get("/api/v1/status").json()
        assert body["kill_switch_active"] is True
        assert body["is_halted"] is True

    def test_pnl_from_state(self) -> None:
        state: dict[str, object] = {"pnl_today": 1500.0, "pnl_today_pct": 0.15}
        body = _client(_mock_redis(state=state)).get("/api/v1/status").json()
        assert body["pnl_today"] == 1500.0
        assert body["pnl_today_pct"] == 0.15

    def test_open_positions_count_from_state(self) -> None:
        state: dict[str, object] = {"open_positions": {"a": {}, "b": {}}}
        body = _client(_mock_redis(state=state)).get("/api/v1/status").json()
        assert body["open_positions_count"] == 2

    def test_redis_failure_returns_safe_defaults(self) -> None:
        r = MagicMock()
        r.get.side_effect = ConnectionError("down")
        body = _client(r).get("/api/v1/status").json()
        assert body["is_halted"] is False
        assert body["pnl_today"] == 0.0

    def test_trading_mode_present(self) -> None:
        body = _client(_mock_redis()).get("/api/v1/status").json()
        assert "trading_mode" in body

    def test_timestamp_ms_present(self) -> None:
        body = _client(_mock_redis()).get("/api/v1/status").json()
        assert body["timestamp_ms"] > 0
