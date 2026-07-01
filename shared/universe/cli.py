"""CLI entry point for the M09 stock universe filter.

Usage (standalone):
    python -m shared.universe \\
        --exchange NSE \\
        --lookback-days 5 \\
        --vix 18.5 \\
        --top-n 20

The CLI:
  1. Reads the current market regime from Redis (M08 stream) — falls back to
     BULL_TREND if no regime has been published yet.
  2. Fetches OHLCV candles from TimescaleDB for all instruments in the exchange.
  3. Fetches NSE compliance lists (with local JSON cache).
  4. Scores each instrument, applies compliance exclusions, and ranks the top-N.
  5. Stores the watchlist to TimescaleDB and caches it in Redis.
  6. Prints the ranked watchlist via structlog.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

from shared.core.config import load_settings
from shared.core.constants import (
    WATCHLIST_CANDLE_LOOKBACK_DAYS,
    WATCHLIST_TOP_N,
)
from shared.core.logging import configure_logging, get_logger
from shared.regime.models import MarketRegime
from shared.storage.connection import apply_schema, get_connection
from shared.storage.repositories import OHLCVRepository
from shared.universe.compliance import load_compliance_list
from shared.universe.filter import run_universe_filter
from shared.universe.repository import (
    apply_universe_schema,
    load_watchlist,
    store_watchlist,
)

logger = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M09: score and rank the intraday stock universe"
    )
    parser.add_argument(
        "--exchange", default="NSE", help="Exchange code (NSE or ASX)"
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=WATCHLIST_CANDLE_LOOKBACK_DAYS,
        help=(
            "Days of 5-min candle history to fetch "
            f"(default: {WATCHLIST_CANDLE_LOOKBACK_DAYS})"
        ),
    )
    parser.add_argument(
        "--vix",
        type=float,
        default=0.0,
        help="Current VIX level for regime override (0.0 = read from Redis)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=WATCHLIST_TOP_N,
        help=f"Maximum watchlist size (default: {WATCHLIST_TOP_N})",
    )
    parser.add_argument(
        "--regime",
        default=None,
        choices=[r.value for r in MarketRegime],
        help="Override regime (skips Redis read; useful for testing)",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Score only — do not write to TimescaleDB or Redis",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load and print the latest cached watchlist instead of re-scoring",
    )
    return parser.parse_args(argv)


def _read_regime_from_redis(settings: object, vix: float) -> MarketRegime:
    """Read the latest published regime from Redis; fall back to BULL_TREND."""
    try:
        import redis as redis_lib

        from shared.regime.publisher import read_latest_regime

        r = redis_lib.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url,  # type: ignore[attr-defined]
            decode_responses=False,
        )
        classification = read_latest_regime(r)
        if classification is not None:
            logger.info(
                "universe_regime_read_from_redis",
                regime=classification.regime.value,
            )
            return classification.regime
    except Exception as exc:  # noqa: BLE001
        logger.warning("universe_regime_redis_read_failed", error=str(exc))

    logger.warning("universe_regime_fallback", regime="BULL_TREND")
    return MarketRegime.BULL_TREND


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``python -m shared.universe``.

    Args:
        argv: Argument list; defaults to sys.argv[1:].
    """
    configure_logging()
    args = _parse_args(argv)
    settings = load_settings()

    try:
        conn = get_connection(settings)
    except psycopg2.OperationalError as exc:
        logger.error("db_connection_failed", error=str(exc))
        sys.exit(1)

    try:
        apply_schema(conn)
        apply_universe_schema(conn)

        if args.load:
            import redis as redis_lib

            r = redis_lib.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url, decode_responses=False
            )
            entries = load_watchlist(args.exchange, conn, r, top_n=args.top_n)
            if not entries:
                logger.info("universe_watchlist_empty", exchange=args.exchange)
            for e in entries:
                logger.info(
                    "watchlist_entry",
                    rank=e.rank,
                    symbol=e.symbol,
                    exchange=e.exchange,
                    composite_score=round(e.composite_score, 4),
                    strategy_id=e.strategy_id,
                    regime=e.regime.value,
                )
            return

        # Determine regime
        if args.regime:
            regime = MarketRegime(args.regime)
            logger.info("universe_regime_override", regime=regime.value)
        else:
            regime = _read_regime_from_redis(settings, args.vix)

        repo = OHLCVRepository(conn)
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=args.lookback_days)

        # Fetch all symbols for the exchange from the instrument master table
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM ohlcv_raw "
                "WHERE exchange = %s AND ts >= %s ORDER BY symbol",
                (args.exchange.upper(), start_dt),
            )
            symbols = [row[0] for row in cur.fetchall()]

        if not symbols:
            logger.warning(
                "universe_no_symbols_found", exchange=args.exchange
            )
            sys.exit(0)

        logger.info(
            "universe_fetching_candles",
            exchange=args.exchange,
            symbol_count=len(symbols),
        )

        candles_by_symbol: dict[str, dict[str, object]] = {}
        import numpy as np

        for sym in symbols:
            candles = repo.query_candles(
                symbol=sym,
                exchange=args.exchange,
                timeframe="5m",
                start=start_dt,
                end=end_dt,
            )
            if candles:
                candles_by_symbol[sym] = {
                    "close": np.array([c.close for c in candles], dtype=np.float64),
                    "high": np.array([c.high for c in candles], dtype=np.float64),
                    "low": np.array([c.low for c in candles], dtype=np.float64),
                    "volume": np.array([c.volume for c in candles], dtype=np.float64),
                }

        instruments = [
            {"symbol": sym, "exchange": args.exchange} for sym in symbols
        ]

        exclusion_list = load_compliance_list()
        logger.info(
            "universe_compliance_loaded",
            asm_count=len(exclusion_list.asm_symbols),
            esm_count=len(exclusion_list.esm_symbols),
            ban_count=len(exclusion_list.ban_symbols),
            mwpl_count=len(exclusion_list.mwpl_exceeded_symbols),
        )

        entries = run_universe_filter(
            instruments=instruments,
            candles_by_symbol=candles_by_symbol,  # type: ignore[arg-type]
            regime=regime,
            exclusion_list=exclusion_list,
            top_n=args.top_n,
        )

        for e in entries:
            logger.info(
                "watchlist_entry",
                rank=e.rank,
                symbol=e.symbol,
                exchange=e.exchange,
                composite_score=round(e.composite_score, 4),
                trend_score=round(e.components.trend_score, 4),
                vol_score=round(e.components.vol_score, 4),
                liq_score=round(e.components.liq_score, 4),
                strategy_id=e.strategy_id,
                regime=e.regime.value,
            )

        if not args.no_store and entries:
            import redis as redis_lib

            r = redis_lib.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url, decode_responses=False
            )
            store_watchlist(entries, conn, r)
            logger.info(
                "universe_stored",
                exchange=args.exchange,
                count=len(entries),
            )
        elif not entries:
            logger.warning("universe_watchlist_empty", exchange=args.exchange)

    finally:
        conn.close()
