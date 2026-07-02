"""Tests for M18 OrchestratorGraph — cycle, HITL, kill switch preemption, shutdown."""

from __future__ import annotations

from shared.orchestrator.graph import OrchestratorGraph
from shared.orchestrator.state import make_initial_state

# ---------------------------------------------------------------------------
# FakeRedis stub
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None

    def delete(self, *names: str) -> int:
        return 0

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        id: str = "*",
        maxlen: int | None = None,
    ) -> bytes:
        entry_id = f"0-{len(self._streams.get(name, []))}"
        self._streams.setdefault(name, []).append((entry_id, fields))
        return entry_id.encode()

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
# Graph construction tests
# ---------------------------------------------------------------------------


class TestOrchestratorGraphConstruction:
    def test_constructs_without_error(self) -> None:
        orch = OrchestratorGraph()
        assert orch is not None

    def test_default_state_not_halted(self) -> None:
        orch = OrchestratorGraph()
        assert not orch.is_halted()

    def test_get_state_returns_typed_dict(self) -> None:
        orch = OrchestratorGraph()
        state = orch.get_state()
        assert "kill_switch_active" in state
        assert "signals_today" in state


# ---------------------------------------------------------------------------
# Clean cycle tests
# ---------------------------------------------------------------------------


class TestOrchestratorCleanCycle:
    def test_clean_cycle_returns_state(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        result = orch.run_cycle(make_initial_state("2026-07-02"))
        assert result is not None

    def test_clean_cycle_no_kill_switch(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        result = orch.run_cycle(make_initial_state())
        assert result is not None
        assert not result["kill_switch_active"]

    def test_cycle_with_signal_increments_count(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        orch = OrchestratorGraph(redis_client=r, enable_hitl=False)
        result = orch.run_cycle(make_initial_state())
        assert result is not None
        assert result["signals_today"] == 1

    def test_second_cycle_uses_previous_state(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        orch = OrchestratorGraph(redis_client=r, enable_hitl=False)
        first = orch.run_cycle(make_initial_state())
        assert first is not None
        # Add second signal
        r.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})
        second = orch.run_cycle(first)
        assert second is not None
        # second cycle should see signals_today >= 1 from previous
        assert second["signals_today"] >= 1


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_circuit_breaker_activates_at_minus_2_pct(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        state = make_initial_state()
        state["pnl_today_pct"] = -0.02
        result = orch.run_cycle(state)
        assert result is not None
        assert result["circuit_breaker_active"] is True

    def test_circuit_breaker_sets_is_halted(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        state = make_initial_state()
        state["pnl_today_pct"] = -0.025
        orch.run_cycle(state)
        assert orch.is_halted()


# ---------------------------------------------------------------------------
# HIGH_VOL_CHAOS tests (RULE 2)
# ---------------------------------------------------------------------------


class TestHighVolChaos:
    def test_high_vol_chaos_blocks_signals(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})
        orch = OrchestratorGraph(redis_client=r, enable_hitl=False)
        state = make_initial_state()
        state["market_regime"] = "HIGH_VOL_CHAOS"
        result = orch.run_cycle(state)
        assert result is not None
        assert result["signals_today"] == 0


# ---------------------------------------------------------------------------
# HITL interrupt tests
# ---------------------------------------------------------------------------


class TestHITLInterrupt:
    def test_large_position_triggers_hitl_interrupt(self) -> None:
        orch = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=True)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}  # 75% of capital
        }
        result = orch.run_cycle(state)
        # Interrupted → None
        assert result is None

    def test_hitl_checkpoint_has_pending_approval(self) -> None:
        orch = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=True)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
        }
        orch.run_cycle(state)
        cp = orch._app.get_state(orch._thread_config)
        assert cp.values.get("pending_hitl_approval") is not None

    def test_approve_hitl_resumes_and_clears_approval(self) -> None:
        orch = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=True)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
        }
        orch.run_cycle(state)
        approved = orch.approve_hitl()
        # After approval, pending_hitl_approval should be cleared
        assert approved is not None
        assert approved["pending_hitl_approval"] is None

    def test_reject_hitl_clears_approval(self) -> None:
        orch = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=True)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
        }
        orch.run_cycle(state)
        orch.reject_hitl()
        final = orch.get_state()
        assert final["pending_hitl_approval"] is None

    def test_hitl_disabled_does_not_interrupt(self) -> None:
        orch = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=False)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
        }
        # Key test: graph completes without blocking for HITL approval
        orch.run_cycle(state)


# ---------------------------------------------------------------------------
# Kill switch preemption tests (RULE 8)
# ---------------------------------------------------------------------------


class TestKillSwitchPreemption:
    def test_trigger_kill_switch_sets_halted(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        orch.run_cycle(make_initial_state())  # establish checkpoint first
        orch.trigger_kill_switch(reason="test")
        assert orch.is_halted()

    def test_kill_switch_preempts_pending_hitl(self) -> None:
        orch = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=True)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
        }
        orch.run_cycle(state)
        # At this point HITL is pending
        orch.trigger_kill_switch(reason="forced_kill")
        final = orch.get_state()
        # Kill switch must win — pending_hitl_approval cleared, kill switch active
        assert final["kill_switch_active"] is True
        assert final["pending_hitl_approval"] is None

    def test_kill_switch_state_persisted_after_cycle(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        orch.run_cycle(make_initial_state())  # establish checkpoint first
        orch.trigger_kill_switch(reason="test")
        state = orch.get_state()
        assert state["kill_switch_active"] is True


# ---------------------------------------------------------------------------
# Shutdown and restore tests
# ---------------------------------------------------------------------------


class TestShutdownRestore:
    def test_shutdown_without_redis_is_noop(self) -> None:
        orch = OrchestratorGraph(enable_hitl=False)
        orch.shutdown()  # should not raise

    def test_shutdown_persists_to_redis(self) -> None:
        r = _FakeRedis()
        orch = OrchestratorGraph(redis_client=r, enable_hitl=False)
        state = make_initial_state()
        state["signals_today"] = 5
        orch.run_cycle(state)
        orch.shutdown()
        assert r.get("orchestrator:state") is not None

    def test_restore_loads_state_from_redis(self) -> None:
        r = _FakeRedis()
        orch = OrchestratorGraph(redis_client=r, enable_hitl=False)
        state = make_initial_state()
        state["signals_today"] = 7
        orch.run_cycle(state)
        orch.shutdown()
        restored = OrchestratorGraph.restore(redis_client=r)
        assert restored.get_state()["signals_today"] == 7

    def test_restore_without_key_returns_fresh_state(self) -> None:
        r = _FakeRedis()
        restored = OrchestratorGraph.restore(redis_client=r)
        assert restored.get_state()["signals_today"] == 0


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


class TestRouting:
    def test_route_kill_when_kill_switch_active(self) -> None:
        state = make_initial_state()
        state["kill_switch_active"] = True
        route = OrchestratorGraph._route_after_risk(state)
        assert route == "kill"

    def test_route_kill_when_circuit_breaker_active(self) -> None:
        state = make_initial_state()
        state["circuit_breaker_active"] = True
        route = OrchestratorGraph._route_after_risk(state)
        assert route == "kill"

    def test_route_kill_wins_over_hitl(self) -> None:
        state = make_initial_state()
        state["kill_switch_active"] = True
        state["pending_hitl_approval"] = {"symbol": "X", "capital_pct": 0.9}
        route = OrchestratorGraph._route_after_risk(state)
        assert route == "kill"

    def test_route_hitl_when_pending_approval(self) -> None:
        state = make_initial_state()
        state["pending_hitl_approval"] = {"symbol": "RELIANCE", "capital_pct": 0.75}
        route = OrchestratorGraph._route_after_risk(state)
        assert route == "hitl"

    def test_route_end_when_clean(self) -> None:
        state = make_initial_state()
        route = OrchestratorGraph._route_after_risk(state)
        assert route == "end"
