"""Data models for M12 Risk & Position Sizing Engine.

`RiskParameters` is the complete input bundle. `RiskDecision` is the output.
`RiskCheck` records each guard's pass/fail result for audit logging.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.regime.models import RegimeClassification


@dataclass(frozen=True)
class RiskCheck:
    """Result of a single risk guard evaluation.

    Args:
        name: Short identifier for the check (e.g. ``'CIRCUIT_BREAKER'``).
        passed: True when the check did not block the trade.
        detail: Human-readable explanation of the outcome.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PositionSize:
    """Computed position sizing output.

    Args:
        quantity: Number of shares or contracts to trade.
        notional_value: ``quantity × entry_price``.
        risk_amount: Capital at risk = ``|entry - stop_loss| × quantity``.
        risk_pct: ``risk_amount`` as a percentage of total capital.
        sizing_method: Either ``'ATR_FIXED_RISK'`` or ``'KELLY'``.
        regime_multiplier: Regime-based scaling factor applied to base risk.
        snapshot_multiplier: 0.5 inside SEBI snapshot window, else 1.0.
    """

    quantity: int
    notional_value: float
    risk_amount: float
    risk_pct: float
    sizing_method: str
    regime_multiplier: float
    snapshot_multiplier: float


@dataclass(frozen=True)
class OpenPosition:
    """Snapshot of a currently open position, used for portfolio-level checks.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code (``'NSE'`` or ``'ASX'``).
        direction: ``'LONG'`` or ``'SHORT'``.
        quantity: Number of open shares/contracts.
        entry_price: Average fill price.
        stop_loss: Current hard stop-loss price.
        sector: Industry sector label (e.g. ``'IT'``, ``'BANKING'``).
            ``'UNKNOWN'`` when not classified.
        risk_amount: Capital at risk for this position (already computed).
        returns: Recent daily returns series (oldest first) for correlation.
    """

    symbol: str
    exchange: str
    direction: str
    quantity: int
    entry_price: float
    stop_loss: float
    sector: str
    risk_amount: float
    returns: Sequence[float] = field(default_factory=list)


@dataclass(frozen=True)
class RiskParameters:
    """Complete input bundle for one risk evaluation pass.

    Args:
        capital: Total account capital in base currency.
        open_positions: All currently open positions.
        daily_pnl: Realized + unrealized P&L for today (negative = loss).
        daily_trade_count: Number of trades already taken today.
        is_snapshot_window: True when within SEBI snapshot window (14:45-15:30 IST).
        regime: Current market regime classification from M08.
        proposed_sector: Sector of the proposed new position (for 5% sector check).
        proposed_returns: Recent daily returns for the proposed symbol
            (for correlation guard).
        use_kelly: If True and ``win_rate``/``avg_win_loss_ratio`` are set, use
            fractional Kelly sizing. False by default; requires paper-trading
            validation before enabling live.
        win_rate: Historical win rate in ``[0, 1]`` (required for Kelly mode).
        avg_win_loss_ratio: Average win / average loss ratio (required for Kelly mode).
        halted: True if ``system:status:halted`` was set in Redis. Caller reads Redis.
    """

    capital: float
    open_positions: Sequence[OpenPosition]
    daily_pnl: float
    daily_trade_count: int
    is_snapshot_window: bool
    regime: RegimeClassification
    proposed_sector: str = "UNKNOWN"
    proposed_returns: Sequence[float] = field(default_factory=list)
    use_kelly: bool = False
    win_rate: float | None = None
    avg_win_loss_ratio: float | None = None
    halted: bool = False


@dataclass(frozen=True)
class RiskDecision:
    """Output of a complete risk evaluation.

    Args:
        approved: True only when all checks passed and a valid size was computed.
        position_size: Computed sizing, or ``None`` if not approved.
        rejection_reason: First failing check's detail string, or ``None``.
        checks: All check outcomes in evaluation order.
    """

    approved: bool
    position_size: PositionSize | None
    rejection_reason: str | None
    checks: list[RiskCheck]
