"""Redis Stream publisher for ReconciliationMismatch events (M17).

Serialises each ``ReconciliationMismatch`` as a Protobuf message and appends it to
``RECONCILIATION_MISMATCH_REDIS_STREAM`` so M18 (orchestrator) and M20 (alerting)
can consume it asynchronously.

Falls back to structured logging if Redis is unavailable (fail-open — the internal
block flag is already set; the stream entry is best-effort delivery to subscribers).
"""

from __future__ import annotations

from typing import Protocol

import structlog

from shared.core.constants import RECONCILIATION_MISMATCH_REDIS_STREAM
from shared.proto.messages_pb2 import ReconciliationMismatch as ProtoMismatch
from shared.reconciliation.models import ReconciliationMismatch

logger = structlog.get_logger(__name__)


class _RedisStream(Protocol):
    """Minimal Redis interface for Stream publish."""

    def xadd(
        self,
        name: str,
        fields: dict[str, str | bytes],
        id: str = "*",
        maxlen: int | None = None,
    ) -> bytes | str:
        ...


class MismatchPublisher:
    """Publishes ReconciliationMismatch events to a Redis Stream.

    Args:
        redis_client: Redis client implementing ``_RedisStream``.  ``None`` →
            events are logged only (no stream delivery).
        stream_key: Redis Stream key (defaults to
            ``RECONCILIATION_MISMATCH_REDIS_STREAM``).
        stream_maxlen: Trim stream to this length (``None`` = unlimited).
    """

    def __init__(
        self,
        redis_client: _RedisStream | None = None,
        stream_key: str = RECONCILIATION_MISMATCH_REDIS_STREAM,
        stream_maxlen: int | None = 10_000,
    ) -> None:
        self._redis = redis_client
        self._stream_key = stream_key
        self._maxlen = stream_maxlen

    def publish(self, mismatch: ReconciliationMismatch) -> str | None:
        """Publish one mismatch event.

        Args:
            mismatch: The mismatch to broadcast.

        Returns:
            Redis Stream entry ID on success, ``None`` if Redis is unavailable.
        """
        proto = ProtoMismatch(
            symbol=mismatch.symbol,
            field=mismatch.field.value,
            internal_value=mismatch.internal_value,
            broker_value=mismatch.broker_value,
            detected_at_ms=mismatch.detected_at_ms,
        )
        payload = proto.SerializeToString()

        logger.warning(
            "reconciliation_mismatch_event",
            symbol=mismatch.symbol,
            exchange=mismatch.exchange,
            field=mismatch.field.value,
            internal_value=mismatch.internal_value,
            broker_value=mismatch.broker_value,
        )

        if self._redis is None:
            return None

        try:
            entry_id = self._redis.xadd(
                self._stream_key,
                {
                    "proto": payload,
                    "symbol": mismatch.symbol,
                    "exchange": mismatch.exchange,
                    "field": mismatch.field.value,
                    "detected_at_ms": str(mismatch.detected_at_ms),
                },
                maxlen=self._maxlen,
            )
            return str(entry_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "reconciliation_mismatch_publish_failed",
                error=str(exc),
            )
            return None

    def publish_all(
        self, mismatches: list[ReconciliationMismatch]
    ) -> list[str]:
        """Publish multiple mismatch events.

        Args:
            mismatches: List of mismatches to publish.

        Returns:
            List of successfully published Stream entry IDs.
        """
        entry_ids: list[str] = []
        for m in mismatches:
            eid = self.publish(m)
            if eid is not None:
                entry_ids.append(eid)
        return entry_ids
