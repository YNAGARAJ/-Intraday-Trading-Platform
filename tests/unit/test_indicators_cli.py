"""Unit tests for shared.indicators.cli -- offline via monkeypatched connections,
mirroring tests/unit/test_backfill.py's TestCli pattern from M03.
"""

import sys
from datetime import UTC, datetime, timedelta

import pytest

import shared.indicators.cli as cli_module
from shared.storage.models import OHLCVCandle

SYMBOL = "RELIANCE.NS"
EXCHANGE = "NSE"


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.closed = False

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self.store[name] = value

    def get(self, name: str) -> str | None:
        return self.store.get(name)

    def close(self) -> None:
        self.closed = True


class FakeRedisModule:
    """Stand-in for the `redis` package -- only `Redis.from_url` is used by cli.py."""

    def __init__(self, client: FakeRedisClient) -> None:
        self._client = client

        class _RedisCls:
            from_url = staticmethod(lambda *a, **kw: client)  # noqa: ARG005

        self.Redis = _RedisCls


class FakeRepository:
    def __init__(self, candles: list[OHLCVCandle]) -> None:
        self.candles = candles
        self.queried_with: tuple[str, str, str] | None = None

    def query_candles(
        self, symbol: str, exchange: str, timeframe: str, start: object, end: object
    ) -> list[OHLCVCandle]:
        self.queried_with = (symbol, exchange, timeframe)
        return self.candles


def _candles(count: int) -> list[OHLCVCandle]:
    t0 = datetime.now(UTC) - timedelta(minutes=5 * count)
    candles = []
    for i in range(count):
        close = 100.0 + (0.3 if i % 3 else -0.2) * (i % 7)
        candles.append(
            OHLCVCandle(
                time=t0 + timedelta(minutes=5 * i),
                symbol=SYMBOL,
                exchange=EXCHANGE,
                open=close - 0.1,
                high=close + 0.3,
                low=close - 0.3,
                close=close,
                volume=100 + i,
            )
        )
    return candles


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    redis_client: FakeRedisClient,
    repo: FakeRepository,
) -> None:
    monkeypatch.setattr(cli_module, "get_connection", lambda settings: conn)
    monkeypatch.setattr(cli_module, "apply_schema", lambda conn: None)
    monkeypatch.setattr(cli_module, "OHLCVRepository", lambda conn: repo)
    monkeypatch.setattr(cli_module, "redis_lib", FakeRedisModule(redis_client))


class TestCli:
    def test_no_candles_found_exits_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        redis_client = FakeRedisClient()
        repo = FakeRepository([])
        _patch_common(monkeypatch, conn, redis_client, repo)
        monkeypatch.setattr(sys, "argv", ["cli.py", "--symbol", SYMBOL])

        cli_module.main()

        assert repo.queried_with == (SYMBOL, EXCHANGE, "5m")
        assert redis_client.store == {}
        assert conn.closed is True
        assert redis_client.closed is True

    def test_computes_and_caches_when_candles_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        redis_client = FakeRedisClient()
        repo = FakeRepository(_candles(250))
        _patch_common(monkeypatch, conn, redis_client, repo)
        monkeypatch.setattr(
            sys, "argv", ["cli.py", "--symbol", SYMBOL, "--timeframe", "5m"]
        )

        cli_module.main()

        assert len(redis_client.store) == 1
        assert conn.closed is True
        assert redis_client.closed is True

    def test_closes_connections_even_if_query_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        redis_client = FakeRedisClient()

        class RaisingRepository:
            def query_candles(
                self, *args: object, **kwargs: object
            ) -> list[OHLCVCandle]:
                raise ConnectionError("simulated DB failure")

        monkeypatch.setattr(cli_module, "get_connection", lambda settings: conn)
        monkeypatch.setattr(cli_module, "apply_schema", lambda conn: None)
        monkeypatch.setattr(
            cli_module, "OHLCVRepository", lambda conn: RaisingRepository()
        )
        monkeypatch.setattr(cli_module, "redis_lib", FakeRedisModule(redis_client))
        monkeypatch.setattr(sys, "argv", ["cli.py"])

        with pytest.raises(ConnectionError):
            cli_module.main()

        assert conn.closed is True
        assert redis_client.closed is True

    def test_rejects_unsupported_timeframe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["cli.py", "--timeframe", "3m"])

        with pytest.raises(SystemExit):
            cli_module.main()
