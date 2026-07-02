"""SEBI-compatible audit log writer for M13.

Every order state change — compliance pass, compliance rejection, kill-switch
activation — is emitted as a structured JSON log entry via structlog.  The log
format is designed to satisfy SEBI's audit-trail requirements (strategy ID, symbol,
action, timestamp, reason).

Secrets are NEVER included in audit log entries (no API keys, no broker tokens).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from shared.compliance.models import (
        ComplianceViolation,
        KillSwitchEvent,
        OrderIntent,
    )

logger = structlog.get_logger(__name__)


def new_audit_id() -> str:
    """Generate a unique audit log identifier."""
    return uuid.uuid4().hex[:16]


def log_compliance_pass(
    order: OrderIntent,
    strategy_tag: str,
    effective_order_type: str,
    mpp_price: float | None,
    audit_id: str,
) -> None:
    """Emit a structured log entry for a compliance-approved order.

    Args:
        order: The original order intent (pre-tag resolution).
        strategy_tag: Compressed broker tag resolved from ``order.strategy_name``.
        effective_order_type: Final order type after any MPP conversion.
        mpp_price: MPP limit price if converted, else ``None``.
        audit_id: Unique identifier for this audit event.
    """
    logger.info(
        "compliance_pass",
        audit_id=audit_id,
        symbol=order.symbol,
        exchange=order.exchange,
        direction=order.direction,
        original_order_type=order.order_type,
        effective_order_type=effective_order_type,
        quantity=order.quantity,
        price=order.price,
        stop_loss=order.stop_loss,
        strategy_name=order.strategy_name,
        strategy_tag=strategy_tag,
        client_order_id=order.client_order_id,
        mpp_price=mpp_price,
        is_exit=order.is_exit,
        ts_ms=int(time.time() * 1000),
    )


def log_compliance_rejection(
    order: OrderIntent,
    violations: list[ComplianceViolation],
    audit_id: str,
) -> None:
    """Emit a structured log entry for a compliance-rejected order.

    Args:
        order: The original order intent.
        violations: All compliance rule violations that fired.
        audit_id: Unique identifier for this audit event.
    """
    logger.warning(
        "compliance_rejection",
        audit_id=audit_id,
        symbol=order.symbol,
        exchange=order.exchange,
        direction=order.direction,
        order_type=order.order_type,
        quantity=order.quantity,
        strategy_name=order.strategy_name,
        client_order_id=order.client_order_id,
        violation_codes=[v.code for v in violations],
        violation_details=[v.detail for v in violations],
        ts_ms=int(time.time() * 1000),
    )


def log_kill_switch(event: KillSwitchEvent) -> None:
    """Emit a critical-severity structured log entry for a kill switch activation.

    Args:
        event: The ``KillSwitchEvent`` describing which tier fired and why.
    """
    logger.critical(
        "kill_switch_activated",
        tier=event.tier,
        reason=event.reason,
        triggered_at_ms=event.triggered_at_ms,
        ts_ms=int(time.time() * 1000),
    )
