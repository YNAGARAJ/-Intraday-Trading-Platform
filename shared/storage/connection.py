"""TimescaleDB connection management via psycopg2.

All TimescaleDB access in this codebase goes through a connection obtained here, and
all SQL goes through `shared.storage.repositories` -- no other module should import
psycopg2 directly.
"""

from pathlib import Path

import psycopg2
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.core.config import Settings

DEFAULT_SCHEMA_PATH: Path = Path(__file__).parent / "schema.sql"


def get_connection(settings: Settings) -> PGConnection:
    """Open a new TimescaleDB connection using `settings.timescale_dsn`.

    Args:
        settings: Loaded `Settings`; only `timescale_dsn` is used.

    Returns:
        A new psycopg2 connection. Callers own its lifecycle (close it when done).
    """
    return psycopg2.connect(settings.timescale_dsn)


def apply_schema(conn: PGConnection, schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
    """Apply `schema.sql` (hypertables, continuous aggregates, policies).

    Idempotent: every statement in schema.sql uses IF NOT EXISTS / *_if_not_exists,
    so this is safe to call on every process startup, not just once.

    Args:
        conn: An open TimescaleDB connection.
        schema_path: Path to the schema SQL file.
    """
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
