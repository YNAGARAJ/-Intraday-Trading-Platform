"""Shared data models for the storage layer: raw ticks and OHLCV candles.

Owned by M03 since it's the module that defines what gets persisted; M04 (indicators),
M16 (ingestion), and others import these rather than redefining their own shapes.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Tick:
    """A single raw market tick."""

    time: datetime
    symbol: str
    exchange: str
    price: float
    volume: int
    bid: float | None = None
    ask: float | None = None


@dataclass(frozen=True)
class OHLCVCandle:
    """A single OHLCV candle at some timeframe."""

    time: datetime
    symbol: str
    exchange: str
    open: float
    high: float
    low: float
    close: float
    volume: int
