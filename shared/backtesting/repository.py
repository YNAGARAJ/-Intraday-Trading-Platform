"""PostgreSQL storage for backtest results.

Stores the BacktestResult summary in the `backtest_results` table (defined in
shared/backtesting/schema.sql). Individual trade records are kept in the CSV
report; only the aggregated metrics row is stored in the DB for trend tracking
and model-promotion gate history.

Schema is applied by calling `apply_backtest_schema(conn)` before the first write.
"""

from __future__ import annotations

import json

import psycopg2
import psycopg2.extensions

from shared.backtesting.models import BacktestResult
from shared.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS backtest_results (
    run_id              TEXT        PRIMARY KEY,
    strategy_id         TEXT        NOT NULL,
    symbol              TEXT        NOT NULL,
    exchange            TEXT        NOT NULL,
    start_date          DATE        NOT NULL,
    end_date            DATE        NOT NULL,
    total_trades        INTEGER     NOT NULL,
    trading_days        INTEGER     NOT NULL,
    sharpe_ratio        DOUBLE PRECISION,
    sortino_ratio       DOUBLE PRECISION,
    max_drawdown_pct    DOUBLE PRECISION,
    win_rate_pct        DOUBLE PRECISION,
    total_return_pct    DOUBLE PRECISION,
    annualized_return_pct DOUBLE PRECISION,
    profit_factor       DOUBLE PRECISION,
    calmar_ratio        DOUBLE PRECISION,
    avg_slippage_bps    DOUBLE PRECISION,
    passed_promotion_gate BOOLEAN   NOT NULL,
    promotion_failures  JSONB,
    report_html_path    TEXT,
    report_csv_path     TEXT,
    completed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_INSERT_SQL = """
INSERT INTO backtest_results (
    run_id, strategy_id, symbol, exchange, start_date, end_date,
    total_trades, trading_days,
    sharpe_ratio, sortino_ratio, max_drawdown_pct, win_rate_pct,
    total_return_pct, annualized_return_pct, profit_factor, calmar_ratio,
    avg_slippage_bps, passed_promotion_gate, promotion_failures,
    report_html_path, report_csv_path, completed_at
) VALUES (
    %(run_id)s, %(strategy_id)s, %(symbol)s, %(exchange)s,
    %(start_date)s, %(end_date)s,
    %(total_trades)s, %(trading_days)s,
    %(sharpe_ratio)s, %(sortino_ratio)s, %(max_drawdown_pct)s, %(win_rate_pct)s,
    %(total_return_pct)s, %(annualized_return_pct)s,
    %(profit_factor)s, %(calmar_ratio)s,
    %(avg_slippage_bps)s, %(passed_promotion_gate)s, %(promotion_failures)s,
    %(report_html_path)s, %(report_csv_path)s, %(completed_at)s
)
ON CONFLICT (run_id) DO UPDATE SET
    passed_promotion_gate = EXCLUDED.passed_promotion_gate,
    report_html_path      = EXCLUDED.report_html_path,
    report_csv_path       = EXCLUDED.report_csv_path;
"""


def apply_backtest_schema(conn: psycopg2.extensions.connection) -> None:
    """Create backtest_results table if it does not yet exist.

    Idempotent — safe to call on every startup.

    Args:
        conn: Open psycopg2 connection to the TimescaleDB / PostgreSQL instance.
    """
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)
    conn.commit()
    logger.debug("backtest_schema_applied")


def save_result(
    result: BacktestResult,
    conn: psycopg2.extensions.connection,
) -> None:
    """Persist a BacktestResult summary row to the `backtest_results` table.

    Args:
        result: Completed backtest result. `report_html_path` and
            `report_csv_path` may be None if reports have not been generated.
        conn: Open psycopg2 connection.
    """
    m = result.metrics
    params = {
        "run_id": result.run_id,
        "strategy_id": result.config.strategy_id,
        "symbol": result.config.symbol,
        "exchange": result.config.exchange,
        "start_date": result.config.start_date,
        "end_date": result.config.end_date,
        "total_trades": m.total_trades,
        "trading_days": m.trading_days,
        "sharpe_ratio": m.sharpe_ratio,
        "sortino_ratio": m.sortino_ratio,
        "max_drawdown_pct": m.max_drawdown_pct,
        "win_rate_pct": m.win_rate_pct,
        "total_return_pct": m.total_return_pct,
        "annualized_return_pct": m.annualized_return_pct,
        "profit_factor": m.profit_factor,
        "calmar_ratio": m.calmar_ratio,
        "avg_slippage_bps": m.avg_slippage_bps,
        "passed_promotion_gate": result.passed_promotion_gate,
        "promotion_failures": json.dumps(result.promotion_failures),
        "report_html_path": result.report_html_path,
        "report_csv_path": result.report_csv_path,
        "completed_at": result.completed_at,
    }
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, params)
    conn.commit()
    logger.info(
        "backtest_result_saved",
        run_id=result.run_id,
        strategy_id=result.config.strategy_id,
        symbol=result.config.symbol,
    )


def load_result(
    run_id: str,
    conn: psycopg2.extensions.connection,
) -> dict[str, object] | None:
    """Load a stored backtest summary row by run_id.

    Returns the row as a plain dict, or None when not found.

    Args:
        run_id: The 8-character hex run identifier.
        conn: Open psycopg2 connection.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, strategy_id, symbol, sharpe_ratio, "
            "max_drawdown_pct, win_rate_pct, passed_promotion_gate "
            "FROM backtest_results WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "run_id": row[0],
        "strategy_id": row[1],
        "symbol": row[2],
        "sharpe_ratio": row[3],
        "max_drawdown_pct": row[4],
        "win_rate_pct": row[5],
        "passed_promotion_gate": row[6],
    }
