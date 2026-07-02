"""Reconciliation Agent for M17.

Periodically diffs broker source-of-truth (positions + open orders) against
internal Redis/Postgres state.  On any mismatch:
  1. Emits a ``ReconciliationMismatch`` proto event to a Redis Stream.
  2. Blocks new entry signals on the affected symbol via ``BlockRegistry``.
  3. Clears the block when the mismatch resolves in the next cycle.

Cycle timing: every ``RECONCILIATION_INTERVAL_SECONDS`` (default 90s) during
market hours; callers also trigger a final cycle at square-off.

Broker data is fetched via the ``BrokerStateProvider`` Protocol — implemented by
real broker adapters (M14/M15) and by the paper stub in tests.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import structlog

from shared.core.constants import RECONCILIATION_INTERVAL_SECONDS
from shared.reconciliation.block_registry import BlockRegistry
from shared.reconciliation.differ import diff_orders, diff_positions
from shared.reconciliation.models import (
    BrokerOrder,
    BrokerPosition,
    InternalOrder,
    InternalPosition,
    ReconciliationMismatch,
    ReconciliationResult,
)
from shared.reconciliation.publisher import MismatchPublisher

logger = structlog.get_logger(__name__)


@runtime_checkable
class BrokerStateProvider(Protocol):
    """Interface for fetching live broker state.

    Implementations must be safe to call from a background thread.
    Both methods return empty lists on any transient broker error (fail-open
    for the reconciliation cycle; the missing data is flagged as a mismatch).
    """

    def get_positions(self) -> list[BrokerPosition]:
        """Return all open positions from the broker."""
        ...

    def get_open_orders(self) -> list[BrokerOrder]:
        """Return all open/pending orders from the broker."""
        ...


@runtime_checkable
class InternalStateProvider(Protocol):
    """Interface for fetching internal (Redis/Postgres) position and order state."""

    def get_positions(self) -> list[InternalPosition]:
        """Return all positions tracked internally."""
        ...

    def get_open_orders(self) -> list[InternalOrder]:
        """Return all open orders tracked internally."""
        ...


class ReconciliationAgent:
    """Periodically reconciles broker state against internal state.

    Args:
        broker_state: Provider for live broker positions and orders.
        internal_state: Provider for internal Redis/Postgres state.
        publisher: ``MismatchPublisher`` for Redis Stream delivery.
        block_registry: ``BlockRegistry`` for per-symbol entry blocking.
        interval_seconds: Seconds between automatic reconciliation cycles.
        on_mismatch: Optional callback invoked for each detected mismatch
            (used by M20 alerting to send Telegram notifications).
    """

    def __init__(
        self,
        broker_state: BrokerStateProvider,
        internal_state: InternalStateProvider,
        publisher: MismatchPublisher | None = None,
        block_registry: BlockRegistry | None = None,
        interval_seconds: int = RECONCILIATION_INTERVAL_SECONDS,
        on_mismatch: Callable[[ReconciliationMismatch], None] | None = None,
    ) -> None:
        self._broker = broker_state
        self._internal = internal_state
        self._publisher = publisher or MismatchPublisher()
        self._blocks = block_registry or BlockRegistry()
        self._interval = interval_seconds
        self._on_mismatch = on_mismatch
        self._running = False
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._last_mismatch_keys: set[str] = set()

    def start(self) -> None:
        """Start the periodic reconciliation cycle in the background."""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._schedule_next()
        logger.info(
            "reconciliation_agent_started",
            interval_s=self._interval,
        )

    def stop(self) -> None:
        """Stop the background reconciliation timer."""
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("reconciliation_agent_stopped")

    def run_cycle(self) -> ReconciliationResult:
        """Execute one full reconciliation cycle synchronously.

        Fetches broker and internal state, diffs them, emits mismatch events,
        updates block flags, and clears stale blocks from prior cycles.

        Returns:
            ``ReconciliationResult`` describing what was found and acted on.
        """
        started_at = int(time.time() * 1000)
        logger.info("reconciliation_cycle_start")

        broker_positions = self._broker.get_positions()
        broker_orders = self._broker.get_open_orders()
        internal_positions = self._internal.get_positions()
        internal_orders = self._internal.get_open_orders()

        position_mismatches = diff_positions(
            broker_positions, internal_positions, now_ms=started_at
        )
        order_mismatches = diff_orders(
            broker_orders, internal_orders, now_ms=started_at
        )
        all_mismatches = position_mismatches + order_mismatches

        current_mismatch_keys: set[str] = set()
        symbols_blocked: list[str] = []
        symbols_cleared: list[str] = []

        for mismatch in all_mismatches:
            key = f"{mismatch.exchange}:{mismatch.symbol}"
            current_mismatch_keys.add(key)
            self._publisher.publish(mismatch)
            if not self._blocks.is_blocked(mismatch.symbol, mismatch.exchange):
                self._blocks.block(mismatch.symbol, mismatch.exchange)
                symbols_blocked.append(key)
            if self._on_mismatch is not None:
                try:
                    self._on_mismatch(mismatch)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "reconciliation_on_mismatch_callback_error",
                        error=str(exc),
                    )

        stale_keys = self._last_mismatch_keys - current_mismatch_keys
        for key in stale_keys:
            exchange, symbol = key.split(":", 1)
            self._blocks.clear(symbol, exchange)
            symbols_cleared.append(key)

        self._last_mismatch_keys = current_mismatch_keys
        completed_at = int(time.time() * 1000)

        result = ReconciliationResult(
            cycle_started_at_ms=started_at,
            cycle_completed_at_ms=completed_at,
            mismatches=all_mismatches,
            symbols_blocked=symbols_blocked,
            symbols_cleared=symbols_cleared,
        )
        logger.info(
            "reconciliation_cycle_complete",
            mismatch_count=result.mismatch_count,
            blocked=len(symbols_blocked),
            cleared=len(symbols_cleared),
            duration_ms=completed_at - started_at,
        )
        return result

    def is_blocked(self, symbol: str, exchange: str) -> bool:
        """Check whether new entries are blocked for a symbol.

        Delegates to the underlying ``BlockRegistry``.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier.

        Returns:
            ``True`` if entries are blocked for this symbol.
        """
        return self._blocks.is_blocked(symbol, exchange)

    def _schedule_next(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        try:
            self.run_cycle()
        except Exception as exc:  # noqa: BLE001
            logger.error("reconciliation_cycle_error", error=str(exc))
        finally:
            self._schedule_next()
