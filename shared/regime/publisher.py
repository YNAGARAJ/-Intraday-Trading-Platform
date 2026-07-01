"""Publish RegimeChanged protobuf events to Redis Streams.

Each regime classification that clears the confidence threshold (or overrides
to HIGH_VOL_CHAOS) is published to the ``REGIME_REDIS_STREAM`` Redis Stream
so that downstream agents (M11 signal engine, M12 risk engine, M18 orchestrator)
can consume it without polling.

Message format
--------------
The message is serialised as a ``RegimeChanged`` protobuf (from
``shared.proto.messages_pb2``) and stored in the Redis Stream field ``data``.
Consumers deserialise using ``RegimeChanged.FromString(data)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from shared.core.constants import REGIME_REDIS_STREAM
from shared.core.logging import get_logger
from shared.proto.messages_pb2 import RegimeChanged
from shared.regime.models import RegimeClassification

if TYPE_CHECKING:
    import redis

logger = get_logger(__name__)

_MAX_STREAM_LENGTH = 1000
"""Trim the stream to at most this many entries to avoid unbounded growth."""

# redis-py 5.x stubs type xadd/xrevrange returns as Awaitable|Any (sync+async
# unified API).  We always use the synchronous client, so cast to concrete types.
_StreamFields = dict[bytes, bytes]
_StreamEntry = tuple[bytes, _StreamFields]


def publish_regime_change(
    classification: RegimeClassification,
    redis_client: "redis.Redis",
) -> str:
    """Serialise a RegimeClassification and publish it to Redis Streams.

    Args:
        classification: The output of RegimeClassifier.classify().
        redis_client: Connected synchronous Redis client.

    Returns:
        The Redis Stream entry ID of the published message.
    """
    msg = RegimeChanged()
    msg.regime = classification.regime.value
    msg.confidence = float(classification.confidence)
    msg.adx = float(classification.features.adx)
    msg.rsi = float(classification.features.rsi)
    msg.vwap_deviation = float(classification.features.vwap_deviation_pct)
    msg.volume_delta = float(classification.features.volume_ratio)
    msg.vix = float(classification.features.vix)
    msg.classified_at_ms = int(classification.classified_at.timestamp() * 1000)

    payload = msg.SerializeToString()
    raw_id = cast(
        bytes,
        redis_client.xadd(
            REGIME_REDIS_STREAM,
            {"data": payload},
            maxlen=_MAX_STREAM_LENGTH,
            approximate=True,
        ),
    )
    entry_id = raw_id if isinstance(raw_id, str) else raw_id.decode()

    logger.info(
        "regime_published",
        regime=classification.regime.value,
        confidence=classification.confidence,
        entry_id=entry_id,
        stream=REGIME_REDIS_STREAM,
    )
    return entry_id


def read_latest_regime(
    redis_client: "redis.Redis",
) -> RegimeClassification | None:
    """Read the most recent RegimeChanged event from the stream.

    Returns ``None`` when the stream is empty or does not exist.

    Args:
        redis_client: Connected synchronous Redis client.

    Returns:
        Deserialized RegimeClassification, or None.
    """
    from datetime import datetime, timezone

    from shared.regime.models import MarketRegime, RegimeFeatures

    raw_entries = cast(
        list[_StreamEntry],
        redis_client.xrevrange(REGIME_REDIS_STREAM, count=1),
    )
    if not raw_entries:
        return None

    _, fields = raw_entries[0]
    payload = fields.get(b"data")
    if payload is None:
        return None

    msg = RegimeChanged()
    msg.ParseFromString(payload)

    try:
        regime = MarketRegime(msg.regime)
    except ValueError:
        logger.warning("unknown_regime_in_stream", raw_regime=msg.regime)
        return None

    features = RegimeFeatures(
        adx=float(msg.adx),
        rsi=float(msg.rsi),
        bb_width_pct=0.0,
        atr_pct=0.0,
        vwap_deviation_pct=float(msg.vwap_deviation),
        volume_ratio=float(msg.volume_delta),
        vix=float(msg.vix),
        atr_spike=False,
    )
    classified_at = datetime.fromtimestamp(
        msg.classified_at_ms / 1000.0, tz=timezone.utc
    )
    return RegimeClassification(
        regime=regime,
        confidence=float(msg.confidence),
        features=features,
        hmm_state=-1,
        classified_at=classified_at,
    )
