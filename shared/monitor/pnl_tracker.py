"""P&L tracker for M19 Real-Time Monitor Agent.

Reads the current-day P&L from Redis (written by M12 RiskEngine) and computes
the circuit-breaker threshold against starting capital.

Redis key: ``RISK_DAILY_PNL_REDIS_KEY`` — format ``risk:daily:pnl:{date}``
           where ``{date}`` is ``YYYYMMDD``.  Value is the absolute P&L as a
           float string (positive = profit, negative = loss).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol

import structlog

from shared.core.constants import (
    KILL_SWITCH_HALTED_KEY,
    ORCHESTRATOR_STATE_REDIS_KEY,
    RECONCILIATION_MISMATCH_REDIS_STREAM,
    RISK_DAILY_PNL_REDIS_KEY,
)
from shared.monitor.models import PnLSnapshot

logger = structlog.get_logger(__name__)

_CIRCUIT_BREAKER_THRESHOLD: float = -0.02


class _RedisKV(Protocol):
    """Minimal Redis interface used by PnLTracker."""

    def get(self, name: str) -> bytes | None:
        ...

    def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        ...


class PnLTracker:
    """Reads daily P&L from Redis and computes circuit-breaker state.

    Args:
        redis_client: Redis client.  ``None`` → returns zeroed snapshot
            (paper/offline mode).
        starting_capital: Session starting capital used to compute P&L percentage.
    """

    def __init__(
        self,
        redis_client: _RedisKV | None = None,
        starting_capital: float = 1_000_000.0,
    ) -> None:
        self._redis = redis_client
        self._starting_capital = starting_capital

    def snapshot(self) -> PnLSnapshot:
        """Return a P&L snapshot for the current session day.

        Returns:
            ``PnLSnapshot`` with absolute P&L, percentage, and circuit-breaker flag.
        """
        pnl_today = self._read_pnl()
        pnl_pct = (
            pnl_today / self._starting_capital
            if self._starting_capital > 0
            else 0.0
        )
        is_cb = pnl_pct <= _CIRCUIT_BREAKER_THRESHOLD
        snapshot = PnLSnapshot(
            pnl_today=pnl_today,
            pnl_today_pct=pnl_pct,
            starting_capital=self._starting_capital,
            is_circuit_breaker=is_cb,
        )
        logger.debug(
            "pnl_tracker_snapshot",
            pnl_today=pnl_today,
            pnl_pct=pnl_pct,
            circuit_breaker=is_cb,
        )
        return snapshot

    def read_system_halted(self) -> bool:
        """Return ``True`` if the kill switch or circuit breaker is active in Redis.

        Returns:
            Halt state read from ``KILL_SWITCH_HALTED_KEY``.
        """
        if self._redis is None:
            return False
        try:
            raw = self._redis.get(KILL_SWITCH_HALTED_KEY)
            return raw is not None
        except Exception as exc:  # noqa: BLE001
            logger.warning("pnl_tracker_halted_read_error", error=str(exc))
            return False

    def read_orchestrator_state(self) -> dict[str, object]:
        """Read the orchestrator's persisted state blob from Redis.

        Returns:
            Parsed ``TradingSystemState`` dict, or empty dict on failure.
        """
        if self._redis is None:
            return {}
        try:
            raw = self._redis.get(ORCHESTRATOR_STATE_REDIS_KEY)
            if raw is None:
                return {}
            payload = raw.decode() if isinstance(raw, bytes) else str(raw)
            result: dict[str, object] = json.loads(payload)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("pnl_tracker_state_read_error", error=str(exc))
            return {}

    def read_reconciliation_mismatches(self) -> int:
        """Count outstanding reconciliation mismatches from the Redis Stream.

        Returns:
            Number of entries in ``RECONCILIATION_MISMATCH_REDIS_STREAM``.
        """
        if self._redis is None:
            return 0
        try:
            entries = self._redis.xrevrange(
                RECONCILIATION_MISMATCH_REDIS_STREAM, max="+", min="-", count=1000
            )
            return len(entries)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pnl_tracker_recon_read_error", error=str(exc))
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_pnl(self) -> float:
        """Read today's absolute P&L from Redis.

        Returns:
            P&L float (positive = profit).  Returns 0.0 on any failure.
        """
        if self._redis is None:
            return 0.0
        today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        key = RISK_DAILY_PNL_REDIS_KEY.format(date=today)
        try:
            raw = self._redis.get(key)
            if raw is None:
                return 0.0
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            return float(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pnl_tracker_pnl_read_error", key=key, error=str(exc))
            return 0.0
