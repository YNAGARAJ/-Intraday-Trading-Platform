"""M21 Reporting Module — data models.

All report objects are plain Python dataclasses so they can be constructed from
any data source (Redis, TimescaleDB, in-memory fills) without coupling the
reporting module to a specific storage backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class TradeRecord:
    """A single completed (or open) trade for inclusion in a report.

    Args:
        trade_id: Unique identifier (typically the client_order_id from M14).
        symbol: Instrument symbol.
        exchange: Market identifier (e.g. ``NSE``, ``ASX``).
        direction: ``"LONG"`` or ``"SHORT"``.
        entry_time_ms: Entry fill timestamp (Unix epoch ms).
        exit_time_ms: Exit fill timestamp; ``None`` if still open.
        entry_price: Average entry fill price.
        exit_price: Average exit fill price; ``None`` if still open.
        quantity: Number of shares / contracts traded.
        pnl: Realised profit/loss in base currency.
        pnl_pct: P&L as percentage of trade notional (entry_price × quantity).
        strategy_tag: Compliance-resolved broker strategy tag.
        slippage_pct: Execution slippage as percentage of limit price; ``None`` if
            not computed (e.g. market order without reference price).
        markout_1m_pct: Post-fill P&L% at T+1 minute; ``None`` if not yet elapsed.
        markout_5m_pct: Post-fill P&L% at T+5 minutes; ``None`` if not yet elapsed.
    """

    trade_id: str
    symbol: str
    exchange: str
    direction: str
    entry_time_ms: int
    exit_time_ms: int | None
    entry_price: float
    exit_price: float | None
    quantity: int
    pnl: float
    pnl_pct: float
    strategy_tag: str
    slippage_pct: float | None = None
    markout_1m_pct: float | None = None
    markout_5m_pct: float | None = None


@dataclass
class MarkoutPoint:
    """Average P&L% at a specific time offset post-fill (markout curve data point).

    Args:
        offset_label: Human-readable offset label, e.g. ``"T+1m"`` or ``"T+5m"``.
        avg_pct: Mean P&L% across all trades with valid data at this offset.
        sample_count: Number of trades contributing to the average.
    """

    offset_label: str
    avg_pct: float
    sample_count: int


@dataclass
class DailyReport:
    """Aggregated performance statistics for a single trading day.

    Args:
        date: Calendar date of the session.
        trades: All trade records for the day (including open positions).
        total_pnl: Sum of realised P&L in base currency.
        total_pnl_pct: ``total_pnl / starting_capital * 100``.
        starting_capital: Portfolio value at session open.
        sharpe: Annualized Sharpe ratio computed from per-trade returns; ``None``
            when fewer than 2 completed trades.
        sortino: Annualized Sortino ratio; ``None`` when no downside deviation.
        max_drawdown_pct: Maximum intraday drawdown as a percentage (0–100).
        win_rate_pct: Percentage of trades with positive P&L (0–100).
        total_trades: Total number of trade records.
        winning_trades: Number of trades with ``pnl > 0``.
        losing_trades: Number of trades with ``pnl < 0``.
        avg_slippage_pct: Mean slippage % across all trades with valid data.
        markout_curve: T+1m / T+5m post-fill P&L% averages.
    """

    date: date
    trades: list[TradeRecord]
    total_pnl: float
    total_pnl_pct: float
    starting_capital: float
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_slippage_pct: float | None = None
    markout_curve: list[MarkoutPoint] = field(default_factory=list)


@dataclass
class MonthlyReport:
    """Aggregated performance statistics for a calendar month.

    Args:
        year: Four-digit year.
        month: Calendar month (1–12).
        daily_reports: All daily reports in the month.
        total_pnl: Sum of daily P&L in base currency.
        total_pnl_pct: ``total_pnl / starting_capital * 100``.
        starting_capital: Portfolio value at month start.
        sharpe: Annualized Sharpe from daily return series; ``None`` if < 2 days.
        sortino: Annualized Sortino from daily return series.
        max_drawdown_pct: Maximum month-to-date drawdown percentage.
        win_rate_pct: Percentage of winning days (daily_pnl > 0).
        total_trades: Total trades across all days.
    """

    year: int
    month: int
    daily_reports: list[DailyReport]
    total_pnl: float
    total_pnl_pct: float
    starting_capital: float
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    total_trades: int = 0
