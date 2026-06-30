"""Redis caching for computed indicator snapshots (TTL: INDICATOR_CACHE_TTL_SECONDS).

Cache key layout: `indicators:{exchange}:{symbol}:{timeframe}` -- mirrors the
exchange-first ordering used elsewhere in the codebase (e.g. ticks/ohlcv_1m's primary
key) so a Redis SCAN by exchange prefix is possible later if needed.
"""

import json
from dataclasses import asdict
from datetime import datetime
from typing import Protocol

from shared.core.constants import INDICATOR_CACHE_TTL_SECONDS
from shared.indicators.models import IndicatorSnapshot


class RedisLike(Protocol):
    """What this module needs from a Redis client -- structurally satisfied by
    `redis.Redis` (real usage) and by a trivial in-memory fake (tests), without
    pulling redis-py's own loosely-typed stub signatures (`Union[Awaitable, Any]`,
    see M02/M03's notes on this stub gap) into our own type surface.
    """

    def set(self, name: str, value: str, ex: int | None = None) -> object: ...
    def get(self, name: str) -> object: ...


def cache_key(symbol: str, exchange: str, timeframe: str) -> str:
    return f"indicators:{exchange}:{symbol}:{timeframe}"


def store_snapshot(client: RedisLike, snapshot: IndicatorSnapshot) -> None:
    """Cache `snapshot`, overwriting any previous value for the same key, with a
    fresh `INDICATOR_CACHE_TTL_SECONDS` TTL."""
    key = cache_key(snapshot.symbol, snapshot.exchange, snapshot.timeframe)
    payload = asdict(snapshot)
    payload["candle_time"] = snapshot.candle_time.isoformat()
    payload["computed_at"] = snapshot.computed_at.isoformat()
    client.set(key, json.dumps(payload), ex=INDICATOR_CACHE_TTL_SECONDS)


def load_snapshot(
    client: RedisLike, symbol: str, exchange: str, timeframe: str
) -> IndicatorSnapshot | None:
    """Return the cached snapshot for `symbol`/`exchange`/`timeframe`, or `None` if
    nothing is cached or the entry has expired (TTL already enforced by Redis)."""
    key = cache_key(symbol, exchange, timeframe)
    raw = client.get(key)
    if raw is None:
        return None
    payload = json.loads(str(raw))
    return IndicatorSnapshot(
        symbol=payload["symbol"],
        exchange=payload["exchange"],
        timeframe=payload["timeframe"],
        candle_time=datetime.fromisoformat(payload["candle_time"]),
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        values=payload["values"],
    )
