"""Unit tests for M12 circuit breaker checks."""

from __future__ import annotations

from shared.risk.circuit_breaker import (
    check_circuit_breaker,
    check_daily_loss_limit,
    check_daily_trade_count,
    check_halted_flag,
)


class TestCheckHaltedFlag:
    def test_not_halted_passes(self) -> None:
        chk = check_halted_flag(False)
        assert chk.passed is True
        assert chk.name == "SYSTEM_HALTED"

    def test_halted_fails(self) -> None:
        chk = check_halted_flag(True)
        assert chk.passed is False
        assert "halted" in chk.detail.lower()

    def test_halted_name_correct(self) -> None:
        chk = check_halted_flag(True)
        assert chk.name == "SYSTEM_HALTED"


class TestCheckDailyLossLimit:
    def test_zero_pnl_passes(self) -> None:
        chk = check_daily_loss_limit(0.0, 100_000.0)
        assert chk.passed is True

    def test_positive_pnl_passes(self) -> None:
        chk = check_daily_loss_limit(500.0, 100_000.0)
        assert chk.passed is True

    def test_exactly_at_limit_fails(self) -> None:
        # -2% of 100,000 = -2,000
        chk = check_daily_loss_limit(-2_000.0, 100_000.0)
        assert chk.passed is False

    def test_below_limit_fails(self) -> None:
        chk = check_daily_loss_limit(-2_500.0, 100_000.0)
        assert chk.passed is False
        assert "circuit-breaker" in chk.detail.lower()

    def test_just_above_limit_passes(self) -> None:
        chk = check_daily_loss_limit(-1_999.0, 100_000.0)
        assert chk.passed is True

    def test_zero_capital_fails(self) -> None:
        chk = check_daily_loss_limit(0.0, 0.0)
        assert chk.passed is False

    def test_name_correct(self) -> None:
        chk = check_daily_loss_limit(-100.0, 100_000.0)
        assert chk.name == "CIRCUIT_BREAKER"

    def test_detail_contains_pct(self) -> None:
        chk = check_daily_loss_limit(-1_000.0, 100_000.0)
        assert "%" in chk.detail

    def test_different_capital_scales(self) -> None:
        # -2% of 500,000 = -10,000
        chk = check_daily_loss_limit(-10_001.0, 500_000.0)
        assert chk.passed is False
        chk2 = check_daily_loss_limit(-9_999.0, 500_000.0)
        assert chk2.passed is True


class TestCheckDailyTradeCount:
    def test_zero_count_passes(self) -> None:
        chk = check_daily_trade_count(0)
        assert chk.passed is True

    def test_below_limit_passes(self) -> None:
        chk = check_daily_trade_count(9)
        assert chk.passed is True

    def test_at_limit_fails(self) -> None:
        chk = check_daily_trade_count(10)
        assert chk.passed is False

    def test_above_limit_fails(self) -> None:
        chk = check_daily_trade_count(15)
        assert chk.passed is False

    def test_name_correct(self) -> None:
        chk = check_daily_trade_count(5)
        assert chk.name == "DAILY_TRADE_LIMIT"

    def test_detail_contains_count(self) -> None:
        chk = check_daily_trade_count(7)
        assert "7" in chk.detail


class TestCheckCircuitBreaker:
    """Tests for the combined check_circuit_breaker convenience function."""

    def test_not_halted_zero_pnl_passes(self) -> None:
        chk = check_circuit_breaker(
            daily_pnl=0.0, capital=100_000.0, halted=False
        )
        assert chk.passed is True

    def test_halted_true_fails(self) -> None:
        chk = check_circuit_breaker(
            daily_pnl=500.0, capital=100_000.0, halted=True
        )
        assert chk.passed is False

    def test_pnl_breach_fails(self) -> None:
        chk = check_circuit_breaker(
            daily_pnl=-2_100.0, capital=100_000.0, halted=False
        )
        assert chk.passed is False

    def test_halted_takes_precedence_over_positive_pnl(self) -> None:
        chk = check_circuit_breaker(
            daily_pnl=1_000.0, capital=100_000.0, halted=True
        )
        assert chk.passed is False
        assert "halted" in chk.detail.lower()
