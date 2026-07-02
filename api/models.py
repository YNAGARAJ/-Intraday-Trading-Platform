"""Pydantic response models for the M22 REST API."""

from __future__ import annotations

from pydantic import BaseModel


class SystemStatus(BaseModel):
    """Snapshot of trading system state returned by GET /api/v1/status."""

    trading_mode: str
    is_halted: bool
    is_paused: bool
    is_degraded: bool
    kill_switch_active: bool
    circuit_breaker_active: bool
    regime: str | None
    pnl_today: float
    pnl_today_pct: float
    open_positions_count: int
    signals_today: int
    trades_today: int
    reconciliation_mismatches: int
    timestamp_ms: int


class PositionOut(BaseModel):
    """Single open position returned by GET /api/v1/positions."""

    symbol: str
    exchange: str
    direction: str
    quantity: int
    entry_price: float


class SignalOut(BaseModel):
    """Single signal event returned by GET /api/v1/signals."""

    signal_id: str
    symbol: str
    exchange: str
    direction: str
    confidence: float
    strategy_tag: str
    timestamp_ms: int


class PnLOut(BaseModel):
    """Daily P&L summary returned by GET /api/v1/pnl."""

    date: str
    total_pnl: float
    total_pnl_pct: float
    starting_capital: float
    open_positions_count: int
    is_halted: bool


class WatchlistOut(BaseModel):
    """Single watchlist entry returned by GET /api/v1/watchlist."""

    symbol: str
    exchange: str
    composite_score: float | None = None


class ControlResponse(BaseModel):
    """Result of a POST /api/v1/controls/* action."""

    success: bool
    action: str
    reason: str
