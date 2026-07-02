"""Tiered Kill Switch for M13 Compliance & Regulatory Engine.

Implements all three tiers required by ASIC's current automated-trading
kill-switch obligations (and the stricter 3-tier standard proposed in CP 386):

  Tier 1 — Autonomous: circuit breaker at -2% daily P&L (RULE 8).
  Tier 2 — External API: ``POST /api/v1/controls/kill`` or Telegram ``/kill``.
  Tier 3 — Heartbeat Failsafe: MonitorAgent detects 2 missed heartbeats (M19).

``KillSwitchManager.trigger()`` is the ONLY authorized setter of
``is_priority=True`` on ``KillSwitchEvent``.  Stop-loss exits (M14) are the
other authorized path — they set ``is_priority`` on the rate-limiter Lua call
directly.  No signal/entry code or API layer ever sets ``is_priority``.

CP 386 note: consultation paper, submissions closed Oct 2025, final rules
targeted by 31 March 2026, PROPOSED commencement April 2027.  Not yet
binding.  Build to the stricter standard regardless (see RULE 1).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Protocol

import structlog

from shared.compliance.audit_log import log_kill_switch
from shared.compliance.models import KillSwitchEvent
from shared.core.constants import (
    KILL_SWITCH_HALTED_KEY,
    KILL_SWITCH_REASON_KEY,
    KILL_SWITCH_TIER_KEY,
)

logger = structlog.get_logger(__name__)


class KillSwitchTrigger(str, Enum):
    """Which tier of the kill switch was activated."""

    TIER1_CIRCUIT_BREAKER = "TIER1_CIRCUIT_BREAKER"
    TIER2_EXTERNAL_API = "TIER2_EXTERNAL_API"
    TIER3_HEARTBEAT = "TIER3_HEARTBEAT"


class RedisClient(Protocol):
    """Minimal Redis interface needed by ``KillSwitchManager``."""

    def set(self, name: str, value: str) -> object:  # noqa: A003
        ...

    def get(self, name: str) -> bytes | None:
        ...


class KillSwitchManager:
    """Manages the tiered kill switch state machine.

    This class is the ONLY place in the codebase that sets
    ``KillSwitchEvent.is_priority``.  Every tier calls ``.trigger()`` which
    produces a ``KillSwitchEvent`` with ``is_priority=True``.

    M14 reads the halted Redis key before submitting any order.  M18 wires
    the full liquidation sequence (cancel all orders → MPP exit → alerts).

    Args:
        redis_client: Connected Redis client.  ``None`` means in-memory only
            (used in tests / paper mode without Redis).
    """

    def __init__(self, redis_client: RedisClient | None = None) -> None:
        self._redis = redis_client
        self._halted = False
        self._last_event: KillSwitchEvent | None = None

    @property
    def is_halted(self) -> bool:
        """True when any tier has activated the kill switch."""
        if self._redis is not None:
            raw = self._redis.get(KILL_SWITCH_HALTED_KEY)
            return raw is not None and raw.decode() == "true"
        return self._halted

    def trigger(
        self,
        trigger_type: KillSwitchTrigger,
        reason: str,
    ) -> KillSwitchEvent:
        """Activate the kill switch.

        Sets ``system:status:halted = true`` in Redis (or in-memory when
        Redis is unavailable).  Emits a critical audit log entry.

        The returned ``KillSwitchEvent`` has ``is_priority=True`` — this is the
        ONLY authorized constructor of that field.  No signal/entry/API code
        may call this method.

        Args:
            trigger_type: Which tier triggered (Tier 1/2/3).
            reason: Human-readable description of the trigger event.

        Returns:
            ``KillSwitchEvent`` with ``is_priority=True`` that M18 uses to
            start the liquidation sequence.
        """
        tier = int(trigger_type.value[4])  # TIER<N>_...
        event = KillSwitchEvent(
            tier=tier,
            reason=reason,
            triggered_at_ms=int(time.time() * 1000),
        )
        self._last_event = event

        if self._redis is not None:
            self._redis.set(KILL_SWITCH_HALTED_KEY, "true")
            self._redis.set(KILL_SWITCH_TIER_KEY, str(tier))
            self._redis.set(KILL_SWITCH_REASON_KEY, reason)
        else:
            self._halted = True

        log_kill_switch(event)
        logger.critical(
            "kill_switch_triggered",
            tier=tier,
            trigger_type=trigger_type.value,
            reason=reason,
        )
        return event

    def trigger_tier1(self, daily_pnl_pct: float) -> KillSwitchEvent:
        """Tier 1: autonomous circuit breaker (-2% daily P&L).

        Called by M12/M18 when ``daily_pnl / capital ≤ -2%``.
        """
        return self.trigger(
            KillSwitchTrigger.TIER1_CIRCUIT_BREAKER,
            f"Daily P&L {daily_pnl_pct:.2f}% breached -2% autonomous circuit breaker.",
        )

    def trigger_tier2(self, source: str = "external_api") -> KillSwitchEvent:
        """Tier 2: external API or Telegram ``/kill`` command.

        Args:
            source: Human-readable description of the API caller (e.g.
                ``'telegram_bot'``, ``'rest_api'``).
        """
        return self.trigger(
            KillSwitchTrigger.TIER2_EXTERNAL_API,
            f"Manual kill switch activated via {source}.",
        )

    def trigger_tier3(self, agent_name: str, missed_heartbeats: int) -> KillSwitchEvent:
        """Tier 3: heartbeat failsafe (M19 MonitorAgent).

        Called when an agent misses ``MAX_MISSED_HEARTBEATS_BEFORE_KILL``
        consecutive heartbeats.

        Args:
            agent_name: Name of the unresponsive agent.
            missed_heartbeats: Count of missed consecutive heartbeats.
        """
        return self.trigger(
            KillSwitchTrigger.TIER3_HEARTBEAT,
            f"Agent '{agent_name}' missed {missed_heartbeats} consecutive heartbeats.",
        )

    @property
    def last_event(self) -> KillSwitchEvent | None:
        """The most recent kill switch event, or ``None`` if not yet triggered."""
        return self._last_event
