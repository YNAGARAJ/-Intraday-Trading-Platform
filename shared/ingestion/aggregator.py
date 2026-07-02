"""NumPy-backed in-memory OHLCV candle aggregator for M16.

Aggregates raw ticks into completed OHLCV bars at configurable intervals (1m / 5m).
When a tick falls into a new bar window, the completed previous bar is returned.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog

from shared.ingestion.models import OHLCVCandle, RawTick

logger = structlog.get_logger(__name__)


@dataclass
class _BarState:
    """In-progress open OHLCV bar for a single symbol."""

    interval_start_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    tick_count: int = 0


def _bar_start_ms(timestamp_ms: int, interval_seconds: int) -> int:
    """Round timestamp_ms down to the nearest interval boundary."""
    interval_ms = interval_seconds * 1_000
    return (timestamp_ms // interval_ms) * interval_ms


class CandleAggregator:
    """Aggregates raw ticks into completed OHLCV candles.

    Maintains one open bar per symbol using NumPy min/max for efficiency.
    When a tick falls in a new interval window the completed bar is flushed
    and a fresh bar started.

    Args:
        interval_seconds: Bar size in seconds (default 60 for 1-minute bars).
    """

    def __init__(self, interval_seconds: int = 60) -> None:
        self._interval = interval_seconds
        self._bars: dict[str, _BarState] = {}

    def ingest(self, tick: RawTick) -> OHLCVCandle | None:
        """Ingest a tick and return a completed candle if the bar just closed.

        Args:
            tick: A validated ``RawTick``.

        Returns:
            Completed ``OHLCVCandle`` when the bar window rolls over, else ``None``.
        """
        key = f"{tick.exchange}:{tick.symbol}"
        bar_start = _bar_start_ms(tick.timestamp_ms, self._interval)

        existing = self._bars.get(key)

        if existing is None:
            self._bars[key] = _BarState(
                interval_start_ms=bar_start,
                open=tick.ltp,
                high=tick.ltp,
                low=tick.ltp,
                close=tick.ltp,
                volume=tick.volume,
                tick_count=1,
            )
            return None

        if bar_start == existing.interval_start_ms:
            # Same bar: update in-place using NumPy scalar ops for consistency
            existing.high = float(np.maximum(existing.high, tick.ltp))
            existing.low = float(np.minimum(existing.low, tick.ltp))
            existing.close = tick.ltp
            existing.volume += tick.volume
            existing.tick_count += 1
            return None

        # Bar rolled: emit completed candle and start fresh
        completed = OHLCVCandle(
            symbol=tick.symbol,
            exchange=tick.exchange,
            interval_seconds=self._interval,
            open=existing.open,
            high=existing.high,
            low=existing.low,
            close=existing.close,
            volume=existing.volume,
            timestamp_ms=existing.interval_start_ms,
            tick_count=existing.tick_count,
        )
        self._bars[key] = _BarState(
            interval_start_ms=bar_start,
            open=tick.ltp,
            high=tick.ltp,
            low=tick.ltp,
            close=tick.ltp,
            volume=tick.volume,
            tick_count=1,
        )
        logger.debug(
            "candle_emitted",
            symbol=tick.symbol,
            exchange=tick.exchange,
            interval_s=self._interval,
            open=completed.open,
            close=completed.close,
            volume=completed.volume,
            ts_ms=completed.timestamp_ms,
        )
        return completed

    def flush(self) -> dict[str, OHLCVCandle]:
        """Force-close all open bars and return the resulting candles.

        Used at end-of-session or on WS reconnect to ensure no in-progress data
        is silently discarded.

        Returns:
            Mapping of ``"EXCHANGE:SYMBOL"`` to the partially-completed ``OHLCVCandle``.
        """
        result: dict[str, OHLCVCandle] = {}
        for key, state in self._bars.items():
            exchange, symbol = key.split(":", 1)
            result[key] = OHLCVCandle(
                symbol=symbol,
                exchange=exchange,
                interval_seconds=self._interval,
                open=state.open,
                high=state.high,
                low=state.low,
                close=state.close,
                volume=state.volume,
                timestamp_ms=state.interval_start_ms,
                tick_count=state.tick_count,
            )
        self._bars.clear()
        logger.info("candle_aggregator_flushed", count=len(result))
        return result

    def reset(self, symbol: str, exchange: str) -> None:
        """Discard the open bar for a symbol (e.g. at ASX staggered open).

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier.
        """
        key = f"{exchange}:{symbol}"
        self._bars.pop(key, None)
        logger.debug("candle_aggregator_reset", symbol=symbol, exchange=exchange)

    @property
    def interval_seconds(self) -> int:
        """Return the configured bar interval in seconds."""
        return self._interval
