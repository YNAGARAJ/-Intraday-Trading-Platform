"""Performance metric computation for backtesting results.

All metrics required by the spec (RULE 6 / M07):
  Sharpe, Sortino, max drawdown, win rate, expectancy, profit factor,
  Calmar ratio, avg slippage, annualised return.

Input: list of Trade objects + equity value series from the vectorbt Portfolio.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import numpy.typing as npt

from shared.backtesting.models import BacktestMetrics, Trade

_ANNUALISATION_FACTOR: Final[float] = 252.0
_MIN_TRADES_FOR_RATIO: Final[int] = 2


def _safe_div(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    return numerator / denominator if denominator != 0.0 else fallback


def compute_metrics(
    trades: list[Trade],
    equity_values: npt.NDArray[np.float64],
    config_initial_capital: float,
    config_risk_free_rate_annual: float,
    trading_days: int,
    candle_bars_per_day: float = 75.0,
) -> BacktestMetrics:
    """Compute all RULE 6 performance metrics from trades and equity curve.

    Args:
        trades: Individual round-trip trades from the backtest.
        equity_values: Portfolio value at each candle bar (from vectorbt).
        config_initial_capital: Starting portfolio value.
        config_risk_free_rate_annual: Annual risk-free rate (for Sharpe/Sortino).
        trading_days: Number of distinct trading days in the backtest window.
        candle_bars_per_day: Bar frequency for annualisation (75 for NSE 5m bars,
            1 for daily bars).

    Returns:
        BacktestMetrics with all fields populated.
    """
    total_trades = len(trades)
    total_return_pct = (
        _safe_div(equity_values[-1] - config_initial_capital, config_initial_capital)
        * 100.0
        if len(equity_values) > 0
        else 0.0
    )

    annualized_return_pct = 0.0
    if trading_days > 0 and total_return_pct > -100.0:
        ann_factor = _ANNUALISATION_FACTOR / trading_days
        annualized_return_pct = (
            (1.0 + total_return_pct / 100.0) ** ann_factor - 1.0
        ) * 100.0

    if total_trades == 0:
        return BacktestMetrics(
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            expectancy_per_trade=0.0,
            profit_factor=0.0,
            calmar_ratio=0.0,
            avg_slippage_bps=0.0,
            total_trades=0,
            trading_days=trading_days,
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return_pct,
        )

    pnl_pcts = np.array([t.pnl_pct for t in trades], dtype=np.float64)
    slippages = np.array(
        [t.entry_slippage_bps + t.exit_slippage_bps for t in trades], dtype=np.float64
    )

    # Win/loss stats
    wins = pnl_pcts[pnl_pcts > 0.0]
    losses = pnl_pcts[pnl_pcts <= 0.0]
    win_rate_pct = len(wins) / total_trades * 100.0
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(abs(np.sum(losses))) if len(losses) > 0 else 0.0
    fallback_pf = 0.0 if gross_profit == 0.0 else 999.0
    profit_factor = _safe_div(gross_profit, gross_loss, fallback=fallback_pf)
    expectancy_per_trade = float(np.mean(pnl_pcts))
    avg_slippage_bps = float(np.mean(slippages))

    # Max drawdown from equity curve
    max_drawdown_pct = 0.0
    if len(equity_values) > 1:
        cummax = np.maximum.accumulate(equity_values)
        drawdowns = (cummax - equity_values) / cummax
        max_drawdown_pct = float(np.max(drawdowns)) * 100.0

    # Sharpe ratio (from bar-level returns, annualised)
    sharpe_ratio = 0.0
    sortino_ratio = 0.0
    if len(equity_values) >= _MIN_TRADES_FOR_RATIO + 1:
        bar_returns = np.diff(equity_values) / equity_values[:-1]
        rfr_per_bar = config_risk_free_rate_annual / (
            _ANNUALISATION_FACTOR * candle_bars_per_day
        )
        excess = bar_returns - rfr_per_bar
        std_excess = float(np.std(excess, ddof=1))
        if std_excess > 0.0:
            sharpe_ratio = (
                float(np.mean(excess))
                / std_excess
                * math.sqrt(_ANNUALISATION_FACTOR * candle_bars_per_day)
            )
        downside = excess[excess < 0.0]
        std_downside = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        if std_downside > 0.0:
            sortino_ratio = (
                float(np.mean(excess))
                / std_downside
                * math.sqrt(_ANNUALISATION_FACTOR * candle_bars_per_day)
            )

    calmar_ratio = _safe_div(annualized_return_pct, max_drawdown_pct)

    return BacktestMetrics(
        sharpe_ratio=round(sharpe_ratio, 4),
        sortino_ratio=round(sortino_ratio, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        win_rate_pct=round(win_rate_pct, 4),
        expectancy_per_trade=round(expectancy_per_trade, 4),
        profit_factor=round(profit_factor, 4),
        calmar_ratio=round(calmar_ratio, 4),
        avg_slippage_bps=round(avg_slippage_bps, 4),
        total_trades=total_trades,
        trading_days=trading_days,
        total_return_pct=round(total_return_pct, 4),
        annualized_return_pct=round(annualized_return_pct, 4),
    )
