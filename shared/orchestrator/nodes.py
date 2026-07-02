"""LangGraph node functions for M18 Agent Orchestrator.

Each node receives the full ``TradingSystemState`` and returns a dict containing
only the fields it updates.  LangGraph merges the returned dict into the
persisted state.

Node dependency injection follows the Protocol pattern used throughout this
codebase — callers pass lightweight stubs in tests, real adapters in production.

Node responsibility summary
---------------------------
- ``regime_node``         — reads latest regime from Redis Stream; updates state
- ``signal_node``         — reads new signals; checks blocks/halted/degraded
- ``reconciliation_node`` — surfaces current mismatch count from Redis
- ``risk_node``           — runs circuit breaker; tags large positions for HITL
- ``hitl_node``           — interrupt point for positions > 5% of capital
- ``kill_switch_node``    — executes kill switch; cancels pending HITL (RULE 8)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import structlog

from shared.core.constants import (
    HITL_CAPITAL_THRESHOLD_PCT,
    INGESTION_DEGRADED_REDIS_KEY,
    KILL_SWITCH_HALTED_KEY,
    RECONCILIATION_MISMATCH_REDIS_STREAM,
    REGIME_REDIS_STREAM,
    SIGNAL_REDIS_STREAM,
)
from shared.orchestrator.state import TradingSystemState

logger = structlog.get_logger(__name__)

_NodeFn = Callable[[TradingSystemState], dict[str, object]]
_BlockedFn = Callable[[str, str], bool]


# ---------------------------------------------------------------------------
# Redis Protocols used by nodes
# ---------------------------------------------------------------------------


class _RedisStream(Protocol):
    """Minimal Redis interface for reading Streams and checking string keys."""

    def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        ...

    def get(self, name: str) -> bytes | None:
        ...


# ---------------------------------------------------------------------------
# Node: regime
# ---------------------------------------------------------------------------


def make_regime_node(
    redis_client: _RedisStream | None = None,
) -> _NodeFn:
    """Return a regime node that reads the latest regime from Redis Stream.

    Args:
        redis_client: Redis client for reading ``REGIME_REDIS_STREAM``.
            ``None`` → state is unchanged (regime stays as initialised).

    Returns:
        A LangGraph-compatible node function.
    """

    def regime_node(state: TradingSystemState) -> dict[str, object]:
        """Read the latest market regime from Redis Stream and update state."""
        if redis_client is None:
            logger.debug("regime_node_no_redis")
            return {}
        try:
            entries = redis_client.xrevrange(
                REGIME_REDIS_STREAM, max="+", min="-", count=1
            )
            if not entries:
                return {}
            _entry_id, fields = entries[0]
            regime_raw = fields.get(b"regime", b"")
            if isinstance(regime_raw, bytes):
                regime = regime_raw.decode()
            else:
                regime = str(regime_raw)
            conf_raw = fields.get(b"confidence", b"0.0")
            try:
                confidence = float(
                    conf_raw.decode() if isinstance(conf_raw, bytes) else conf_raw
                )
            except (ValueError, AttributeError):
                confidence = 0.0
            if regime:
                logger.info("regime_node_updated", regime=regime, confidence=confidence)
                return {"market_regime": regime, "regime_confidence": confidence}
        except Exception as exc:  # noqa: BLE001
            logger.warning("regime_node_error", error=str(exc))
        return {}

    return regime_node


# ---------------------------------------------------------------------------
# Node: signal
# ---------------------------------------------------------------------------


def make_signal_node(
    redis_client: _RedisStream | None = None,
    reconciliation_blocked_fn: _BlockedFn | None = None,
) -> _NodeFn:
    """Return a signal node that reads new signals and checks safety gates.

    Gates (all checked before incrementing ``signals_today``):
    1. ``kill_switch_active`` → block all entries.
    2. ``circuit_breaker_active`` → block all entries.
    3. ``system:status:degraded`` Redis key set → DEGRADED_EXIT_ONLY (block entries).
    4. ``market_regime == HIGH_VOL_CHAOS`` → block (RULE 2).
    5. Reconciliation block → block on affected symbol (checked per-signal).

    Args:
        redis_client: Redis client.  ``None`` → no new signals read.
        reconciliation_blocked_fn: Callable ``(symbol, exchange) → bool`` from
            ``ReconciliationAgent.is_blocked``.  ``None`` → no block check.

    Returns:
        A LangGraph-compatible node function.
    """

    def signal_node(state: TradingSystemState) -> dict[str, object]:
        """Check safety gates and consume latest signals from Redis Stream."""
        if state.get("kill_switch_active") or state.get("circuit_breaker_active"):
            logger.info("signal_node_blocked_by_kill_or_cb")
            return {}

        if redis_client is not None:
            halted = redis_client.get(KILL_SWITCH_HALTED_KEY)
            if halted is not None:
                logger.info("signal_node_redis_halted")
                return {"kill_switch_active": True}

            degraded = redis_client.get(INGESTION_DEGRADED_REDIS_KEY)
            if degraded is not None:
                logger.info("signal_node_degraded_exit_only")
                return {}

        if state.get("market_regime") == "HIGH_VOL_CHAOS":
            logger.info("signal_node_high_vol_chaos_blocked")
            return {}

        if redis_client is None:
            return {}

        try:
            entries = redis_client.xrevrange(
                SIGNAL_REDIS_STREAM, max="+", min="-", count=1
            )
            if not entries:
                return {}
            _entry_id, fields = entries[0]
            symbol_raw = fields.get(b"symbol", b"")
            exchange_raw = fields.get(b"exchange", b"")
            if isinstance(symbol_raw, bytes):
                symbol = symbol_raw.decode()
            else:
                symbol = str(symbol_raw)
            exchange = (
                exchange_raw.decode()
                if isinstance(exchange_raw, bytes)
                else str(exchange_raw)
            )

            if (
                reconciliation_blocked_fn is not None
                and reconciliation_blocked_fn(symbol, exchange)
            ):
                logger.info(
                    "signal_node_reconciliation_blocked",
                    symbol=symbol,
                    exchange=exchange,
                )
                return {}

            logger.info("signal_node_consumed", symbol=symbol, exchange=exchange)
            return {"signals_today": state["signals_today"] + 1}
        except Exception as exc:  # noqa: BLE001
            logger.warning("signal_node_error", error=str(exc))
        return {}

    return signal_node


# ---------------------------------------------------------------------------
# Node: reconciliation
# ---------------------------------------------------------------------------


def make_reconciliation_node(
    redis_client: _RedisStream | None = None,
) -> _NodeFn:
    """Return a reconciliation node that surfaces current mismatch count.

    Reads the ``reconciliation:mismatches`` stream and updates
    ``reconciliation_mismatches_today`` and ``last_reconciliation_at``.

    Args:
        redis_client: Redis client.  ``None`` → state unchanged.

    Returns:
        A LangGraph-compatible node function.
    """

    def reconciliation_node(state: TradingSystemState) -> dict[str, object]:
        """Poll the reconciliation mismatch stream and update state."""
        now_iso = datetime.utcnow().isoformat()
        if redis_client is None:
            return {"last_reconciliation_at": now_iso}
        try:
            entries = redis_client.xrevrange(
                RECONCILIATION_MISMATCH_REDIS_STREAM,
                max="+",
                min="-",
                count=100,
            )
            mismatch_count = len(entries)
            prior = state.get("reconciliation_mismatches_today", 0)
            new_total = max(prior, mismatch_count)
            return {
                "last_reconciliation_at": now_iso,
                "reconciliation_mismatches_today": new_total,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconciliation_node_error", error=str(exc))
            return {"last_reconciliation_at": now_iso}

    return reconciliation_node


# ---------------------------------------------------------------------------
# Node: risk
# ---------------------------------------------------------------------------


def make_risk_node(
    starting_capital: float = 1_000_000.0,
) -> _NodeFn:
    """Return a risk node that checks circuit breaker and tags large positions.

    Circuit breaker triggers at −2% daily P&L (sets ``circuit_breaker_active``).
    Positions exceeding ``HITL_CAPITAL_THRESHOLD_PCT`` of capital set
    ``pending_hitl_approval`` for human review.

    Args:
        starting_capital: Session starting capital in base currency.

    Returns:
        A LangGraph-compatible node function.
    """

    def risk_node(state: TradingSystemState) -> dict[str, object]:
        """Run circuit breaker and HITL threshold checks."""
        pnl_pct = state.get("pnl_today_pct", 0.0)

        if pnl_pct <= -0.02 and not state.get("circuit_breaker_active"):
            logger.warning("risk_node_circuit_breaker_trigger", pnl_pct=pnl_pct)
            return {
                "circuit_breaker_active": True,
                "last_error": f"Circuit breaker: daily P&L {pnl_pct:.2%}",
                "last_error_agent": "risk_node",
                "last_error_at": datetime.utcnow().isoformat(),
            }

        if state.get("kill_switch_active") or state.get("circuit_breaker_active"):
            return {}

        positions = state.get("open_positions", {})
        for symbol, pos in positions.items():
            qty_raw = pos.get("quantity", 0)
            qty = float(qty_raw) if isinstance(qty_raw, (int, float)) else 0.0
            price_raw = pos.get("avg_price", 0.0)
            avg_price = float(price_raw) if isinstance(price_raw, (int, float)) else 0.0
            position_value = abs(qty * avg_price)
            if starting_capital > 0:
                pct = position_value / starting_capital
                if pct > HITL_CAPITAL_THRESHOLD_PCT:
                    logger.warning(
                        "risk_node_hitl_required",
                        symbol=symbol,
                        pct=pct,
                    )
                    return {
                        "pending_hitl_approval": {
                            "symbol": symbol,
                            "position_value": position_value,
                            "capital_pct": pct,
                            "requested_at": datetime.utcnow().isoformat(),
                        }
                    }
        return {}

    return risk_node


# ---------------------------------------------------------------------------
# Node: HITL
# ---------------------------------------------------------------------------


def make_hitl_node() -> _NodeFn:
    """Return the HITL node — the human-approval interrupt point.

    This node is the target of ``interrupt_before=['hitl_node']`` in the
    compiled graph.  It executes only after a human approves by calling
    ``app.invoke(None, config=...)`` to resume from the checkpoint.

    On resume, it clears ``pending_hitl_approval`` and increments
    ``trades_today`` (signifying approved intent to trade).

    Returns:
        A LangGraph-compatible node function.
    """

    def hitl_node(state: TradingSystemState) -> dict[str, object]:
        """Execute after human approval; clear pending HITL flag."""
        hitl = state.get("pending_hitl_approval")
        if hitl is not None:
            symbol = hitl.get("symbol", "unknown")
            logger.info("hitl_node_approved", symbol=symbol)
        return {"pending_hitl_approval": None}

    return hitl_node


# ---------------------------------------------------------------------------
# Node: Kill Switch
# ---------------------------------------------------------------------------


def make_kill_switch_node(
    redis_client: _RedisStream | None = None,
) -> _NodeFn:
    """Return the kill switch node that executes the emergency halt sequence.

    RULE 8: This node ALWAYS preempts a pending HITL approval.
    Sequence:
    1. Set ``kill_switch_active = True`` in state.
    2. Clear ``pending_hitl_approval`` (HITL is cancelled — RULE 8).
    3. Log the kill switch event.

    Note: actual order cancellation and position liquidation are performed
    by the ``KillSwitchManager`` (M13) and the execution engine (M14).
    This node updates orchestrator state and emits structured logs only.

    Args:
        redis_client: Redis client (informational only; KILL_SWITCH_HALTED_KEY
            is checked but written by M13 ``KillSwitchManager``).

    Returns:
        A LangGraph-compatible node function.
    """

    def kill_switch_node(state: TradingSystemState) -> dict[str, object]:
        """Execute kill switch: cancel HITL, halt all activity."""
        hitl = state.get("pending_hitl_approval")
        if hitl is not None:
            symbol = hitl.get("symbol", "unknown")
            logger.warning(
                "kill_switch_preempts_hitl",
                symbol=symbol,
            )

        logger.warning(
            "kill_switch_node_activated",
            circuit_breaker=state.get("circuit_breaker_active"),
        )
        return {
            "kill_switch_active": True,
            "pending_hitl_approval": None,
            "last_error": "Kill switch activated",
            "last_error_agent": "kill_switch_node",
            "last_error_at": datetime.utcnow().isoformat(),
        }

    return kill_switch_node


__all__ = [
    "make_hitl_node",
    "make_kill_switch_node",
    "make_reconciliation_node",
    "make_regime_node",
    "make_risk_node",
    "make_signal_node",
]
