"""yfinance REST fallback for M16 Data Ingestion Agent.

Used when the primary WebSocket feed drops.  Fetches recent 1-minute bars and
converts them to synthetic ``RawTick`` objects (one tick per bar, at bar close).

This fallback triggers ``DEGRADED_EXIT_ONLY`` mode — the calling agent blocks
new entry signals until the WebSocket reconnects.

yfinance is dev-only (per CLAUDE.md: never for live signals).  In production this
path should be reached only transiently during a WS outage.
"""

from __future__ import annotations

import time

import structlog

from shared.ingestion.models import RawTick

logger = structlog.get_logger(__name__)

_NSE_SUFFIX = ".NS"
_BSE_SUFFIX = ".BO"
_ASX_SUFFIX = ".AX"


def _yf_ticker(symbol: str, exchange: str) -> str:
    """Build a yfinance ticker string from symbol + exchange."""
    if exchange in ("NSE", "BSE"):
        suffix = _NSE_SUFFIX if exchange == "NSE" else _BSE_SUFFIX
        return f"{symbol}{suffix}"
    if exchange == "ASX":
        return f"{symbol}{_ASX_SUFFIX}"
    return symbol


class YFinanceFallback:
    """Fetches recent 1-minute bars from Yahoo Finance as synthetic ticks.

    Each 1-minute OHLCV bar is converted to a single synthetic tick at the bar
    close time.  Volume is the full bar volume.

    Args:
        period_minutes: How many minutes of history to fetch (default 5).
    """

    def __init__(self, period_minutes: int = 5) -> None:
        self._period_minutes = period_minutes

    def fetch_ticks(self, symbol: str, exchange: str) -> list[RawTick]:
        """Fetch recent synthetic ticks for a symbol.

        Args:
            symbol: Instrument symbol (e.g. ``"RELIANCE"``).
            exchange: Exchange (``"NSE"``, ``"BSE"``, ``"ASX"``).

        Returns:
            List of synthetic ``RawTick`` objects (one per 1m bar), most recent last.
            Returns empty list on any error (fail-open, never raises).
        """
        try:
            import yfinance as yf  # noqa: PLC0415
        except ImportError:
            logger.warning("yfinance_not_installed_fallback_returning_empty")
            return []

        ticker_str = _yf_ticker(symbol, exchange)
        try:
            df = yf.download(
                ticker_str,
                period=f"{self._period_minutes + 1}m",
                interval="1m",
                progress=False,
                auto_adjust=True,
            )
            if df is None or df.empty:
                logger.warning(
                    "yfinance_no_data",
                    symbol=symbol,
                    exchange=exchange,
                    ticker=ticker_str,
                )
                return []

            ticks: list[RawTick] = []
            for idx, row in df.iterrows():
                close_price = float(row["Close"])
                volume = int(row["Volume"])
                ts_ms = int(idx.timestamp() * 1000)
                if close_price <= 0:
                    continue
                ticks.append(
                    RawTick(
                        symbol=symbol,
                        exchange=exchange,
                        ltp=close_price,
                        volume=volume,
                        timestamp_ms=ts_ms,
                    )
                )
            logger.info(
                "yfinance_fallback_ticks_fetched",
                symbol=symbol,
                exchange=exchange,
                count=len(ticks),
            )
            return ticks

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "yfinance_fallback_error",
                symbol=symbol,
                exchange=exchange,
                error=str(exc),
            )
            return []

    def fetch_synthetic_ticks(
        self,
        symbol: str,
        exchange: str,
        base_price: float = 100.0,
        count: int = 5,
    ) -> list[RawTick]:
        """Generate deterministic synthetic ticks for paper/test mode.

        Used by VERIFY scenarios without needing a real network call.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier.
            base_price: Starting LTP for synthetic ticks.
            count: Number of ticks to generate.

        Returns:
            List of synthetic ``RawTick`` objects at 1-second intervals.
        """
        now_ms = int(time.time() * 1000)
        ticks = []
        for i in range(count):
            ticks.append(
                RawTick(
                    symbol=symbol,
                    exchange=exchange,
                    ltp=round(base_price + i * 0.05, 2),
                    volume=100 + i * 10,
                    timestamp_ms=now_ms - (count - i) * 1_000,
                )
            )
        return ticks
