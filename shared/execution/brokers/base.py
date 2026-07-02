"""Abstract base for all broker adapters (M14 Strategy Pattern).

Every concrete adapter (Paper, Kite, IBKR) must implement this interface.
``ExecutionEngine`` calls only these three methods — it is never broker-aware.

Idempotency contract:
- ``place_order`` must check ``tagged.original.client_order_id`` against the
  broker order book before submitting.  If the order already exists (because a
  prior call succeeded but the response was lost), return the existing fill
  record instead of submitting again.  Never blind-retry.
- ``query_order`` is used by ``ExecutionEngine`` to verify ambiguous responses
  before retrying.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from shared.compliance.models import TaggedOrder
    from shared.execution.models import FillReport


@runtime_checkable
class BrokerAdapter(Protocol):
    """Minimal broker interface used by ``ExecutionEngine``.

    All methods are synchronous; any async I/O in real adapters should be
    wrapped to present a blocking interface at this layer (event-loop isolation
    is a deployment concern, not a protocol concern).
    """

    def place_order(self, tagged: TaggedOrder) -> FillReport:
        """Submit the order to the broker and return a fill report.

        Implementations MUST check ``tagged.original.client_order_id`` against
        the broker's order book first.  Return the existing fill record if the
        order already exists (idempotent).

        Args:
            tagged: Compliance-resolved order with strategy tag and effective
                order type set by M13.

        Returns:
            ``FillReport`` with current order status (PLACED, FILLED, REJECTED,
            or PARTIALLY_FILLED depending on how quickly the broker responds).

        Raises:
            BrokerTransientError: For retryable failures (network timeout,
                rate-limit hit).  Engine will retry with exponential jitter.
            BrokerPermanentError: For non-retryable failures (insufficient
                funds, invalid symbol).  Engine will dead-letter the order.
        """
        ...

    def query_order(self, client_order_id: str) -> FillReport | None:
        """Query the broker for the current state of an order by its idempotency key.

        Called by ``ExecutionEngine`` before any retry when ``place_order``
        returns an ambiguous response (timeout, connection drop).  Prevents
        double-fills.

        Args:
            client_order_id: The idempotency key assigned before submission.

        Returns:
            ``FillReport`` if the broker has the order; ``None`` if not found.
        """
        ...

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a live order.

        Used by the kill-switch liquidation sequence (M13/M18) and the
        compliance cron force square-off (App 1).

        Args:
            client_order_id: The idempotency key of the order to cancel.

        Returns:
            ``True`` if the cancel was accepted; ``False`` if already filled
            or not found.
        """
        ...


class BrokerTransientError(Exception):
    """Retryable broker error (network timeout, temporary unavailability)."""


class BrokerPermanentError(Exception):
    """Non-retryable broker error (invalid order, insufficient funds)."""
