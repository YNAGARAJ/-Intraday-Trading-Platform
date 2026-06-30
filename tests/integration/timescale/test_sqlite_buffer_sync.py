"""Integration test: SQLiteFailoverBuffer syncing to a real TimescaleDB (RULE 5)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.storage.models import Tick
from shared.storage.repositories import TickRepository
from shared.storage.sqlite_buffer import SQLiteFailoverBuffer

T0 = datetime(2026, 6, 1, 9, 15, tzinfo=UTC)


def test_buffered_ticks_sync_to_real_timescaledb(
    pg_connection: PGConnection, tmp_path: Path
) -> None:
    buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
    ticks = [
        Tick(time=T0, symbol="RELIANCE", exchange="NSE", price=2450.5, volume=100),
        Tick(time=T0, symbol="TCS", exchange="NSE", price=3800.0, volume=50),
    ]
    buffer.append(ticks)

    tick_repo = TickRepository(pg_connection)
    synced = buffer.sync_to_timescale(tick_repo)

    assert synced == 2
    assert buffer.pending_count() == 0
    assert tick_repo.count("RELIANCE", "NSE", T0, T0) == 0  # exclusive end, sanity
    assert tick_repo.count("RELIANCE", "NSE", T0, T0 + timedelta(seconds=1)) == 1
