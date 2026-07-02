"""M21 Reporting Module — performance metrics computation.

All functions operate on plain Python lists/floats; no database or Redis access.
Annualization factor: sqrt(252) trading days per year.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np

from shared.reporting.models import (
    DailyReport,
    MarkoutPoint,
    MonthlyReport,
    TradeRecord,
)

_ANNUALIZATION: float = math.sqrt(252)


def compute_sharpe(returns: list[float], annualize: bool = True) -> float | None:
    """Annualized Sharpe ratio from a return series.

    Args:
        returns: Daily or per-trade returns as fractions (0.01 = 1%).
        annualize: Multiply by sqrt(252) when True.

    Returns:
        Sharpe ratio, or None when fewer than 2 data points or zero variance.
    """
    if len(returns) < 2:
        return None
    arr = np.array(returns, dtype=float)
    std = float(np.std(arr, ddof=1))
    if std == 0.0 or not math.isfinite(std):
        return None
    sharpe = float(np.mean(arr)) / std
    return sharpe * _ANNUALIZATION if annualize else sharpe


def compute_sortino(returns: list[float], annualize: bool = True) -> float | None:
    """Annualized Sortino ratio from a return series (downside deviation denominator).

    Args:
        returns: Daily or per-trade returns as fractions.
        annualize: Multiply by sqrt(252) when True.

    Returns:
        Sortino ratio, or None when there are no negative returns or < 2 data points.
    """
    if len(returns) < 2:
        return None
    arr = np.array(returns, dtype=float)
    mean = float(np.mean(arr))
    downside = arr[arr < 0.0]
    if len(downside) == 0:
        return None
    ds_std = float(np.std(downside))
    if ds_std == 0.0 or not math.isfinite(ds_std):
        return None
    sortino = mean / ds_std
    return sortino * _ANNUALIZATION if annualize else sortino


def compute_max_drawdown(returns: list[float]) -> float:
    """Maximum drawdown as a fraction (0.05 = 5%) from a return series.

    Uses cumulative wealth path: W_t = Π(1 + r_i); drawdown = (peak - W_t) / peak.

    Args:
        returns: Daily or per-trade returns as fractions.

    Returns:
        Maximum drawdown fraction in [0, 1]; 0.0 for empty input.
    """
    if not returns:
        return 0.0
    wealth = np.cumprod(1.0 + np.array(returns, dtype=float))
    peak = np.maximum.accumulate(wealth)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(peak > 0.0, (peak - wealth) / peak, 0.0)
    return float(np.max(drawdowns))


def _build_markout_curve(trades: list[TradeRecord]) -> list[MarkoutPoint]:
    """Compute average T+1m and T+5m markout P&L% from trade records."""
    points = []
    for label, values in [
        ("T+1m", [t.markout_1m_pct for t in trades if t.markout_1m_pct is not None]),
        ("T+5m", [t.markout_5m_pct for t in trades if t.markout_5m_pct is not None]),
    ]:
        if values:
            points.append(
                MarkoutPoint(
                    offset_label=label,
                    avg_pct=float(np.mean(np.array(values, dtype=float))),
                    sample_count=len(values),
                )
            )
    return points


def compute_daily_report(
    report_date: date,
    trades: list[TradeRecord],
    starting_capital: float,
) -> DailyReport:
    """Build a DailyReport from a list of trade records.

    Args:
        report_date: The trading session date.
        trades: All trade records for the day.
        starting_capital: Portfolio value at session open.

    Returns:
        A fully-populated DailyReport with all computed performance metrics.
    """
    total_pnl = sum(t.pnl for t in trades)
    total_pnl_pct = (
        (total_pnl / starting_capital * 100) if starting_capital > 0 else 0.0
    )
    winning = [t for t in trades if t.pnl > 0]
    losing = [t for t in trades if t.pnl < 0]
    win_rate = (len(winning) / len(trades) * 100) if trades else 0.0
    slippages = [t.slippage_pct for t in trades if t.slippage_pct is not None]
    avg_slip = float(np.mean(np.array(slippages, dtype=float))) if slippages else None

    # Per-trade return fractions for Sharpe / Sortino
    returns = [t.pnl_pct / 100.0 for t in trades]

    return DailyReport(
        date=report_date,
        trades=trades,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        starting_capital=starting_capital,
        sharpe=compute_sharpe(returns),
        sortino=compute_sortino(returns),
        max_drawdown_pct=compute_max_drawdown(returns) * 100.0,
        win_rate_pct=win_rate,
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        avg_slippage_pct=avg_slip,
        markout_curve=_build_markout_curve(trades),
    )


def compute_monthly_report(
    year: int,
    month: int,
    daily_reports: list[DailyReport],
) -> MonthlyReport:
    """Build a MonthlyReport by aggregating a list of DailyReports.

    Args:
        year: Four-digit year.
        month: Calendar month (1–12).
        daily_reports: All daily reports for the month in chronological order.

    Returns:
        A MonthlyReport with aggregated metrics computed from daily returns.
    """
    starting_capital = daily_reports[0].starting_capital if daily_reports else 0.0
    total_pnl = sum(r.total_pnl for r in daily_reports)
    total_pnl_pct = (
        (total_pnl / starting_capital * 100) if starting_capital > 0 else 0.0
    )
    all_trades = [t for r in daily_reports for t in r.trades]
    winning_days = [r for r in daily_reports if r.total_pnl > 0]
    win_rate = (
        (len(winning_days) / len(daily_reports) * 100) if daily_reports else 0.0
    )

    # Use daily P&L% (as fractions) for monthly Sharpe/Sortino
    daily_returns = [r.total_pnl_pct / 100.0 for r in daily_reports]

    return MonthlyReport(
        year=year,
        month=month,
        daily_reports=daily_reports,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        starting_capital=starting_capital,
        sharpe=compute_sharpe(daily_returns),
        sortino=compute_sortino(daily_returns),
        max_drawdown_pct=compute_max_drawdown(daily_returns) * 100.0,
        win_rate_pct=win_rate,
        total_trades=len(all_trades),
    )
