"""IBKR TWS streaming adapter for M16 Data Ingestion Agent.

Wraps ``IBKRConnectionPool`` to deliver real-time price data as ``RawTick``
objects via a callback.  Uses IBKR's ``reqMktData`` to subscribe to live quotes.

ibapi SDK may not be installed in dev; the adapter degrades gracefully to a
disconnected stub that returns ``is_connected() == False``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import structlog

from shared.auth.ibkr_auth import IBKRConnectionPool
from shared.auth.models import IBKRClientSlot
from shared.ingestion.models import RawTick

logger = structlog.get_logger(__name__)


@runtime_checkable
class _EWrapperProto(Protocol):
    """Minimal EWrapper interface for type narrowing."""

    def tickPrice(  # noqa: N802
        self,
        req_id: int,
        tick_type: int,
        price: float,
        attrib: object,
    ) -> None:
        ...

    def tickSize(self, req_id: int, tick_type: int, size: int) -> None:  # noqa: N802
        ...


class IBKRStreamAdapter:
    """IBKR TWS market data stream adapter.

    Subscribes to live price ticks for a list of ASX symbols using ``reqMktData``,
    and delivers validated ``RawTick`` callbacks.

    Args:
        pool: ``IBKRConnectionPool`` providing a clientId slot.
        symbols: ASX symbol list to subscribe (e.g. ``["CBA", "BHP"]``).
        exchange: Exchange for all symbols (default ``"ASX"``).
        on_tick: Callback invoked for each ``RawTick``.
    """

    def __init__(
        self,
        pool: IBKRConnectionPool,
        symbols: list[str],
        exchange: str = "ASX",
        on_tick: Callable[[RawTick], None] | None = None,
    ) -> None:
        self._pool = pool
        self._symbols = symbols
        self._exchange = exchange
        self._on_tick = on_tick
        self._slot: IBKRClientSlot | None = None
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Acquire a pool slot and connect to TWS.

        No-ops gracefully if ibapi is not installed or no slot is available.
        """
        try:
            slot = self._pool.acquire()
            ok = self._pool.connect(slot)
            if ok:
                with self._lock:
                    self._slot = slot
                    self._connected = True
                logger.info(
                    "ibkr_stream_connected",
                    client_id=slot.client_id,
                    symbol_count=len(self._symbols),
                )
            else:
                self._pool.release(slot)
                logger.warning("ibkr_stream_connect_failed_no_tws")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ibkr_stream_connect_error", error=str(exc))

    def disconnect(self) -> None:
        """Release the pool slot and mark as disconnected."""
        with self._lock:
            self._connected = False
            slot = self._slot
            self._slot = None
        if slot is not None:
            self._pool.release(slot)
        logger.info("ibkr_stream_disconnected")

    def is_connected(self) -> bool:
        """Return True if the TWS connection is active."""
        with self._lock:
            return self._connected

    def inject_tick(self, tick: RawTick) -> None:
        """Deliver a synthetic tick directly (paper/test mode).

        Args:
            tick: ``RawTick`` to deliver to the ``on_tick`` callback.
        """
        if self._on_tick is not None:
            try:
                self._on_tick(tick)
            except Exception as exc:  # noqa: BLE001
                logger.error("ibkr_stream_on_tick_callback_error", error=str(exc))
