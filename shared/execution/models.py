"""Data models for M14 Order Execution Engine.

``FillReport`` is the canonical output of every broker submission attempt.
``DeadLetterEntry`` records permanently-failed orders for operator review.
``OrderStatus`` tracks the lifecycle of every order through the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderStatus(str, Enum):
    """Lifecycle states for an order managed by the execution engine."""

    PENDING = "PENDING"
    """Constructed but not yet submitted to the broker."""

    PLACED = "PLACED"
    """Submitted to the broker and acknowledged (broker_order_id assigned)."""

    FILLED = "FILLED"
    """Fully filled — ``filled_quantity == requested_quantity``."""

    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    """Partially filled — ``filled_quantity < requested_quantity``."""

    REJECTED = "REJECTED"
    """Broker or compliance engine rejected the order."""

    CANCELLED = "CANCELLED"
    """Cancelled before fill (manual or kill-switch sequence)."""


@dataclass(frozen=True)
class FillReport:
    """Result of a single order submission attempt.

    Returned by ``ExecutionEngine.submit()`` and ``BrokerAdapter.place_order()``
    for every order (successful, partial, or failed).

    Args:
        client_order_id: Echo of the idempotency key from the input ``OrderIntent``.
        broker_order_id: Broker-assigned order ID (``None`` on rejection before
            placement).
        symbol: Instrument symbol.
        exchange: Market identifier.
        direction: ``'LONG'`` or ``'SHORT'``.
        filled_quantity: Shares/contracts actually filled (0 on rejection).
        requested_quantity: Original quantity from the ``OrderIntent``.
        filled_price: Average fill price (``None`` on rejection).
        status: Final lifecycle state.
        rejection_reason: Human-readable reason on ``REJECTED``; ``None`` otherwise.
        placed_at_ms: Unix epoch milliseconds when the order was placed.
        filled_at_ms: Unix epoch milliseconds when the fill was confirmed.
            ``None`` when not yet filled.
        slippage_pct: ``|filled_price - limit_price| / limit_price * 100``.
            ``None`` on rejection or market orders without a reference price.
        is_partial: True when ``filled_quantity < requested_quantity``.
        sl_quantity: Stop-loss quantity, recomputed against ``filled_quantity``
            (not ``requested_quantity``) to avoid over-hedging on partial fills.
        attempt_count: Number of submission attempts (1 = succeeded first try).
        strategy_tag: Compressed broker tag resolved by M13 compliance engine.
        compliance_audit_id: The audit log ID from M13's compliance decision.
    """

    client_order_id: str
    broker_order_id: str | None
    symbol: str
    exchange: str
    direction: str
    filled_quantity: int
    requested_quantity: int
    filled_price: float | None
    status: OrderStatus
    rejection_reason: str | None
    placed_at_ms: int
    filled_at_ms: int | None
    slippage_pct: float | None
    is_partial: bool
    sl_quantity: int
    attempt_count: int
    strategy_tag: str
    compliance_audit_id: str


@dataclass(frozen=True)
class DeadLetterEntry:
    """An order that exhausted all retry attempts and was sent to the dead-letter queue.

    Persisted to Redis list ``dlq:orders`` and triggers a Telegram alert (M20).

    Args:
        client_order_id: Original idempotency key.
        symbol: Instrument symbol.
        exchange: Market identifier.
        last_error: Final error message before DLQ entry.
        attempt_count: Total number of attempts made.
        enqueued_at_ms: Unix epoch milliseconds when the entry was created.
        strategy_tag: Compliance-resolved broker tag.
    """

    client_order_id: str
    symbol: str
    exchange: str
    last_error: str
    attempt_count: int
    enqueued_at_ms: int
    strategy_tag: str
