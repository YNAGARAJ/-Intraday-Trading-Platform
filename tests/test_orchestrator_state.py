"""Tests for M18 orchestrator state schema and helpers."""

from __future__ import annotations

from shared.orchestrator.state import (
    make_initial_state,
    state_from_json,
    state_to_json,
)


class TestMakeInitialState:
    def test_required_fields_present(self) -> None:
        s = make_initial_state("2026-07-02")
        assert s["market_date"] == "2026-07-02"
        assert s["session_state"] == "CLOSED"
        assert s["market_regime"] == "MEAN_REVERTING"
        assert s["regime_confidence"] == 0.0

    def test_safety_flags_default_false(self) -> None:
        s = make_initial_state()
        assert s["kill_switch_active"] is False
        assert s["circuit_breaker_active"] is False
        assert s["snapshot_window_active"] is False

    def test_optional_fields_default_none(self) -> None:
        s = make_initial_state()
        assert s["pending_hitl_approval"] is None
        assert s["last_reconciliation_at"] is None
        assert s["last_error"] is None
        assert s["last_error_agent"] is None
        assert s["last_error_at"] is None

    def test_counters_default_zero(self) -> None:
        s = make_initial_state()
        assert s["signals_today"] == 0
        assert s["trades_today"] == 0
        assert s["pnl_today"] == 0.0
        assert s["pnl_today_pct"] == 0.0
        assert s["ops_last_second"] == 0
        assert s["reconciliation_mismatches_today"] == 0

    def test_collections_default_empty(self) -> None:
        s = make_initial_state()
        assert s["watchlist"] == []
        assert s["open_positions"] == {}
        assert s["open_orders"] == {}
        assert s["strategy_ids"] == {}
        assert s["agent_heartbeats"] == {}

    def test_default_date_populated(self) -> None:
        s = make_initial_state()
        assert len(s["market_date"]) == 10  # YYYY-MM-DD


class TestStateSerialization:
    def test_roundtrip_preserves_strings(self) -> None:
        s = make_initial_state("2026-07-02")
        s["market_regime"] = "BULL_TREND"
        s["session_state"] = "OPEN"
        restored = state_from_json(state_to_json(s))
        assert restored["market_regime"] == "BULL_TREND"
        assert restored["session_state"] == "OPEN"

    def test_roundtrip_preserves_int_counters(self) -> None:
        s = make_initial_state()
        s["signals_today"] = 7
        s["trades_today"] = 3
        s["reconciliation_mismatches_today"] = 2
        restored = state_from_json(state_to_json(s))
        assert restored["signals_today"] == 7
        assert restored["trades_today"] == 3
        assert restored["reconciliation_mismatches_today"] == 2

    def test_roundtrip_preserves_bool_flags(self) -> None:
        s = make_initial_state()
        s["kill_switch_active"] = True
        s["circuit_breaker_active"] = True
        restored = state_from_json(state_to_json(s))
        assert restored["kill_switch_active"] is True
        assert restored["circuit_breaker_active"] is True

    def test_roundtrip_preserves_none_fields(self) -> None:
        s = make_initial_state()
        restored = state_from_json(state_to_json(s))
        assert restored["pending_hitl_approval"] is None

    def test_roundtrip_preserves_nested_dict(self) -> None:
        s = make_initial_state()
        s["open_positions"] = {"RELIANCE": {"quantity": 10, "avg_price": 2500.0}}
        restored = state_from_json(state_to_json(s))
        assert "RELIANCE" in restored["open_positions"]

    def test_state_to_json_is_string(self) -> None:
        s = make_initial_state()
        assert isinstance(state_to_json(s), str)
