"""Tests for GET /api/v1/positions endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis


def _mock_redis(state: dict[str, object] | None = None) -> MagicMock:
    r = MagicMock()
    r.get.return_value = json.dumps(state or {})
    return r


def _client(r: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    return TestClient(app, raise_server_exceptions=False)


class TestPositionsEndpoint:
    def test_returns_200(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/positions").status_code == 200

    def test_empty_when_no_state(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/positions").json() == []

    def test_returns_positions_from_state(self) -> None:
        state: dict[str, object] = {
            "open_positions": {
                "ord-1": {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "direction": "LONG",
                    "quantity": 100,
                    "entry_price": 2900.0,
                }
            }
        }
        data = _client(_mock_redis(state)).get("/api/v1/positions").json()
        assert len(data) == 1
        assert data[0]["symbol"] == "RELIANCE"
        assert data[0]["direction"] == "LONG"
        assert data[0]["quantity"] == 100

    def test_multiple_positions(self) -> None:
        state: dict[str, object] = {
            "open_positions": {
                "o1": {
                    "symbol": "A",
                    "exchange": "NSE",
                    "direction": "LONG",
                    "quantity": 10,
                    "entry_price": 100.0,
                },
                "o2": {
                    "symbol": "B",
                    "exchange": "NSE",
                    "direction": "SHORT",
                    "quantity": 5,
                    "entry_price": 200.0,
                },
            }
        }
        data = _client(_mock_redis(state)).get("/api/v1/positions").json()
        assert len(data) == 2

    def test_skips_invalid_entries(self) -> None:
        state: dict[str, object] = {
            "open_positions": {
                "bad": "not-a-dict",
                "good": {
                    "symbol": "X",
                    "exchange": "NSE",
                    "direction": "LONG",
                    "quantity": 1,
                    "entry_price": 10.0,
                },
            }
        }
        data = _client(_mock_redis(state)).get("/api/v1/positions").json()
        assert len(data) == 1

    def test_redis_error_returns_empty(self) -> None:
        r = MagicMock()
        r.get.side_effect = ConnectionError("down")
        assert _client(r).get("/api/v1/positions").json() == []
