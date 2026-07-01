"""Unit tests for shared.backtesting.promotion_gate — RULE 6 model-promotion gate."""

from shared.backtesting.models import BacktestMetrics
from shared.backtesting.promotion_gate import check_promotion_gate
from shared.core.constants import (
    PAPER_TRADING_MAX_DRAWDOWN_PCT,
    PAPER_TRADING_MIN_DAYS,
    PAPER_TRADING_MIN_SHARPE,
    PAPER_TRADING_MIN_WIN_RATE_PCT,
)


def _metrics(
    sharpe: float = 2.0,
    win_rate: float = 60.0,
    max_dd: float = 3.0,
    trading_days: int = 25,
) -> BacktestMetrics:
    return BacktestMetrics(
        sharpe_ratio=sharpe,
        sortino_ratio=sharpe * 1.2,
        max_drawdown_pct=max_dd,
        win_rate_pct=win_rate,
        expectancy_per_trade=0.5,
        profit_factor=1.8,
        calmar_ratio=2.0,
        avg_slippage_bps=5.0,
        total_trades=20,
        trading_days=trading_days,
        total_return_pct=15.0,
        annualized_return_pct=18.0,
    )


class TestAllGatesPass:
    def test_strong_metrics_pass_all_gates(self) -> None:
        failures = check_promotion_gate(_metrics())
        assert failures == []

    def test_passing_result_returns_empty_list(self) -> None:
        assert check_promotion_gate(_metrics(sharpe=3.0, win_rate=65.0)) == []


class TestIndividualGateFailures:
    def test_insufficient_trading_days_fails(self) -> None:
        failures = check_promotion_gate(
            _metrics(trading_days=PAPER_TRADING_MIN_DAYS - 1)
        )
        assert any("trading_days" in f or "min_trading_days" in f for f in failures)

    def test_low_sharpe_fails(self) -> None:
        failures = check_promotion_gate(_metrics(sharpe=PAPER_TRADING_MIN_SHARPE))
        # Must be strictly greater than the threshold
        assert any("sharpe" in f for f in failures)

    def test_sharpe_exactly_at_threshold_fails(self) -> None:
        # The gate is strict (>), so exactly 1.5 should fail
        failures = check_promotion_gate(_metrics(sharpe=1.5))
        assert any("sharpe" in f for f in failures)

    def test_low_win_rate_fails(self) -> None:
        failures = check_promotion_gate(
            _metrics(win_rate=PAPER_TRADING_MIN_WIN_RATE_PCT)
        )
        assert any("win_rate" in f for f in failures)

    def test_high_drawdown_fails(self) -> None:
        failures = check_promotion_gate(_metrics(max_dd=PAPER_TRADING_MAX_DRAWDOWN_PCT))
        assert any("drawdown" in f for f in failures)


class TestMultipleGateFailures:
    def test_all_gates_fail(self) -> None:
        bad = _metrics(sharpe=0.5, win_rate=30.0, max_dd=10.0, trading_days=5)
        failures = check_promotion_gate(bad)
        assert len(failures) == 4

    def test_two_gates_fail_returns_two_entries(self) -> None:
        m = _metrics(sharpe=1.0, max_dd=6.0)
        failures = check_promotion_gate(m)
        assert len(failures) == 2


class TestGateLabelsAreDescriptive:
    def test_failure_labels_are_strings(self) -> None:
        failures = check_promotion_gate(_metrics(sharpe=0.0, win_rate=0.0))
        for f in failures:
            assert isinstance(f, str)
            assert len(f) > 0
