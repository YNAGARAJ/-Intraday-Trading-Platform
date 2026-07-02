"""Data models for M19 Real-Time Monitor Agent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HeartbeatRecord:
    """Per-agent heartbeat tracking record.

    Args:
        agent_name: Logical name of the monitored agent.
        last_seen_ms: Unix timestamp (milliseconds) of the last received heartbeat.
        missed_count: Consecutive missed heartbeat cycles since last recovery.
    """

    agent_name: str
    last_seen_ms: float
    missed_count: int = 0


@dataclass
class AgentHealth:
    """Health summary for a single agent at a point in time.

    Args:
        agent_name: Logical name of the agent.
        is_healthy: ``True`` when ``missed_count < MAX_MISSED_HEARTBEATS_BEFORE_KILL``.
        last_seen_ms: Unix ms of the most recent heartbeat.
        missed_count: Consecutive misses detected in the current poll cycle.
        age_seconds: Elapsed seconds since the last heartbeat.
    """

    agent_name: str
    is_healthy: bool
    last_seen_ms: float
    missed_count: int
    age_seconds: float


@dataclass
class PnLSnapshot:
    """P&L state captured at a single monitoring tick.

    Args:
        pnl_today: Absolute daily P&L in base currency.
        pnl_today_pct: Daily P&L as a fraction of starting capital.
        starting_capital: Starting capital for this session.
        is_circuit_breaker: ``True`` when ``pnl_today_pct ≤ -0.02`` (RULE 8).
    """

    pnl_today: float
    pnl_today_pct: float
    starting_capital: float
    is_circuit_breaker: bool


@dataclass
class MonitorSnapshot:
    """Complete system health snapshot from one MonitorAgent poll cycle.

    Args:
        timestamp_ms: Unix ms when this snapshot was taken.
        pnl: P&L state for the current session.
        agent_health: Per-agent health records, keyed by agent name.
        open_positions_count: Number of currently open positions.
        signals_today: Total signals generated today.
        reconciliation_mismatches: Outstanding reconciliation mismatches.
        system_halted: ``True`` when the kill switch or circuit breaker is active.
    """

    timestamp_ms: float
    pnl: PnLSnapshot
    agent_health: dict[str, AgentHealth] = field(default_factory=dict)
    open_positions_count: int = 0
    signals_today: int = 0
    reconciliation_mismatches: int = 0
    system_halted: bool = False
