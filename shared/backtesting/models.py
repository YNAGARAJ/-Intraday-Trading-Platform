"""M07 Backtesting Engine — data models.

All output types for the backtesting pipeline. BacktestResult is the top-level
container consumed by the report generator, promotion gate, and PostgreSQL repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

DIRECTION_LONG: Final[int] = 1
DIRECTION_SHORT: Final[int] = -1


@dataclass(frozen=True)
class SlippageBucket:
    """Log-normal slippage parameters for one time-of-day segment.

    Args:
        name: Human-readable label (OPEN, MID_SESSION, CLOSE).
        start_hour: Bucket start hour (local market time, 24h).
        start_minute: Bucket start minute.
        end_hour: Bucket end hour (exclusive).
        end_minute: Bucket end minute (exclusive).
        mu: Log-normal mu parameter (log-space mean) for slippage in basis points.
        sigma: Log-normal sigma parameter (log-space std) for slippage in bps.
    """

    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    mu: float
    sigma: float


@dataclass(frozen=True)
class Trade:
    """A single round-trip trade extracted from a completed backtest.

    Args:
        trade_id: Unique identifier (e.g. '0', '1', ...).
        symbol: Instrument symbol.
        exchange: Exchange code.
        strategy_id: Strategy identifier (same as BacktestConfig.strategy_id).
        direction: DIRECTION_LONG (+1) or DIRECTION_SHORT (-1).
        entry_time: Bar timestamp at which the trade was entered.
        exit_time: Bar timestamp at which the trade was closed.
        entry_price: Slippage-adjusted fill price on entry.
        exit_price: Slippage-adjusted fill price on exit.
        entry_slippage_bps: Slippage paid at entry in basis points.
        exit_slippage_bps: Slippage paid at exit in basis points.
        quantity: Notional quantity traded (in instrument units).
        pnl: Raw P&L in price units (direction-adjusted: positive = win).
        pnl_pct: P&L as % of entry capital deployed (direction-adjusted).
    """

    trade_id: str
    symbol: str
    exchange: str
    strategy_id: str
    direction: int
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    entry_slippage_bps: float
    exit_slippage_bps: float
    quantity: float
    pnl: float
    pnl_pct: float


@dataclass(frozen=True)
class MarkoutPoint:
    """Average price return at a fixed time offset after trade entry.

    Tracks adverse selection: if avg_return_pct is negative at T+1m but the trade
    eventually wins, the entry timing is suboptimal (buying into short-term weakness).
    """

    offset_label: str  # "T+1m" or "T+5m"
    avg_return_pct: float
    median_return_pct: float
    win_rate_at_offset: float
    sample_count: int


@dataclass(frozen=True)
class BacktestMetrics:
    """Aggregated performance metrics for a completed backtest run.

    All metrics are from the perspective of the strategy (not the benchmark).
    Ratios are annualised using the candle frequency detected by the engine.
    """

    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    expectancy_per_trade: float
    profit_factor: float
    calmar_ratio: float
    avg_slippage_bps: float
    total_trades: int
    trading_days: int
    total_return_pct: float
    annualized_return_pct: float


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run.

    Args:
        strategy_id: Short identifier (≤ STRATEGY_ID_MAX_LENGTH chars) embedded
            in every generated Trade; used for report titles and DB storage.
        symbol: Instrument symbol (e.g. "RELIANCE").
        exchange: Exchange code ("NSE" or "ASX").
        start_date: Inclusive start date for candle fetch and backtest window.
        end_date: Inclusive end date.
        initial_capital: Starting portfolio value (default BACKTEST_INITIAL_CAPITAL).
        position_size_pct: Fraction of portfolio per trade (default 0.02 = 2%).
        risk_free_rate_annual: Annual risk-free rate for Sharpe/Sortino annualisation.
    """

    strategy_id: str
    symbol: str
    exchange: str
    start_date: date
    end_date: date
    initial_capital: float = 100_000.0
    position_size_pct: float = 0.02
    risk_free_rate_annual: float = 0.065


@dataclass(frozen=True)
class BacktestResult:
    """Top-level output of a completed backtest.

    Args:
        run_id: Short unique identifier for this run (8 hex chars).
        config: The config used to produce this result.
        trades: List of individual round-trip trades, oldest first.
        metrics: Aggregated performance metrics.
        markout_curves: T+1m and T+5m adverse-selection curves.
        equity_curve: (timestamp, portfolio_value) pairs for the equity chart.
        passed_promotion_gate: True when all RULE 6 gates pass.
        promotion_failures: List of gate labels that failed (empty when passing).
        report_html_path: Absolute path to the generated HTML report (or None).
        report_csv_path: Absolute path to the generated CSV trade log (or None).
        completed_at: UTC timestamp when the run finished.
    """

    run_id: str
    config: BacktestConfig
    trades: list[Trade]
    metrics: BacktestMetrics
    markout_curves: list[MarkoutPoint]
    equity_curve: list[tuple[datetime, float]]
    passed_promotion_gate: bool
    promotion_failures: list[str]
    report_html_path: str | None
    report_csv_path: str | None
    completed_at: datetime


@dataclass(frozen=True)
class WalkForwardWindow:
    """A single in-sample / out-of-sample fold of a walk-forward run."""

    window_index: int
    in_sample_start: date
    in_sample_end: date
    out_of_sample_start: date
    out_of_sample_end: date
    best_params: dict[str, float]
    in_sample_metrics: BacktestMetrics
    out_of_sample_metrics: BacktestMetrics
    passed_oos_gate: bool


@dataclass(frozen=True)
class WalkForwardResult:
    """Aggregated walk-forward optimisation output.

    Args:
        strategy_id: Strategy identifier.
        symbol: Instrument symbol.
        exchange: Exchange code.
        windows: All individual fold results, oldest first.
        avg_oos_sharpe: Mean out-of-sample Sharpe across passing windows.
        avg_oos_drawdown_pct: Mean out-of-sample drawdown across passing windows.
        avg_oos_win_rate_pct: Mean out-of-sample win rate across passing windows.
        windows_passed: Number of OOS windows that cleared the promotion gate.
    """

    strategy_id: str
    symbol: str
    exchange: str
    windows: list[WalkForwardWindow]
    avg_oos_sharpe: float
    avg_oos_drawdown_pct: float
    avg_oos_win_rate_pct: float
    windows_passed: int
