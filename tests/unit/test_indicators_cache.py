"""Unit tests for shared.indicators.cache -- offline via a fake Redis client (just
the .set/.get surface store_snapshot/load_snapshot actually use).
"""

from datetime import UTC, datetime

from shared.core.constants import INDICATOR_CACHE_TTL_SECONDS
from shared.indicators.cache import cache_key, load_snapshot, store_snapshot
from shared.indicators.models import IndicatorSnapshot


class FakeRedis:
    """Stand-in for redis.Redis -- records the TTL passed to `set` and stores
    everything as strings, matching `decode_responses=True` behavior."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.last_ex: int | None = None

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.last_ex = ex

    def get(self, key: str) -> str | None:
        return self.store.get(key)


def _snapshot() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="RELIANCE.NS",
        exchange="NSE",
        timeframe="5m",
        candle_time=datetime(2026, 6, 1, 3, 45, tzinfo=UTC),
        computed_at=datetime(2026, 6, 1, 3, 45, 30, tzinfo=UTC),
        values={"RSI": {"RSI_14": 55.5}, "EMA": {"EMA_9": None}},
    )


class TestCacheKey:
    def test_format(self) -> None:
        assert cache_key("RELIANCE.NS", "NSE", "5m") == "indicators:NSE:RELIANCE.NS:5m"


class TestStoreAndLoadSnapshot:
    def test_round_trip_preserves_all_fields(self) -> None:
        client = FakeRedis()
        snapshot = _snapshot()

        store_snapshot(client, snapshot)
        loaded = load_snapshot(client, "RELIANCE.NS", "NSE", "5m")

        assert loaded == snapshot

    def test_uses_indicator_cache_ttl(self) -> None:
        client = FakeRedis()

        store_snapshot(client, _snapshot())

        assert client.last_ex == INDICATOR_CACHE_TTL_SECONDS

    def test_missing_key_returns_none(self) -> None:
        client = FakeRedis()

        assert load_snapshot(client, "NOPE", "NSE", "5m") is None
