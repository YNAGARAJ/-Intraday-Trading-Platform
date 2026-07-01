"""M07 Backtesting Engine — vectorbt-based portfolio runner with log-normal slippage.

Per spec: "vectorbt backtester. CRITICAL: slippage distribution model (log-normal,
NOT mid-price fills), fit to actual fill data, parameterized by time-of-day bucket
+ bid-ask spread width at signal."

Architecture:
  1. Accept candles + pre-computed entry/exit boolean arrays.
  2. For each entry/exit bar, sample slippage from the log-normal model (slippage.py)
     to produce adjusted execution prices.
  3. Run vectorbt.Portfolio.from_signals with adjusted price series for P&L computation.
  4. Extract individual trades, compute markout curves, metrics, check RULE 6 gate.
  5. Return a BacktestResult ready for report generation and PostgreSQL storage.

EMA crossover strategy (`ema_crossover_signals`) is the reference implementation
used by the VERIFY test and CLI; other strategies pass their own signal arrays.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt
import pandas as pd
import talib
import vectorbt as vbt

from shared.backtesting.markout import compute_markout_curves
from shared.backtesting.metrics import compute_metrics
from shared.backtesting.models import (
    DIRECTION_LONG,
    BacktestConfig,
    BacktestResult,
    Trade,
)
from shared.backtesting.promotion_gate import check_promotion_gate
from shared.backtesting.slippage import sample_slippage_bps
from shared.core.constants import (
    BACKTEST_INITIAL_CAPITAL,
    BACKTEST_POSITION_SIZE_PCT,
    BACKTEST_RISK_FREE_RATE_ANNUAL,
    EMA_PERIODS,
)
from shared.core.logging import get_logger
from shared.storage.models import OHLCVCandle

logger = get_logger(__name__)

_EMA_FAST: int = EMA_PERIODS[0]  # 9
_EMA_SLOW: int = EMA_PERIODS[1]  # 21
_MIN_CANDLES: int = 30


def ema_crossover_signals(
    candles: list[OHLCVCandle],
    fast_period: int = _EMA_FAST,
    slow_period: int = _EMA_SLOW,
) -> tuple[list[bool], list[bool]]:
    """Generate long-only EMA crossover entry and exit signals.

    Entry: fast EMA crosses above slow EMA (bullish crossover).
    Exit: fast EMA crosses below slow EMA (bearish crossover).

    Args:
        candles: OHLCV candles, oldest first.
        fast_period: Fast EMA period (default 9).
        slow_period: Slow EMA period (default 21).

    Returns:
        Tuple of (entry_signals, exit_signals) boolean lists, one per candle.
    """
    if len(candles) < slow_period + 1:
        return [False] * len(candles), [False] * len(candles)

    close = np.array([c.close for c in candles], dtype=np.float64)
    fast_ema = talib.EMA(close, timeperiod=fast_period)
    slow_ema = talib.EMA(close, timeperiod=slow_period)

    entries: list[bool] = [False] * len(candles)
    exits: list[bool] = [False] * len(candles)
    in_trade = False

    for i in range(1, len(candles)):
        if np.isnan(fast_ema[i]) or np.isnan(slow_ema[i]):
            continue
        if np.isnan(fast_ema[i - 1]) or np.isnan(slow_ema[i - 1]):
            continue

        cross_up = fast_ema[i] > slow_ema[i] and fast_ema[i - 1] <= slow_ema[i - 1]
        cross_down = fast_ema[i] < slow_ema[i] and fast_ema[i - 1] >= slow_ema[i - 1]

        if cross_up and not in_trade:
            entries[i] = True
            in_trade = True
        elif cross_down and in_trade:
            exits[i] = True
            in_trade = False

    return entries, exits


def _infer_bars_per_day(candles: list[OHLCVCandle]) -> float:
    """Estimate the number of candle bars per trading day for annualisation."""
    if len(candles) < 2:
        return 1.0
    delta_secs = (candles[1].time - candles[0].time).total_seconds()
    if delta_secs <= 0:
        return 1.0
    # NSE session = 375 minutes; ASX = 360 minutes
    session_minutes = 375.0
    return session_minutes * 60.0 / delta_secs


def _infer_freq(candles: list[OHLCVCandle]) -> str:
    """Return a pandas-compatible frequency string for the candle series."""
    if len(candles) < 2:
        return "1D"
    delta_secs = abs((candles[1].time - candles[0].time).total_seconds())
    if delta_secs <= 60:
        return "1T"
    if delta_secs <= 300:
        return "5T"
    if delta_secs <= 900:
        return "15T"
    if delta_secs <= 3600:
        return "1h"
    return "1D"


def _count_trading_days(candles: list[OHLCVCandle]) -> int:
    return len({c.time.date() for c in candles})


def _extract_trades(
    records: pd.DataFrame,
    config: BacktestConfig,
    candles: list[OHLCVCandle],
    entry_slippage: npt.NDArray[np.float64],
    exit_slippage: npt.NDArray[np.float64],
) -> list[Trade]:
    """Convert vectorbt trade records into our Trade model.

    Args:
        records: vectorbt trades.records_readable DataFrame.
        config: Backtest configuration.
        candles: OHLCV candle list (for timestamp lookups by bar index).
        entry_slippage: Per-bar entry slippage in bps (indexed by bar number).
        exit_slippage: Per-bar exit slippage in bps.

    Returns:
        List of Trade objects, one per round-trip.
    """
    trades: list[Trade] = []
    if records.empty:
        return trades

    for row_idx, row in records.iterrows():
        entry_idx = int(row.get("Open Index", 0))
        exit_idx = int(row.get("Close Index", 0))
        entry_price = float(row.get("Open Price", 0.0))
        exit_price = float(row.get("Close Price", 0.0))
        pnl_pct = float(row.get("Return", 0.0)) * 100.0
        quantity = float(row.get("Size", 0.0))

        entry_time = (
            candles[entry_idx].time if entry_idx < len(candles) else candles[-1].time
        )
        exit_time = (
            candles[exit_idx].time if exit_idx < len(candles) else candles[-1].time
        )
        pnl = (exit_price - entry_price) * quantity

        trades.append(
            Trade(
                trade_id=str(row_idx),
                symbol=config.symbol,
                exchange=config.exchange,
                strategy_id=config.strategy_id,
                direction=DIRECTION_LONG,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                entry_slippage_bps=(
                    float(entry_slippage[entry_idx])
                    if entry_idx < len(entry_slippage)
                    else 0.0
                ),
                exit_slippage_bps=(
                    float(exit_slippage[exit_idx])
                    if exit_idx < len(exit_slippage)
                    else 0.0
                ),
                quantity=quantity,
                pnl=round(pnl, 4),
                pnl_pct=round(pnl_pct, 4),
            )
        )
    return trades


def run_backtest(
    config: BacktestConfig,
    candles: list[OHLCVCandle],
    entry_signals: list[bool],
    exit_signals: list[bool],
    spread_bps: float = 5.0,
    slippage_rng: np.random.Generator | None = None,
) -> BacktestResult:
    """Run a vectorbt-powered backtest with log-normal slippage injection.

    Args:
        config: Backtest parameters (capital, position size, dates, strategy ID).
        candles: OHLCV candle series covering at minimum config.start_date to
            config.end_date, oldest first. Must have len >= _MIN_CANDLES.
        entry_signals: Boolean list (one per candle): True = enter long at that bar.
        exit_signals: Boolean list (one per candle): True = exit long at that bar.
        spread_bps: Estimated bid-ask spread for slippage scaling (default 5 bps).
        slippage_rng: Optional RNG for reproducible slippage sampling in tests.

    Returns:
        BacktestResult with all fields populated, promotion gate evaluated,
        and report paths set to None (caller invokes report.generate_reports
        to write files and fill those paths in).

    Raises:
        ValueError: When fewer than _MIN_CANDLES candles are provided.
    """
    if len(candles) < _MIN_CANDLES:
        raise ValueError(
            f"Need at least {_MIN_CANDLES} candles for a backtest, got {len(candles)}"
        )
    if len(entry_signals) != len(candles) or len(exit_signals) != len(candles):
        raise ValueError(
            "entry_signals and exit_signals must have the same length as candles"
        )

    n = len(candles)
    close = np.array([c.close for c in candles], dtype=np.float64)
    timestamps = [c.time for c in candles]
    entries_arr = np.array(entry_signals, dtype=bool)
    exits_arr = np.array(exit_signals, dtype=bool)

    rng = slippage_rng or np.random.default_rng(42)
    adj_price = close.copy()
    entry_slip_bps = np.zeros(n, dtype=np.float64)
    exit_slip_bps = np.zeros(n, dtype=np.float64)

    for i in range(n):
        if entries_arr[i]:
            slip = sample_slippage_bps(candles[i].time, spread_bps=spread_bps, rng=rng)
            entry_slip_bps[i] = slip
            adj_price[i] = close[i] * (1.0 + slip / 10_000.0)
        elif exits_arr[i]:
            slip = sample_slippage_bps(candles[i].time, spread_bps=spread_bps, rng=rng)
            exit_slip_bps[i] = slip
            adj_price[i] = close[i] * (1.0 - slip / 10_000.0)

    freq = _infer_freq(candles)
    bars_per_day = _infer_bars_per_day(candles)
    trading_days = _count_trading_days(candles)

    idx = pd.DatetimeIndex(timestamps)
    pf = vbt.Portfolio.from_signals(
        close=pd.Series(close, index=idx),
        entries=pd.Series(entries_arr, index=idx),
        exits=pd.Series(exits_arr, index=idx),
        price=pd.Series(adj_price, index=idx),
        size=config.position_size_pct,
        size_type="percent",
        init_cash=config.initial_capital,
        freq=freq,
    )

    equity_series: pd.Series = pf.value()
    equity_values: npt.NDArray[np.float64] = np.asarray(
        equity_series.values, dtype=np.float64
    )

    records = pf.trades.records_readable
    trades = _extract_trades(records, config, candles, entry_slip_bps, exit_slip_bps)

    metrics = compute_metrics(
        trades=trades,
        equity_values=equity_values,
        config_initial_capital=config.initial_capital,
        config_risk_free_rate_annual=config.risk_free_rate_annual,
        trading_days=trading_days,
        candle_bars_per_day=bars_per_day,
    )
    markout_curves = compute_markout_curves(trades, candles)
    failures = check_promotion_gate(metrics)
    equity_curve = list(
        zip(timestamps[: len(equity_values)], equity_values.tolist(), strict=False)
    )

    run_id = uuid.uuid4().hex[:8]
    logger.info(
        "backtest_completed",
        run_id=run_id,
        strategy_id=config.strategy_id,
        symbol=config.symbol,
        trades=len(trades),
        sharpe=metrics.sharpe_ratio,
        max_dd_pct=metrics.max_drawdown_pct,
        passed_gate=len(failures) == 0,
    )

    return BacktestResult(
        run_id=run_id,
        config=config,
        trades=trades,
        metrics=metrics,
        markout_curves=markout_curves,
        equity_curve=equity_curve,
        passed_promotion_gate=len(failures) == 0,
        promotion_failures=failures,
        report_html_path=None,
        report_csv_path=None,
        completed_at=datetime.now(timezone.utc),
    )


def default_config(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    strategy_id: str = "EMA9X21",
) -> BacktestConfig:
    """Return a BacktestConfig with spec defaults for CLI and testing convenience."""
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=365)
    return BacktestConfig(
        strategy_id=strategy_id,
        symbol=symbol,
        exchange=exchange,
        start_date=start,
        end_date=end,
        initial_capital=BACKTEST_INITIAL_CAPITAL,
        position_size_pct=BACKTEST_POSITION_SIZE_PCT,
        risk_free_rate_annual=BACKTEST_RISK_FREE_RATE_ANNUAL,
    )
