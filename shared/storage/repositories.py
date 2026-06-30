"""Repository pattern: ALL TimescaleDB reads/writes go through these two classes.

No other module should issue raw SQL against the `ticks` / `ohlcv_*` tables directly --
that keeps the schema (shared/storage/schema.sql) as the single place table/column
names are known, and makes it possible to swap the storage engine later without
touching callers.
"""

from collections.abc import Sequence
from datetime import datetime

from psycopg2.extensions import connection as PGConnection  # noqa: N812
from psycopg2.extras import execute_values

from shared.storage.models import OHLCVCandle, Tick

_OHLCV_TABLE_BY_TIMEFRAME: dict[str, str] = {
    "1m": "ohlcv_1m",
    "5m": "ohlcv_5m",
    "15m": "ohlcv_15m",
    "1h": "ohlcv_1h",
}
"""Whitelist of valid timeframe -> table names. `query_candles` rejects anything not in
this dict before it ever reaches SQL string construction -- see the comment there."""


class TickRepository:
    """Reads and writes the raw `ticks` hypertable."""

    def __init__(self, conn: PGConnection) -> None:
        self._conn = conn

    def insert_many(self, ticks: Sequence[Tick]) -> int:
        """Bulk-insert ticks. Returns the number of rows inserted."""
        if not ticks:
            return 0
        rows = [
            (t.time, t.symbol, t.exchange, t.price, t.volume, t.bid, t.ask)
            for t in ticks
        ]
        with self._conn.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO ticks (time, symbol, exchange, price, volume, bid, ask) "
                "VALUES %s",
                rows,
            )
        self._conn.commit()
        return len(rows)

    def count(self, symbol: str, exchange: str, start: datetime, end: datetime) -> int:
        """Count ticks for `symbol` in `[start, end)`."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ticks "
                "WHERE symbol = %s AND exchange = %s AND time >= %s AND time < %s",
                (symbol, exchange, start, end),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0


class OHLCVRepository:
    """Reads and writes OHLCV candles.

    Only `ohlcv_1m` is directly writable: `ohlcv_5m`/`ohlcv_15m`/`ohlcv_1h` are
    TimescaleDB continuous aggregates computed automatically from it, not standalone
    tables -- there is no `upsert_5m` etc., by design.
    """

    def __init__(self, conn: PGConnection) -> None:
        self._conn = conn

    def upsert_1m(self, candles: Sequence[OHLCVCandle]) -> int:
        """Insert or update `ohlcv_1m` rows. Returns the number of rows written."""
        if not candles:
            return 0
        rows = [
            (c.time, c.symbol, c.exchange, c.open, c.high, c.low, c.close, c.volume)
            for c in candles
        ]
        with self._conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO ohlcv_1m
                    (time, symbol, exchange, open, high, low, close, volume)
                VALUES %s
                ON CONFLICT (symbol, exchange, time) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume
                """,
                rows,
            )
        self._conn.commit()
        return len(rows)

    def query_candles(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVCandle]:
        """Query candles for `symbol` at `timeframe` in `[start, end)`, time-ordered.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            timeframe: One of "1m", "5m", "15m", "1h".
            start: Inclusive range start.
            end: Exclusive range end.

        Raises:
            ValueError: If `timeframe` isn't one of the supported values.
        """
        table = _OHLCV_TABLE_BY_TIMEFRAME.get(timeframe)
        if table is None:
            raise ValueError(
                f"unsupported timeframe {timeframe!r}, expected one of "
                f"{sorted(_OHLCV_TABLE_BY_TIMEFRAME)}"
            )
        # `table` is interpolated into the query string, but it can only ever be one of
        # the 4 hardcoded values in _OHLCV_TABLE_BY_TIMEFRAME above (never derived from
        # unvalidated input) -- safe by construction, not by escaping.
        query = (
            f"SELECT time, symbol, exchange, open, high, low, close, volume "
            f"FROM {table} "
            f"WHERE symbol = %s AND exchange = %s AND time >= %s AND time < %s "
            f"ORDER BY time"
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (symbol, exchange, start, end))
            rows = cur.fetchall()
        return [
            OHLCVCandle(
                time=row[0],
                symbol=row[1],
                exchange=row[2],
                open=row[3],
                high=row[4],
                low=row[5],
                close=row[6],
                volume=row[7],
            )
            for row in rows
        ]
