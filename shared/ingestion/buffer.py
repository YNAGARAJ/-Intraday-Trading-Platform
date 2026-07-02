"""Async Redis tick buffer queue for M16 Data Ingestion Agent.

Ticks are serialized to JSON and pushed to a Redis List (``TICK_BUFFER_REDIS_KEY``).
A batch worker drains this queue in chunks of up to ``TICK_BUFFER_FLUSH_COUNT`` items
every ``TICK_BUFFER_FLUSH_INTERVAL_SECONDS`` seconds to avoid DB write saturation.

Falls back to an in-memory list if Redis is unavailable (no data loss on reconnect;
the in-memory buffer drains first on flush).
"""

from __future__ import annotations

import json
import time
from typing import Protocol

import structlog

from shared.core.constants import (
    TICK_BUFFER_FLUSH_COUNT,
    TICK_BUFFER_FLUSH_INTERVAL_SECONDS,
    TICK_BUFFER_REDIS_KEY,
)
from shared.ingestion.models import RawTick

logger = structlog.get_logger(__name__)


class _RedisQueue(Protocol):
    """Minimal Redis interface required by TickBuffer."""

    def rpush(self, name: str, *values: str) -> int:
        ...

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        ...

    def llen(self, name: str) -> int:
        ...

    def ltrim(self, name: str, start: int, end: int) -> bool:
        ...


def _tick_to_json(tick: RawTick) -> str:
    return json.dumps(
        {
            "symbol": tick.symbol,
            "exchange": tick.exchange,
            "ltp": tick.ltp,
            "volume": tick.volume,
            "timestamp_ms": tick.timestamp_ms,
        }
    )


def _json_to_tick(raw: str | bytes) -> RawTick:
    d = json.loads(raw)
    return RawTick(
        symbol=d["symbol"],
        exchange=d["exchange"],
        ltp=float(d["ltp"]),
        volume=int(d["volume"]),
        timestamp_ms=int(d["timestamp_ms"]),
    )


class TickBuffer:
    """Dual-mode tick queue: Redis primary, in-memory fallback.

    Args:
        redis_client: Optional Redis client implementing ``_RedisQueue``.
            When ``None``, all ticks go to the in-memory fallback list.
        flush_count: Flush to DB when this many ticks have accumulated.
        flush_interval_seconds: Maximum seconds between flushes.
    """

    def __init__(
        self,
        redis_client: _RedisQueue | None = None,
        flush_count: int = TICK_BUFFER_FLUSH_COUNT,
        flush_interval_seconds: int = TICK_BUFFER_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._flush_count = flush_count
        self._flush_interval = flush_interval_seconds
        self._memory: list[str] = []
        self._last_flush_ts = time.time()

    def push(self, tick: RawTick) -> None:
        """Serialize and enqueue a tick.

        Args:
            tick: A validated ``RawTick`` to buffer.
        """
        payload = _tick_to_json(tick)
        if self._redis is not None:
            try:
                self._redis.rpush(TICK_BUFFER_REDIS_KEY, payload)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "tick_buffer_redis_push_failed_using_memory",
                    error=str(exc),
                )
        self._memory.append(payload)
        logger.debug("tick_buffered_in_memory", symbol=tick.symbol)

    def pending_count(self) -> int:
        """Return the number of ticks waiting in the queue.

        Returns:
            Tick count from Redis (if available) plus in-memory fallback count.
        """
        redis_count = 0
        if self._redis is not None:
            try:
                redis_count = self._redis.llen(TICK_BUFFER_REDIS_KEY)
            except Exception:  # noqa: BLE001
                pass
        return redis_count + len(self._memory)

    def drain(self, n: int | None = None) -> list[RawTick]:
        """Read and remove up to *n* ticks from the queue.

        Drains in-memory fallback first, then Redis.

        Args:
            n: Maximum number of ticks to drain.  ``None`` means drain all.

        Returns:
            List of deserialized ``RawTick`` objects.
        """
        limit = n if n is not None else self.pending_count()
        ticks: list[RawTick] = []

        # Drain in-memory first
        memory_take = min(limit, len(self._memory))
        raw_memory = self._memory[:memory_take]
        self._memory = self._memory[memory_take:]
        for raw in raw_memory:
            try:
                ticks.append(_json_to_tick(raw))
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("tick_buffer_deserialize_error", error=str(exc))
        remaining = limit - len(ticks)

        if remaining > 0 and self._redis is not None:
            try:
                raw_redis = self._redis.lrange(
                    TICK_BUFFER_REDIS_KEY, 0, remaining - 1
                )
                if raw_redis:
                    self._redis.ltrim(
                        TICK_BUFFER_REDIS_KEY, len(raw_redis), -1
                    )
                for raw_b in raw_redis:
                    try:
                        ticks.append(_json_to_tick(raw_b))
                    except (KeyError, ValueError, json.JSONDecodeError) as exc:
                        logger.warning(
                            "tick_buffer_deserialize_error", error=str(exc)
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("tick_buffer_redis_drain_failed", error=str(exc))

        self._last_flush_ts = time.time()
        return ticks

    def should_flush(self) -> bool:
        """Return True if either the count or time threshold has been met."""
        elapsed = time.time() - self._last_flush_ts
        return (
            self.pending_count() >= self._flush_count
            or elapsed >= self._flush_interval
        )
