"""M19 VERIFY harness — 20 scenarios for the Real-Time Monitor Agent.

Run:
    python -m shared.monitor
"""

from __future__ import annotations

import time

import structlog
from prometheus_client import CollectorRegistry

from shared.monitor.agent import MonitorAgent
from shared.monitor.heartbeat import HeartbeatChecker
from shared.monitor.metrics import PrometheusMetrics
from shared.monitor.models import MonitorSnapshot, PnLSnapshot
from shared.monitor.pnl_tracker import PnLTracker

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check(label: str, condition: bool) -> bool:
    if condition:
        logger.info("VERIFY_PASS", scenario=label)
    else:
        logger.error("VERIFY_FAIL", scenario=label)
    return condition


# ---------------------------------------------------------------------------
# FakeRedis stub
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-memory Redis stub for VERIFY scenarios."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None

    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._store:
                del self._store[n]
                count += 1
        return count

    def xadd(self, name: str, fields: dict[str, str]) -> bytes:
        eid = f"{int(time.time() * 1000)}-0"
        self._streams.setdefault(name, []).append((eid, fields))
        return eid.encode()

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


# ---------------------------------------------------------------------------
# Kill switch stub
# ---------------------------------------------------------------------------


class _FakeKillSwitch:
    """In-memory kill switch stub that records trigger calls."""

    def __init__(self) -> None:
        self.triggered = False
        self.reason: str = ""

    def trigger_tier3(self, reason: str, redis_client: object = None) -> None:
        self.triggered = True
        self.reason = reason


# ---------------------------------------------------------------------------
# VERIFY scenarios
# ---------------------------------------------------------------------------


def run_verify() -> bool:
    results: list[bool] = []

    # --- S01: HeartbeatRecord initialises correctly ---
    from shared.monitor.models import HeartbeatRecord

    hb_record = HeartbeatRecord(agent_name="signal_agent", last_seen_ms=1_000_000.0)
    results.append(
        _check(
            "S01: HeartbeatRecord initialises with correct defaults",
            hb_record.agent_name == "signal_agent"
            and hb_record.last_seen_ms == 1_000_000.0
            and hb_record.missed_count == 0,
        )
    )

    # --- S02: HeartbeatChecker marks fresh heartbeat as healthy ---
    now_ms = time.time() * 1000
    checker2 = HeartbeatChecker(interval_seconds=30)
    checker2.add_watched_agent("signal_agent")
    checker2.register_heartbeat("signal_agent", now_ms=now_ms)
    health2 = checker2.check_all(now_ms=now_ms + 5_000)  # 5 s later — within 30s
    results.append(
        _check(
            "S02: fresh heartbeat (5s old) → agent is healthy",
            health2["signal_agent"].is_healthy is True
            and health2["signal_agent"].missed_count == 0,
        )
    )

    # --- S03: HeartbeatChecker detects 1 missed heartbeat (not yet at threshold) ---
    checker3 = HeartbeatChecker(interval_seconds=30, max_misses=2)
    checker3.add_watched_agent("data_agent")
    checker3.register_heartbeat("data_agent", now_ms=now_ms)
    health3 = checker3.check_all(now_ms=now_ms + 45_000)  # 45s later → 1 miss
    results.append(
        _check(
            "S03: 45s stale heartbeat → missed_count=1, still healthy (threshold=2)",
            health3["data_agent"].missed_count == 1
            and health3["data_agent"].is_healthy is True,
        )
    )

    # --- S04: HeartbeatChecker triggers kill switch at 2 consecutive misses ---
    ks4 = _FakeKillSwitch()
    checker4 = HeartbeatChecker(
        interval_seconds=30, max_misses=2, kill_switch=ks4
    )
    checker4.add_watched_agent("signal_agent")
    checker4.register_heartbeat("signal_agent", now_ms=now_ms)
    # First miss
    checker4.check_all(now_ms=now_ms + 45_000)
    # Second miss → triggers kill
    checker4.check_all(now_ms=now_ms + 90_000)
    results.append(
        _check(
            "S04: 2 consecutive misses → Tier 3 kill switch triggered (RULE 8)",
            ks4.triggered is True and "signal_agent" in ks4.reason,
        )
    )

    # --- S05: HeartbeatChecker resets miss count after recovery ---
    checker5 = HeartbeatChecker(interval_seconds=30, max_misses=2)
    checker5.add_watched_agent("risk_agent")
    checker5.register_heartbeat("risk_agent", now_ms=now_ms)
    checker5.check_all(now_ms=now_ms + 45_000)  # 1 miss
    # Agent recovers
    checker5.register_heartbeat("risk_agent", now_ms=now_ms + 60_000)
    health5 = checker5.check_all(now_ms=now_ms + 65_000)
    results.append(
        _check(
            "S05: heartbeat recovery resets missed_count to 0",
            health5["risk_agent"].missed_count == 0
            and health5["risk_agent"].is_healthy is True,
        )
    )

    # --- S06: HeartbeatChecker ignores agents not in watch list ---
    checker6 = HeartbeatChecker(interval_seconds=30)
    health6 = checker6.check_all(now_ms=now_ms)
    results.append(
        _check(
            "S06: no watched agents → check_all returns empty dict",
            health6 == {},
        )
    )

    # --- S07: PnLTracker returns zero when no Redis data ---
    pnl7 = PnLTracker(redis_client=None)
    snap7 = pnl7.snapshot()
    results.append(
        _check(
            "S07: PnLTracker with no Redis returns zero snapshot",
            snap7.pnl_today == 0.0
            and snap7.pnl_today_pct == 0.0
            and snap7.is_circuit_breaker is False,
        )
    )

    # --- S08: PnLTracker reads correct P&L from Redis ---
    from datetime import datetime, timezone

    r8 = _FakeRedis()
    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    r8.set(f"risk:daily:pnl:{today}", "-15000.0")
    pnl8 = PnLTracker(redis_client=r8, starting_capital=1_000_000.0)
    snap8 = pnl8.snapshot()
    results.append(
        _check(
            "S08: PnLTracker reads absolute P&L from Redis",
            abs(snap8.pnl_today - (-15000.0)) < 0.01,
        )
    )

    # --- S09: PnLTracker computes pnl_pct = pnl / starting_capital ---
    snap9 = snap8  # reuse: -15000 / 1_000_000 = -0.015
    results.append(
        _check(
            "S09: PnLTracker pnl_today_pct = pnl / starting_capital",
            abs(snap9.pnl_today_pct - (-0.015)) < 1e-9,
        )
    )

    # --- S10: PnLTracker.snapshot returns is_circuit_breaker=True at ≤ −2% ---
    r10 = _FakeRedis()
    r10.set(f"risk:daily:pnl:{today}", "-25000.0")  # −2.5%
    pnl10 = PnLTracker(redis_client=r10, starting_capital=1_000_000.0)
    snap10 = pnl10.snapshot()
    results.append(
        _check(
            "S10: is_circuit_breaker=True when pnl_pct ≤ -2%",
            snap10.is_circuit_breaker is True,
        )
    )

    # --- S11: PrometheusMetrics created with custom registry (no collision) ---
    reg11 = CollectorRegistry()
    pm11 = PrometheusMetrics(registry=reg11)
    results.append(
        _check(
            "S11: PrometheusMetrics instantiation with custom registry",
            pm11 is not None,
        )
    )

    # --- S12: PrometheusMetrics.update sets pnl_today_pct gauge ---
    reg12 = CollectorRegistry()
    pm12 = PrometheusMetrics(registry=reg12)
    snap12 = MonitorSnapshot(
        timestamp_ms=now_ms,
        pnl=PnLSnapshot(
            pnl_today=-20000.0,
            pnl_today_pct=-0.02,
            starting_capital=1_000_000.0,
            is_circuit_breaker=True,
        ),
    )
    pm12.update(snap12)
    results.append(
        _check(
            "S12: PrometheusMetrics.update sets pnl_today_pct gauge",
            abs(pm12.pnl_today_pct._value.get() - (-0.02)) < 1e-9,
        )
    )

    # --- S13: PrometheusMetrics.update sets reconciliation_mismatches gauge ---
    reg13 = CollectorRegistry()
    pm13 = PrometheusMetrics(registry=reg13)
    snap13 = MonitorSnapshot(
        timestamp_ms=now_ms,
        pnl=PnLSnapshot(0.0, 0.0, 1_000_000.0, False),
        reconciliation_mismatches=5,
    )
    pm13.update(snap13)
    results.append(
        _check(
            "S13: PrometheusMetrics reconciliation_mismatches gauge = 5",
            pm13.reconciliation_mismatches_total._value.get() == 5.0,
        )
    )

    # --- S14: PrometheusMetrics.update sets system_halted gauge ---
    reg14 = CollectorRegistry()
    pm14 = PrometheusMetrics(registry=reg14)
    snap14_halted = MonitorSnapshot(
        timestamp_ms=now_ms,
        pnl=PnLSnapshot(0.0, 0.0, 1_000_000.0, False),
        system_halted=True,
    )
    pm14.update(snap14_halted)
    results.append(
        _check(
            "S14: system_halted gauge = 1 when system is halted",
            pm14.system_halted._value.get() == 1.0,
        )
    )

    # --- S15: PrometheusMetrics.update sets heartbeat_age per agent label ---
    reg15 = CollectorRegistry()
    pm15 = PrometheusMetrics(registry=reg15)
    from shared.monitor.models import AgentHealth

    snap15 = MonitorSnapshot(
        timestamp_ms=now_ms,
        pnl=PnLSnapshot(0.0, 0.0, 1_000_000.0, False),
        agent_health={
            "signal_agent": AgentHealth(
                agent_name="signal_agent",
                is_healthy=True,
                last_seen_ms=now_ms - 10_000,
                missed_count=0,
                age_seconds=10.0,
            )
        },
    )
    pm15.update(snap15)
    results.append(
        _check(
            "S15: heartbeat_age_seconds gauge set per agent label",
            abs(
                pm15.heartbeat_age_seconds.labels(
                    agent_name="signal_agent"
                )._value.get()
                - 10.0
            )
            < 1e-9,
        )
    )

    # --- S16: MonitorAgent.register_heartbeat writes to Redis ---
    r16 = _FakeRedis()
    hb16 = HeartbeatChecker(redis_client=r16, interval_seconds=30)
    hb16.add_watched_agent("signal_agent")
    pm16 = PrometheusMetrics(registry=CollectorRegistry())
    pnl16 = PnLTracker(redis_client=r16)
    agent16 = MonitorAgent(pnl16, hb16, pm16)
    agent16.register_heartbeat("signal_agent", now_ms=now_ms)
    redis_key = "monitor:heartbeat:signal_agent"
    raw16 = r16.get(redis_key)
    results.append(
        _check(
            "S16: MonitorAgent.register_heartbeat writes timestamp to Redis",
            raw16 is not None,
        )
    )

    # --- S17: MonitorAgent.poll_once returns MonitorSnapshot ---
    r17 = _FakeRedis()
    hb17 = HeartbeatChecker(redis_client=r17, interval_seconds=30)
    pm17 = PrometheusMetrics(registry=CollectorRegistry())
    pnl17 = PnLTracker(redis_client=r17)
    agent17 = MonitorAgent(pnl17, hb17, pm17)
    snap17 = agent17.poll_once(now_ms=now_ms)
    results.append(
        _check(
            "S17: MonitorAgent.poll_once returns a MonitorSnapshot",
            isinstance(snap17, MonitorSnapshot)
            and snap17.timestamp_ms == now_ms,
        )
    )

    # --- S18: MonitorAgent triggers kill switch after missed heartbeats ---
    ks18 = _FakeKillSwitch()
    r18 = _FakeRedis()
    hb18 = HeartbeatChecker(
        redis_client=r18,
        kill_switch=ks18,
        interval_seconds=30,
        max_misses=2,
    )
    hb18.add_watched_agent("signal_agent")
    hb18.register_heartbeat("signal_agent", now_ms=now_ms)
    pm18 = PrometheusMetrics(registry=CollectorRegistry())
    pnl18 = PnLTracker(redis_client=r18)
    agent18 = MonitorAgent(pnl18, hb18, pm18)
    # Two poll cycles 45s apart → 2 consecutive misses → kill
    agent18.poll_once(now_ms=now_ms + 45_000)
    agent18.poll_once(now_ms=now_ms + 90_000)
    results.append(
        _check(
            "S18: MonitorAgent triggers Tier 3 kill switch after 2 missed heartbeats",
            ks18.triggered is True,
        )
    )

    # --- S19: MonitorAgent start/stop lifecycle ---
    r19 = _FakeRedis()
    hb19 = HeartbeatChecker(redis_client=r19, interval_seconds=3600)
    pm19 = PrometheusMetrics(registry=CollectorRegistry())
    pnl19 = PnLTracker(redis_client=r19)
    agent19 = MonitorAgent(pnl19, hb19, pm19, poll_interval_seconds=3600)
    agent19.start()
    started = agent19.is_running()
    agent19.stop(timeout=2.0)
    stopped = not agent19.is_running()
    results.append(
        _check(
            "S19: MonitorAgent start/stop lifecycle works correctly",
            started is True and stopped is True,
        )
    )

    # --- S20: reconciliation_mismatches surfaces correctly from stream ---
    r20 = _FakeRedis()
    r20.xadd("reconciliation:mismatches", {"type": "position"})
    r20.xadd("reconciliation:mismatches", {"type": "order"})
    r20.xadd("reconciliation:mismatches", {"type": "position"})
    pnl20 = PnLTracker(redis_client=r20)
    count20 = pnl20.read_reconciliation_mismatches()
    results.append(
        _check(
            "S20: reconciliation mismatch count from Redis stream = 3",
            count20 == 3,
        )
    )

    total = len(results)
    passed = sum(results)
    logger.info("VERIFY_SUMMARY", passed=passed, total=total)
    return passed == total
