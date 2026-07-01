"""Fixtures for M07 integration tests — needs a real TimescaleDB.

Applies both the storage schema (ohlcv_1m) and the backtest schema
(backtest_results table) before the test session starts, then truncates
all relevant tables between tests.
"""

from collections.abc import Iterator

import psycopg2
import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.backtesting.repository import apply_backtest_schema
from shared.storage.connection import apply_schema

TEST_DSN = "postgresql://trading:trading@localhost:5433/trading_ts"


@pytest.fixture(scope="session")
def pg_connection() -> Iterator[PGConnection]:
    try:
        conn = psycopg2.connect(TEST_DSN)
    except psycopg2.OperationalError:
        pytest.skip(f"No TimescaleDB reachable at {TEST_DSN} — start one to run these")
    apply_schema(conn)
    apply_backtest_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clean_state(pg_connection: PGConnection) -> Iterator[None]:
    def _truncate() -> None:
        with pg_connection.cursor() as cur:
            cur.execute("TRUNCATE ticks, ohlcv_1m")
            cur.execute("DELETE FROM backtest_results")
        pg_connection.commit()

    _truncate()
    yield
    _truncate()
