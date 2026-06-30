"""Integration test for shared.storage.connection.get_connection."""

from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.core.config import Settings
from shared.core.types import AppId
from shared.storage.connection import get_connection
from tests.integration.timescale.conftest import TEST_DSN


def test_get_connection_returns_working_connection(pg_connection: PGConnection) -> None:
    # `pg_connection` is requested only to reuse its skip-if-unreachable check above;
    # this test exercises get_connection()'s own connection, not the fixture's.
    settings = Settings(app_id=AppId.INDIA, timescale_dsn=TEST_DSN)

    conn = get_connection(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    finally:
        conn.close()
