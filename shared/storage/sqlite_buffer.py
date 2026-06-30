"""Local SQLite failover buffer (RULE 5: DB failure policy).

When TimescaleDB is unreachable, ticks append here instead of being dropped; once the
database recovers, `sync_to_timescale` flushes everything pending back to it. This is
a local durability backstop, not a queue replacement -- callers decide when/how often
to attempt a sync (e.g. on a timer, or on the next successful write after a failure).
"""

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from shared.storage.models import Tick
from shared.storage.repositories import TickRepository

DEFAULT_BUFFER_PATH: Path = Path("shared/data/buffer.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS buffered_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    price REAL NOT NULL,
    volume INTEGER NOT NULL,
    bid REAL,
    ask REAL,
    synced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_buffered_ticks_synced ON buffered_ticks (synced);
"""


class SQLiteFailoverBuffer:
    """Append-only local buffer for ticks that couldn't be written to TimescaleDB."""

    def __init__(self, path: Path = DEFAULT_BUFFER_PATH) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def append(self, ticks: Sequence[Tick]) -> int:
        """Append `ticks` to the local buffer. Returns the number appended."""
        if not ticks:
            return 0
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO buffered_ticks "
                "(time, symbol, exchange, price, volume, bid, ask) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        t.time.isoformat(),
                        t.symbol,
                        t.exchange,
                        t.price,
                        t.volume,
                        t.bid,
                        t.ask,
                    )
                    for t in ticks
                ],
            )
        return len(ticks)

    def pending(self) -> list[Tick]:
        """Return all not-yet-synced buffered ticks, oldest first."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT time, symbol, exchange, price, volume, bid, ask "
                "FROM buffered_ticks WHERE synced = 0 ORDER BY id"
            )
            rows = cursor.fetchall()
        return [
            Tick(
                time=datetime.fromisoformat(row[0]),
                symbol=row[1],
                exchange=row[2],
                price=row[3],
                volume=row[4],
                bid=row[5],
                ask=row[6],
            )
            for row in rows
        ]

    def pending_count(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT count(*) FROM buffered_ticks WHERE synced = 0"
            )
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    def mark_synced(self, count: int) -> None:
        """Mark the oldest `count` unsynced rows as synced."""
        if count <= 0:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE buffered_ticks SET synced = 1 WHERE id IN ("
                "SELECT id FROM buffered_ticks WHERE synced = 0 ORDER BY id LIMIT ?)",
                (count,),
            )

    def sync_to_timescale(self, tick_repository: TickRepository) -> int:
        """Flush all pending buffered ticks to TimescaleDB via `tick_repository`.

        Returns the number of ticks synced. If the repository write itself raises
        (TimescaleDB still unavailable), buffered rows are left unsynced for the next
        attempt -- this method does not catch that exception, callers decide retry
        policy.
        """
        rows = self.pending()
        if not rows:
            return 0
        tick_repository.insert_many(rows)
        self.mark_synced(len(rows))
        return len(rows)
