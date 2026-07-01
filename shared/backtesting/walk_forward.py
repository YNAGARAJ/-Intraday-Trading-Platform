"""Walk-forward optimisation for backtesting strategies.

Splits the candle history into rolling in-sample / out-of-sample window pairs,
optimises strategy parameters on in-sample data (by Sharpe), and evaluates on
the subsequent out-of-sample window. Each OOS result is checked against the
RULE 6 promotion gate.

The optimisation objective is always Sharpe ratio (spec: "Walk-forward
optimisation" with RULE 6's Sharpe > 1.5 gate as the performance target).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np

from shared.backtesting.engine import run_backtest
from shared.backtesting.models import (
    BacktestConfig,
    BacktestMetrics,
    WalkForwardResult,
    WalkForwardWindow,
)
from shared.backtesting.promotion_gate import check_promotion_gate
from shared.core.constants import (
    WALK_FORWARD_IN_SAMPLE_DAYS,
    WALK_FORWARD_OUT_OF_SAMPLE_DAYS,
    WALK_FORWARD_STEP_DAYS,
)
from shared.core.logging import get_logger
from shared.storage.models import OHLCVCandle

logger = get_logger(__name__)

SignalFn = Callable[
    [list[OHLCVCandle], dict[str, float]], tuple[list[bool], list[bool]]
]

_ZERO_METRICS = BacktestMetrics(
    sharpe_ratio=0.0,
    sortino_ratio=0.0,
    max_drawdown_pct=0.0,
    win_rate_pct=0.0,
    expectancy_per_trade=0.0,
    profit_factor=0.0,
    calmar_ratio=0.0,
    avg_slippage_bps=0.0,
    total_trades=0,
    trading_days=0,
    total_return_pct=0.0,
    annualized_return_pct=0.0,
)


def _candles_in_range(
    candles: list[OHLCVCandle], start: date, end: date
) -> list[OHLCVCandle]:
    return [c for c in candles if start <= c.time.date() <= end]


def _run_with_params(
    config: BacktestConfig,
    candles: list[OHLCVCandle],
    signal_fn: SignalFn,
    params: dict[str, float],
    rng: np.random.Generator,
) -> BacktestMetrics:
    """Run a single backtest with the given parameters and return its metrics."""
    if len(candles) < 30:
        return _ZERO_METRICS
    entries, exits = signal_fn(candles, params)
    try:
        result = run_backtest(config, candles, entries, exits, slippage_rng=rng)
        return result.metrics
    except (ValueError, RuntimeError):
        return _ZERO_METRICS


def run_walk_forward(
    config: BacktestConfig,
    candles: list[OHLCVCandle],
    signal_fn: SignalFn,
    param_grid: list[dict[str, float]],
    in_sample_days: int = WALK_FORWARD_IN_SAMPLE_DAYS,
    out_of_sample_days: int = WALK_FORWARD_OUT_OF_SAMPLE_DAYS,
    step_days: int = WALK_FORWARD_STEP_DAYS,
) -> WalkForwardResult:
    """Run walk-forward optimisation over the full candle history.

    For each fold:
      1. In-sample window: try every params dict in `param_grid`; pick the one
         with the highest Sharpe ratio.
      2. Out-of-sample window: run with the best params; check RULE 6 gate.
      3. Advance the window by `step_days` and repeat.

    Args:
        config: Base backtest config (symbol, exchange, capital, etc.).
            start_date / end_date are overridden by each window.
        candles: Full history, oldest first.
        signal_fn: Callable(candles, params) -> (entry_bools, exit_bools).
        param_grid: List of parameter dicts to try on each in-sample window.
        in_sample_days: Trading days per in-sample fold.
        out_of_sample_days: Trading days per out-of-sample fold.
        step_days: Trading days to advance between folds.

    Returns:
        WalkForwardResult with all window results and aggregated OOS metrics.
    """
    if not candles:
        return WalkForwardResult(
            strategy_id=config.strategy_id,
            symbol=config.symbol,
            exchange=config.exchange,
            windows=[],
            avg_oos_sharpe=0.0,
            avg_oos_drawdown_pct=0.0,
            avg_oos_win_rate_pct=0.0,
            windows_passed=0,
        )

    all_dates = sorted({c.time.date() for c in candles})
    rng = np.random.default_rng(42)
    windows: list[WalkForwardWindow] = []
    window_idx = 0
    cursor = 0

    while True:
        is_end = cursor + in_sample_days
        oos_end = is_end + out_of_sample_days
        if is_end > len(all_dates) or oos_end > len(all_dates):
            break

        is_start_date = all_dates[cursor]
        is_end_date = all_dates[is_end - 1]
        oos_start_date = all_dates[is_end]
        oos_end_date = all_dates[min(oos_end - 1, len(all_dates) - 1)]

        is_candles = _candles_in_range(candles, is_start_date, is_end_date)
        oos_candles = _candles_in_range(candles, oos_start_date, oos_end_date)

        # Optimise on in-sample: pick params with highest Sharpe
        best_params: dict[str, float] = param_grid[0] if param_grid else {}
        best_sharpe = -999.0
        best_is_metrics = _ZERO_METRICS

        is_config = BacktestConfig(
            strategy_id=config.strategy_id,
            symbol=config.symbol,
            exchange=config.exchange,
            start_date=is_start_date,
            end_date=is_end_date,
            initial_capital=config.initial_capital,
            position_size_pct=config.position_size_pct,
            risk_free_rate_annual=config.risk_free_rate_annual,
        )

        for params in param_grid:
            m = _run_with_params(is_config, is_candles, signal_fn, params, rng)
            if m.sharpe_ratio > best_sharpe:
                best_sharpe = m.sharpe_ratio
                best_params = params
                best_is_metrics = m

        # Evaluate best params on out-of-sample
        oos_config = BacktestConfig(
            strategy_id=config.strategy_id,
            symbol=config.symbol,
            exchange=config.exchange,
            start_date=oos_start_date,
            end_date=oos_end_date,
            initial_capital=config.initial_capital,
            position_size_pct=config.position_size_pct,
            risk_free_rate_annual=config.risk_free_rate_annual,
        )
        oos_metrics = _run_with_params(
            oos_config, oos_candles, signal_fn, best_params, rng
        )
        oos_failures = check_promotion_gate(oos_metrics)
        passed_oos = len(oos_failures) == 0

        windows.append(
            WalkForwardWindow(
                window_index=window_idx,
                in_sample_start=is_start_date,
                in_sample_end=is_end_date,
                out_of_sample_start=oos_start_date,
                out_of_sample_end=oos_end_date,
                best_params=best_params,
                in_sample_metrics=best_is_metrics,
                out_of_sample_metrics=oos_metrics,
                passed_oos_gate=passed_oos,
            )
        )

        logger.debug(
            "walk_forward_window_done",
            window=window_idx,
            oos_sharpe=oos_metrics.sharpe_ratio,
            passed=passed_oos,
        )
        window_idx += 1
        cursor += step_days

    oos_sharpes = [w.out_of_sample_metrics.sharpe_ratio for w in windows]
    oos_dds = [w.out_of_sample_metrics.max_drawdown_pct for w in windows]
    oos_wrs = [w.out_of_sample_metrics.win_rate_pct for w in windows]
    passed_count = sum(1 for w in windows if w.passed_oos_gate)

    logger.info(
        "walk_forward_completed",
        windows=len(windows),
        windows_passed=passed_count,
        avg_oos_sharpe=(
            round(sum(oos_sharpes) / len(oos_sharpes), 4) if oos_sharpes else 0.0
        ),
    )

    avg_sharpe = round(sum(oos_sharpes) / len(oos_sharpes), 4) if oos_sharpes else 0.0
    return WalkForwardResult(
        strategy_id=config.strategy_id,
        symbol=config.symbol,
        exchange=config.exchange,
        windows=windows,
        avg_oos_sharpe=avg_sharpe,
        avg_oos_drawdown_pct=round(sum(oos_dds) / len(oos_dds), 4) if oos_dds else 0.0,
        avg_oos_win_rate_pct=round(sum(oos_wrs) / len(oos_wrs), 4) if oos_wrs else 0.0,
        windows_passed=passed_count,
    )
