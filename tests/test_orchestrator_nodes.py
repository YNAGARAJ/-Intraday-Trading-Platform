"""Tests for M18 orchestrator node functions."""

from __future__ import annotations

from shared.orchestrator.nodes import (
    make_hitl_node,
    make_kill_switch_node,
    make_reconciliation_node,
    make_regime_node,
    make_risk_node,
    make_signal_node,
)
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
# regime_node tests
# ---------------------------------------------------------------------------


class TestRegimeNode:
    def test_no_redis_returns_empty(self) -> None:
        fn = make_regime_node(redis_client=None)
        result = fn(make_initial_state())
        assert result == {}

    def test_reads_regime_from_stream(self) -> None:
        r = _FakeRedis()
        r.xadd("regime:changes", {"regime": "BULL_TREND", "confidence": "0.9"})
        fn = make_regime_node(redis_client=r)
        result = fn(make_initial_state())
        assert result.get("market_regime") == "BULL_TREND"
        conf = result.get("regime_confidence", 0)
        assert abs(float(conf) - 0.9) < 1e-9  # type: ignore[arg-type]

    def test_empty_stream_returns_empty(self) -> None:
        r = _FakeRedis()
        fn = make_regime_node(redis_client=r)
        result = fn(make_initial_state())
        assert result == {}

    def test_bad_confidence_defaults_zero(self) -> None:
        r = _FakeRedis()
        r.xadd("regime:changes", {"regime": "BEAR_TREND", "confidence": "not_a_float"})
        fn = make_regime_node(redis_client=r)
        result = fn(make_initial_state())
        assert result.get("regime_confidence") == 0.0


# ---------------------------------------------------------------------------
# signal_node tests
# ---------------------------------------------------------------------------


class TestSignalNode:
    def test_no_redis_returns_empty(self) -> None:
        fn = make_signal_node(redis_client=None)
        result = fn(make_initial_state())
        assert result == {}

    def test_consumes_signal_increments_counter(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})
        fn = make_signal_node(redis_client=r)
        state = make_initial_state()
        result = fn(state)
        assert result.get("signals_today") == 1

    def test_high_vol_chaos_blocks_signal(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        fn = make_signal_node(redis_client=r)
        state = make_initial_state()
        state["market_regime"] = "HIGH_VOL_CHAOS"
        result = fn(state)
        assert result == {}

    def test_kill_switch_blocks_signal(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        fn = make_signal_node(redis_client=r)
        state = make_initial_state()
        state["kill_switch_active"] = True
        result = fn(state)
        assert result == {}

    def test_circuit_breaker_blocks_signal(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        fn = make_signal_node(redis_client=r)
        state = make_initial_state()
        state["circuit_breaker_active"] = True
        result = fn(state)
        assert result == {}

    def test_redis_halt_key_blocks_and_sets_flag(self) -> None:
        r = _FakeRedis()
        r.set("system:status:halted", "1")
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        fn = make_signal_node(redis_client=r)
        result = fn(make_initial_state())
        assert result.get("kill_switch_active") is True

    def test_degraded_key_blocks_entries(self) -> None:
        r = _FakeRedis()
        r.set("system:status:degraded", "1")
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})
        fn = make_signal_node(redis_client=r)
        result = fn(make_initial_state())
        assert result == {}

    def test_reconciliation_block_prevents_signal(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})

        def _blocked(symbol: str, exchange: str) -> bool:
            return symbol == "RELIANCE" and exchange == "NSE"

        fn = make_signal_node(redis_client=r, reconciliation_blocked_fn=_blocked)
        result = fn(make_initial_state())
        assert result == {}

    def test_reconciliation_block_passes_unblocked_symbol(self) -> None:
        r = _FakeRedis()
        r.xadd("signals:generated", {"symbol": "INFY", "exchange": "NSE"})

        def _blocked(symbol: str, exchange: str) -> bool:
            return symbol == "RELIANCE"  # only RELIANCE blocked

        fn = make_signal_node(redis_client=r, reconciliation_blocked_fn=_blocked)
        state = make_initial_state()
        result = fn(state)
        assert result.get("signals_today") == 1

    def test_empty_stream_returns_empty(self) -> None:
        r = _FakeRedis()
        fn = make_signal_node(redis_client=r)
        result = fn(make_initial_state())
        assert result == {}


# ---------------------------------------------------------------------------
# reconciliation_node tests
# ---------------------------------------------------------------------------


class TestReconciliationNode:
    def test_no_redis_sets_timestamp(self) -> None:
        fn = make_reconciliation_node(redis_client=None)
        result = fn(make_initial_state())
        assert "last_reconciliation_at" in result

    def test_empty_mismatch_stream_sets_zero(self) -> None:
        r = _FakeRedis()
        fn = make_reconciliation_node(redis_client=r)
        result = fn(make_initial_state())
        assert result.get("reconciliation_mismatches_today") == 0

    def test_mismatch_stream_entries_counted(self) -> None:
        r = _FakeRedis()
        r.xadd("reconciliation:mismatches", {"type": "position"})
        r.xadd("reconciliation:mismatches", {"type": "order"})
        fn = make_reconciliation_node(redis_client=r)
        result = fn(make_initial_state())
        assert result.get("reconciliation_mismatches_today") == 2

    def test_does_not_decrease_existing_count(self) -> None:
        r = _FakeRedis()
        r.xadd("reconciliation:mismatches", {"type": "position"})
        fn = make_reconciliation_node(redis_client=r)
        state = make_initial_state()
        state["reconciliation_mismatches_today"] = 10
        result = fn(state)
        assert result.get("reconciliation_mismatches_today") == 10


# ---------------------------------------------------------------------------
# risk_node tests
# ---------------------------------------------------------------------------


class TestRiskNode:
    def test_no_positions_no_changes(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        result = fn(make_initial_state())
        assert result == {}

    def test_circuit_breaker_at_minus_2_pct(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        state = make_initial_state()
        state["pnl_today_pct"] = -0.02
        result = fn(state)
        assert result.get("circuit_breaker_active") is True

    def test_circuit_breaker_at_minus_2_point_5_pct(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        state = make_initial_state()
        state["pnl_today_pct"] = -0.025
        result = fn(state)
        assert result.get("circuit_breaker_active") is True

    def test_no_circuit_breaker_at_minus_1_pct(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        state = make_initial_state()
        state["pnl_today_pct"] = -0.01
        result = fn(state)
        assert not result.get("circuit_breaker_active")

    def test_hitl_triggered_for_large_position(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        state = make_initial_state()
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}  # 75 000 → 75%
        }
        result = fn(state)
        assert result.get("pending_hitl_approval") is not None
        assert result["pending_hitl_approval"]["symbol"] == "RELIANCE"  # type: ignore[index]

    def test_no_hitl_for_small_position(self) -> None:
        fn = make_risk_node(starting_capital=1_000_000.0)
        state = make_initial_state()
        state["open_positions"] = {
            "INFY": {"quantity": 1, "avg_price": 1800.0}  # 1 800 / 1 000 000 = 0.18%
        }
        result = fn(state)
        assert result.get("pending_hitl_approval") is None

    def test_no_hitl_when_kill_already_active(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        state = make_initial_state()
        state["kill_switch_active"] = True
        state["open_positions"] = {
            "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
        }
        result = fn(state)
        assert result == {}

    def test_circuit_breaker_error_context_logged(self) -> None:
        fn = make_risk_node(starting_capital=100_000.0)
        state = make_initial_state()
        state["pnl_today_pct"] = -0.03
        result = fn(state)
        assert result.get("last_error_agent") == "risk_node"


# ---------------------------------------------------------------------------
# hitl_node tests
# ---------------------------------------------------------------------------


class TestHitlNode:
    def test_clears_pending_approval(self) -> None:
        fn = make_hitl_node()
        state = make_initial_state()
        state["pending_hitl_approval"] = {"symbol": "RELIANCE", "capital_pct": 0.75}
        result = fn(state)
        assert result.get("pending_hitl_approval") is None

    def test_noop_when_no_pending_approval(self) -> None:
        fn = make_hitl_node()
        state = make_initial_state()
        result = fn(state)
        assert result.get("pending_hitl_approval") is None


# ---------------------------------------------------------------------------
# kill_switch_node tests
# ---------------------------------------------------------------------------


class TestKillSwitchNode:
    def test_sets_kill_switch_active(self) -> None:
        fn = make_kill_switch_node(redis_client=None)
        result = fn(make_initial_state())
        assert result.get("kill_switch_active") is True

    def test_clears_pending_hitl(self) -> None:
        fn = make_kill_switch_node(redis_client=None)
        state = make_initial_state()
        state["pending_hitl_approval"] = {"symbol": "RELIANCE", "capital_pct": 0.75}
        result = fn(state)
        assert result.get("pending_hitl_approval") is None

    def test_sets_error_context(self) -> None:
        fn = make_kill_switch_node(redis_client=None)
        result = fn(make_initial_state())
        assert result.get("last_error") == "Kill switch activated"
        assert result.get("last_error_agent") == "kill_switch_node"
        assert result.get("last_error_at") is not None
