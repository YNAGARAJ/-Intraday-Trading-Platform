"""Position and order diff logic for M17 Reconciliation Agent.

Compares broker source-of-truth against internal state and produces a list of
``ReconciliationMismatch`` records.  No side effects — pure comparison logic.
"""

from __future__ import annotations

import time

import structlog

from shared.core.constants import RECONCILIATION_TOLERANCE_PRICE_PCT
from shared.reconciliation.models import (
    BrokerOrder,
    BrokerPosition,
    InternalOrder,
    InternalPosition,
    MismatchField,
    ReconciliationMismatch,
)

logger = structlog.get_logger(__name__)


def _position_key(symbol: str, exchange: str) -> str:
    return f"{exchange}:{symbol}"


def diff_positions(
    broker_positions: list[BrokerPosition],
    internal_positions: list[InternalPosition],
    now_ms: int | None = None,
) -> list[ReconciliationMismatch]:
    """Compare broker positions against internal position state.

    Detects:
    - Quantity mismatch (broker ≠ internal).
    - Average-price mismatch beyond ``RECONCILIATION_TOLERANCE_PRICE_PCT``.
    - Position present internally but missing at broker.
    - Position present at broker but absent internally.

    Args:
        broker_positions: Positions from the broker API.
        internal_positions: Positions from internal Redis/Postgres state.
        now_ms: Timestamp for mismatch records (defaults to current wall time).

    Returns:
        List of ``ReconciliationMismatch`` objects (empty if fully reconciled).
    """
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    mismatches: list[ReconciliationMismatch] = []

    broker_map = {_position_key(p.symbol, p.exchange): p for p in broker_positions}
    internal_map = {_position_key(p.symbol, p.exchange): p for p in internal_positions}

    for key, internal in internal_map.items():
        broker = broker_map.get(key)
        if broker is None:
            if internal.quantity != 0:
                mismatches.append(
                    ReconciliationMismatch(
                        symbol=internal.symbol,
                        exchange=internal.exchange,
                        field=MismatchField.POSITION_MISSING,
                        internal_value=str(internal.quantity),
                        broker_value="0",
                        detected_at_ms=ts,
                    )
                )
            continue

        if broker.quantity != internal.quantity:
            mismatches.append(
                ReconciliationMismatch(
                    symbol=internal.symbol,
                    exchange=internal.exchange,
                    field=MismatchField.QUANTITY,
                    internal_value=str(internal.quantity),
                    broker_value=str(broker.quantity),
                    detected_at_ms=ts,
                )
            )

        if internal.avg_price > 0:
            price_delta = (
                abs(broker.avg_price - internal.avg_price) / internal.avg_price
            )
            if price_delta > RECONCILIATION_TOLERANCE_PRICE_PCT:
                mismatches.append(
                    ReconciliationMismatch(
                        symbol=internal.symbol,
                        exchange=internal.exchange,
                        field=MismatchField.AVG_PRICE,
                        internal_value=f"{internal.avg_price:.4f}",
                        broker_value=f"{broker.avg_price:.4f}",
                        detected_at_ms=ts,
                    )
                )

    for key, broker in broker_map.items():
        if key not in internal_map and broker.quantity != 0:
            mismatches.append(
                ReconciliationMismatch(
                    symbol=broker.symbol,
                    exchange=broker.exchange,
                    field=MismatchField.UNEXPECTED_POSITION,
                    internal_value="0",
                    broker_value=str(broker.quantity),
                    detected_at_ms=ts,
                )
            )

    if mismatches:
        logger.warning(
            "reconciliation_position_mismatches",
            count=len(mismatches),
            fields=[m.field.value for m in mismatches],
        )
    return mismatches


def diff_orders(
    broker_orders: list[BrokerOrder],
    internal_orders: list[InternalOrder],
    now_ms: int | None = None,
) -> list[ReconciliationMismatch]:
    """Compare broker open orders against internal order state.

    Detects:
    - Order present internally but missing at broker (may have been manually cancelled).
    - Order present at broker but absent internally (manually placed bypassing system).
    - Order status differs between internal and broker records.

    Args:
        broker_orders: Open/pending orders from the broker API.
        internal_orders: Orders tracked in internal state.
        now_ms: Timestamp for mismatch records (defaults to current wall time).

    Returns:
        List of ``ReconciliationMismatch`` objects.
    """
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    mismatches: list[ReconciliationMismatch] = []

    broker_map = {o.client_order_id: o for o in broker_orders}
    internal_map = {o.client_order_id: o for o in internal_orders}

    for coid, internal in internal_map.items():
        broker = broker_map.get(coid)
        if broker is None:
            mismatches.append(
                ReconciliationMismatch(
                    symbol=internal.symbol,
                    exchange=internal.exchange,
                    field=MismatchField.ORDER_MISSING,
                    internal_value=internal.status,
                    broker_value="NOT_FOUND",
                    detected_at_ms=ts,
                )
            )
            continue

        if broker.status.upper() != internal.status.upper():
            mismatches.append(
                ReconciliationMismatch(
                    symbol=internal.symbol,
                    exchange=internal.exchange,
                    field=MismatchField.ORDER_STATUS,
                    internal_value=internal.status,
                    broker_value=broker.status,
                    detected_at_ms=ts,
                )
            )

    for coid, broker in broker_map.items():
        if coid not in internal_map:
            mismatches.append(
                ReconciliationMismatch(
                    symbol=broker.symbol,
                    exchange=broker.exchange,
                    field=MismatchField.UNEXPECTED_ORDER,
                    internal_value="NOT_FOUND",
                    broker_value=broker.status,
                    detected_at_ms=ts,
                )
            )

    if mismatches:
        logger.warning(
            "reconciliation_order_mismatches",
            count=len(mismatches),
            fields=[m.field.value for m in mismatches],
        )
    return mismatches
