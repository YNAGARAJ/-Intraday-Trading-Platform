"""LangGraph shared state schema for M18 Agent Orchestrator.

The ``TradingSystemState`` TypedDict is the single source of truth shared across
all agent nodes in the state graph.  Nodes return a dict containing only the
fields they mutate; LangGraph merges updates into the persisted state.

Immutability contract (RULE 8):
- ``circuit_breaker_active`` and ``kill_switch_active`` are set to ``True`` by the
  kill-switch node only and never reset to ``False`` within a live session.
- ``pending_hitl_approval`` is cleared (set to ``None``) by the kill-switch node
  whenever a kill-switch event fires — the kill switch ALWAYS preempts a pending
  HITL approval, never the reverse.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from typing_extensions import TypedDict


class TradingSystemState(TypedDict):
    """Full shared state for the LangGraph orchestrator.

    All fields are required to be present; ``Optional`` means the value may be
    ``None`` but the key must exist in the dict.
    """

    # --- Session ---
    session_state: str
    """One of ``CLOSED`` | ``PRE_MARKET`` | ``OPEN`` |
    ``SNAPSHOT_WINDOW`` | ``APPROACHING_CLOSE``."""

    market_date: str
    """ISO date string ``YYYY-MM-DD`` for the current trading session."""

    # --- Regime ---
    market_regime: str
    """One of ``BULL_TREND`` | ``BEAR_TREND`` | ``MEAN_REVERTING`` |
    ``HIGH_VOL_CHAOS``."""

    regime_confidence: float
    """Classifier confidence for the current regime (0.0–1.0)."""

    # --- Universe & Watchlist ---
    watchlist: list[dict[str, object]]
    """List of ``WatchlistEntry`` TypedDicts from M09."""

    # --- Positions & Orders ---
    open_positions: dict[str, dict[str, object]]
    """symbol → Position dict (quantity, avg_price, strategy, pnl, etc.)."""

    open_orders: dict[str, dict[str, object]]
    """order_id → Order dict (symbol, status, quantity, etc.)."""

    # --- P&L ---
    signals_today: int
    """Count of valid signals generated during this session."""

    trades_today: int
    """Count of fills (entries + exits) during this session."""

    pnl_today: float
    """Absolute P&L in base currency since session open."""

    pnl_today_pct: float
    """P&L as a fraction of starting capital (e.g. −0.02 = −2%)."""

    # --- Safety flags (IMMUTABLE once set True in live mode) ---
    circuit_breaker_active: bool
    """Set to True at −2% daily P&L.  Never reset to False in live mode (RULE 8)."""

    kill_switch_active: bool
    """Set to True by any KillSwitch tier.  Blocks all entries and new orders."""

    snapshot_window_active: bool
    """True during the SEBI snapshot window (14:45–15:30 IST)."""

    # --- Human-in-the-loop ---
    pending_hitl_approval: Optional[dict[str, object]]
    """Non-None when a human approval is required (position > 5% of capital).
    Cleared immediately when kill_switch_active is set to True (RULE 8)."""

    # --- SEBI compliance ---
    strategy_ids: dict[str, str]
    """strategy_name → registered SEBI strategy ID or generic algo ID."""

    ops_last_second: int
    """Orders placed in the last second; self-throttled to ≤ 10 unless priority."""

    # --- Agent health ---
    agent_heartbeats: dict[str, str]
    """agent_name → ISO-format last heartbeat timestamp string."""

    # --- Reconciliation ---
    last_reconciliation_at: Optional[str]
    """ISO-format timestamp of the last successful reconciliation cycle."""

    reconciliation_mismatches_today: int
    """Running count of unique mismatches surfaced today."""

    # --- Error tracking ---
    last_error: Optional[str]
    """Human-readable description of the most recent agent error."""

    last_error_agent: Optional[str]
    """Name of the agent that raised ``last_error``."""

    last_error_at: Optional[str]
    """ISO-format timestamp when ``last_error`` occurred."""


def make_initial_state(market_date: str = "") -> TradingSystemState:
    """Return a zero-value ``TradingSystemState`` for session start.

    Args:
        market_date: ISO date string for the trading session.  Defaults to
            today's date if empty.

    Returns:
        A ``TradingSystemState`` with safe default values.
    """
    if not market_date:
        market_date = datetime.utcnow().strftime("%Y-%m-%d")

    return TradingSystemState(
        session_state="CLOSED",
        market_date=market_date,
        market_regime="MEAN_REVERTING",
        regime_confidence=0.0,
        watchlist=[],
        open_positions={},
        open_orders={},
        signals_today=0,
        trades_today=0,
        pnl_today=0.0,
        pnl_today_pct=0.0,
        circuit_breaker_active=False,
        kill_switch_active=False,
        snapshot_window_active=False,
        pending_hitl_approval=None,
        strategy_ids={},
        ops_last_second=0,
        agent_heartbeats={},
        last_reconciliation_at=None,
        reconciliation_mismatches_today=0,
        last_error=None,
        last_error_agent=None,
        last_error_at=None,
    )


def state_to_json(state: TradingSystemState) -> str:
    """Serialise state to JSON for Redis persistence.

    Args:
        state: The current orchestrator state.

    Returns:
        JSON string representation of the state.
    """
    return json.dumps(dict(state))


def state_from_json(raw: str) -> TradingSystemState:
    """Deserialise state from a Redis-stored JSON string.

    Args:
        raw: JSON string previously returned by ``state_to_json``.

    Returns:
        Reconstructed ``TradingSystemState``.
    """
    data = json.loads(raw)
    initial = make_initial_state()
    initial.update(data)
    return initial
