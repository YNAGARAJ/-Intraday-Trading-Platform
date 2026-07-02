"""Heartbeat checker for M19 Real-Time Monitor Agent.

Implements the Tier 3 Kill Switch trigger:
    MonitorAgent detects SignalAgent missed 2 consecutive heartbeats
    → invokes Kill Switch → prevents rogue behavior from crashed agent.

Each monitored agent writes its name to Redis at ``MONITOR_HEARTBEAT_REDIS_KEY_PREFIX``
once per heartbeat cycle.  The HeartbeatChecker polls those keys and fires a Tier 3
kill switch after ``MAX_MISSED_HEARTBEATS_BEFORE_KILL`` consecutive misses.
"""

from __future__ import annotations

import time
from typing import Protocol

import structlog

from shared.core.constants import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_MISSED_HEARTBEATS_BEFORE_KILL,
    MONITOR_HEARTBEAT_REDIS_KEY_PREFIX,
)
from shared.monitor.models import AgentHealth, HeartbeatRecord

logger = structlog.get_logger(__name__)


class _RedisKV(Protocol):
    """Minimal Redis interface for heartbeat tracking."""

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def get(self, name: str) -> bytes | None:
        ...


class _KillSwitchTrigger(Protocol):
    """Minimal interface for triggering a Tier 3 kill switch."""

    def trigger_tier3(
        self,
        reason: str,
        redis_client: object = None,
    ) -> object:
        ...


class HeartbeatChecker:
    """Monitors per-agent heartbeat timestamps and triggers the Tier 3 kill switch.

    Agents call ``register_heartbeat(agent_name)`` once per heartbeat cycle to
    write their timestamp to Redis.  The checker's ``check_all()`` method reads
    those timestamps and increments the miss counter for any agent whose last
    heartbeat is older than ``interval_seconds``.  When the counter reaches
    ``max_misses``, a Tier 3 kill switch is triggered.

    Args:
        redis_client: Redis client for heartbeat key reads/writes.
            ``None`` → in-memory only (paper/test mode without Redis).
        kill_switch: Optional Tier 3 kill switch trigger.  If provided,
            ``trigger_tier3(reason)`` is called when the miss threshold is hit.
        interval_seconds: Seconds between expected heartbeats.
        max_misses: Consecutive misses before triggering the kill switch.
    """

    def __init__(
        self,
        redis_client: _RedisKV | None = None,
        kill_switch: _KillSwitchTrigger | None = None,
        interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
        max_misses: int = MAX_MISSED_HEARTBEATS_BEFORE_KILL,
    ) -> None:
        self._redis = redis_client
        self._kill_switch = kill_switch
        self._interval = interval_seconds
        self._max_misses = max_misses
        self._records: dict[str, HeartbeatRecord] = {}

    def add_watched_agent(self, agent_name: str) -> None:
        """Register an agent to be monitored for heartbeat liveness.

        Args:
            agent_name: Logical name of the agent to watch.
        """
        if agent_name not in self._records:
            self._records[agent_name] = HeartbeatRecord(
                agent_name=agent_name,
                last_seen_ms=time.time() * 1000,
            )
            logger.info("heartbeat_watch_added", agent=agent_name)

    def register_heartbeat(
        self,
        agent_name: str,
        now_ms: float | None = None,
    ) -> None:
        """Record a live heartbeat for an agent.

        Writes the current timestamp to Redis at
        ``monitor:heartbeat:<agent_name>`` and resets the in-process miss count.

        Args:
            agent_name: Agent that sent the heartbeat.
            now_ms: Override timestamp (Unix ms).  ``None`` → wall clock.
        """
        ts_ms = now_ms if now_ms is not None else time.time() * 1000
        redis_key = f"{MONITOR_HEARTBEAT_REDIS_KEY_PREFIX}:{agent_name}"
        if self._redis is not None:
            try:
                self._redis.set(redis_key, str(ts_ms))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "heartbeat_redis_write_failed", agent=agent_name, error=str(exc)
                )
        if agent_name not in self._records:
            self._records[agent_name] = HeartbeatRecord(
                agent_name=agent_name,
                last_seen_ms=ts_ms,
            )
        else:
            self._records[agent_name].last_seen_ms = ts_ms
            self._records[agent_name].missed_count = 0
        logger.debug("heartbeat_registered", agent=agent_name, ts_ms=ts_ms)

    def check_all(
        self, now_ms: float | None = None
    ) -> dict[str, AgentHealth]:
        """Poll all watched agents and update miss counters.

        For each watched agent:
        - Reads the Redis heartbeat key (if Redis available) and updates local
          ``last_seen_ms`` if the Redis value is fresher.
        - Computes ``age_seconds = (now_ms - last_seen_ms) / 1000``.
        - If ``age_seconds > interval_seconds``, increments ``missed_count``.
        - If ``age_seconds ≤ interval_seconds``, resets ``missed_count`` to 0.
        - If ``missed_count ≥ max_misses``, triggers the Tier 3 kill switch.

        Args:
            now_ms: Override timestamp (Unix ms).  ``None`` → wall clock.

        Returns:
            Dict mapping agent name → ``AgentHealth`` snapshot.
        """
        ts_ms = now_ms if now_ms is not None else time.time() * 1000
        health: dict[str, AgentHealth] = {}
        for agent_name, record in self._records.items():
            self._refresh_from_redis(agent_name, record)
            age_seconds = (ts_ms - record.last_seen_ms) / 1000.0
            if age_seconds > self._interval:
                record.missed_count += 1
                logger.warning(
                    "heartbeat_missed",
                    agent=agent_name,
                    missed_count=record.missed_count,
                    age_seconds=age_seconds,
                )
                if record.missed_count >= self._max_misses:
                    self._trigger_kill(agent_name, record.missed_count)
            else:
                record.missed_count = 0

            is_healthy = record.missed_count < self._max_misses
            health[agent_name] = AgentHealth(
                agent_name=agent_name,
                is_healthy=is_healthy,
                last_seen_ms=record.last_seen_ms,
                missed_count=record.missed_count,
                age_seconds=age_seconds,
            )
        return health

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_from_redis(
        self, agent_name: str, record: HeartbeatRecord
    ) -> None:
        """Pull latest heartbeat timestamp from Redis if newer than in-process state.

        Args:
            agent_name: Agent to refresh.
            record: In-process record to update.
        """
        if self._redis is None:
            return
        redis_key = f"{MONITOR_HEARTBEAT_REDIS_KEY_PREFIX}:{agent_name}"
        try:
            raw = self._redis.get(redis_key)
            if raw is None:
                return
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            ts_ms = float(text)
            if ts_ms > record.last_seen_ms:
                record.last_seen_ms = ts_ms
                record.missed_count = 0
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "heartbeat_redis_read_failed", agent=agent_name, error=str(exc)
            )

    def _trigger_kill(self, agent_name: str, missed: int) -> None:
        """Invoke the Tier 3 kill switch for a crashed agent.

        Args:
            agent_name: Agent whose heartbeat was lost.
            missed: Number of consecutive misses.
        """
        reason = (
            f"Tier 3: agent '{agent_name}' missed {missed} consecutive heartbeats"
        )
        logger.error(
            "heartbeat_tier3_kill_triggered",
            agent=agent_name,
            missed=missed,
        )
        if self._kill_switch is not None:
            try:
                self._kill_switch.trigger_tier3(reason=reason)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "heartbeat_kill_switch_failed",
                    agent=agent_name,
                    error=str(exc),
                )
