"""Tests for M19 PrometheusMetrics."""

from __future__ import annotations

import time

from prometheus_client import CollectorRegistry

from shared.monitor.metrics import PrometheusMetrics
from shared.monitor.models import AgentHealth, MonitorSnapshot, PnLSnapshot


def _pnl(
    pct: float = 0.0,
    abs_: float = 0.0,
    capital: float = 1_000_000.0,
    cb: bool = False,
) -> PnLSnapshot:
    return PnLSnapshot(
        pnl_today=abs_,
        pnl_today_pct=pct,
        starting_capital=capital,
        is_circuit_breaker=cb,
    )


def _snap(
    pnl: PnLSnapshot | None = None,
    agent_health: dict[str, AgentHealth] | None = None,
    positions: int = 0,
    signals: int = 0,
    mismatches: int = 0,
    halted: bool = False,
) -> MonitorSnapshot:
    return MonitorSnapshot(
        timestamp_ms=time.time() * 1000,
        pnl=pnl or _pnl(),
        agent_health=agent_health or {},
        open_positions_count=positions,
        signals_today=signals,
        reconciliation_mismatches=mismatches,
        system_halted=halted,
    )


class TestPrometheusMetricsInit:
    def test_instantiates_with_default_registry(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        assert pm is not None

    def test_auto_creates_registry(self) -> None:
        pm = PrometheusMetrics()
        assert pm._registry is not None

    def test_each_instance_has_own_registry(self) -> None:
        pm1 = PrometheusMetrics()
        pm2 = PrometheusMetrics()
        assert pm1._registry is not pm2._registry


class TestPrometheusMetricsUpdate:
    def test_pnl_today_pct_gauge(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(pnl=_pnl(pct=-0.015)))
        assert abs(pm.pnl_today_pct._value.get() - (-0.015)) < 1e-9

    def test_pnl_today_abs_gauge(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(pnl=_pnl(abs_=-15000.0)))
        assert abs(pm.pnl_today_abs._value.get() - (-15000.0)) < 0.01

    def test_open_positions_gauge(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(positions=5))
        assert pm.open_positions_count._value.get() == 5.0

    def test_signals_today_gauge(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(signals=12))
        assert pm.signals_today_total._value.get() == 12.0

    def test_reconciliation_mismatches_gauge(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(mismatches=3))
        assert pm.reconciliation_mismatches_total._value.get() == 3.0

    def test_system_halted_gauge_true(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(halted=True))
        assert pm.system_halted._value.get() == 1.0

    def test_system_halted_gauge_false(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(halted=False))
        assert pm.system_halted._value.get() == 0.0

    def test_heartbeat_age_per_agent_label(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        health = {
            "signal_agent": AgentHealth(
                agent_name="signal_agent",
                is_healthy=True,
                last_seen_ms=1000.0,
                missed_count=0,
                age_seconds=15.0,
            )
        }
        pm.update(_snap(agent_health=health))
        val = pm.heartbeat_age_seconds.labels(agent_name="signal_agent")._value.get()
        assert abs(val - 15.0) < 1e-9

    def test_multiple_agent_labels(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        health = {
            "sig": AgentHealth("sig", True, 1000.0, 0, 5.0),
            "risk": AgentHealth("risk", True, 1000.0, 0, 20.0),
        }
        pm.update(_snap(agent_health=health))
        assert pm.heartbeat_age_seconds.labels(agent_name="sig")._value.get() == 5.0
        assert pm.heartbeat_age_seconds.labels(agent_name="risk")._value.get() == 20.0

    def test_update_overwrites_previous_value(self) -> None:
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pm.update(_snap(signals=5))
        pm.update(_snap(signals=9))
        assert pm.signals_today_total._value.get() == 9.0
