"""Zerodha Kite WebSocket adapter for M16 Data Ingestion Agent.

Wraps ``kiteconnect.KiteTicker`` to deliver validated ``RawTick`` objects via a
callback.  Kite sends cumulative day-session volume; the adapter converts this to
per-tick delta volume before emitting.

kiteconnect SDK may not be installed in dev; the adapter degrades gracefully to
a disconnected stub that returns ``is_connected() == False``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import structlog

from shared.ingestion.models import RawTick

logger = structlog.get_logger(__name__)


@runtime_checkable
class _KiteTickerProto(Protocol):
    """Structural interface for KiteTicker used in type narrowing."""

    def connect(self, threaded: bool = True) -> None:
        ...

    def close(self) -> None:
        ...

    def subscribe(self, instrument_tokens: list[int]) -> None:
        ...

    def set_mode(self, mode: str, instrument_tokens: list[int]) -> None:
        ...

    on_ticks: Callable[..., None] | None
    on_connect: Callable[..., None] | None
    on_close: Callable[..., None] | None
    on_error: Callable[..., None] | None


class KiteWebSocketAdapter:
    """Kite Connect WebSocket feed adapter.

    Converts Kite's tick payloads to ``RawTick`` objects and calls the registered
    ``on_tick`` callback.

    Args:
        api_key: Kite Connect API key.
        access_token: Valid Kite access token.
        instrument_tokens: List of Kite instrument token integers to subscribe.
        on_tick: Callback invoked for each validated ``RawTick``.
        symbol_map: Mapping from instrument_token → (symbol, exchange) tuple.
    """

    def __init__(
        self,
        api_key: str,
        access_token: str,
        instrument_tokens: list[int],
        on_tick: Callable[[RawTick], None],
        symbol_map: dict[int, tuple[str, str]] | None = None,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._tokens = instrument_tokens
        self._on_tick = on_tick
        self._symbol_map = symbol_map or {}
        self._ticker: object | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._prev_vol: dict[int, int] = {}

    def connect(self) -> None:
        """Connect to the Kite WebSocket feed.

        No-ops gracefully if kiteconnect is not installed.
        """
        try:
            from kiteconnect import KiteTicker  # noqa: PLC0415

            ticker = KiteTicker(self._api_key, self._access_token)
            ticker.on_ticks = self._handle_ticks
            ticker.on_connect = self._handle_connect
            ticker.on_close = self._handle_close
            ticker.on_error = self._handle_error
            self._ticker = ticker
            ticker.connect(threaded=True)
            logger.info("kite_ws_connecting", token_count=len(self._tokens))
        except ImportError:
            logger.warning(
                "kiteconnect_not_installed_kite_ws_unavailable"
            )

    def disconnect(self) -> None:
        """Disconnect from the Kite WebSocket feed."""
        with self._lock:
            self._connected = False
            if isinstance(self._ticker, _KiteTickerProto):
                try:
                    self._ticker.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("kite_ws_close_error", error=str(exc))
        logger.info("kite_ws_disconnected")

    def is_connected(self) -> bool:
        """Return True if the WebSocket is currently connected."""
        with self._lock:
            return self._connected

    def _handle_connect(self, ws: object, response: object) -> None:
        with self._lock:
            self._connected = True
        if isinstance(self._ticker, _KiteTickerProto):
            self._ticker.subscribe(self._tokens)
            self._ticker.set_mode("full", self._tokens)
        logger.info("kite_ws_connected", token_count=len(self._tokens))

    def _handle_close(self, ws: object, code: object, reason: object) -> None:
        with self._lock:
            self._connected = False
        logger.warning("kite_ws_closed", code=code, reason=reason)

    def _handle_error(self, ws: object, code: object, reason: object) -> None:
        logger.error("kite_ws_error", code=code, reason=reason)

    @staticmethod
    def _to_int(v: object, default: int = 0) -> int:
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            try:
                return int(float(v))
            except ValueError:
                return default
        return default

    @staticmethod
    def _to_float(v: object, default: float = 0.0) -> float:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return default
        return default

    def _handle_ticks(self, ws: object, ticks: list[dict[str, object]]) -> None:
        for raw in ticks:
            token = self._to_int(raw.get("instrument_token"), 0)
            ltp = self._to_float(raw.get("last_price"), 0.0)
            cum_vol = self._to_int(raw.get("volume_traded"), 0)
            ts_ms = self._to_int(raw.get("timestamp"), 0)

            if ltp <= 0:
                continue

            # Convert cumulative → per-tick volume delta
            prev = self._prev_vol.get(token, cum_vol)
            delta_vol = max(0, cum_vol - prev)
            self._prev_vol[token] = cum_vol

            symbol, exchange = self._symbol_map.get(token, (str(token), "NSE"))
            tick = RawTick(
                symbol=symbol,
                exchange=exchange,
                ltp=ltp,
                volume=delta_vol,
                timestamp_ms=ts_ms,
            )
            try:
                self._on_tick(tick)
            except Exception as exc:  # noqa: BLE001
                logger.error("kite_ws_on_tick_callback_error", error=str(exc))
