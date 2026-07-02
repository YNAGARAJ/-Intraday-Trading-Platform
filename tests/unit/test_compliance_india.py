"""Unit tests for M13 India (SEBI) compliance checks."""

from __future__ import annotations

from datetime import datetime

from shared.compliance.india import (
    check_force_square_off,
    check_leverage,
    check_market_order,
    check_mwpl,
    check_strategy_id,
    compute_mpp_price,
    run_india_checks,
)
from shared.compliance.models import OrderIntent


def _order(**kwargs: object) -> OrderIntent:
    defaults: dict[str, object] = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "direction": "LONG",
        "order_type": "LIMIT",
        "quantity": 10,
        "price": 2450.0,
        "stop_loss": 2413.0,
        "strategy_name": "EMA_VWAP_TREND",
        "client_order_id": "IND-001",
        "ltp": 2450.0,
        "notional_value": 24500.0,
        "capital": 100_000.0,
    }
    defaults.update(kwargs)
    return OrderIntent(**defaults)  # type: ignore[arg-type]


_IST_OPEN = datetime(2026, 7, 2, 10, 30)
_IST_AFTER_SQUAREOFF = datetime(2026, 7, 2, 15, 15)
_IST_AT_SQUAREOFF = datetime(2026, 7, 2, 15, 10)


class TestCheckStrategyId:
    def test_none_tag_returns_violation(self) -> None:
        violations = check_strategy_id(_order(), strategy_tag=None)
        assert len(violations) == 1
        assert violations[0].code == "NO_STRATEGY_ID"

    def test_valid_tag_passes(self) -> None:
        assert check_strategy_id(_order(), strategy_tag="STRAT001") == []

    def test_non_india_exchange_skipped(self) -> None:
        o = _order(exchange="ASX")
        assert check_strategy_id(o, strategy_tag=None) == []

    def test_bse_enforced(self) -> None:
        o = _order(exchange="BSE")
        violations = check_strategy_id(o, strategy_tag=None)
        assert len(violations) == 1

    def test_paper_skipped(self) -> None:
        o = _order(exchange="PAPER")
        assert check_strategy_id(o, strategy_tag=None) == []


class TestComputeMppPrice:
    def test_buy_adds_buffer(self) -> None:
        o = _order(direction="LONG", ltp=2450.0)
        price = compute_mpp_price(o)
        assert price == round(2450.0 * 1.0025, 2)

    def test_sell_subtracts_buffer(self) -> None:
        o = _order(direction="SHORT", ltp=2450.0)
        price = compute_mpp_price(o)
        assert price == round(2450.0 * 0.9975, 2)

    def test_none_ltp_returns_none(self) -> None:
        o = _order(ltp=None)
        assert compute_mpp_price(o) is None

    def test_zero_ltp_returns_none(self) -> None:
        o = _order(ltp=0.0)
        assert compute_mpp_price(o) is None

    def test_price_rounded_to_2dp(self) -> None:
        o = _order(direction="LONG", ltp=1000.0)
        price = compute_mpp_price(o)
        assert price is not None
        assert price == round(price, 2)


class TestCheckMarketOrder:
    def test_market_buy_converted_to_mpp(self) -> None:
        o = _order(order_type="MARKET", price=None, ltp=2450.0)
        violations, eff_type, mpp = check_market_order(o)
        assert violations == []
        assert eff_type == "MPP"
        assert mpp == round(2450.0 * 1.0025, 2)

    def test_market_sell_converted_to_mpp(self) -> None:
        o = _order(direction="SHORT", order_type="MARKET", price=None, ltp=2450.0)
        violations, eff_type, mpp = check_market_order(o)
        assert violations == []
        assert eff_type == "MPP"
        assert mpp == round(2450.0 * 0.9975, 2)

    def test_market_without_ltp_rejected(self) -> None:
        o = _order(order_type="MARKET", price=None, ltp=None)
        violations, eff_type, mpp = check_market_order(o)
        assert len(violations) == 1
        assert violations[0].code == "MARKET_ORDER_NO_LTP"
        assert mpp is None

    def test_limit_order_passthrough(self) -> None:
        o = _order(order_type="LIMIT")
        violations, eff_type, mpp = check_market_order(o)
        assert violations == []
        assert eff_type == "LIMIT"
        assert mpp is None

    def test_sl_order_passthrough(self) -> None:
        o = _order(order_type="SL")
        violations, eff_type, mpp = check_market_order(o)
        assert violations == []
        assert eff_type == "SL"

    def test_asx_market_passthrough(self) -> None:
        o = _order(exchange="ASX", order_type="MARKET")
        violations, eff_type, mpp = check_market_order(o)
        assert violations == []
        assert eff_type == "MARKET"


class TestCheckLeverage:
    def test_within_5x_passes(self) -> None:
        o = _order(notional_value=400_000.0, capital=100_000.0)  # 4x
        assert check_leverage(o) == []

    def test_exactly_5x_passes(self) -> None:
        o = _order(notional_value=500_000.0, capital=100_000.0)
        assert check_leverage(o) == []

    def test_above_5x_rejected(self) -> None:
        o = _order(notional_value=600_000.0, capital=100_000.0)  # 6x
        violations = check_leverage(o)
        assert len(violations) == 1
        assert violations[0].code == "LEVERAGE_EXCEEDED"

    def test_exit_order_bypasses_leverage_check(self) -> None:
        o = _order(notional_value=999_999.0, capital=100.0, is_exit=True)
        assert check_leverage(o) == []

    def test_zero_capital_skipped(self) -> None:
        o = _order(notional_value=1_000_000.0, capital=0.0)
        assert check_leverage(o) == []

    def test_asx_skipped(self) -> None:
        o = _order(exchange="ASX", notional_value=1_000_000.0, capital=100.0)
        assert check_leverage(o) == []


class TestCheckMwpl:
    def test_below_threshold_passes(self) -> None:
        o = _order(mwpl_pct=85.0)
        assert check_mwpl(o) == []

    def test_above_threshold_rejected(self) -> None:
        o = _order(mwpl_pct=91.5)
        violations = check_mwpl(o)
        assert len(violations) == 1
        assert violations[0].code == "MWPL_EXCEEDED"

    def test_at_threshold_rejected(self) -> None:
        o = _order(mwpl_pct=90.1)
        assert len(check_mwpl(o)) == 1

    def test_none_mwpl_pct_skipped(self) -> None:
        o = _order(mwpl_pct=None)
        assert check_mwpl(o) == []

    def test_exit_bypasses_mwpl(self) -> None:
        o = _order(mwpl_pct=99.9, is_exit=True)
        assert check_mwpl(o) == []

    def test_asx_skipped(self) -> None:
        o = _order(exchange="ASX", mwpl_pct=95.0)
        assert check_mwpl(o) == []


class TestCheckForceSquareOff:
    def test_before_squareoff_passes(self) -> None:
        o = _order()
        assert check_force_square_off(o, _IST_OPEN) == []

    def test_at_squareoff_time_rejected(self) -> None:
        o = _order()
        violations = check_force_square_off(o, _IST_AT_SQUAREOFF)
        assert len(violations) == 1
        assert violations[0].code == "FORCE_SQUARE_OFF"

    def test_after_squareoff_rejected(self) -> None:
        o = _order()
        violations = check_force_square_off(o, _IST_AFTER_SQUAREOFF)
        assert len(violations) == 1

    def test_exit_allowed_after_squareoff(self) -> None:
        o = _order(is_exit=True)
        assert check_force_square_off(o, _IST_AFTER_SQUAREOFF) == []

    def test_asx_skipped(self) -> None:
        o = _order(exchange="ASX")
        assert check_force_square_off(o, _IST_AFTER_SQUAREOFF) == []


class TestRunIndiaChecks:
    def test_all_pass_returns_empty_violations(self) -> None:
        o = _order()
        violations, eff_type, mpp = run_india_checks(o, "STRAT001", _IST_OPEN)
        assert violations == []
        assert eff_type == "LIMIT"
        assert mpp is None

    def test_market_order_converts_in_combined_run(self) -> None:
        o = _order(order_type="MARKET", price=None, ltp=2450.0)
        violations, eff_type, mpp = run_india_checks(o, "STRAT001", _IST_OPEN)
        assert violations == []
        assert eff_type == "MPP"
        assert mpp is not None

    def test_multiple_violations_collected(self) -> None:
        o = _order(
            notional_value=700_000.0,  # leverage > 5x
            mwpl_pct=95.0,  # mwpl > 90%
        )
        violations, _, _ = run_india_checks(o, "STRAT001", _IST_OPEN)
        codes = {v.code for v in violations}
        assert "LEVERAGE_EXCEEDED" in codes
        assert "MWPL_EXCEEDED" in codes

    def test_no_strategy_tag_first_violation(self) -> None:
        o = _order()
        violations, _, _ = run_india_checks(o, None, _IST_OPEN)
        assert any(v.code == "NO_STRATEGY_ID" for v in violations)

    def test_skip_time_check_when_none(self) -> None:
        o = _order(notional_value=700_000.0)  # leverage block only
        violations, _, _ = run_india_checks(o, "STRAT001", now_ist=None)
        codes = {v.code for v in violations}
        assert "FORCE_SQUARE_OFF" not in codes
        assert "LEVERAGE_EXCEEDED" in codes
