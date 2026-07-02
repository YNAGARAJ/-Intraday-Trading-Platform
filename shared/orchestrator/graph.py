"""LangGraph State Graph wiring for M18 Agent Orchestrator.

The graph executes one orchestration cycle:

    regime_node → signal_node → reconciliation_node → risk_node
                                                           │
                         ┌─────────────────────────────────┤
                         ▼                                 │
                  kill_switch_node ◄──── kill/CB active ───┤
                         │                                 │
                         ▼                                 ▼
                        END                          hitl_node → END
                                                           │
                                                           ▼
                                                          END

HITL interrupt:
  Compiled with ``interrupt_before=['hitl_node']``.  When ``pending_hitl_approval``
  is set and the graph reaches the routing step, it halts BEFORE ``hitl_node``.
  Callers resume by invoking ``app.invoke(None, config=thread_config)``.

Kill switch preemption (RULE 8):
  If ``kill_switch_active`` or ``circuit_breaker_active`` is True when the routing
  function runs, the graph routes to ``kill_switch_node`` instead of ``hitl_node``.
  An in-flight HITL is cancelled by ``kill_switch_node`` which clears
  ``pending_hitl_approval`` in state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from shared.core.constants import ORCHESTRATOR_STATE_REDIS_KEY
from shared.orchestrator.nodes import (
    make_hitl_node,
    make_kill_switch_node,
    make_reconciliation_node,
    make_regime_node,
    make_risk_node,
    make_signal_node,
)
from shared.orchestrator.state import (
    TradingSystemState,
    make_initial_state,
    state_from_json,
    state_to_json,
)

logger = structlog.get_logger(__name__)

# Node name constants (avoid typos in add_conditional_edges)
_REGIME = "regime_node"
_SIGNAL = "signal_node"
_RECON = "reconciliation_node"
_RISK = "risk_node"
_HITL = "hitl_node"
_KILL = "kill_switch_node"

_ROUTE_KILL = "kill"
_ROUTE_HITL = "hitl"
_ROUTE_END = "end"


class _RedisKV(Protocol):
    """Minimal Redis interface used by the graph for state persistence."""

    def get(self, name: str) -> bytes | None:
        ...

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        ...


class OrchestratorGraph:
    """Wraps the LangGraph ``CompiledGraph`` and exposes a simple cycle API.

    Args:
        redis_client: Redis client for Streams, key checks, and state
            persistence.  ``None`` → in-memory only (paper/test mode).
        starting_capital: Starting capital for HITL threshold and circuit
            breaker calculations.
        reconciliation_blocked_fn: Callable ``(symbol, exchange) → bool``
            from ``ReconciliationAgent.is_blocked``.  ``None`` → no block check.
        thread_id: LangGraph checkpoint thread identifier for this session.
        enable_hitl: If ``False``, the ``hitl_node`` is not used as an
            interrupt point (useful for automated paper-trading runs).
    """

    def __init__(
        self,
        redis_client: _RedisKV | None = None,
        starting_capital: float = 1_000_000.0,
        reconciliation_blocked_fn: Callable[[str, str], bool] | None = None,
        thread_id: str = "default",
        enable_hitl: bool = True,
    ) -> None:
        self._redis = redis_client
        self._thread_id = thread_id
        self._enable_hitl = enable_hitl
        self._checkpointer = MemorySaver()
        self._state = make_initial_state()

        regime_fn = make_regime_node(redis_client=redis_client)
        signal_fn = make_signal_node(
            redis_client=redis_client,
            reconciliation_blocked_fn=reconciliation_blocked_fn,
        )
        recon_fn = make_reconciliation_node(redis_client=redis_client)
        risk_fn = make_risk_node(starting_capital=starting_capital)
        hitl_fn = make_hitl_node()
        kill_fn = make_kill_switch_node(redis_client=redis_client)

        g: StateGraph = StateGraph(TradingSystemState)
        g.add_node(_REGIME, regime_fn)
        g.add_node(_SIGNAL, signal_fn)
        g.add_node(_RECON, recon_fn)
        g.add_node(_RISK, risk_fn)
        g.add_node(_HITL, hitl_fn)
        g.add_node(_KILL, kill_fn)

        g.set_entry_point(_REGIME)
        g.add_edge(_REGIME, _SIGNAL)
        g.add_edge(_SIGNAL, _RECON)
        g.add_edge(_RECON, _RISK)

        g.add_conditional_edges(
            _RISK,
            self._route_after_risk,
            {_ROUTE_KILL: _KILL, _ROUTE_HITL: _HITL, _ROUTE_END: END},
        )
        g.add_edge(_HITL, END)
        g.add_edge(_KILL, END)

        interrupt_before = [_HITL] if enable_hitl else None
        self._app = g.compile(
            checkpointer=self._checkpointer,
            interrupt_before=interrupt_before,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_risk(state: TradingSystemState) -> str:
        """Decide next node after ``risk_node``.

        Kill switch / circuit breaker always wins over HITL (RULE 8).

        Args:
            state: Current orchestrator state.

        Returns:
            One of ``"kill"``, ``"hitl"``, or ``"end"``.
        """
        if state.get("kill_switch_active") or state.get("circuit_breaker_active"):
            return _ROUTE_KILL
        if state.get("pending_hitl_approval") is not None:
            return _ROUTE_HITL
        return _ROUTE_END

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def _thread_config(self) -> dict[str, object]:
        return {"configurable": {"thread_id": self._thread_id}}

    def run_cycle(
        self, input_state: TradingSystemState | None = None
    ) -> TradingSystemState | None:
        """Execute one orchestration cycle.

        If the cycle is interrupted for HITL, returns ``None`` and stores the
        checkpoint.  Call ``approve_hitl()`` or ``reject_hitl()`` to resume.

        Args:
            input_state: State overrides for this cycle.  ``None`` resumes from
                the last checkpoint (used after HITL approval/rejection).

        Returns:
            The updated ``TradingSystemState``, or ``None`` if interrupted for
            HITL approval.
        """
        invoke_input: TradingSystemState | None = input_state or self._state
        raw = self._app.invoke(invoke_input, config=self._thread_config)
        result: TradingSystemState | None = raw if raw is not None else None
        if result is not None:
            self._state = result
        logger.info(
            "orchestrator_cycle_complete",
            interrupted=result is None,
            kill_switch=self._state.get("kill_switch_active"),
            signals_today=self._state.get("signals_today"),
        )
        return result

    def approve_hitl(self) -> TradingSystemState | None:
        """Resume execution after human approval of a pending HITL interrupt.

        Returns:
            Updated state after HITL node executes, or ``None`` if still
            interrupted.
        """
        logger.info("hitl_approved", thread_id=self._thread_id)
        raw = self._app.invoke(None, config=self._thread_config)
        result: TradingSystemState | None = raw if raw is not None else None
        if result is not None:
            self._state = result
        return result

    def reject_hitl(self) -> None:
        """Cancel the pending HITL approval (human rejected the trade).

        Clears ``pending_hitl_approval`` in the checkpoint and re-runs the
        graph from the routing step, which will route to END.
        """
        logger.info("hitl_rejected", thread_id=self._thread_id)
        self._app.update_state(
            self._thread_config,
            {"pending_hitl_approval": None},
        )
        result = self._app.invoke(None, config=self._thread_config)
        if result is not None:
            self._state = result

    def trigger_kill_switch(self, reason: str = "manual") -> None:
        """Activate the kill switch, preempting any pending HITL (RULE 8).

        Updates local state immediately (for ``is_halted()`` callers) and
        also updates the LangGraph checkpoint so the next cycle routes to
        ``kill_switch_node``.

        Args:
            reason: Human-readable reason for the kill switch activation.
        """
        logger.warning("orchestrator_kill_switch_triggered", reason=reason)
        # Update local state immediately so is_halted() returns True at once
        self._state["kill_switch_active"] = True
        self._state["pending_hitl_approval"] = None
        self._app.update_state(
            self._thread_config,
            {"kill_switch_active": True, "pending_hitl_approval": None},
        )
        result = self._app.invoke(None, config=self._thread_config)
        if result is not None:
            self._state = result

    def get_state(self) -> TradingSystemState:
        """Return the current in-memory state snapshot.

        Returns:
            The most recently completed ``TradingSystemState``.
        """
        return self._state

    def is_halted(self) -> bool:
        """Return ``True`` if the kill switch or circuit breaker is active.

        Returns:
            ``True`` when any halt condition is in effect.
        """
        return bool(
            self._state.get("kill_switch_active")
            or self._state.get("circuit_breaker_active")
        )

    def shutdown(self) -> None:
        """Serialise current state to Redis for crash-recovery on restart.

        Writes the full ``TradingSystemState`` to ``ORCHESTRATOR_STATE_REDIS_KEY``.
        """
        if self._redis is None:
            logger.info("orchestrator_shutdown_no_redis")
            return
        try:
            payload = state_to_json(self._state)
            self._redis.set(ORCHESTRATOR_STATE_REDIS_KEY, payload)
            logger.info(
                "orchestrator_shutdown_state_persisted",
                key=ORCHESTRATOR_STATE_REDIS_KEY,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("orchestrator_shutdown_persist_failed", error=str(exc))

    @classmethod
    def restore(
        cls,
        redis_client: _RedisKV,
        **kwargs: object,
    ) -> "OrchestratorGraph":
        """Restore an orchestrator from a previously persisted Redis state.

        Args:
            redis_client: Redis client to read the saved state from.
            **kwargs: Additional keyword arguments forwarded to ``__init__``.

        Returns:
            A new ``OrchestratorGraph`` with state loaded from Redis.
        """
        raw = redis_client.get(ORCHESTRATOR_STATE_REDIS_KEY)
        instance = cls(redis_client=redis_client, **kwargs)  # type: ignore[arg-type]
        if raw is not None:
            payload = raw.decode() if isinstance(raw, bytes) else str(raw)
            instance._state = state_from_json(payload)
            logger.info("orchestrator_state_restored")
        return instance
