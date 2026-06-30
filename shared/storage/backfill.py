"""Dev-only yfinance historical OHLCV backfill utility.

NEVER used for live entry signals (per spec: yfinance is for dev historical backfill
only). Standalone runnable:

    python -m shared.storage.backfill --symbol RELIANCE.NS --days 30

CAVEAT: Yahoo Finance's public API is rate-limited per source IP and returned HTTP 429
for every request tried from this build's sandboxed network -- confirmed for both an
NSE symbol and well-known US tickers, so it isn't symbol-specific. The implementation
below is correct against yfinance's documented interface (`fetch_history` is injectable
for testing); re-verify reachability in your actual deployment environment. See
tests/integration/test_yfinance_backfill_live.py.
"""

import argparse
from typing import Protocol, cast

import pandas as pd
import yfinance as yf

from shared.core.config import load_settings
from shared.core.logging import configure_logging, get_logger
from shared.core.types import AppId
from shared.storage.connection import apply_schema, get_connection
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

logger = get_logger(__name__)

ONE_MINUTE_INTERVAL = "1m"
COARSE_BACKFILL_INTERVAL = "5m"
ONE_MINUTE_MAX_BACKFILL_DAYS = 7
"""Yahoo Finance only serves 1-minute data for the trailing ~7 days; longer backfills
must request a coarser interval (5m, good for up to ~60 days)."""


def _exchange_for_symbol(symbol: str) -> str:
    if symbol.endswith((".NS", ".BO")):
        return "NSE"
    if symbol.endswith(".AX"):
        return "ASX"
    return "UNKNOWN"


class HistoryFetcher(Protocol):
    def __call__(self, symbol: str, period: str, interval: str) -> pd.DataFrame: ...


class OHLCVWriter(Protocol):
    """What `backfill()` needs from a repository -- structurally satisfied by
    `OHLCVRepository`, and by any test double exposing just `upsert_1m`."""

    def upsert_1m(self, candles: list[OHLCVCandle]) -> int: ...


def _default_fetch_history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    history: pd.DataFrame = yf.Ticker(symbol).history(period=period, interval=interval)
    return history


def candles_from_history(
    symbol: str, exchange: str, df: pd.DataFrame
) -> list[OHLCVCandle]:
    """Convert a yfinance `history()` DataFrame into `OHLCVCandle` rows.

    Each row becomes one `ohlcv_1m` table row at its own native granularity (5m when
    backfilling beyond `ONE_MINUTE_MAX_BACKFILL_DAYS`) -- the 5m/15m/1h continuous
    aggregates still roll these up correctly, since each time bucket simply contains
    whichever rows actually exist for it.
    """
    candles = []
    for index, row in df.iterrows():
        # df.iterrows() types the index as Hashable; at runtime it's always a
        # pandas Timestamp for a yfinance history DataFrame's DatetimeIndex.
        timestamp = cast(pd.Timestamp, index)
        candles.append(
            OHLCVCandle(
                time=timestamp.to_pydatetime(),
                symbol=symbol,
                exchange=exchange,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
            )
        )
    return candles


def backfill(
    symbol: str,
    days: int,
    repository: OHLCVWriter,
    exchange: str | None = None,
    fetch_history: HistoryFetcher = _default_fetch_history,
) -> int:
    """Fetch `days` of history for `symbol` and write it to `ohlcv_1m`.

    Args:
        symbol: yfinance ticker symbol (e.g. "RELIANCE.NS").
        days: Number of trailing days to backfill.
        repository: Target `OHLCVRepository`.
        exchange: Exchange code; inferred from the symbol suffix if not given.
        fetch_history: Injectable for testing -- defaults to a real yfinance call.

    Returns:
        Number of candle rows written.
    """
    resolved_exchange = exchange or _exchange_for_symbol(symbol)
    interval = (
        ONE_MINUTE_INTERVAL
        if days <= ONE_MINUTE_MAX_BACKFILL_DAYS
        else COARSE_BACKFILL_INTERVAL
    )

    df = fetch_history(symbol, period=f"{days}d", interval=interval)
    candles = candles_from_history(symbol, resolved_exchange, df)
    written = repository.upsert_1m(candles)

    logger.info(
        "backfill_complete",
        symbol=symbol,
        exchange=resolved_exchange,
        days=days,
        interval=interval,
        rows=written,
    )
    return written


def main() -> None:
    """CLI entrypoint: `python -m shared.storage.backfill --symbol ... --days ...`."""
    parser = argparse.ArgumentParser(description="yfinance OHLCV backfill (dev only)")
    parser.add_argument("--symbol", default="RELIANCE.NS")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    configure_logging("INFO")
    # app_id is arbitrary here -- only settings.timescale_dsn is used by this CLI.
    settings = load_settings(app_id=AppId.INDIA)
    conn = get_connection(settings)
    try:
        apply_schema(conn)
        repository = OHLCVRepository(conn)
        backfill(args.symbol, args.days, repository)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
