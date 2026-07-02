"""Dead-letter queue for permanently-failed orders (M14).

After exhausting all retries, the execution engine enqueues the order here.
M20 (Alerting) monitors ``dlq:orders`` and fires a Telegram alert on each
new entry.  The queue is append-only — never deleted; operator must review
and manually reprocess or acknowledge.
"""

from __future__ import annotations

import json
import time
from typing import Protocol

import structlog

from shared.core.constants import DLQ_REDIS_KEY
from shared.execution.models import DeadLetterEntry

logger = structlog.get_logger(__name__)


class RedisClient(Protocol):
    """Minimal Redis interface needed by ``DeadLetterQueue``."""

    def rpush(self, name: str, *values: str) -> int:
        ...

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        ...


class DeadLetterQueue:
    """Append-only dead-letter queue backed by Redis or in-memory fallback.

    Args:
        redis_client: Connected Redis client.  ``None`` = in-memory mode
            (used in tests and when Redis is unavailable — RULE 5).
    """

    def __init__(self, redis_client: RedisClient | None = None) -> None:
        self._redis = redis_client
        self._memory: list[str] = []

    def enqueue(
        self,
        client_order_id: str,
        symbol: str,
        exchange: str,
        last_error: str,
        attempt_count: int,
        strategy_tag: str,
    ) -> DeadLetterEntry:
        """Append a permanently-failed order to the queue.

        Args:
            client_order_id: Order idempotency key.
            symbol: Instrument symbol.
            exchange: Market identifier.
            last_error: Final error message from the broker/engine.
            attempt_count: Total submission attempts made.
            strategy_tag: Compliance-resolved broker tag.

        Returns:
            ``DeadLetterEntry`` appended to the queue.
        """
        entry = DeadLetterEntry(
            client_order_id=client_order_id,
            symbol=symbol,
            exchange=exchange,
            last_error=last_error,
            attempt_count=attempt_count,
            enqueued_at_ms=int(time.time() * 1000),
            strategy_tag=strategy_tag,
        )
        payload = json.dumps(
            {
                "client_order_id": entry.client_order_id,
                "symbol": entry.symbol,
                "exchange": entry.exchange,
                "last_error": entry.last_error,
                "attempt_count": entry.attempt_count,
                "enqueued_at_ms": entry.enqueued_at_ms,
                "strategy_tag": entry.strategy_tag,
            }
        )
        if self._redis is not None:
            self._redis.rpush(DLQ_REDIS_KEY, payload)
        else:
            self._memory.append(payload)

        logger.critical(
            "order_dead_lettered",
            client_order_id=client_order_id,
            symbol=symbol,
            exchange=exchange,
            last_error=last_error,
            attempt_count=attempt_count,
        )
        return entry

    def peek(self, count: int = 10) -> list[DeadLetterEntry]:
        """Return the last ``count`` entries from the queue (for testing/audit)."""
        if self._redis is not None:
            raw_list = self._redis.lrange(DLQ_REDIS_KEY, -count, -1)
            raw = [r.decode() if isinstance(r, bytes) else r for r in raw_list]
        else:
            raw = self._memory[-count:]
        entries: list[DeadLetterEntry] = []
        for payload in raw:
            data = json.loads(payload)
            entries.append(
                DeadLetterEntry(
                    client_order_id=data["client_order_id"],
                    symbol=data["symbol"],
                    exchange=data["exchange"],
                    last_error=data["last_error"],
                    attempt_count=data["attempt_count"],
                    enqueued_at_ms=data["enqueued_at_ms"],
                    strategy_tag=data["strategy_tag"],
                )
            )
        return entries

    def size(self) -> int:
        """Return the number of entries in the queue."""
        if self._redis is not None:
            from redis import Redis  # noqa: PLC0415

            if isinstance(self._redis, Redis):
                result = self._redis.llen(DLQ_REDIS_KEY)
                return int(result)
        return len(self._memory)
