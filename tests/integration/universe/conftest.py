"""Fixtures for M09 universe integration tests — need live TimescaleDB + Redis.

Follows the same pattern as tests/integration/regime/conftest.py.
Skips automatically when TimescaleDB is unreachable.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg2
import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.storage.connection import apply_schema
from shared.universe.repository import apply_universe_schema

TEST_DSN = "postgresql://trading:trading@localhost:5433/trading_ts"


@pytest.fixture(scope="session")
def pg_connection() -> Iterator[PGConnection]:
    try:
        conn = psycopg2.connect(TEST_DSN)
    except psycopg2.OperationalError:
        pytest.skip(
            f"No TimescaleDB reachable at {TEST_DSN} -- start one to run these"
        )
    apply_schema(conn)
    apply_universe_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clean_watchlist(pg_connection: PGConnection) -> Iterator[None]:
    def _truncate() -> None:
        with pg_connection.cursor() as cur:
            cur.execute("TRUNCATE watchlist_history")
        pg_connection.commit()

    _truncate()
    yield
    _truncate()
