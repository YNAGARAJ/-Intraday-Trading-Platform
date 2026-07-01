"""Unit tests for shared.backtesting.metrics — all RULE 6 metric computations."""

from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt
import pytest

from shared.backtesting.metrics import compute_metrics
from shared.backtesting.models import Trade

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
_T1 = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)


def _trade(pnl_pct: float, entry_slip: float = 5.0, exit_slip: float = 4.0) -> Trade:
    direction = 1
    entry_price = 100.0
    exit_price = entry_price * (1 + pnl_pct / 100.0)
    return Trade(
        trade_id="0",
        symbol="TEST",
        exchange="NSE",
        strategy_id="TST",
        direction=direction,
        entry_time=_T0,
        exit_time=_T1,
        entry_price=entry_price,
        exit_price=exit_price,
        entry_slippage_bps=entry_slip,
        exit_slippage_bps=exit_slip,
        quantity=10.0,
        pnl=(exit_price - entry_price) * 10.0,
        pnl_pct=pnl_pct,
    )


def _flat_equity(n: int = 100, initial: float = 100_000.0) -> npt.NDArray[np.float64]:
    return np.full(n, initial, dtype=np.float64)


def _trending_equity(
    n: int = 100, initial: float = 100_000.0, gain: float = 1.2
) -> npt.NDArray[np.float64]:
    return np.linspace(initial, initial * gain, n)


class TestComputeMetricsNoTrades:
    def test_zero_trades_returns_zeros(self) -> None:
        eq = _flat_equity()
        m = compute_metrics(
            trades=[],
            equity_values=eq,
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=252,
        )
        assert m.total_trades == 0
        assert m.sharpe_ratio == 0.0
        assert m.win_rate_pct == 0.0
        assert m.profit_factor == 0.0


class TestWinRate:
    def test_all_winners(self) -> None:
        trades = [_trade(1.0), _trade(2.0), _trade(0.5)]
        m = compute_metrics(
            trades=trades,
            equity_values=_trending_equity(),
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=60,
        )
        assert m.win_rate_pct == pytest.approx(100.0)

    def test_half_winners(self) -> None:
        trades = [_trade(1.0), _trade(-1.0), _trade(2.0), _trade(-2.0)]
        m = compute_metrics(
            trades=trades,
            equity_values=_flat_equity(),
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=60,
        )
        assert m.win_rate_pct == pytest.approx(50.0)

    def test_all_losers(self) -> None:
        trades = [_trade(-1.0), _trade(-2.0)]
        m = compute_metrics(
            trades=trades,
            equity_values=_flat_equity(),
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=30,
        )
        assert m.win_rate_pct == pytest.approx(0.0)
        assert m.profit_factor == pytest.approx(0.0)


class TestMaxDrawdown:
    def test_flat_equity_zero_drawdown(self) -> None:
        trades = [_trade(0.5)]
        m = compute_metrics(
            trades=trades,
            equity_values=_flat_equity(),
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=30,
        )
        assert m.max_drawdown_pct == pytest.approx(0.0, abs=1e-9)

    def test_50_pct_drawdown(self) -> None:
        # Equity goes from 100k → 200k → 100k → drawdown is 50%
        eq = np.array([100_000.0, 150_000.0, 200_000.0, 150_000.0, 100_000.0])
        trades = [_trade(0.5)]
        m = compute_metrics(
            trades=trades,
            equity_values=eq,
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=5,
        )
        assert m.max_drawdown_pct == pytest.approx(50.0, abs=0.01)


class TestProfitFactor:
    def test_profit_factor_3x(self) -> None:
        trades = [_trade(3.0), _trade(-1.0)]
        m = compute_metrics(
            trades=trades,
            equity_values=_trending_equity(),
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=30,
        )
        assert m.profit_factor == pytest.approx(3.0, abs=0.01)


class TestAvgSlippage:
    def test_avg_slippage_computed(self) -> None:
        trades = [_trade(1.0, entry_slip=6.0, exit_slip=4.0)]  # total 10 bps
        m = compute_metrics(
            trades=trades,
            equity_values=_trending_equity(),
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=10,
        )
        assert m.avg_slippage_bps == pytest.approx(10.0)


class TestTotalReturn:
    def test_total_return_20_pct(self) -> None:
        eq = np.array([100_000.0, 120_000.0])
        trades = [_trade(20.0)]
        m = compute_metrics(
            trades=trades,
            equity_values=eq,
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=252,
        )
        assert m.total_return_pct == pytest.approx(20.0, abs=0.01)

    def test_annualized_return_positive_for_gain(self) -> None:
        eq = _trending_equity(gain=1.1)
        trades = [_trade(10.0)]
        m = compute_metrics(
            trades=trades,
            equity_values=eq,
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=126,  # ~6 months
        )
        # A 10% gain in 6 months should annualise to ~21%
        assert m.annualized_return_pct > 10.0


class TestSharpe:
    def test_strongly_trending_equity_positive_sharpe(self) -> None:
        eq = _trending_equity(n=500, gain=1.5)
        trades = [_trade(50.0)]
        m = compute_metrics(
            trades=trades,
            equity_values=eq,
            config_initial_capital=100_000.0,
            config_risk_free_rate_annual=0.065,
            trading_days=252,
        )
        assert m.sharpe_ratio > 0.0
