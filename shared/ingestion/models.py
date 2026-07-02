"""Data models for M16 Data Ingestion Agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IngestionStatus(str, Enum):
    """Operational state of the Data Ingestion Agent."""

    LIVE = "LIVE"
    """Primary WebSocket active; full data quality guaranteed."""

    DEGRADED = "DEGRADED"
    """WebSocket down; REST/yfinance fallback active.
    System enters DEGRADED_EXIT_ONLY mode: new entries blocked, exits managed."""

    PAPER = "PAPER"
    """Paper/simulation mode; synthetic ticks injected directly."""


@dataclass(frozen=True)
class RawTick:
    """A single market data tick from a broker feed.

    Args:
        symbol: Instrument symbol (e.g. ``"RELIANCE"``).
        exchange: Exchange identifier (``"NSE"``, ``"BSE"``, ``"ASX"``).
        ltp: Last traded price (must be > 0).
        volume: Trade volume for **this tick only** (not cumulative).
            Adapters are responsible for converting cumulative feed volume to per-tick.
        timestamp_ms: Unix epoch milliseconds at which the trade occurred.
    """

    symbol: str
    exchange: str
    ltp: float
    volume: int
    timestamp_ms: int


@dataclass(frozen=True)
class OHLCVCandle:
    """A completed OHLCV bar aggregated from raw ticks.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange identifier.
        interval_seconds: Bar duration in seconds (60 for 1m, 300 for 5m).
        open: Price of the first tick in the bar.
        high: Maximum price seen in the bar.
        low: Minimum price seen in the bar.
        close: Price of the last tick in the bar.
        volume: Total volume across all ticks in the bar.
        timestamp_ms: Bar start time (Unix epoch milliseconds, rounded to interval).
        tick_count: Number of ticks that contributed to this bar.
    """

    symbol: str
    exchange: str
    interval_seconds: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp_ms: int
    tick_count: int = 0


class TickValidationError(Exception):
    """Raised by TickSequenceValidator when a tick fails validation."""
