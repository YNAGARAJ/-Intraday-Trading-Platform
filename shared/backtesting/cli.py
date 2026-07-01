"""CLI entry point for the M07 backtesting engine.

Usage (standalone):
    python -m shared.backtesting \\
        --symbol RELIANCE --exchange NSE \\
        --strategy ema_crossover \\
        --start-date 2023-01-01 --end-date 2023-12-31 \\
        --report-dir /tmp/backtest_reports

The CLI:
  1. Connects to TimescaleDB and queries adjusted OHLCV candles for the period.
  2. Generates entry/exit signals for the requested strategy.
  3. Runs the vectorbt backtest with log-normal slippage injection.
  4. Generates HTML + CSV reports.
  5. Stores results in the `backtest_results` PostgreSQL table.
  6. Logs the promotion gate outcome (RULE 6).

Currently supported strategies: ema_crossover (EMA 9/21 crossover long-only).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

import psycopg2

from shared.backtesting.engine import ema_crossover_signals, run_backtest
from shared.backtesting.models import BacktestConfig
from shared.backtesting.report import generate_reports
from shared.backtesting.repository import apply_backtest_schema, save_result
from shared.core.config import load_settings
from shared.core.logging import configure_logging, get_logger
from shared.instruments.adjustment import adjusted_candles
from shared.instruments.models import CorporateAction
from shared.storage.connection import apply_schema, get_connection
from shared.storage.repositories import OHLCVRepository

logger = get_logger(__name__)

_SUPPORTED_STRATEGIES = ("ema_crossover",)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M07: run a strategy backtest and generate reports"
    )
    parser.add_argument("--symbol", default="RELIANCE", help="Instrument symbol")
    parser.add_argument("--exchange", default="NSE", help="Exchange code (NSE or ASX)")
    parser.add_argument(
        "--strategy",
        default="ema_crossover",
        choices=_SUPPORTED_STRATEGIES,
        help="Strategy to backtest",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Backtest start date YYYY-MM-DD (default: 1 year ago)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Backtest end date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--timeframe",
        default="1m",
        help="Candle timeframe to query (default: 1m)",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory for HTML/CSV reports (default: system temp dir)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip saving results to PostgreSQL (useful for dry runs)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for `python -m shared.backtesting`.

    Args:
        argv: Argument list; defaults to sys.argv[1:].
    """
    configure_logging()
    args = _parse_args(argv)

    end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start_date = (
        date.fromisoformat(args.start_date)
        if args.start_date
        else end_date - timedelta(days=365)
    )

    report_dir = args.report_dir or tempfile.mkdtemp(prefix="backtest_")
    settings = load_settings()
    try:
        conn = get_connection(settings)
    except psycopg2.OperationalError as exc:
        logger.error("db_connection_failed", error=str(exc))
        sys.exit(1)
    try:
        apply_schema(conn)
        apply_backtest_schema(conn)

        repo = OHLCVRepository(conn)
        start_dt = datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
        )
        end_dt = datetime(
            end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc
        )
        raw_candles = repo.query_candles(
            symbol=args.symbol,
            exchange=args.exchange,
            timeframe=args.timeframe,
            start=start_dt,
            end=end_dt,
        )

        if not raw_candles:
            logger.info(
                "no_candles_found",
                symbol=args.symbol,
                exchange=args.exchange,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
            )
            return

        # Apply corporate-action adjustments (M05) — empty list when none available
        actions: list[CorporateAction] = []
        candles = adjusted_candles(raw_candles, actions)

        logger.info(
            "backtest_starting",
            symbol=args.symbol,
            exchange=args.exchange,
            strategy=args.strategy,
            candles=len(candles),
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

        config = BacktestConfig(
            strategy_id="EMA9X21",
            symbol=args.symbol,
            exchange=args.exchange,
            start_date=start_date,
            end_date=end_date,
        )

        if args.strategy == "ema_crossover":
            entries, exits = ema_crossover_signals(candles)
        else:
            logger.error("unsupported_strategy", strategy=args.strategy)
            sys.exit(1)

        result = run_backtest(config, candles, entries, exits)
        result = generate_reports(result, report_dir)

        if not args.no_db:
            save_result(result, conn)

        logger.info(
            "backtest_done",
            run_id=result.run_id,
            trades=result.metrics.total_trades,
            sharpe=result.metrics.sharpe_ratio,
            max_dd_pct=result.metrics.max_drawdown_pct,
            win_rate_pct=result.metrics.win_rate_pct,
            passed_gate=result.passed_promotion_gate,
            html_report=result.report_html_path,
            csv_report=result.report_csv_path,
        )

        if not result.passed_promotion_gate:
            logger.warning(
                "promotion_gate_failed",
                failures=result.promotion_failures,
            )

    finally:
        conn.close()
