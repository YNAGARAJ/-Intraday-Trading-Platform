"""Publish a `SignalResult` to Redis Streams as a `SignalGenerated` protobuf.

The atomic Lua script (`signal_dedup.lua`) checks:
  1. System is not halted (`system:status:halted`).
  2. No duplicate signal for this symbol/direction in the dedup window.
If both checks pass, the script publishes to the stream atomically and sets
the dedup key with the configured TTL.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import redis
import structlog

from shared.core.constants import (
    SIGNAL_DEDUP_WINDOW_SECONDS,
    SIGNAL_EXPIRY_MINUTES,
    SIGNAL_REDIS_STREAM,
)
from shared.proto.messages_pb2 import SignalGenerated
from shared.signals.models import SignalResult

logger = structlog.get_logger(__name__)

_LUA_PATH = Path(__file__).parent.parent / "lua" / "signal_dedup.lua"
_LUA_SCRIPT: str | None = None


def _load_lua() -> str:
    global _LUA_SCRIPT
    if _LUA_SCRIPT is None:
        _LUA_SCRIPT = _LUA_PATH.read_text()
    return _LUA_SCRIPT


def _build_proto(result: SignalResult, engine: object) -> SignalGenerated:
    """Convert `SignalResult` to `SignalGenerated` protobuf message."""
    from datetime import UTC, datetime  # noqa: PLC0415

    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    expiry_ms = now_ms + SIGNAL_EXPIRY_MINUTES * 60 * 1000

    msg = SignalGenerated()
    msg.signal_id = str(uuid.uuid4())
    msg.symbol = result.symbol
    msg.exchange = result.exchange
    msg.direction = result.direction
    msg.confidence = result.confidence
    msg.entry_price = result.entry_price
    msg.stop_loss = result.stop_loss
    msg.target1 = result.target1
    msg.target2 = result.target2
    msg.atr = result.atr
    msg.confirming_indicators.extend(result.confirming_indicators)
    msg.confirming_timeframes.extend(result.confirming_timeframes)
    msg.candlestick_pattern = result.candlestick_pattern
    msg.strategy_id = result.strategy_id[: 8]
    msg.generated_at_ms = now_ms
    msg.expires_at_ms = expiry_ms
    msg.regime = result.regime
    return msg


class SignalPublisher:
    """Publishes signals to Redis Streams using an atomic Lua dedup script.

    Args:
        redis_client: Connected Redis client.
        stream_key: Redis Stream key (default: ``SIGNAL_REDIS_STREAM``).
        dedup_window_seconds: Dedup TTL in seconds.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_key: str = SIGNAL_REDIS_STREAM,
        dedup_window_seconds: int = SIGNAL_DEDUP_WINDOW_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._stream_key = stream_key
        self._dedup_window = dedup_window_seconds
        self._script = self._redis.register_script(_load_lua())

    def publish(self, result: SignalResult) -> str | None:
        """Publish `result` to Redis Streams if dedup and halt checks pass.

        Args:
            result: A successfully generated signal (``result.generated`` must
                be True — callers should not publish failed results).

        Returns:
            Redis Stream entry ID string on success, or ``None`` when the Lua
            script returns ``HALTED`` or ``DUPLICATE``.
        """
        if not result.generated:
            logger.warning(
                "publish_skipped_not_generated",
                symbol=result.symbol,
                direction=result.direction,
            )
            return None

        proto_msg = _build_proto(result, None)
        payload = proto_msg.SerializeToString()

        dedup_key = (
            f"signal:dedup:{result.symbol}:{result.direction}"
        )

        lua_result = self._script(
            keys=[dedup_key, self._stream_key],
            args=[str(self._dedup_window), payload],
        )

        status_code = int(lua_result[0])
        raw1 = lua_result[1]
        status_msg = raw1.decode() if isinstance(raw1, bytes) else str(raw1)

        if status_code == 0:
            logger.info(
                "signal_publish_blocked",
                symbol=result.symbol,
                direction=result.direction,
                reason=status_msg,
            )
            return None

        entry_id_raw = lua_result[2]
        if isinstance(entry_id_raw, bytes):
            entry_id = entry_id_raw.decode()
        else:
            entry_id = str(entry_id_raw)
        logger.info(
            "signal_published",
            symbol=result.symbol,
            exchange=result.exchange,
            direction=result.direction,
            confidence=result.confidence,
            entry_id=entry_id,
            stream=self._stream_key,
        )
        return entry_id
