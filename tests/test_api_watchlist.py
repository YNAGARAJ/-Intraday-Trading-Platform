"""Tests for GET /api/v1/watchlist endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis


def _mock_redis(
    watchlist: list[dict[str, object]] | None = None,
    exchange: str = "NSE",
) -> MagicMock:
    r = MagicMock()

    def _get(key: str) -> str | None:
        if key == f"universe:watchlist:{exchange}":
            return json.dumps(watchlist) if watchlist is not None else None
        return None

    r.get.side_effect = _get
    return r


def _client(r: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    return TestClient(app, raise_server_exceptions=False)


class TestWatchlistEndpoint:
    def test_returns_200(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/watchlist").status_code == 200

    def test_empty_when_no_watchlist(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/watchlist").json() == []

    def test_returns_watchlist_entries(self) -> None:
        wl: list[dict[str, object]] = [
            {"symbol": "TCS", "exchange": "NSE", "composite_score": 0.82}
        ]
        data = _client(_mock_redis(wl)).get("/api/v1/watchlist").json()
        assert len(data) == 1
        assert data[0]["symbol"] == "TCS"
        assert data[0]["composite_score"] == 0.82

    def test_exchange_query_param_nse(self) -> None:
        wl: list[dict[str, object]] = [{"symbol": "RELIANCE", "exchange": "NSE"}]
        data = _client(_mock_redis(wl, exchange="NSE")).get(
            "/api/v1/watchlist?exchange=NSE"
        ).json()
        assert len(data) == 1

    def test_exchange_query_param_asx(self) -> None:
        wl: list[dict[str, object]] = [{"symbol": "BHP", "exchange": "ASX"}]
        data = _client(_mock_redis(wl, exchange="ASX")).get(
            "/api/v1/watchlist?exchange=ASX"
        ).json()
        assert len(data) == 1
        assert data[0]["symbol"] == "BHP"

    def test_none_composite_score(self) -> None:
        wl: list[dict[str, object]] = [{"symbol": "INFY", "exchange": "NSE"}]
        data = _client(_mock_redis(wl)).get("/api/v1/watchlist").json()
        assert data[0]["composite_score"] is None

    def test_skips_invalid_entries(self) -> None:
        wl: list[dict[str, object]] = [
            "not-a-dict",  # type: ignore[list-item]
            {"symbol": "VALID", "exchange": "NSE"},
        ]
        data = _client(_mock_redis(wl)).get("/api/v1/watchlist").json()
        assert len(data) == 1

    def test_redis_error_returns_empty(self) -> None:
        r = MagicMock()
        r.get.side_effect = ConnectionError("down")
        assert _client(r).get("/api/v1/watchlist").json() == []
