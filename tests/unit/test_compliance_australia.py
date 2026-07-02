"""Unit tests for M13 Australia (ASIC) compliance checks."""

from __future__ import annotations

from datetime import datetime

from shared.compliance.australia import (
    check_layering,
    check_post_close_cutoff,
    check_short_sell,
    check_staggered_open,
    check_wash_trading,
    run_australia_checks,
)
from shared.compliance.models import OrderIntent, RecentOrder

_NOW_MS = 1_700_000_000_000  # fixed for deterministic tests
_APPROVED_SHORT = frozenset({"BHP", "CBA", "ANZ"})


def _asx(**kwargs: object) -> OrderIntent:
    defaults: dict[str, object] = {
        "symbol": "BHP",
        "exchange": "ASX",
        "direction": "LONG",
        "order_type": "LIMIT",
        "quantity": 100,
        "price": 45.0,
        "stop_loss": 43.5,
        "strategy_name": "EMA_VWAP_TREND",
        "client_order_id": "ASX-001",
        "ltp": 45.0,
        "notional_value": 4500.0,
        "capital": 100_000.0,
    }
    defaults.update(kwargs)
    return OrderIntent(**defaults)  # type: ignore[arg-type]


def _recent(symbol: str, direction: str, ms_ago: int) -> RecentOrder:
    return RecentOrder(
        symbol=symbol, direction=direction, placed_at_ms=_NOW_MS - ms_ago
    )


class TestCheckWashTrading:
    def test_opposing_within_60s_rejected(self) -> None:
        order = _asx(direction="LONG")
        recent = [_recent("BHP", "SHORT", 30_000)]  # 30s ago
        violations = check_wash_trading(order, recent, _NOW_MS)
        assert len(violations) == 1
        assert violations[0].code == "WASH_TRADING"

    def test_opposing_after_60s_passes(self) -> None:
        order = _asx(direction="LONG")
        recent = [_recent("BHP", "SHORT", 70_000)]  # 70s ago
        assert check_wash_trading(order, recent, _NOW_MS) == []

    def test_same_direction_not_wash_trade(self) -> None:
        order = _asx(direction="LONG")
        recent = [_recent("BHP", "LONG", 10_000)]
        assert check_wash_trading(order, recent, _NOW_MS) == []

    def test_different_symbol_not_wash_trade(self) -> None:
        order = _asx(direction="LONG")
        recent = [_recent("CBA", "SHORT", 10_000)]
        assert check_wash_trading(order, recent, _NOW_MS) == []

    def test_empty_recent_passes(self) -> None:
        order = _asx(direction="LONG")
        assert check_wash_trading(order, [], _NOW_MS) == []

    def test_nse_skipped(self) -> None:
        order = _asx(exchange="NSE", direction="LONG")
        recent = [_recent("NSE", "SHORT", 5_000)]
        assert check_wash_trading(order, recent, _NOW_MS) == []

    def test_exactly_at_boundary_rejected(self) -> None:
        order = _asx(direction="LONG")
        recent = [_recent("BHP", "SHORT", 60_000)]  # exactly 60s = still within window
        violations = check_wash_trading(order, recent, _NOW_MS)
        assert len(violations) == 1


class TestCheckLayering:
    def test_opposing_pending_rejected(self) -> None:
        order = _asx(direction="LONG")
        pending = [
            RecentOrder(symbol="BHP", direction="SHORT", placed_at_ms=_NOW_MS - 1000)
        ]
        violations = check_layering(order, pending)
        assert len(violations) == 1
        assert violations[0].code == "LAYERING"

    def test_same_direction_pending_passes(self) -> None:
        order = _asx(direction="LONG")
        pending = [
            RecentOrder(symbol="BHP", direction="LONG", placed_at_ms=_NOW_MS - 1000)
        ]
        assert check_layering(order, pending) == []

    def test_different_symbol_pending_passes(self) -> None:
        order = _asx(direction="LONG")
        pending = [
            RecentOrder(symbol="CBA", direction="SHORT", placed_at_ms=_NOW_MS - 1000)
        ]
        assert check_layering(order, pending) == []

    def test_empty_pending_passes(self) -> None:
        order = _asx(direction="LONG")
        assert check_layering(order, []) == []

    def test_nse_skipped(self) -> None:
        order = _asx(exchange="NSE", direction="LONG")
        pending = [RecentOrder(symbol="NSE", direction="SHORT", placed_at_ms=0)]
        assert check_layering(order, pending) == []


class TestCheckShortSell:
    def test_unapproved_symbol_rejected(self) -> None:
        order = _asx(direction="SHORT", symbol="XYZ")
        violations = check_short_sell(order, _APPROVED_SHORT)
        assert len(violations) == 1
        assert violations[0].code == "SHORT_SELL_NOT_APPROVED"

    def test_approved_symbol_passes(self) -> None:
        order = _asx(direction="SHORT", symbol="BHP")
        assert check_short_sell(order, _APPROVED_SHORT) == []

    def test_long_order_skipped(self) -> None:
        order = _asx(direction="LONG", symbol="XYZ")
        assert check_short_sell(order, _APPROVED_SHORT) == []

    def test_exit_short_skipped(self) -> None:
        order = _asx(direction="SHORT", symbol="XYZ", is_exit=True)
        assert check_short_sell(order, _APPROVED_SHORT) == []

    def test_nse_skipped(self) -> None:
        order = _asx(exchange="NSE", direction="SHORT", symbol="RELIANCE")
        assert check_short_sell(order, frozenset()) == []

    def test_empty_approved_list_rejects_all(self) -> None:
        order = _asx(direction="SHORT", symbol="BHP")
        violations = check_short_sell(order, frozenset())
        assert len(violations) == 1


class TestCheckStaggeredOpen:
    def test_within_15min_rejected(self) -> None:
        order = _asx()
        group_open_ms = _NOW_MS - (5 * 60 * 1000)  # 5 min ago
        violations = check_staggered_open(order, group_open_ms, _NOW_MS)
        assert len(violations) == 1
        assert violations[0].code == "STAGGERED_OPEN_NOISE_FILTER"

    def test_after_15min_passes(self) -> None:
        order = _asx()
        group_open_ms = _NOW_MS - (20 * 60 * 1000)  # 20 min ago
        assert check_staggered_open(order, group_open_ms, _NOW_MS) == []

    def test_exactly_15min_passes(self) -> None:
        order = _asx()
        group_open_ms = _NOW_MS - (15 * 60 * 1000)
        assert check_staggered_open(order, group_open_ms, _NOW_MS) == []

    def test_none_group_open_skipped(self) -> None:
        order = _asx()
        assert check_staggered_open(order, None, _NOW_MS) == []

    def test_exit_bypasses_filter(self) -> None:
        order = _asx(is_exit=True)
        group_open_ms = _NOW_MS - (2 * 60 * 1000)
        assert check_staggered_open(order, group_open_ms, _NOW_MS) == []

    def test_nse_skipped(self) -> None:
        order = _asx(exchange="NSE")
        group_open_ms = _NOW_MS - 1000
        assert check_staggered_open(order, group_open_ms, _NOW_MS) == []


class TestCheckPostCloseCutoff:
    _CUTOFF_BEFORE = datetime(2026, 7, 2, 16, 15, 0)
    _CUTOFF_AT = datetime(2026, 7, 2, 16, 21, 30)
    _CUTOFF_AFTER = datetime(2026, 7, 2, 16, 30, 0)

    def test_before_cutoff_passes(self) -> None:
        order = _asx()
        assert check_post_close_cutoff(order, self._CUTOFF_BEFORE) == []

    def test_at_cutoff_rejected(self) -> None:
        order = _asx()
        violations = check_post_close_cutoff(order, self._CUTOFF_AT)
        assert len(violations) == 1
        assert violations[0].code == "POST_CLOSE_CUTOFF"

    def test_after_cutoff_rejected(self) -> None:
        order = _asx()
        violations = check_post_close_cutoff(order, self._CUTOFF_AFTER)
        assert len(violations) == 1

    def test_exit_allowed_past_cutoff(self) -> None:
        order = _asx(is_exit=True)
        assert check_post_close_cutoff(order, self._CUTOFF_AFTER) == []

    def test_nse_skipped(self) -> None:
        order = _asx(exchange="NSE")
        assert check_post_close_cutoff(order, self._CUTOFF_AFTER) == []


class TestRunAustraliaChecks:
    def test_all_pass_clean_order(self) -> None:
        order = _asx(direction="LONG")
        violations = run_australia_checks(
            order=order,
            recent_orders=[],
            pending_orders=[],
            approved_short_list=_APPROVED_SHORT,
            now_ms=_NOW_MS,
        )
        assert violations == []

    def test_multiple_violations_collected(self) -> None:
        order = _asx(direction="SHORT", symbol="UNKNOWN")
        recent = [_recent("UNKNOWN", "LONG", 10_000)]
        pending = [
            RecentOrder(symbol="UNKNOWN", direction="LONG", placed_at_ms=_NOW_MS - 1000)
        ]
        violations = run_australia_checks(
            order=order,
            recent_orders=recent,
            pending_orders=pending,
            approved_short_list=frozenset(),
            now_ms=_NOW_MS,
        )
        codes = {v.code for v in violations}
        assert "WASH_TRADING" in codes
        assert "SHORT_SELL_NOT_APPROVED" in codes

    def test_post_close_with_datetime(self) -> None:
        order = _asx()
        now_aest = datetime(2026, 7, 2, 16, 30, 0)
        violations = run_australia_checks(
            order=order,
            recent_orders=[],
            pending_orders=[],
            approved_short_list=frozenset(),
            now_ms=_NOW_MS,
            now_aest=now_aest,
        )
        assert any(v.code == "POST_CLOSE_CUTOFF" for v in violations)
