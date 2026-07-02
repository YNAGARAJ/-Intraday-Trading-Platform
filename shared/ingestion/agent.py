"""Data Ingestion Agent for M16.

Orchestrates:
  - WebSocket tick subscription (Kite or IBKR adapter)
  - NumPy candle aggregation (1m and 5m)
  - Redis tick buffer with async DB flush
  - yfinance fallback on WS drop (RULE 5: < 2s switchover)
  - DEGRADED_EXIT_ONLY state propagation via Redis

Paper mode: synthetic ticks injected via ``inject_tick()`` — no real network calls.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable

import structlog

from shared.core.constants import (
    CANDLE_INTERVAL_1M,
    CANDLE_INTERVAL_5M,
    INGESTION_DEGRADED_REDIS_KEY,
    WS_FALLBACK_TIMEOUT_SECONDS,
)
from shared.ingestion.aggregator import CandleAggregator
from shared.ingestion.buffer import TickBuffer
from shared.ingestion.models import IngestionStatus, OHLCVCandle, RawTick
from shared.ingestion.validator import TickSequenceValidator
from shared.ingestion.yfinance_fallback import YFinanceFallback

logger = structlog.get_logger(__name__)


@runtime_checkable
class _WebSocketProvider(Protocol):
    """Structural interface for WS adapters (KiteWS or IBKRStream)."""

    def connect(self) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def is_connected(self) -> bool:
        ...


class _RedisStatus(Protocol):
    """Minimal Redis interface for DEGRADED flag propagation."""

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def delete(self, *names: str) -> int:
        ...


class DataIngestionAgent:
    """Orchestrates real-time market data ingestion.

    Accepts ticks from a WebSocket provider, validates them, aggregates into
    OHLCV candles, and pushes raw ticks to the Redis buffer for async DB writes.

    Args:
        symbols: Symbols to track (e.g. ``["RELIANCE", "INFY"]``).
        exchange: Market exchange for all symbols.
        ws_provider: WebSocket adapter (``KiteWebSocketAdapter`` or
            ``IBKRStreamAdapter``).  ``None`` → paper mode.
        fallback: ``YFinanceFallback`` for REST polling on WS outage.
        validator: ``TickSequenceValidator`` (shared or per-agent).
        aggregator_1m: 1-minute candle aggregator.
        aggregator_5m: 5-minute candle aggregator.
        tick_buffer: ``TickBuffer`` for async DB writes.
        status_redis: Optional Redis client for DEGRADED flag writes.
        mode: Starting ``IngestionStatus`` (default PAPER).
    """

    def __init__(
        self,
        symbols: list[str],
        exchange: str,
        ws_provider: _WebSocketProvider | None = None,
        fallback: YFinanceFallback | None = None,
        validator: TickSequenceValidator | None = None,
        aggregator_1m: CandleAggregator | None = None,
        aggregator_5m: CandleAggregator | None = None,
        tick_buffer: TickBuffer | None = None,
        status_redis: _RedisStatus | None = None,
        mode: IngestionStatus = IngestionStatus.PAPER,
    ) -> None:
        self._symbols = symbols
        self._exchange = exchange
        self._ws = ws_provider
        self._fallback = fallback or YFinanceFallback()
        self._validator = validator or TickSequenceValidator()
        self._agg1m = aggregator_1m or CandleAggregator(CANDLE_INTERVAL_1M)
        self._agg5m = aggregator_5m or CandleAggregator(CANDLE_INTERVAL_5M)
        self._buffer = tick_buffer or TickBuffer()
        self._status_redis = status_redis
        self._mode = mode
        self._last_tick_ts: float = 0.0
        self._latest_1m: dict[str, OHLCVCandle] = {}
        self._latest_5m: dict[str, OHLCVCandle] = {}
        self._lock = threading.Lock()
        self._running = False
        self._watchdog_thread: threading.Thread | None = None

    @property
    def mode(self) -> IngestionStatus:
        """Current ingestion mode (LIVE / DEGRADED / PAPER)."""
        with self._lock:
            return self._mode

    def start(self) -> None:
        """Connect WebSocket and start the watchdog thread.

        In PAPER mode, the WS is not connected — call ``inject_tick()`` directly.
        """
        with self._lock:
            if self._running:
                return
            self._running = True

        if self._ws is not None and self._mode == IngestionStatus.LIVE:
            self._ws.connect()
            logger.info("data_ingestion_agent_started", exchange=self._exchange)
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                daemon=True,
                name="ingestion-watchdog",
            )
            self._watchdog_thread.start()
        else:
            logger.info(
                "data_ingestion_agent_paper_mode",
                exchange=self._exchange,
                symbols=self._symbols,
            )

    def stop(self) -> None:
        """Disconnect WebSocket and stop the watchdog thread."""
        with self._lock:
            self._running = False
        if self._ws is not None:
            self._ws.disconnect()
        self._clear_degraded()
        logger.info("data_ingestion_agent_stopped", exchange=self._exchange)

    def inject_tick(self, tick: RawTick) -> list[OHLCVCandle]:
        """Inject a tick directly (paper/test/fallback path).

        Validates → aggregates → buffers.

        Args:
            tick: ``RawTick`` to process.

        Returns:
            List of any ``OHLCVCandle`` objects completed by this tick
            (0 or more entries, across 1m and 5m aggregators).

        Raises:
            ``TickValidationError`` if the tick fails validation.
        """
        self._validator.validate(tick)

        with self._lock:
            self._last_tick_ts = time.time()

        completed: list[OHLCVCandle] = []

        c1m = self._agg1m.ingest(tick)
        if c1m is not None:
            with self._lock:
                self._latest_1m[tick.symbol] = c1m
            completed.append(c1m)

        c5m = self._agg5m.ingest(tick)
        if c5m is not None:
            with self._lock:
                self._latest_5m[tick.symbol] = c5m
            completed.append(c5m)

        self._buffer.push(tick)

        if completed:
            logger.info(
                "candles_completed",
                symbol=tick.symbol,
                count=len(completed),
            )
        return completed

    def get_latest_candle(
        self, symbol: str, interval: int = CANDLE_INTERVAL_1M
    ) -> OHLCVCandle | None:
        """Return the most recently completed candle for a symbol.

        Args:
            symbol: Instrument symbol.
            interval: Bar interval in seconds (60 or 300).

        Returns:
            Most recent completed ``OHLCVCandle``, or ``None`` if not yet available.
        """
        with self._lock:
            if interval == CANDLE_INTERVAL_5M:
                return self._latest_5m.get(symbol)
            return self._latest_1m.get(symbol)

    def flush_open_bars(self) -> dict[str, OHLCVCandle]:
        """Force-close all in-progress bars.  Called at end-of-session.

        Returns:
            Mapping of ``"EXCHANGE:SYMBOL"`` → ``OHLCVCandle`` for all open bars.
        """
        result = self._agg1m.flush()
        result.update(self._agg5m.flush())
        return result

    def _watchdog_loop(self) -> None:
        """Background thread: detect WS timeout and switch to fallback."""
        while True:
            with self._lock:
                if not self._running:
                    break
                elapsed = time.time() - self._last_tick_ts
                ws_connected = (
                    self._ws.is_connected() if self._ws is not None else False
                )
                mode = self._mode

            if (
                mode == IngestionStatus.LIVE
                and elapsed > WS_FALLBACK_TIMEOUT_SECONDS
                and self._last_tick_ts > 0
            ):
                self._enter_degraded()
                self._run_fallback()
            elif (
                mode == IngestionStatus.DEGRADED
                and ws_connected
            ):
                self._exit_degraded()

            time.sleep(0.5)

    def _run_fallback(self) -> None:
        """Fetch yfinance REST data for all symbols in DEGRADED mode."""
        for symbol in self._symbols:
            ticks = self._fallback.fetch_ticks(symbol, self._exchange)
            for tick in ticks:
                try:
                    self.inject_tick(tick)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "fallback_tick_inject_error",
                        symbol=symbol,
                        error=str(exc),
                    )

    def _enter_degraded(self) -> None:
        with self._lock:
            if self._mode == IngestionStatus.DEGRADED:
                return
            self._mode = IngestionStatus.DEGRADED
        self._set_degraded()
        logger.warning(
            "ingestion_degraded_exit_only_activated",
            reason="ws_timeout",
            timeout_s=WS_FALLBACK_TIMEOUT_SECONDS,
        )

    def _exit_degraded(self) -> None:
        with self._lock:
            self._mode = IngestionStatus.LIVE
        self._clear_degraded()
        logger.info("ingestion_live_mode_restored")

    def _set_degraded(self) -> None:
        if self._status_redis is not None:
            try:
                self._status_redis.set(INGESTION_DEGRADED_REDIS_KEY, "true")
            except Exception as exc:  # noqa: BLE001
                logger.warning("degraded_flag_redis_set_failed", error=str(exc))

    def _clear_degraded(self) -> None:
        if self._status_redis is not None:
            try:
                self._status_redis.delete(INGESTION_DEGRADED_REDIS_KEY)
            except Exception as exc:  # noqa: BLE001
                logger.warning("degraded_flag_redis_clear_failed", error=str(exc))
