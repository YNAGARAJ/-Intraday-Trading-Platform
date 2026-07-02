"""Prometheus metrics exporter for M19 Real-Time Monitor Agent.

All metrics are registered on a per-instance ``CollectorRegistry`` to allow
safe parallel use in tests (avoids "Duplicated timeseries" errors from the
default global registry).

Metrics exported:
    trading_pnl_today_pct          Gauge   Daily P&L as fraction of capital
    trading_pnl_today_abs          Gauge   Daily P&L in base currency
    trading_open_positions_count   Gauge   Number of currently open positions
    trading_signals_today_total    Gauge   Signals generated today
    trading_reconciliation_mismatches_total  Gauge  Mismatch count
    trading_system_halted          Gauge   1 = halted (kill switch / CB), 0 = live
    trading_agent_heartbeat_age_seconds  Gauge<agent>  Seconds since last heartbeat
"""

from __future__ import annotations

import structlog
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    start_http_server,
)

from shared.core.constants import PROMETHEUS_METRICS_PORT
from shared.monitor.models import MonitorSnapshot

logger = structlog.get_logger(__name__)


class PrometheusMetrics:
    """Prometheus metrics registry for the trading system.

    Each instance owns its own ``CollectorRegistry`` so that multiple instances
    can coexist in tests without duplicate-metric errors.

    Args:
        registry: Custom ``CollectorRegistry``.  ``None`` → a fresh registry
            is created automatically.
    """

    def __init__(
        self, registry: CollectorRegistry | None = None
    ) -> None:
        self._registry = registry if registry is not None else CollectorRegistry()

        self.pnl_today_pct = Gauge(
            "trading_pnl_today_pct",
            "Daily P&L as fraction of starting capital (negative = loss)",
            registry=self._registry,
        )
        self.pnl_today_abs = Gauge(
            "trading_pnl_today_abs",
            "Daily P&L in base currency",
            registry=self._registry,
        )
        self.open_positions_count = Gauge(
            "trading_open_positions_count",
            "Number of currently open positions",
            registry=self._registry,
        )
        self.signals_today_total = Gauge(
            "trading_signals_today_total",
            "Total signals generated today",
            registry=self._registry,
        )
        self.reconciliation_mismatches_total = Gauge(
            "trading_reconciliation_mismatches_total",
            "Outstanding reconciliation mismatches (broker vs internal state)",
            registry=self._registry,
        )
        self.system_halted = Gauge(
            "trading_system_halted",
            "1 when the kill switch or circuit breaker is active, 0 otherwise",
            registry=self._registry,
        )
        self.heartbeat_age_seconds = Gauge(
            "trading_agent_heartbeat_age_seconds",
            "Seconds elapsed since each monitored agent's last heartbeat",
            labelnames=["agent_name"],
            registry=self._registry,
        )

    def update(self, snapshot: MonitorSnapshot) -> None:
        """Update all Prometheus metrics from a ``MonitorSnapshot``.

        Args:
            snapshot: Current system health snapshot from ``MonitorAgent.poll_once()``.
        """
        self.pnl_today_pct.set(snapshot.pnl.pnl_today_pct)
        self.pnl_today_abs.set(snapshot.pnl.pnl_today)
        self.open_positions_count.set(snapshot.open_positions_count)
        self.signals_today_total.set(snapshot.signals_today)
        self.reconciliation_mismatches_total.set(snapshot.reconciliation_mismatches)
        self.system_halted.set(1.0 if snapshot.system_halted else 0.0)

        for agent_name, health in snapshot.agent_health.items():
            self.heartbeat_age_seconds.labels(agent_name=agent_name).set(
                health.age_seconds
            )

        logger.debug(
            "prometheus_metrics_updated",
            pnl_pct=snapshot.pnl.pnl_today_pct,
            open_positions=snapshot.open_positions_count,
            signals=snapshot.signals_today,
            mismatches=snapshot.reconciliation_mismatches,
            halted=snapshot.system_halted,
        )

    def start_http_server(self, port: int = PROMETHEUS_METRICS_PORT) -> None:
        """Start the Prometheus HTTP /metrics endpoint.

        Args:
            port: TCP port to bind.  Defaults to ``PROMETHEUS_METRICS_PORT`` (8000).
        """
        start_http_server(port=port, registry=self._registry)
        logger.info("prometheus_http_server_started", port=port)
