"""CLI entry point for the M08 market regime classifier.

Usage (standalone):
    python -m shared.regime \\
        --symbol NIFTY50 --exchange NSE \\
        --lookback-days 30 \\
        --vix 18.5

The CLI:
  1. Connects to TimescaleDB and queries 5-minute OHLCV candles.
  2. Extracts RegimeFeatures from the most recent REGIME_FEATURE_LOOKBACK bars.
  3. Classifies the current regime via rule-based (no MLflow) or model-based
     (if --run-id provided) inference.
  4. Prints the classification result and publishes to Redis if --publish flag
     is set.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

from shared.core.config import load_settings
from shared.core.constants import REGIME_FEATURE_LOOKBACK
from shared.core.logging import configure_logging, get_logger
from shared.regime.classifier import RegimeClassifier
from shared.regime.features import extract_features
from shared.regime.models import MarketRegime
from shared.storage.connection import apply_schema, get_connection
from shared.storage.repositories import OHLCVRepository

logger = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M08: classify current market regime from OHLCV candles"
    )
    parser.add_argument("--symbol", default="NIFTY50", help="Instrument symbol")
    parser.add_argument(
        "--exchange", default="NSE", help="Exchange code (NSE or ASX)"
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=5,
        help="Days of 5-min candles to fetch (default: 5)",
    )
    parser.add_argument(
        "--vix",
        type=float,
        default=0.0,
        help="Current VIX level (0.0 = unavailable)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="MLflow run ID to load a fitted classifier (omit for rule-based)",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish result to Redis Streams (requires REDIS_URL env var)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB connection (for dry-run with --run-id only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``python -m shared.regime``.

    Args:
        argv: Argument list; defaults to sys.argv[1:].
    """
    configure_logging()
    args = _parse_args(argv)

    # Load fitted classifier from MLflow when run-id is provided
    classifier: RegimeClassifier
    if args.run_id:
        from shared.regime.mlflow_registry import load_classifier

        classifier = load_classifier(args.run_id)
        logger.info("regime_classifier_loaded_from_mlflow", run_id=args.run_id)
    else:
        classifier = RegimeClassifier()
        logger.info("regime_using_rule_based_classifier")

    if args.no_db:
        logger.warning(
            "no_db_mode: cannot fetch candles; use --run-id with live data"
        )
        sys.exit(0)

    settings = load_settings()
    try:
        conn = get_connection(settings)
    except psycopg2.OperationalError as exc:
        logger.error("db_connection_failed", error=str(exc))
        sys.exit(1)
    try:
        apply_schema(conn)
        repo = OHLCVRepository(conn)

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=args.lookback_days)

        candles = repo.query_candles(
            symbol=args.symbol,
            exchange=args.exchange,
            timeframe="5m",
            start=start_dt,
            end=end_dt,
        )

        if len(candles) < REGIME_FEATURE_LOOKBACK:
            logger.error(
                "insufficient_candles",
                symbol=args.symbol,
                exchange=args.exchange,
                available=len(candles),
                required=REGIME_FEATURE_LOOKBACK,
            )
            sys.exit(1)

        features = extract_features(candles, vix=args.vix)
        classification = classifier.classify(features)

        logger.info(
            "regime_classification_result",
            symbol=args.symbol,
            exchange=args.exchange,
            regime=classification.regime.value,
            confidence=classification.confidence,
            adx=features.adx,
            rsi=features.rsi,
            vwap_deviation_pct=features.vwap_deviation_pct,
            vix=features.vix,
            atr_spike=features.atr_spike,
        )

        if classification.regime == MarketRegime.HIGH_VOL_CHAOS:
            logger.warning(
                "HIGH_VOL_CHAOS_detected_new_entries_blocked",
                symbol=args.symbol,
            )

        if args.publish:
            import redis as redis_lib

            r = redis_lib.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url, decode_responses=False
            )
            from shared.regime.publisher import publish_regime_change

            entry_id = publish_regime_change(classification, r)
            logger.info("regime_published_to_stream", entry_id=entry_id)

    finally:
        conn.close()
