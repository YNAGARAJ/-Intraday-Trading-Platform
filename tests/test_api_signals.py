"""Tests for GET /api/v1/signals endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis


def _mock_redis(
    stream_entries: list[tuple[str, dict[str, str]]] | None = None,
) -> MagicMock:
    r = MagicMock()
    r.xrevrange.return_value = stream_entries or []
    return r


def _client(r: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    return TestClient(app, raise_server_exceptions=False)


class TestSignalsEndpoint:
    def test_returns_200(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/signals").status_code == 200

    def test_empty_when_no_stream(self) -> None:
        assert _client(_mock_redis()).get("/api/v1/signals").json() == []

    def test_returns_signals_from_stream(self) -> None:
        entries = [
            (
                "1700000000000-0",
                {
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "direction": "LONG",
                    "confidence": "0.87",
                    "strategy_tag": "STRAT001",
                    "timestamp_ms": "1700000000000",
                },
            )
        ]
        data = _client(_mock_redis(entries)).get("/api/v1/signals").json()
        assert len(data) == 1
        assert data[0]["symbol"] == "INFY"
        assert data[0]["confidence"] == 0.87
        assert data[0]["signal_id"] == "1700000000000-0"

    def test_limit_query_param(self) -> None:
        r = _mock_redis()
        _client(r).get("/api/v1/signals?limit=5")
        r.xrevrange.assert_called_once()
        call_args = r.xrevrange.call_args
        # count is passed as positional or keyword
        count_val = (
            call_args.kwargs.get("count")
            if call_args.kwargs.get("count") is not None
            else call_args.args[1]
            if len(call_args.args) > 1
            else None
        )
        assert count_val == 5

    def test_skips_malformed_entry(self) -> None:
        entries = [
            (
                "bad-id",
                {"confidence": "not-a-float"},
            )
        ]
        data = _client(_mock_redis(entries)).get("/api/v1/signals").json()  # type: ignore[arg-type]
        assert isinstance(data, list)

    def test_redis_error_returns_empty(self) -> None:
        r = MagicMock()
        r.xrevrange.side_effect = ConnectionError("down")
        assert _client(r).get("/api/v1/signals").json() == []
