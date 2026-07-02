"""Tests for GET /api/v1/pnl endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis


def _mock_redis(
    pnl: float | None = None,
    halted: bool = False,
) -> MagicMock:
    r = MagicMock()

    def _get(key: str) -> str | None:
        if key.startswith("risk:daily:pnl:"):
            return str(pnl) if pnl is not None else None
        if key == "system:status:halted":
            return "1" if halted else None
        if key == "orchestrator:state":
            return "{}"
        return None

    r.get.side_effect = _get
    return r


def _client(r: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    return TestClient(app, raise_server_exceptions=False)


class TestPnLEndpoint:
    def test_returns_200(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/pnl").status_code == 200

    def test_zero_pnl_when_no_redis_data(self) -> None:
        body = _client(_mock_redis()).get("/api/v1/pnl").json()
        assert body["total_pnl"] == 0.0

    def test_reads_pnl_from_redis_key(self) -> None:
        body = _client(_mock_redis(pnl=2500.0)).get("/api/v1/pnl").json()
        assert body["total_pnl"] == 2500.0

    def test_negative_pnl_preserved(self) -> None:
        body = _client(_mock_redis(pnl=-1200.0)).get("/api/v1/pnl").json()
        assert body["total_pnl"] == -1200.0

    def test_is_halted_reflects_redis(self) -> None:
        body = _client(_mock_redis(halted=True)).get("/api/v1/pnl").json()
        assert body["is_halted"] is True

    def test_date_field_present(self) -> None:
        body = _client(_mock_redis()).get("/api/v1/pnl").json()
        assert len(body["date"]) == 10  # YYYY-MM-DD

    def test_redis_error_returns_zeros(self) -> None:
        r = MagicMock()
        r.get.side_effect = ConnectionError("down")
        body = _client(r).get("/api/v1/pnl").json()
        assert body["total_pnl"] == 0.0
        assert body["is_halted"] is False
