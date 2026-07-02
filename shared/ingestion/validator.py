"""Tick sequence validator for M16 Data Ingestion Agent.

Rejects ticks that are corrupt, zero-priced, or arrive out of sequence.
Referenced as ``TickSequenceValidator`` in CLAUDE.md API names.
"""

from __future__ import annotations

import time

import structlog

from shared.core.constants import TICK_MAX_BACKWARD_MS, TICK_MAX_FUTURE_MS
from shared.ingestion.models import RawTick, TickValidationError

logger = structlog.get_logger(__name__)


class TickSequenceValidator:
    """Validates individual ticks and detects sequence anomalies.

    Maintains per-symbol last-seen timestamp.  Ticks are rejected if they:
    - Have a price ≤ 0.
    - Have negative volume.
    - Have a timestamp more than ``TICK_MAX_BACKWARD_MS`` ms before the previous
      accepted tick for the same symbol (sequence reversal / duplicate delivery).
    - Have a timestamp more than ``TICK_MAX_FUTURE_MS`` ms ahead of wall-clock time
      (clock skew / feed bug).
    """

    def __init__(self) -> None:
        self._last_ts_ms: dict[str, int] = {}

    def validate(self, tick: RawTick) -> None:
        """Validate a raw tick, raising on failure.

        Args:
            tick: The ``RawTick`` to validate.

        Raises:
            TickValidationError: If any validation rule fires.
        """
        key = f"{tick.exchange}:{tick.symbol}"

        if tick.ltp <= 0:
            raise TickValidationError(
                f"zero/negative price: {tick.symbol} ltp={tick.ltp}"
            )
        if tick.volume < 0:
            raise TickValidationError(
                f"negative volume: {tick.symbol} volume={tick.volume}"
            )

        now_ms = int(time.time() * 1000)
        if tick.timestamp_ms > now_ms + TICK_MAX_FUTURE_MS:
            raise TickValidationError(
                f"timestamp in the future: {tick.symbol} "
                f"ts={tick.timestamp_ms} now={now_ms}"
            )

        last = self._last_ts_ms.get(key)
        if last is not None and tick.timestamp_ms < last - TICK_MAX_BACKWARD_MS:
            raise TickValidationError(
                f"out-of-sequence tick: {tick.symbol} "
                f"ts={tick.timestamp_ms} last={last}"
            )

        self._last_ts_ms[key] = tick.timestamp_ms
        logger.debug(
            "tick_validated",
            symbol=tick.symbol,
            exchange=tick.exchange,
            ltp=tick.ltp,
            ts_ms=tick.timestamp_ms,
        )

    def reset(self, symbol: str, exchange: str = "") -> None:
        """Clear the last-seen timestamp for a symbol.

        Call this at ASX staggered open to allow fresh sequence tracking when the
        ticker's group window opens.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier (default ``""`` clears all matching symbols).
        """
        if exchange:
            key = f"{exchange}:{symbol}"
            self._last_ts_ms.pop(key, None)
        else:
            keys = [k for k in self._last_ts_ms if k.endswith(f":{symbol}")]
            for k in keys:
                del self._last_ts_ms[k]
        logger.debug("tick_validator_reset", symbol=symbol, exchange=exchange)
