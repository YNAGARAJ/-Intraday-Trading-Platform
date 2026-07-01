"""Standalone diagnostic CLI for the indicator engine.

    python -m shared.indicators --symbol RELIANCE.NS --exchange NSE --timeframe 5m

Queries `INDICATOR_LOOKBACK_CANDLES` worth of recent candles for the given
symbol/exchange/timeframe from TimescaleDB, computes every registered indicator,
caches the result in Redis, and prints a summary including the compute+cache latency
(the M04 VERIFY metric: must stay under `INDICATOR_LATENCY_BUDGET_MS`).

If no candles exist yet for the requested symbol (e.g. nothing has been backfilled),
this reports zero rows and exits cleanly rather than crashing -- the same
graceful-degradation pattern M03's backfill CLI uses for an unreachable data source.
"""

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta

import psycopg2
import redis as redis_lib

from shared.core.config import load_settings
from shared.core.constants import (
    INDICATOR_LATENCY_BUDGET_MS,
    INDICATOR_LOOKBACK_CANDLES,
)
from shared.core.logging import configure_logging, get_logger
from shared.core.types import AppId
from shared.indicators.cache import store_snapshot
from shared.indicators.engine import compute_snapshot
from shared.storage.connection import apply_schema, get_connection
from shared.storage.repositories import OHLCVRepository

logger = get_logger(__name__)

_TIMEFRAME_TO_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def main() -> None:
    parser = argparse.ArgumentParser(description="Indicator engine diagnostic CLI")
    parser.add_argument("--symbol", default="RELIANCE.NS")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument(
        "--timeframe", default="5m", choices=sorted(_TIMEFRAME_TO_MINUTES)
    )
    args = parser.parse_args()

    configure_logging("INFO")
    # app_id is arbitrary here -- only settings.timescale_dsn/redis_url are used.
    settings = load_settings(app_id=AppId.INDIA)
    try:
        conn = get_connection(settings)
    except psycopg2.OperationalError as exc:
        logger.error("db_connection_failed", error=str(exc))
        sys.exit(1)
    redis_client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        apply_schema(conn)
        repository = OHLCVRepository(conn)

        lookback_minutes = (
            _TIMEFRAME_TO_MINUTES[args.timeframe] * INDICATOR_LOOKBACK_CANDLES
        )
        end = datetime.now(UTC)
        start = end - timedelta(minutes=lookback_minutes)
        candles = repository.query_candles(
            args.symbol, args.exchange, args.timeframe, start, end
        )

        if not candles:
            logger.info(
                "no_candles_found",
                symbol=args.symbol,
                exchange=args.exchange,
                timeframe=args.timeframe,
            )
            return

        t0 = time.perf_counter()
        snapshot = compute_snapshot(args.symbol, args.exchange, args.timeframe, candles)
        store_snapshot(redis_client, snapshot)
        latency_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "indicators_computed",
            symbol=args.symbol,
            exchange=args.exchange,
            timeframe=args.timeframe,
            candle_count=len(candles),
            indicator_count=len(snapshot.values),
            latency_ms=round(latency_ms, 3),
            latency_budget_ms=INDICATOR_LATENCY_BUDGET_MS,
            within_budget=latency_ms < INDICATOR_LATENCY_BUDGET_MS,
        )
        for name, output in snapshot.values.items():
            if output:
                logger.info("indicator_result", name=name, **output)
    finally:
        redis_client.close()  # type: ignore[no-untyped-call]
        conn.close()


if __name__ == "__main__":
    main()
