"""Fixtures for M04's integration tests -- needs both a real TimescaleDB and a real
Redis, so this gets its own subdirectory (mirroring tests/integration/redis/ and
tests/integration/timescale/) rather than reusing either of those conftest.py files
directly: an autouse fixture scoped to one of those directories wouldn't apply here,
and importing fixtures across sibling directories isn't how pytest fixture discovery
works. The connection logic itself is intentionally a thin duplicate of those two
conftests rather than a shared abstraction -- see CLAUDE.md's guidance against
premature abstraction for two ~10-line fixtures.
"""

from collections.abc import Iterator

import psycopg2
import pytest
import redis as redis_lib
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.storage.connection import apply_schema

TEST_DSN = "postgresql://trading:trading@localhost:5433/trading_ts"
REDIS_TEST_URL = "redis://localhost:6379/15"


@pytest.fixture(scope="session")
def pg_connection() -> Iterator[PGConnection]:
    try:
        conn = psycopg2.connect(TEST_DSN)
    except psycopg2.OperationalError:
        pytest.skip(f"No TimescaleDB reachable at {TEST_DSN} -- start one to run these")
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def redis_client() -> Iterator[redis_lib.Redis]:
    client = redis_lib.Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.ConnectionError:
        pytest.skip(f"No Redis reachable at {REDIS_TEST_URL} -- start one to run these")
    yield client
    client.close()  # type: ignore[no-untyped-call]  # redis-py 5.0.3 stub gap: close() is untyped


@pytest.fixture(autouse=True)
def _clean_state(
    pg_connection: PGConnection, redis_client: redis_lib.Redis
) -> Iterator[None]:
    def _truncate() -> None:
        with pg_connection.cursor() as cur:
            cur.execute("TRUNCATE ticks, ohlcv_1m")
        pg_connection.commit()

    _truncate()
    redis_client.flushdb()
    yield
    _truncate()
    redis_client.flushdb()
