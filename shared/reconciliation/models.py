"""Data models for M17 Reconciliation Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MismatchField(str, Enum):
    """Which field diverged between internal state and broker source-of-truth."""

    QUANTITY = "quantity"
    AVG_PRICE = "avg_price"
    ORDER_STATUS = "order_status"
    POSITION_MISSING = "position_missing"
    ORDER_MISSING = "order_missing"
    UNEXPECTED_POSITION = "unexpected_position"
    UNEXPECTED_ORDER = "unexpected_order"


@dataclass(frozen=True)
class BrokerPosition:
    """A position as reported by the broker API.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange identifier.
        quantity: Net position quantity (positive = long, negative = short).
        avg_price: Average cost basis for the position.
        product: Product type (e.g. ``"MIS"``, ``"CNC"``, ``"NRML"``).
    """

    symbol: str
    exchange: str
    quantity: int
    avg_price: float
    product: str = "MIS"


@dataclass(frozen=True)
class BrokerOrder:
    """An open/pending order as reported by the broker API.

    Args:
        order_id: Broker-assigned order identifier.
        client_order_id: System-assigned idempotency key.
        symbol: Instrument symbol.
        exchange: Exchange identifier.
        status: Broker order status string (e.g. ``"OPEN"``, ``"PENDING"``).
        quantity: Ordered quantity.
        filled_quantity: Filled portion so far.
        avg_price: Average fill price (0.0 if unfilled).
    """

    order_id: str
    client_order_id: str
    symbol: str
    exchange: str
    status: str
    quantity: int
    filled_quantity: int
    avg_price: float


@dataclass(frozen=True)
class InternalPosition:
    """A position as tracked in internal Redis/Postgres state.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange identifier.
        quantity: Net position quantity.
        avg_price: Average cost basis.
    """

    symbol: str
    exchange: str
    quantity: int
    avg_price: float


@dataclass(frozen=True)
class InternalOrder:
    """An open order as tracked in internal state.

    Args:
        client_order_id: System-assigned idempotency key.
        symbol: Instrument symbol.
        exchange: Exchange identifier.
        status: Internal status string.
        filled_quantity: Filled portion tracked internally.
    """

    client_order_id: str
    symbol: str
    exchange: str
    status: str
    filled_quantity: int


@dataclass(frozen=True)
class ReconciliationMismatch:
    """A detected divergence between internal and broker state.

    Args:
        symbol: Instrument symbol affected.
        exchange: Exchange identifier.
        field: Which data field diverged (see ``MismatchField``).
        internal_value: Value as tracked internally (string representation).
        broker_value: Value as reported by the broker (string representation).
        detected_at_ms: Unix epoch milliseconds when the mismatch was detected.
    """

    symbol: str
    exchange: str
    field: MismatchField
    internal_value: str
    broker_value: str
    detected_at_ms: int


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation cycle.

    Args:
        cycle_started_at_ms: Unix epoch ms when the cycle began.
        cycle_completed_at_ms: Unix epoch ms when the cycle finished.
        mismatches: All mismatches detected in this cycle.
        symbols_blocked: Symbols that were blocked for new entries.
        symbols_cleared: Symbols that had blocks cleared (previously blocked).
    """

    cycle_started_at_ms: int
    cycle_completed_at_ms: int
    mismatches: list[ReconciliationMismatch] = field(default_factory=list)
    symbols_blocked: list[str] = field(default_factory=list)
    symbols_cleared: list[str] = field(default_factory=list)

    @property
    def has_mismatches(self) -> bool:
        """Return True if any mismatches were detected."""
        return len(self.mismatches) > 0

    @property
    def mismatch_count(self) -> int:
        """Number of mismatches found in this cycle."""
        return len(self.mismatches)
