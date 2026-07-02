"""Unit tests for M13 ComplianceEngine (integration of all checks)."""

from __future__ import annotations

from datetime import datetime

from shared.compliance.engine import ComplianceEngine
from shared.compliance.models import OrderIntent, RecentOrder
from shared.compliance.strategy_registry import StrategyRegistry

_IST_OPEN = datetime(2026, 7, 2, 10, 30)
_IST_AFTER_SQUAREOFF = datetime(2026, 7, 2, 15, 15)
_AEST_AFTER_CUTOFF = datetime(2026, 7, 2, 16, 30)
_NOW_MS = 1_700_000_000_000


def _engine(use_generic: bool = False) -> ComplianceEngine:
    return ComplianceEngine(registry=StrategyRegistry(use_generic=use_generic))


def _nse(**kwargs: object) -> OrderIntent:
    defaults: dict[str, object] = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "direction": "LONG",
        "order_type": "LIMIT",
        "quantity": 10,
        "price": 2450.0,
        "stop_loss": 2413.0,
        "strategy_name": "EMA_VWAP_TREND",
        "client_order_id": "ENG-001",
        "ltp": 2450.0,
        "notional_value": 24500.0,
        "capital": 100_000.0,
    }
    defaults.update(kwargs)
    return OrderIntent(**defaults)  # type: ignore[arg-type]


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
        "client_order_id": "ENG-ASX-001",
        "ltp": 45.0,
        "notional_value": 4500.0,
        "capital": 100_000.0,
    }
    defaults.update(kwargs)
    return OrderIntent(**defaults)  # type: ignore[arg-type]


class TestComplianceEngineIndia:
    def test_valid_nse_order_approved(self) -> None:
        eng = _engine()
        dec = eng.check(_nse(), now_ist=_IST_OPEN)
        assert dec.approved is True
        assert dec.tagged_order is not None
        assert dec.tagged_order.strategy_tag == "STRAT001"
        assert dec.violations == []

    def test_unknown_strategy_rejected(self) -> None:
        eng = _engine()
        dec = eng.check(_nse(strategy_name="UNKNOWN"), now_ist=_IST_OPEN)
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "NO_STRATEGY_ID" in codes

    def test_market_order_converted_to_mpp(self) -> None:
        eng = _engine()
        order = _nse(order_type="MARKET", price=None)
        dec = eng.check(order, now_ist=_IST_OPEN)
        assert dec.approved is True
        assert dec.tagged_order is not None
        assert dec.tagged_order.effective_order_type == "MPP"
        assert dec.tagged_order.mpp_price is not None

    def test_market_order_without_ltp_rejected(self) -> None:
        eng = _engine()
        order = _nse(order_type="MARKET", price=None, ltp=None)
        dec = eng.check(order, now_ist=_IST_OPEN)
        assert dec.approved is False

    def test_leverage_exceeded_rejected(self) -> None:
        eng = _engine()
        order = _nse(notional_value=600_000.0, capital=100_000.0)
        dec = eng.check(order, now_ist=_IST_OPEN)
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "LEVERAGE_EXCEEDED" in codes

    def test_mwpl_exceeded_rejected(self) -> None:
        eng = _engine()
        order = _nse(mwpl_pct=95.0)
        dec = eng.check(order, now_ist=_IST_OPEN)
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "MWPL_EXCEEDED" in codes

    def test_force_square_off_rejected(self) -> None:
        eng = _engine()
        dec = eng.check(_nse(), now_ist=_IST_AFTER_SQUAREOFF)
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "FORCE_SQUARE_OFF" in codes

    def test_generic_algo_id_mode(self) -> None:
        eng = _engine(use_generic=True)
        order = _nse(strategy_name="COMPLETELY_UNKNOWN")
        dec = eng.check(order, now_ist=_IST_OPEN)
        assert dec.approved is True
        assert dec.tagged_order is not None
        assert dec.tagged_order.strategy_tag == "GENALG01"

    def test_audit_id_present(self) -> None:
        eng = _engine()
        dec = eng.check(_nse(), now_ist=_IST_OPEN)
        assert dec.audit_id
        assert len(dec.audit_id) > 0

    def test_tagged_order_preserves_original(self) -> None:
        eng = _engine()
        order = _nse()
        dec = eng.check(order, now_ist=_IST_OPEN)
        assert dec.tagged_order is not None
        assert dec.tagged_order.original is order


class TestComplianceEngineAustralia:
    def test_valid_asx_long_approved(self) -> None:
        eng = _engine()
        dec = eng.check(
            _asx(),
            approved_short_list=frozenset({"BHP"}),
            now_ms=_NOW_MS,
        )
        assert dec.approved is True

    def test_wash_trading_rejected(self) -> None:
        eng = _engine()
        recent = [
            RecentOrder(symbol="BHP", direction="SHORT", placed_at_ms=_NOW_MS - 10_000)
        ]
        dec = eng.check(
            _asx(direction="LONG"),
            recent_orders=recent,
            now_ms=_NOW_MS,
        )
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "WASH_TRADING" in codes

    def test_short_sell_unapproved_rejected(self) -> None:
        eng = _engine()
        dec = eng.check(
            _asx(direction="SHORT", symbol="XYZ"),
            approved_short_list=frozenset({"BHP"}),
            now_ms=_NOW_MS,
        )
        assert dec.approved is False

    def test_short_sell_approved_passes(self) -> None:
        eng = _engine()
        dec = eng.check(
            _asx(direction="SHORT", symbol="BHP"),
            approved_short_list=frozenset({"BHP"}),
            now_ms=_NOW_MS,
        )
        assert dec.approved is True

    def test_post_close_cutoff_rejected(self) -> None:
        eng = _engine()
        dec = eng.check(
            _asx(),
            now_aest=_AEST_AFTER_CUTOFF,
            now_ms=_NOW_MS,
        )
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "POST_CLOSE_CUTOFF" in codes

    def test_staggered_open_rejected(self) -> None:
        eng = _engine()
        group_open_ms = _NOW_MS - (3 * 60 * 1000)  # 3 min ago
        dec = eng.check(
            _asx(),
            group_open_ms=group_open_ms,
            now_ms=_NOW_MS,
        )
        assert dec.approved is False
        codes = {v.code for v in dec.violations}
        assert "STAGGERED_OPEN_NOISE_FILTER" in codes


class TestCompliancePaperExchange:
    def test_paper_always_approved(self) -> None:
        eng = _engine()
        order = _nse(exchange="PAPER")
        dec = eng.check(order)
        assert dec.approved is True

    def test_paper_no_strategy_tag_uses_truncated_name(self) -> None:
        eng = _engine()
        order = _nse(exchange="PAPER", strategy_name="UNKNOWN_LONG_NAME")
        dec = eng.check(order)
        assert dec.approved is True
        assert dec.tagged_order is not None
        assert len(dec.tagged_order.strategy_tag) <= 8
