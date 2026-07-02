"""GET /api/v1/signals — recent signals from the Redis stream."""

from __future__ import annotations

import time
from typing import cast

import redis
from fastapi import APIRouter, Depends, Query

from api.auth import optional_api_key
from api.deps import get_redis
from api.models import SignalOut
from shared.core.constants import API_SIGNALS_STREAM_MAX_READ, SIGNAL_REDIS_STREAM

router = APIRouter(prefix="/api/v1", tags=["signals"])


@router.get("/signals", response_model=list[SignalOut])
def get_signals(
    limit: int = Query(default=20, ge=1, le=API_SIGNALS_STREAM_MAX_READ),
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(optional_api_key),  # noqa: B008
) -> list[SignalOut]:
    """Return the most recent signals from the signals:generated Redis stream.

    Returns an empty list when the stream does not exist or Redis is unreachable.
    """
    try:
        raw = cast(
            list[tuple[str, dict[str, str]]],
            r.xrevrange(SIGNAL_REDIS_STREAM, count=limit),
        )
    except Exception:  # noqa: BLE001
        return []

    out: list[SignalOut] = []
    for entry_id, fields in reversed(raw):
        try:
            out.append(
                SignalOut(
                    signal_id=entry_id,
                    symbol=fields.get("symbol", ""),
                    exchange=fields.get("exchange", ""),
                    direction=fields.get("direction", ""),
                    confidence=float(fields.get("confidence", "0")),
                    strategy_tag=fields.get("strategy_tag", ""),
                    timestamp_ms=int(
                        fields.get(
                            "timestamp_ms", str(int(time.time() * 1000))
                        )
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return out
