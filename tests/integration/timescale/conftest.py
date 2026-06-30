"""TimescaleDB-backed fixtures, scoped to tests/integration/timescale/ only.

Deliberately not in tests/integration/conftest.py -- see the equivalent note in
tests/integration/redis/conftest.py for why autouse DB-specific fixtures must stay
scoped to their own subdirectory rather than leaking into unrelated integration tests.

These tests require a real TimescaleDB server. The fixture skips the whole module if
nothing is reachable, so `pytest` stays green on a bare host with no Docker -- bring
one up to actually exercise these:

    docker run --rm -d --name trading-test-timescale -p 5433:5432 \\
        -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=trading \\
        -e POSTGRES_DB=trading_ts timescale/timescaledb:2.14.0-pg16
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
            cur.execute("TRUNCATE ticks, ohlcv_1m")
        pg_connection.commit()

    _truncate()
    yield
    _truncate()
