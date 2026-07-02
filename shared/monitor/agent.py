"""MonitorAgent — Real-Time Monitor Agent for M19.

Wires together P&L tracking, heartbeat checking, and Prometheus metrics into
a periodic background polling loop.

Polling cycle (every ``poll_interval_seconds``):
1. Read P&L from Redis via ``PnLTracker``.
2. Read system halt state from Redis.
3. Read open-position count and signal count from orchestrator state blob.
4. Count reconciliation mismatches from Redis stream.
5. Check all agent heartbeats via ``HeartbeatChecker``
   (triggers Tier 3 kill switch if threshold exceeded — see RULE 8).
6. Build a ``MonitorSnapshot`` and push to ``PrometheusMetrics``.
"""

from __future__ import annotations

import threading
import time

import structlog

from shared.core.constants import MONITOR_POLL_INTERVAL_SECONDS
from shared.monitor.heartbeat import HeartbeatChecker
from shared.monitor.metrics import PrometheusMetrics
from shared.monitor.models import MonitorSnapshot
from shared.monitor.pnl_tracker import PnLTracker

logger = structlog.get_logger(__name__)


class MonitorAgent:
    """Background polling agent for real-time system health monitoring.

    Args:
        pnl_tracker: ``PnLTracker`` instance for reading P&L state.
        heartbeat_checker: ``HeartbeatChecker`` for agent liveness monitoring.
        metrics: ``PrometheusMetrics`` instance to update on each cycle.
        poll_interval_seconds: Seconds between poll cycles.
    """

    def __init__(
        self,
        pnl_tracker: PnLTracker,
        heartbeat_checker: HeartbeatChecker,
        metrics: PrometheusMetrics,
        poll_interval_seconds: int = MONITOR_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._pnl = pnl_tracker
        self._hb = heartbeat_checker
        self._metrics = metrics
        self._poll_interval = poll_interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_snapshot: MonitorSnapshot | None = None

    def register_heartbeat(
        self,
        agent_name: str,
        now_ms: float | None = None,
    ) -> None:
        """Record a live heartbeat from an agent.

        Proxies to ``HeartbeatChecker.register_heartbeat()``.

        Args:
            agent_name: Name of the agent sending the heartbeat.
            now_ms: Override timestamp (Unix ms).  ``None`` → wall clock.
        """
        self._hb.register_heartbeat(agent_name, now_ms=now_ms)

    def poll_once(self, now_ms: float | None = None) -> MonitorSnapshot:
        """Execute one monitoring cycle and return a snapshot.

        Args:
            now_ms: Override timestamp (Unix ms) for deterministic testing.

        Returns:
            ``MonitorSnapshot`` reflecting current system state.
        """
        ts_ms = now_ms if now_ms is not None else time.time() * 1000

        pnl_snap = self._pnl.snapshot()
        system_halted = self._pnl.read_system_halted() or pnl_snap.is_circuit_breaker
        orc_state = self._pnl.read_orchestrator_state()

        open_positions_count = len(
            orc_state.get("open_positions", {})  # type: ignore[arg-type]
        )
        signals_today_raw = orc_state.get("signals_today", 0)
        signals_today = (
            int(signals_today_raw) if isinstance(signals_today_raw, int) else 0
        )
        recon_raw = orc_state.get("reconciliation_mismatches_today", 0)
        recon_from_state = int(recon_raw) if isinstance(recon_raw, int) else 0
        recon_from_stream = self._pnl.read_reconciliation_mismatches()
        reconciliation_mismatches = max(recon_from_state, recon_from_stream)

        agent_health = self._hb.check_all(now_ms=ts_ms)

        snapshot = MonitorSnapshot(
            timestamp_ms=ts_ms,
            pnl=pnl_snap,
            agent_health=agent_health,
            open_positions_count=open_positions_count,
            signals_today=signals_today,
            reconciliation_mismatches=reconciliation_mismatches,
            system_halted=system_halted,
        )
        self._metrics.update(snapshot)
        self._last_snapshot = snapshot

        logger.info(
            "monitor_agent_poll_complete",
            pnl_pct=pnl_snap.pnl_today_pct,
            positions=open_positions_count,
            signals=signals_today,
            mismatches=reconciliation_mismatches,
            halted=system_halted,
        )
        return snapshot

    def get_last_snapshot(self) -> MonitorSnapshot | None:
        """Return the most recent completed poll snapshot.

        Returns:
            Last ``MonitorSnapshot``, or ``None`` if no poll has run yet.
        """
        return self._last_snapshot

    def start(self) -> None:
        """Start the background polling thread.

        The thread runs ``poll_once()`` every ``poll_interval_seconds`` until
        ``stop()`` is called.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("monitor_agent_already_running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="monitor-agent", daemon=True
        )
        self._thread.start()
        logger.info(
            "monitor_agent_started", poll_interval=self._poll_interval
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background polling thread.

        Args:
            timeout: Seconds to wait for the thread to exit.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("monitor_agent_stopped")

    def is_running(self) -> bool:
        """Return ``True`` if the background polling thread is alive.

        Returns:
            Thread liveness status.
        """
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Background thread: poll once per interval until stopped."""
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                logger.error("monitor_agent_poll_error", error=str(exc))
            self._stop_event.wait(timeout=float(self._poll_interval))
