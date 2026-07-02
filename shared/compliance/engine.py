"""Compliance Engine — single entry point for all pre-trade compliance checks (M13).

``ComplianceEngine.check()`` is the mandatory gate between signal generation
(M11/M12) and order submission (M14).  M14 must not submit any order without
a ``ComplianceDecision`` with ``approved=True``.  There is no bypass path.

Evaluation sequence:
  1. Resolve strategy tag (StrategyRegistry).
  2. India checks (if NSE/BSE): strategy ID presence, MPP conversion, leverage, MWPL,
     force square-off time.
  3. Australia checks (if ASX): wash trading, layering, short-sell, staggered open,
     post-close cutoff.
  4. Collect all violations — reject on first non-empty violation list (fail-fast per
     market; within each market all violations are collected so the audit log has
     full context).
  5. Write audit log entry (pass or rejection).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from shared.compliance.audit_log import (
    log_compliance_pass,
    log_compliance_rejection,
    new_audit_id,
)
from shared.compliance.australia import run_australia_checks
from shared.compliance.india import run_india_checks
from shared.compliance.models import (
    ComplianceDecision,
    ComplianceViolation,
    OrderIntent,
    TaggedOrder,
)
from shared.compliance.strategy_registry import StrategyRegistry

if TYPE_CHECKING:
    from shared.compliance.models import RecentOrder

logger = structlog.get_logger(__name__)


class ComplianceEngine:
    """Runs all India and Australia compliance checks on an order intent.

    Stateless after construction: the registry is read-only; all external
    state (MWPL %, recent orders, current time) is passed per-call.

    Args:
        registry: Pre-built ``StrategyRegistry``.  Defaults to a new instance
            that reads ``USE_GENERIC_ALGO_ID`` from the environment.
    """

    def __init__(self, registry: StrategyRegistry | None = None) -> None:
        self._registry = registry or StrategyRegistry()

    def check(
        self,
        order: OrderIntent,
        now_ist: datetime | None = None,
        now_aest: datetime | None = None,
        recent_orders: list[RecentOrder] | None = None,
        pending_orders: list[RecentOrder] | None = None,
        approved_short_list: frozenset[str] | None = None,
        now_ms: int | None = None,
        group_open_ms: int | None = None,
    ) -> ComplianceDecision:
        """Run all applicable compliance checks for ``order``.

        Args:
            order: The proposed trade — populated by M11/M12 signal+risk pipeline.
            now_ist: Current IST datetime for India force-square-off check.
                ``None`` skips the time check (paper mode or non-India order).
            now_aest: Current AEST datetime for ASX post-close cutoff check.
                ``None`` skips the time check.
            recent_orders: Orders placed recently (wash-trade check, ASX only).
            pending_orders: Currently live orders (layering check, ASX only).
            approved_short_list: IBKR-verified short-sell symbols (ASX only).
            now_ms: Current Unix epoch milliseconds (wash-trade timing).
                Defaults to ``int(time.time() * 1000)`` when ``None``.
            group_open_ms: ASX group open timestamp for staggered-open check.

        Returns:
            ``ComplianceDecision`` — ``approved=True`` only when ALL checks pass.
        """
        import time  # noqa: PLC0415

        audit_id = new_audit_id()
        _now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        _recent = recent_orders or []
        _pending = pending_orders or []
        _short_list = approved_short_list or frozenset()

        all_violations: list[ComplianceViolation] = []
        effective_order_type = order.order_type
        mpp_price: float | None = None

        # --- Resolve strategy tag ---
        strategy_tag = self._registry.resolve(order.strategy_name)

        # --- India (NSE/BSE) checks ---
        if order.exchange in ("NSE", "BSE"):
            india_violations, effective_order_type, mpp_price = run_india_checks(
                order=order,
                strategy_tag=strategy_tag,
                now_ist=now_ist,
            )
            all_violations.extend(india_violations)

        # --- Australia (ASX) checks ---
        elif order.exchange == "ASX":
            aus_violations = run_australia_checks(
                order=order,
                recent_orders=_recent,
                pending_orders=_pending,
                approved_short_list=_short_list,
                now_ms=_now_ms,
                group_open_ms=group_open_ms,
                now_aest=now_aest,
            )
            all_violations.extend(aus_violations)

        # PAPER exchange: always pass through — used for simulation.
        # Strategy tag still resolved so audit logs are consistent.

        if all_violations:
            log_compliance_rejection(order, all_violations, audit_id)
            return ComplianceDecision(
                approved=False,
                violations=all_violations,
                tagged_order=None,
                audit_id=audit_id,
            )

        # Build the tagged order with resolved strategy ID and MPP conversion
        if strategy_tag is None:
            # PAPER exchange or future exchange without strategy enforcement
            strategy_tag = order.strategy_name[:8]

        tagged = TaggedOrder(
            original=order,
            strategy_tag=strategy_tag,
            effective_order_type=effective_order_type,
            mpp_price=mpp_price,
        )

        log_compliance_pass(
            order=order,
            strategy_tag=strategy_tag,
            effective_order_type=effective_order_type,
            mpp_price=mpp_price,
            audit_id=audit_id,
        )

        return ComplianceDecision(
            approved=True,
            violations=[],
            tagged_order=tagged,
            audit_id=audit_id,
        )
