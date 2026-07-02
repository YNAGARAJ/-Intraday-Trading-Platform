"""Tests for M19 HeartbeatChecker."""

from __future__ import annotations

import time

from shared.monitor.heartbeat import HeartbeatChecker


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None


class _FakeKillSwitch:
    def __init__(self) -> None:
        self.triggered = False
        self.reason: str = ""

    def trigger_tier3(self, reason: str, redis_client: object = None) -> None:
        self.triggered = True
        self.reason = reason


class TestHeartbeatCheckerBasics:
    def test_empty_watch_list_returns_empty(self) -> None:
        checker = HeartbeatChecker()
        assert checker.check_all() == {}

    def test_add_watched_agent_adds_to_records(self) -> None:
        checker = HeartbeatChecker()
        checker.add_watched_agent("sig")
        assert "sig" in checker._records

    def test_add_same_agent_twice_is_idempotent(self) -> None:
        checker = HeartbeatChecker()
        checker.add_watched_agent("sig")
        checker.add_watched_agent("sig")
        assert len(checker._records) == 1

    def test_register_heartbeat_adds_agent_if_not_watched(self) -> None:
        checker = HeartbeatChecker()
        checker.register_heartbeat("new_agent")
        assert "new_agent" in checker._records

    def test_register_heartbeat_resets_missed_count(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30, max_misses=2)
        checker.add_watched_agent("sig")
        checker.register_heartbeat("sig", now_ms=now_ms)
        checker.check_all(now_ms=now_ms + 45_000)  # 1 miss
        checker.register_heartbeat("sig", now_ms=now_ms + 60_000)
        health = checker.check_all(now_ms=now_ms + 65_000)
        assert health["sig"].missed_count == 0


class TestHeartbeatFreshness:
    def test_fresh_heartbeat_is_healthy(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30)
        checker.add_watched_agent("sig")
        checker.register_heartbeat("sig", now_ms=now_ms)
        health = checker.check_all(now_ms=now_ms + 5_000)
        assert health["sig"].is_healthy is True
        assert health["sig"].missed_count == 0

    def test_age_seconds_correct(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30)
        checker.add_watched_agent("sig")
        checker.register_heartbeat("sig", now_ms=now_ms)
        health = checker.check_all(now_ms=now_ms + 10_000)
        assert abs(health["sig"].age_seconds - 10.0) < 0.01

    def test_stale_heartbeat_increments_missed_count(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30, max_misses=3)
        checker.add_watched_agent("data")
        checker.register_heartbeat("data", now_ms=now_ms)
        health = checker.check_all(now_ms=now_ms + 45_000)
        assert health["data"].missed_count == 1
        assert health["data"].is_healthy is True  # below threshold

    def test_two_consecutive_misses_unhealthy(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30, max_misses=2)
        checker.add_watched_agent("sig")
        checker.register_heartbeat("sig", now_ms=now_ms)
        checker.check_all(now_ms=now_ms + 45_000)  # miss 1
        health = checker.check_all(now_ms=now_ms + 90_000)  # miss 2
        assert health["sig"].missed_count == 2
        assert health["sig"].is_healthy is False

    def test_multiple_agents_independently_tracked(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30, max_misses=2)
        checker.add_watched_agent("sig")
        checker.add_watched_agent("risk")
        checker.register_heartbeat("sig", now_ms=now_ms)
        checker.register_heartbeat("risk", now_ms=now_ms)
        # Only sig goes stale
        checker.register_heartbeat("risk", now_ms=now_ms + 40_000)
        health = checker.check_all(now_ms=now_ms + 50_000)
        assert health["sig"].missed_count == 1
        assert health["risk"].missed_count == 0


class TestKillSwitchTrigger:
    def test_triggers_at_max_misses(self) -> None:
        ks = _FakeKillSwitch()
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(
            interval_seconds=30, max_misses=2, kill_switch=ks
        )
        checker.add_watched_agent("signal_agent")
        checker.register_heartbeat("signal_agent", now_ms=now_ms)
        checker.check_all(now_ms=now_ms + 45_000)  # miss 1
        checker.check_all(now_ms=now_ms + 90_000)  # miss 2 → trigger
        assert ks.triggered is True
        assert "signal_agent" in ks.reason

    def test_no_kill_switch_without_injected_trigger(self) -> None:
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(interval_seconds=30, max_misses=2)
        checker.add_watched_agent("sig")
        checker.register_heartbeat("sig", now_ms=now_ms)
        checker.check_all(now_ms=now_ms + 45_000)
        checker.check_all(now_ms=now_ms + 90_000)
        # No exception raised even without kill switch

    def test_kill_switch_called_on_each_check_at_or_above_threshold(self) -> None:
        ks = _FakeKillSwitch()
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(
            interval_seconds=30, max_misses=1, kill_switch=ks
        )
        checker.add_watched_agent("sig")
        checker.register_heartbeat("sig", now_ms=now_ms)
        checker.check_all(now_ms=now_ms + 45_000)  # miss 1 ≥ max_misses=1
        assert ks.triggered is True

    def test_reason_contains_missed_count(self) -> None:
        ks = _FakeKillSwitch()
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(
            interval_seconds=30, max_misses=2, kill_switch=ks
        )
        checker.add_watched_agent("risk_agent")
        checker.register_heartbeat("risk_agent", now_ms=now_ms)
        checker.check_all(now_ms=now_ms + 45_000)
        checker.check_all(now_ms=now_ms + 90_000)
        assert "2" in ks.reason


class TestRedisIntegration:
    def test_register_heartbeat_writes_to_redis(self) -> None:
        r = _FakeRedis()
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(redis_client=r)
        checker.register_heartbeat("sig", now_ms=now_ms)
        raw = r.get("monitor:heartbeat:sig")
        assert raw is not None
        assert abs(float(raw.decode()) - now_ms) < 1.0

    def test_refresh_from_redis_on_check(self) -> None:
        r = _FakeRedis()
        now_ms = time.time() * 1000
        checker = HeartbeatChecker(redis_client=r, interval_seconds=30)
        checker.add_watched_agent("sig")
        # Record old last_seen in process
        checker._records["sig"].last_seen_ms = now_ms - 60_000
        # But Redis has a fresh timestamp
        r.set("monitor:heartbeat:sig", str(now_ms - 5_000))
        health = checker.check_all(now_ms=now_ms)
        # Redis value refreshes the in-process record → healthy
        assert health["sig"].is_healthy is True
