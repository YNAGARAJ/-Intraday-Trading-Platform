"""Tests for M19 MonitorAgent."""

from __future__ import annotations

import json
import time

from prometheus_client import CollectorRegistry

from shared.monitor.agent import MonitorAgent
from shared.monitor.heartbeat import HeartbeatChecker
from shared.monitor.metrics import PrometheusMetrics
from shared.monitor.models import MonitorSnapshot
from shared.monitor.pnl_tracker import PnLTracker


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None

    def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        entries = self._streams.get(name, [])
        result = [
            (eid.encode(), {k.encode(): v.encode() for k, v in fields.items()})
            for eid, fields in reversed(entries)
        ]
        if count is not None:
            result = result[:count]
        return result

    def xadd(self, name: str, fields: dict[str, str]) -> bytes:
        self._streams.setdefault(name, []).append(("0-0", fields))
        return b"0-0"


class _FakeKillSwitch:
    def __init__(self) -> None:
        self.triggered = False

    def trigger_tier3(self, reason: str, redis_client: object = None) -> None:
        self.triggered = True


def _make_agent(
    r: _FakeRedis | None = None,
    ks: _FakeKillSwitch | None = None,
    capital: float = 1_000_000.0,
    interval: int = 30,
    hb_interval: int = 30,
    max_misses: int = 2,
) -> MonitorAgent:
    redis = r or _FakeRedis()
    hb = HeartbeatChecker(
        redis_client=redis,
        kill_switch=ks,
        interval_seconds=hb_interval,
        max_misses=max_misses,
    )
    pm = PrometheusMetrics(registry=CollectorRegistry())
    pnl = PnLTracker(redis_client=redis, starting_capital=capital)
    return MonitorAgent(pnl, hb, pm, poll_interval_seconds=interval)


class TestMonitorAgentPollOnce:
    def test_returns_monitor_snapshot(self) -> None:
        agent = _make_agent()
        snap = agent.poll_once()
        assert isinstance(snap, MonitorSnapshot)

    def test_timestamp_set_correctly(self) -> None:
        now_ms = time.time() * 1000
        agent = _make_agent()
        snap = agent.poll_once(now_ms=now_ms)
        assert snap.timestamp_ms == now_ms

    def test_zero_pnl_when_no_redis_data(self) -> None:
        agent = _make_agent()
        snap = agent.poll_once()
        assert snap.pnl.pnl_today == 0.0

    def test_reads_orchestrator_state_positions(self) -> None:
        r = _FakeRedis()
        state = {"open_positions": {"RELIANCE": {}, "INFY": {}}, "signals_today": 5}
        r.set("orchestrator:state", json.dumps(state))
        agent = _make_agent(r=r)
        snap = agent.poll_once()
        assert snap.open_positions_count == 2
        assert snap.signals_today == 5

    def test_reconciliation_mismatches_from_stream(self) -> None:
        r = _FakeRedis()
        r.xadd("reconciliation:mismatches", {"type": "pos"})
        r.xadd("reconciliation:mismatches", {"type": "ord"})
        agent = _make_agent(r=r)
        snap = agent.poll_once()
        assert snap.reconciliation_mismatches == 2

    def test_system_halted_when_key_present(self) -> None:
        r = _FakeRedis()
        r.set("system:status:halted", "1")
        agent = _make_agent(r=r)
        snap = agent.poll_once()
        assert snap.system_halted is True

    def test_system_halted_when_circuit_breaker_fires(self) -> None:
        from datetime import datetime, timezone
        r = _FakeRedis()
        today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        r.set(f"risk:daily:pnl:{today}", "-25000.0")
        agent = _make_agent(r=r, capital=1_000_000.0)
        snap = agent.poll_once()
        assert snap.system_halted is True
        assert snap.pnl.is_circuit_breaker is True

    def test_poll_updates_last_snapshot(self) -> None:
        agent = _make_agent()
        assert agent.get_last_snapshot() is None
        agent.poll_once()
        assert agent.get_last_snapshot() is not None


class TestRegisterHeartbeat:
    def test_register_heartbeat_proxies_to_checker(self) -> None:
        r = _FakeRedis()
        agent = _make_agent(r=r)
        now_ms = time.time() * 1000
        agent.register_heartbeat("signal_agent", now_ms=now_ms)
        raw = r.get("monitor:heartbeat:signal_agent")
        assert raw is not None

    def test_heartbeat_reflected_in_poll_health(self) -> None:
        r = _FakeRedis()
        agent = _make_agent(r=r)
        now_ms = time.time() * 1000
        agent._hb.add_watched_agent("signal_agent")
        agent.register_heartbeat("signal_agent", now_ms=now_ms)
        snap = agent.poll_once(now_ms=now_ms + 5_000)
        assert snap.agent_health["signal_agent"].is_healthy is True


class TestKillSwitchViaPoll:
    def test_poll_triggers_kill_after_consecutive_misses(self) -> None:
        ks = _FakeKillSwitch()
        r = _FakeRedis()
        now_ms = time.time() * 1000
        hb = HeartbeatChecker(
            redis_client=r, kill_switch=ks, interval_seconds=30, max_misses=2
        )
        hb.add_watched_agent("data_agent")
        hb.register_heartbeat("data_agent", now_ms=now_ms)
        pm = PrometheusMetrics(registry=CollectorRegistry())
        pnl = PnLTracker(redis_client=r)
        agent = MonitorAgent(pnl, hb, pm)
        agent.poll_once(now_ms=now_ms + 45_000)
        agent.poll_once(now_ms=now_ms + 90_000)
        assert ks.triggered is True


class TestLifecycle:
    def test_starts_and_stops_cleanly(self) -> None:
        agent = _make_agent(interval=3600)
        agent.start()
        assert agent.is_running() is True
        agent.stop(timeout=2.0)
        assert agent.is_running() is False

    def test_double_start_is_safe(self) -> None:
        agent = _make_agent(interval=3600)
        agent.start()
        agent.start()  # should not raise or create second thread
        assert agent.is_running() is True
        agent.stop(timeout=2.0)

    def test_stop_without_start_is_safe(self) -> None:
        agent = _make_agent(interval=3600)
        agent.stop(timeout=1.0)  # should not raise
