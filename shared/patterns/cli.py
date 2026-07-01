"""Standalone diagnostic CLI for the pattern recognition engine.

    python -m shared.patterns --symbol RELIANCE --exchange NSE --timeframe 5m

Queries the last `SR_LOOKBACK_CANDLES` (100) candles for the given
symbol/exchange/timeframe from TimescaleDB, computes candlestick patterns, ORB state,
and S/R levels, then logs the results. Exits cleanly with a `no_candles_found` event
when no data exists for the symbol -- same graceful-degradation pattern as M03/M04/M05.

Passing --timeframes 1m,5m,15m runs multi-timeframe analysis instead.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

import psycopg2

from shared.core.config import load_settings
from shared.core.constants import SR_LOOKBACK_CANDLES
from shared.core.logging import configure_logging, get_logger
from shared.core.types import AppId
from shared.patterns.engine import compute_multi_timeframe, compute_snapshot
from shared.patterns.models import PatternSnapshot
from shared.storage.connection import apply_schema, get_connection
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

logger = get_logger(__name__)

_TIMEFRAME_TO_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def main() -> None:
    """Entry point for `python -m shared.patterns`."""
    parser = argparse.ArgumentParser(description="Pattern recognition engine CLI")
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument(
        "--timeframe",
        default="5m",
        choices=sorted(_TIMEFRAME_TO_MINUTES),
        help="Primary timeframe (used when --timeframes is not set).",
    )
    parser.add_argument(
        "--timeframes",
        default="",
        help="Comma-separated list for multi-timeframe analysis, e.g. '1m,5m,15m'.",
    )
    args = parser.parse_args()

    configure_logging("INFO")
    settings = load_settings(app_id=AppId.INDIA)
    try:
        conn = get_connection(settings)
    except psycopg2.OperationalError as exc:
        logger.error("db_connection_failed", error=str(exc))
        sys.exit(1)
    try:
        apply_schema(conn)
        repository = OHLCVRepository(conn)

        requested_tfs = (
            [tf.strip() for tf in args.timeframes.split(",") if tf.strip()]
            if args.timeframes
            else [args.timeframe]
        )

        end = datetime.now(UTC)

        if len(requested_tfs) == 1:
            tf = requested_tfs[0]
            mins = _TIMEFRAME_TO_MINUTES.get(tf, 5)
            start = end - timedelta(minutes=mins * SR_LOOKBACK_CANDLES)
            candles = repository.query_candles(
                args.symbol, args.exchange, tf, start, end
            )
            if not candles:
                logger.info(
                    "no_candles_found",
                    symbol=args.symbol,
                    exchange=args.exchange,
                    timeframe=tf,
                )
                return
            snapshot = compute_snapshot(args.symbol, args.exchange, tf, candles)
            _log_snapshot(snapshot)
        else:
            tf_candles: dict[str, list[OHLCVCandle]] = {}
            for tf in requested_tfs:
                mins = _TIMEFRAME_TO_MINUTES.get(tf, 5)
                start = end - timedelta(minutes=mins * SR_LOOKBACK_CANDLES)
                candles = repository.query_candles(
                    args.symbol, args.exchange, tf, start, end
                )
                tf_candles[tf] = list(candles)
            if not any(tf_candles.values()):
                logger.info(
                    "no_candles_found_any_timeframe",
                    symbol=args.symbol,
                    exchange=args.exchange,
                    timeframes=requested_tfs,
                )
                return
            mtf = compute_multi_timeframe(args.symbol, args.exchange, tf_candles)
            logger.info(
                "multi_timeframe_result",
                symbol=args.symbol,
                exchange=args.exchange,
                timeframes=requested_tfs,
                confirmed_bullish=mtf.confirmed_bullish_patterns,
                confirmed_bearish=mtf.confirmed_bearish_patterns,
            )
            for _tf, snap in mtf.snapshots.items():
                _log_snapshot(snap)
    finally:
        conn.close()


def _log_snapshot(snapshot: PatternSnapshot) -> None:
    """Log a PatternSnapshot's contents at INFO level."""
    if not isinstance(snapshot, PatternSnapshot):
        return

    recent_cdl = [
        s
        for s in snapshot.candlestick_signals
        if s.bar_index >= max(0, len(snapshot.candlestick_signals) - 10)
    ]
    logger.info(
        "pattern_snapshot",
        symbol=snapshot.symbol,
        exchange=snapshot.exchange,
        timeframe=snapshot.timeframe,
        candle_time=snapshot.candle_time.isoformat(),
        total_cdl_signals=len(snapshot.candlestick_signals),
        recent_cdl_signals=[
            {"name": s.name, "direction": s.direction, "bar": s.bar_index}
            for s in recent_cdl
        ],
        sr_level_count=len(snapshot.sr_levels),
        sr_levels=[
            {
                "price": lv.price,
                "type": lv.level_type,
                "touches": lv.touches,
                "strength": round(lv.strength, 3),
            }
            for lv in snapshot.sr_levels
        ],
        orb_formed=(
            snapshot.orb_state.range_formed if snapshot.orb_state is not None else False
        ),
        orb_high=(
            snapshot.orb_state.orb_high
            if snapshot.orb_state is not None and snapshot.orb_state.range_formed
            else None
        ),
        orb_low=(
            snapshot.orb_state.orb_low
            if snapshot.orb_state is not None and snapshot.orb_state.range_formed
            else None
        ),
        orb_breakout_direction=(
            snapshot.orb_state.breakout_direction
            if snapshot.orb_state is not None
            else None
        ),
    )
