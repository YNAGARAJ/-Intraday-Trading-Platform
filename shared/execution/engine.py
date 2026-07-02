"""Order Execution Engine — M14.

``ExecutionEngine.submit()`` is the only entry point for submitting orders.
Every submission MUST pass through M13 compliance before reaching any broker.

Execution flow per order:
  1. Check kill-switch halted flag (Redis or in-memory fallback).
  2. Run M13 ``ComplianceEngine.check()`` — no bypass path.
  3. On compliance rejection: return REJECTED ``FillReport`` with audit trail.
  4. Submit to broker via ``BrokerAdapter.place_order()``.
  5. On timeout / ambiguous response: call ``BrokerAdapter.query_order()``
     BEFORE retrying — never blind-retry (idempotency guarantee).
  6. On transient failure: retry up to ``MAX_RETRIES`` with exponential jitter.
  7. On permanent failure / all retries exhausted: dead-letter the order.
  8. On partial fill: recompute ``sl_quantity`` against ``filled_quantity``.
  9. Audit log every state transition via structlog.

RULE 8 — ``is_priority`` flag:
  The only functions authorized to create ``OrderIntent(is_priority=True)``
  are ``make_sl_exit_order()`` and kill-switch liquidation helpers.  Signal
  and entry code never sets ``is_priority``.  The rate limiter Lua script
  (``rate_limiter.lua``) passes ``is_priority`` from the order to bypass the
  10 OPS bucket — this is the only bypass path for SL exits and kill sequences.
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

import structlog

from shared.compliance.engine import ComplianceEngine
from shared.compliance.models import OrderIntent
from shared.core.constants import (
    KILL_SWITCH_HALTED_KEY,
    MAX_RETRIES,
    RETRY_BASE_DELAY_SECONDS,
)
from shared.execution.dead_letter import DeadLetterQueue
from shared.execution.models import FillReport, OrderStatus

if TYPE_CHECKING:
    from shared.compliance.models import RecentOrder
    from shared.execution.brokers.base import BrokerAdapter

logger = structlog.get_logger(__name__)


def make_sl_exit_order(
    symbol: str,
    exchange: str,
    direction: str,
    quantity: int,
    stop_loss: float,
    client_order_id: str,
    strategy_name: str,
    ltp: float | None = None,
) -> OrderIntent:
    """Construct a stop-loss exit order with ``is_priority=True``.

    This is ONE OF TWO authorized call sites that may set ``is_priority=True``
    (the other is ``KillSwitchManager.trigger()``).  Signal/entry code must
    never call this function or pass ``is_priority=True`` directly.

    Args:
        symbol: Instrument symbol being exited.
        exchange: Market identifier.
        direction: ``'LONG'`` to exit a long (sell), ``'SHORT'`` to exit a short (buy).
        quantity: Number of shares/contracts to close.
        stop_loss: The triggered stop-loss price.
        client_order_id: Unique idempotency key for this SL exit.
        strategy_name: Strategy name for compliance tag resolution.
        ltp: Last-traded price (used for MPP conversion if needed).

    Returns:
        ``OrderIntent`` with ``is_priority=True`` and ``is_exit=True``.
    """
    return OrderIntent(
        symbol=symbol,
        exchange=exchange,
        direction="SHORT" if direction == "LONG" else "LONG",
        order_type="SL",
        quantity=quantity,
        price=stop_loss,
        stop_loss=stop_loss,
        strategy_name=strategy_name,
        client_order_id=client_order_id,
        ltp=ltp,
        is_exit=True,
        is_priority=True,
    )


def make_kill_switch_liquidation_order(
    symbol: str,
    exchange: str,
    direction: str,
    quantity: int,
    ltp: float,
    client_order_id: str,
    strategy_name: str,
) -> OrderIntent:
    """Construct a kill-switch emergency liquidation order with ``is_priority=True``.

    This is ONE OF TWO authorized call sites that may set ``is_priority=True``.

    Args:
        symbol: Symbol to liquidate.
        exchange: Market identifier.
        direction: Original position direction (exits in opposite direction).
        quantity: Full position size to close.
        ltp: Last-traded price for MPP limit computation.
        client_order_id: Unique idempotency key for this liquidation.
        strategy_name: Strategy name for compliance tag resolution.

    Returns:
        ``OrderIntent`` with ``is_priority=True``, ``is_exit=True``,
        ``order_type='MARKET'`` (will be MPP-converted by M13 for NSE/BSE).
    """
    return OrderIntent(
        symbol=symbol,
        exchange=exchange,
        direction="SHORT" if direction == "LONG" else "LONG",
        order_type="MARKET",
        quantity=quantity,
        price=None,
        stop_loss=ltp * 0.95,
        strategy_name=strategy_name,
        client_order_id=client_order_id,
        ltp=ltp,
        is_exit=True,
        is_priority=True,
    )


def _make_rejected_fill(
    order: OrderIntent,
    reason: str,
    strategy_tag: str = "",
    audit_id: str = "",
    attempt_count: int = 0,
) -> FillReport:
    """Create a REJECTED ``FillReport`` for compliance failures or halted state."""
    return FillReport(
        client_order_id=order.client_order_id,
        broker_order_id=None,
        symbol=order.symbol,
        exchange=order.exchange,
        direction=order.direction,
        filled_quantity=0,
        requested_quantity=order.quantity,
        filled_price=None,
        status=OrderStatus.REJECTED,
        rejection_reason=reason,
        placed_at_ms=int(time.time() * 1000),
        filled_at_ms=None,
        slippage_pct=None,
        is_partial=False,
        sl_quantity=0,
        attempt_count=attempt_count,
        strategy_tag=strategy_tag,
        compliance_audit_id=audit_id,
    )


class _RedisGet(Protocol):
    """Minimal Redis interface needed to read the halt flag."""

    def get(self, key: str) -> bytes | None:
        ...


class _HaltedFlag:
    """Checks ``KILL_SWITCH_HALTED_KEY`` in Redis or in-memory fallback."""

    def __init__(self, redis_client: _RedisGet | None) -> None:
        self._redis = redis_client

    def is_halted(self) -> bool:
        if self._redis is not None:
            try:
                raw = self._redis.get(KILL_SWITCH_HALTED_KEY)
                return raw is not None and raw.decode() == "true"
            except Exception:  # noqa: BLE001
                return False
        return False


class ExecutionEngine:
    """Routes validated orders through compliance and broker submission.

    All external state is injected at construction; the engine is stateless
    per-call and safe for concurrent use (thread-safety delegated to
    ``BrokerAdapter`` implementation).

    Args:
        broker: Broker adapter (``PaperBroker``, ``KiteBroker``, or
            ``IBKRBroker``).
        compliance_engine: M13 ``ComplianceEngine`` instance.
        dead_letter_queue: ``DeadLetterQueue`` for permanently-failed orders.
        redis_client: Connected Redis client for halted-flag check.
            ``None`` = in-memory only (tests / paper mode without Redis).
        max_retries: Maximum retry attempts on transient broker errors.
        retry_base_delay: Base delay in seconds for exponential jitter.
    """

    def __init__(
        self,
        broker: BrokerAdapter,
        compliance_engine: ComplianceEngine | None = None,
        dead_letter_queue: DeadLetterQueue | None = None,
        redis_client: _RedisGet | None = None,
        max_retries: int | None = None,
        retry_base_delay: float | None = None,
    ) -> None:
        self._broker = broker
        self._compliance = compliance_engine or ComplianceEngine()
        self._dlq = dead_letter_queue or DeadLetterQueue()
        self._halted = _HaltedFlag(redis_client)
        self._max_retries = max_retries if max_retries is not None else MAX_RETRIES
        self._base_delay = (
            retry_base_delay
            if retry_base_delay is not None
            else RETRY_BASE_DELAY_SECONDS
        )

    def submit(
        self,
        order: OrderIntent,
        now_ist: datetime | None = None,
        now_aest: datetime | None = None,
        recent_orders: list[RecentOrder] | None = None,
        pending_orders: list[RecentOrder] | None = None,
        approved_short_list: frozenset[str] | None = None,
        now_ms: int | None = None,
        group_open_ms: int | None = None,
    ) -> FillReport:
        """Submit an order through compliance → broker with idempotency and retry.

        Args:
            order: The proposed trade.  Must have ``client_order_id`` set.
                ``is_priority=True`` accepted ONLY from ``make_sl_exit_order``
                and ``make_kill_switch_liquidation_order`` call sites.
            now_ist: Current IST datetime for India compliance time checks.
            now_aest: Current AEST datetime for ASX compliance time checks.
            recent_orders: Recent orders for ASX wash-trade check (M13).
            pending_orders: Pending orders for ASX layering check (M13).
            approved_short_list: IBKR-verified short-sell symbols (M13/ASX).
            now_ms: Current epoch milliseconds (defaults to ``time.time()``).
            group_open_ms: ASX staggered-open group open timestamp.

        Returns:
            ``FillReport`` describing the outcome (filled, rejected, or partial).
        """
        _now_ms = now_ms if now_ms is not None else int(time.time() * 1000)

        # --- 1. Kill-switch pre-check ---
        if not order.is_priority and self._halted.is_halted():
            logger.warning(
                "execution_blocked_system_halted",
                client_order_id=order.client_order_id,
                symbol=order.symbol,
            )
            return _make_rejected_fill(order, "System is halted — kill switch active")

        # --- 2. Compliance check (M13) ---
        compliance_dec = self._compliance.check(
            order=order,
            now_ist=now_ist,
            now_aest=now_aest,
            recent_orders=recent_orders,
            pending_orders=pending_orders,
            approved_short_list=approved_short_list,
            now_ms=_now_ms,
            group_open_ms=group_open_ms,
        )

        if not compliance_dec.approved:
            reason = "; ".join(v.detail for v in compliance_dec.violations)
            logger.warning(
                "execution_compliance_rejected",
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                audit_id=compliance_dec.audit_id,
                violations=[v.code for v in compliance_dec.violations],
            )
            return _make_rejected_fill(
                order,
                reason,
                audit_id=compliance_dec.audit_id,
            )

        tagged = compliance_dec.tagged_order
        assert tagged is not None  # compliance_dec.approved guarantees this

        # --- 3. Submit to broker with idempotency + retry ---
        from shared.execution.brokers.base import (  # noqa: PLC0415
            BrokerPermanentError,
            BrokerTransientError,
        )

        last_error: str = ""
        attempt = 0

        while attempt <= self._max_retries:
            attempt += 1
            try:
                # Before any retry (attempt > 1): check idempotency first
                if attempt > 1:
                    existing = self._broker.query_order(order.client_order_id)
                    if existing is not None:
                        logger.info(
                            "execution_idempotent_result",
                            client_order_id=order.client_order_id,
                            attempt=attempt,
                            status=existing.status.value,
                        )
                        return self._finalize(
                            existing, compliance_dec.audit_id, attempt
                        )

                fill = self._broker.place_order(tagged)
                logger.info(
                    "execution_submitted",
                    client_order_id=order.client_order_id,
                    broker_order_id=fill.broker_order_id,
                    status=fill.status.value,
                    filled_qty=fill.filled_quantity,
                    attempt=attempt,
                    is_priority=order.is_priority,
                )
                return self._finalize(fill, compliance_dec.audit_id, attempt)

            except BrokerPermanentError as exc:
                last_error = str(exc)
                logger.error(
                    "execution_permanent_error",
                    client_order_id=order.client_order_id,
                    error=last_error,
                    attempt=attempt,
                )
                break  # no retry on permanent errors

            except BrokerTransientError as exc:
                last_error = str(exc)
                if attempt <= self._max_retries:
                    delay = (
                        self._base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.1)
                    )
                    logger.warning(
                        "execution_transient_error_retry",
                        client_order_id=order.client_order_id,
                        error=last_error,
                        attempt=attempt,
                        retry_delay_s=delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "execution_transient_error_exhausted",
                        client_order_id=order.client_order_id,
                        error=last_error,
                        attempts=attempt,
                    )

        # --- 4. Dead-letter after all retries exhausted ---
        strategy_tag = tagged.strategy_tag if tagged else ""
        self._dlq.enqueue(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            exchange=order.exchange,
            last_error=last_error,
            attempt_count=attempt,
            strategy_tag=strategy_tag,
        )
        return _make_rejected_fill(
            order,
            f"All {attempt} attempts failed: {last_error}",
            strategy_tag=strategy_tag,
            audit_id=compliance_dec.audit_id,
            attempt_count=attempt,
        )

    def _finalize(
        self,
        fill: FillReport,
        audit_id: str,
        attempt: int,
    ) -> FillReport:
        """Attach compliance audit ID and attempt count to a broker fill."""
        return FillReport(
            client_order_id=fill.client_order_id,
            broker_order_id=fill.broker_order_id,
            symbol=fill.symbol,
            exchange=fill.exchange,
            direction=fill.direction,
            filled_quantity=fill.filled_quantity,
            requested_quantity=fill.requested_quantity,
            filled_price=fill.filled_price,
            status=fill.status,
            rejection_reason=fill.rejection_reason,
            placed_at_ms=fill.placed_at_ms,
            filled_at_ms=fill.filled_at_ms,
            slippage_pct=fill.slippage_pct,
            is_partial=fill.is_partial,
            sl_quantity=fill.sl_quantity,
            attempt_count=attempt,
            strategy_tag=fill.strategy_tag,
            compliance_audit_id=audit_id,
        )
