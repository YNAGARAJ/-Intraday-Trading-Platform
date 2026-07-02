"""Paper broker — in-memory order book for simulation and testing.

Fills orders immediately at the effective limit/MPP price.  Supports
idempotency checks, partial fills (configurable), and query/cancel.

Thread-safe via internal locking: concurrent submissions in tests are safe.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import structlog

from shared.execution.models import FillReport, OrderStatus

if TYPE_CHECKING:
    from shared.compliance.models import TaggedOrder

logger = structlog.get_logger(__name__)

_PAPER_BROKER_ID_PREFIX: str = "PAPER-"


class PaperBroker:
    """Fully functional in-memory broker for paper trading and testing.

    Args:
        partial_fill_ratio: When set to a value in (0, 1), every order is
            filled at this fraction of the requested quantity (simulates
            partial fills).  Default ``None`` means full fills.
        fail_count: If set, the first ``fail_count`` calls to ``place_order``
            raise ``BrokerTransientError`` before succeeding.  Useful for
            testing retry logic.
    """

    def __init__(
        self,
        partial_fill_ratio: float | None = None,
        fail_count: int = 0,
    ) -> None:
        self._orders: dict[str, FillReport] = {}
        self._partial_fill_ratio = partial_fill_ratio
        self._remaining_failures = fail_count
        self._lock = threading.Lock()
        self._seq = 0

    def _next_broker_id(self) -> str:
        self._seq += 1
        return f"{_PAPER_BROKER_ID_PREFIX}{self._seq:06d}"

    def place_order(self, tagged: TaggedOrder) -> FillReport:
        """Fill the order immediately in memory (idempotent).

        Args:
            tagged: Compliance-resolved order from M13.

        Returns:
            ``FillReport`` with ``status=FILLED`` or ``PARTIALLY_FILLED``.

        Raises:
            BrokerTransientError: If ``fail_count`` retries are still pending.
        """
        from shared.execution.brokers.base import BrokerTransientError  # noqa: PLC0415

        with self._lock:
            coid = tagged.original.client_order_id

            # Idempotency: return existing record if already submitted
            if coid in self._orders:
                logger.info(
                    "paper_broker_idempotent",
                    client_order_id=coid,
                    existing_status=self._orders[coid].status.value,
                )
                return self._orders[coid]

            # Simulate transient failures for retry testing
            if self._remaining_failures > 0:
                self._remaining_failures -= 1
                raise BrokerTransientError(
                    f"Paper broker simulated transient error "
                    f"({self._remaining_failures + 1} remaining)"
                )

            now_ms = int(time.time() * 1000)
            broker_id = self._next_broker_id()
            requested_qty = tagged.original.quantity

            # Determine fill price: MPP price if converted, else limit price
            fill_price = (
                tagged.mpp_price
                if tagged.mpp_price is not None
                else tagged.original.price
                if tagged.original.price is not None
                else tagged.original.stop_loss  # SL orders fill at stop price
            )

            # Compute fill quantity (partial fill simulation)
            if self._partial_fill_ratio is not None:
                filled_qty = max(1, int(requested_qty * self._partial_fill_ratio))
                status = (
                    OrderStatus.FILLED
                    if filled_qty == requested_qty
                    else OrderStatus.PARTIALLY_FILLED
                )
            else:
                filled_qty = requested_qty
                status = OrderStatus.FILLED

            # Slippage calculation (paper: zero slippage vs reference price)
            slippage: float | None = None
            ref_price = tagged.original.price
            if ref_price is not None and fill_price is not None and ref_price > 0:
                slippage = abs(fill_price - ref_price) / ref_price * 100.0

            # SL quantity proportional to fill (never over-hedge)
            sl_qty = filled_qty  # 1:1 for single-fill orders; M18 manages SL sizing

            report = FillReport(
                client_order_id=coid,
                broker_order_id=broker_id,
                symbol=tagged.original.symbol,
                exchange=tagged.original.exchange,
                direction=tagged.original.direction,
                filled_quantity=filled_qty,
                requested_quantity=requested_qty,
                filled_price=fill_price,
                status=status,
                rejection_reason=None,
                placed_at_ms=now_ms,
                filled_at_ms=now_ms,
                slippage_pct=slippage,
                is_partial=filled_qty < requested_qty,
                sl_quantity=sl_qty,
                attempt_count=1,
                strategy_tag=tagged.strategy_tag,
                compliance_audit_id="",
            )
            self._orders[coid] = report

            logger.info(
                "paper_order_filled",
                client_order_id=coid,
                broker_order_id=broker_id,
                symbol=tagged.original.symbol,
                exchange=tagged.original.exchange,
                direction=tagged.original.direction,
                filled_qty=filled_qty,
                requested_qty=requested_qty,
                fill_price=fill_price,
                status=status.value,
            )
            return report

    def query_order(self, client_order_id: str) -> FillReport | None:
        """Return the existing fill record for ``client_order_id``, or ``None``."""
        with self._lock:
            return self._orders.get(client_order_id)

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a pending order.  Returns False if already filled."""
        with self._lock:
            existing = self._orders.get(client_order_id)
            if existing is None:
                return False
            if existing.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                return False
            cancelled = FillReport(
                client_order_id=existing.client_order_id,
                broker_order_id=existing.broker_order_id,
                symbol=existing.symbol,
                exchange=existing.exchange,
                direction=existing.direction,
                filled_quantity=0,
                requested_quantity=existing.requested_quantity,
                filled_price=None,
                status=OrderStatus.CANCELLED,
                rejection_reason="cancelled",
                placed_at_ms=existing.placed_at_ms,
                filled_at_ms=None,
                slippage_pct=None,
                is_partial=False,
                sl_quantity=0,
                attempt_count=existing.attempt_count,
                strategy_tag=existing.strategy_tag,
                compliance_audit_id=existing.compliance_audit_id,
            )
            self._orders[client_order_id] = cancelled
            logger.info("paper_order_cancelled", client_order_id=client_order_id)
            return True

    def open_orders(self) -> list[FillReport]:
        """Return all non-terminal (PENDING/PLACED) orders."""
        with self._lock:
            return [
                r
                for r in self._orders.values()
                if r.status in (OrderStatus.PENDING, OrderStatus.PLACED)
            ]

    def all_fills(self) -> list[FillReport]:
        """Return all recorded fill reports (for testing/audit)."""
        with self._lock:
            return list(self._orders.values())
