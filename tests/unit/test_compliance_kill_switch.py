"""Unit tests for M13 KillSwitchManager (tiered kill switch)."""

from __future__ import annotations

import pytest

from shared.compliance.kill_switch import KillSwitchManager, KillSwitchTrigger
from shared.compliance.models import KillSwitchEvent


class TestKillSwitchTrigger:
    def test_all_tiers_defined(self) -> None:
        assert KillSwitchTrigger.TIER1_CIRCUIT_BREAKER
        assert KillSwitchTrigger.TIER2_EXTERNAL_API
        assert KillSwitchTrigger.TIER3_HEARTBEAT

    def test_tier_number_extraction(self) -> None:
        assert int(KillSwitchTrigger.TIER1_CIRCUIT_BREAKER.value[4]) == 1
        assert int(KillSwitchTrigger.TIER2_EXTERNAL_API.value[4]) == 2
        assert int(KillSwitchTrigger.TIER3_HEARTBEAT.value[4]) == 3


class TestKillSwitchManagerNoRedis:
    def _ks(self) -> KillSwitchManager:
        return KillSwitchManager(redis_client=None)

    def test_not_halted_initially(self) -> None:
        ks = self._ks()
        assert ks.is_halted is False

    def test_trigger_sets_halted(self) -> None:
        ks = self._ks()
        ks.trigger(KillSwitchTrigger.TIER1_CIRCUIT_BREAKER, "test")
        assert ks.is_halted is True

    def test_trigger_returns_kill_switch_event(self) -> None:
        ks = self._ks()
        ev = ks.trigger(KillSwitchTrigger.TIER1_CIRCUIT_BREAKER, "circuit breaker")
        assert isinstance(ev, KillSwitchEvent)

    def test_event_is_priority_always_true(self) -> None:
        ks = self._ks()
        ev = ks.trigger(KillSwitchTrigger.TIER2_EXTERNAL_API, "test")
        assert ev.is_priority is True

    def test_tier1_sets_correct_tier(self) -> None:
        ks = self._ks()
        ev = ks.trigger_tier1(daily_pnl_pct=-2.1)
        assert ev.tier == 1

    def test_tier2_sets_correct_tier(self) -> None:
        ks = self._ks()
        ev = ks.trigger_tier2("telegram")
        assert ev.tier == 2

    def test_tier3_sets_correct_tier(self) -> None:
        ks = self._ks()
        ev = ks.trigger_tier3("SignalAgent", 2)
        assert ev.tier == 3

    def test_last_event_stored(self) -> None:
        ks = self._ks()
        assert ks.last_event is None
        ev = ks.trigger_tier1(-2.5)
        assert ks.last_event is ev

    def test_tier1_reason_mentions_pnl(self) -> None:
        ks = self._ks()
        ev = ks.trigger_tier1(-2.3)
        assert "-2.30%" in ev.reason

    def test_tier2_reason_mentions_source(self) -> None:
        ks = self._ks()
        ev = ks.trigger_tier2("rest_api")
        assert "rest_api" in ev.reason

    def test_tier3_reason_mentions_agent(self) -> None:
        ks = self._ks()
        ev = ks.trigger_tier3("MonitorAgent", 3)
        assert "MonitorAgent" in ev.reason
        assert "3" in ev.reason

    def test_multiple_triggers_all_set_halted(self) -> None:
        ks = self._ks()
        ks.trigger_tier1(-2.1)
        ks.trigger_tier2()
        ks.trigger_tier3("A", 2)
        assert ks.is_halted is True

    def test_trigger_at_ms_is_recent(self) -> None:
        import time

        ks = self._ks()
        before = int(time.time() * 1000)
        ev = ks.trigger_tier2()
        after = int(time.time() * 1000)
        assert before <= ev.triggered_at_ms <= after


class TestKillSwitchEventValidation:
    def test_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="tier must be 1, 2, or 3"):
            KillSwitchEvent(tier=0, reason="bad", triggered_at_ms=0)

    def test_tier_5_raises(self) -> None:
        with pytest.raises(ValueError):
            KillSwitchEvent(tier=5, reason="bad", triggered_at_ms=0)


class TestKillSwitchWithMockRedis:
    class _FakeRedis:
        def __init__(self) -> None:
            self._store: dict[str, str] = {}

        def set(self, name: str, value: str) -> None:
            self._store[name] = value

        def get(self, name: str) -> bytes | None:
            v = self._store.get(name)
            return v.encode() if v is not None else None

    def test_redis_halted_set(self) -> None:
        redis = self._FakeRedis()
        ks = KillSwitchManager(redis_client=redis)
        assert ks.is_halted is False
        ks.trigger_tier1(-2.5)
        assert redis._store.get("system:status:halted") == "true"
        assert ks.is_halted is True

    def test_redis_tier_key_set(self) -> None:
        from shared.core.constants import KILL_SWITCH_TIER_KEY

        redis = self._FakeRedis()
        ks = KillSwitchManager(redis_client=redis)
        ks.trigger_tier2("test_api")
        assert redis._store.get(KILL_SWITCH_TIER_KEY) == "2"

    def test_redis_reason_key_set(self) -> None:
        from shared.core.constants import KILL_SWITCH_REASON_KEY

        redis = self._FakeRedis()
        ks = KillSwitchManager(redis_client=redis)
        ks.trigger_tier3("SignalAgent", 2)
        reason = redis._store.get(KILL_SWITCH_REASON_KEY) or ""
        assert "SignalAgent" in reason
