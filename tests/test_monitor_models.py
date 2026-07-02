"""Tests for M19 monitor data models."""

from __future__ import annotations

from shared.monitor.models import (
    AgentHealth,
    HeartbeatRecord,
    MonitorSnapshot,
    PnLSnapshot,
)


class TestHeartbeatRecord:
    def test_defaults(self) -> None:
        r = HeartbeatRecord(agent_name="sig", last_seen_ms=1_000.0)
        assert r.agent_name == "sig"
        assert r.last_seen_ms == 1_000.0
        assert r.missed_count == 0

    def test_explicit_missed_count(self) -> None:
        r = HeartbeatRecord(agent_name="sig", last_seen_ms=1_000.0, missed_count=2)
        assert r.missed_count == 2


class TestAgentHealth:
    def test_healthy_agent(self) -> None:
        h = AgentHealth(
            agent_name="sig",
            is_healthy=True,
            last_seen_ms=1_000.0,
            missed_count=0,
            age_seconds=5.0,
        )
        assert h.is_healthy is True
        assert h.age_seconds == 5.0

    def test_unhealthy_agent(self) -> None:
        h = AgentHealth(
            agent_name="sig",
            is_healthy=False,
            last_seen_ms=1_000.0,
            missed_count=2,
            age_seconds=90.0,
        )
        assert h.is_healthy is False
        assert h.missed_count == 2


class TestPnLSnapshot:
    def test_circuit_breaker_on(self) -> None:
        s = PnLSnapshot(
            pnl_today=-25_000.0,
            pnl_today_pct=-0.025,
            starting_capital=1_000_000.0,
            is_circuit_breaker=True,
        )
        assert s.is_circuit_breaker is True
        assert s.pnl_today_pct < -0.02

    def test_no_circuit_breaker(self) -> None:
        s = PnLSnapshot(
            pnl_today=10_000.0,
            pnl_today_pct=0.01,
            starting_capital=1_000_000.0,
            is_circuit_breaker=False,
        )
        assert s.is_circuit_breaker is False


class TestMonitorSnapshot:
    def test_defaults(self) -> None:
        pnl = PnLSnapshot(0.0, 0.0, 1_000_000.0, False)
        s = MonitorSnapshot(timestamp_ms=12345.0, pnl=pnl)
        assert s.timestamp_ms == 12345.0
        assert s.agent_health == {}
        assert s.open_positions_count == 0
        assert s.signals_today == 0
        assert s.reconciliation_mismatches == 0
        assert s.system_halted is False

    def test_with_agent_health(self) -> None:
        pnl = PnLSnapshot(0.0, 0.0, 1_000_000.0, False)
        health = {
            "sig": AgentHealth("sig", True, 1000.0, 0, 5.0)
        }
        s = MonitorSnapshot(timestamp_ms=1.0, pnl=pnl, agent_health=health)
        assert "sig" in s.agent_health
