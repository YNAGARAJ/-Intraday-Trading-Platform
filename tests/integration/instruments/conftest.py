"""TimescaleDB-backed fixtures, scoped to tests/integration/instruments/ only --
same rationale as tests/integration/timescale/conftest.py (a sibling directory): an
autouse cleanup fixture here must not leak into unrelated integration tests.
"""

from collections.abc import Iterator

import psycopg2
import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.storage.connection import apply_schema

TEST_DSN = "postgresql://trading:trading@localhost:5433/trading_ts"


@pytest.fixture(scope="session")
def pg_connection() -> Iterator[PGConnection]:
    try:
        conn = psycopg2.connect(TEST_DSN)
    except psycopg2.OperationalError:
        pytest.skip(f"No TimescaleDB reachable at {TEST_DSN} -- start one to run these")
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clean_tables(pg_connection: PGConnection) -> Iterator[None]:
    def _truncate() -> None:
        with pg_connection.cursor() as cur:
            cur.execute("TRUNCATE ticks, ohlcv_1m, instruments, corporate_actions")
        pg_connection.commit()

    _truncate()
    yield
    _truncate()
