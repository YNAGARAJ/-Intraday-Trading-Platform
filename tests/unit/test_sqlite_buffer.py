"""Unit tests for shared.storage.sqlite_buffer.SQLiteFailoverBuffer.

Uses a real (temp-file) SQLite DB -- SQLite itself needs no external service, so these
stay true unit tests despite touching disk.
"""

from datetime import datetime
from pathlib import Path

from shared.storage.models import Tick
from shared.storage.sqlite_buffer import SQLiteFailoverBuffer

T0 = datetime(2026, 6, 30, 9, 15, 0)


def _tick(symbol: str = "RELIANCE", **overrides: object) -> Tick:
    defaults: dict[str, object] = {
        "time": T0,
        "symbol": symbol,
        "exchange": "NSE",
        "price": 2450.5,
        "volume": 100,
    }
    defaults.update(overrides)
    return Tick(**defaults)  # type: ignore[arg-type]


class FakeTickRepository:
    """Stand-in for TickRepository -- records what would have been inserted."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.inserted: list[Tick] = []

    def insert_many(self, ticks: list[Tick]) -> int:
        if self.fail:
            raise ConnectionError("simulated TimescaleDB outage")
        self.inserted.extend(ticks)
        return len(ticks)


class TestSQLiteFailoverBuffer:
    def test_append_and_pending_roundtrip(self, tmp_path: Path) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        ticks = [_tick(symbol="RELIANCE"), _tick(symbol="TCS")]

        appended = buffer.append(ticks)

        assert appended == 2
        pending = buffer.pending()
        assert len(pending) == 2
        assert {t.symbol for t in pending} == {"RELIANCE", "TCS"}

    def test_append_empty_is_noop(self, tmp_path: Path) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")

        assert buffer.append([]) == 0
        assert buffer.pending() == []

    def test_pending_count(self, tmp_path: Path) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        buffer.append([_tick(), _tick(), _tick()])

        assert buffer.pending_count() == 3

    def test_mark_synced_marks_oldest_first(self, tmp_path: Path) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        buffer.append([_tick(symbol="A"), _tick(symbol="B"), _tick(symbol="C")])

        buffer.mark_synced(2)

        remaining = buffer.pending()
        assert len(remaining) == 1
        assert remaining[0].symbol == "C"

    def test_mark_synced_zero_is_noop(self, tmp_path: Path) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        buffer.append([_tick()])

        buffer.mark_synced(0)

        assert buffer.pending_count() == 1

    def test_sync_to_timescale_flushes_and_marks_synced(self, tmp_path: Path) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        buffer.append([_tick(symbol="RELIANCE"), _tick(symbol="TCS")])
        repo = FakeTickRepository()

        synced = buffer.sync_to_timescale(repo)  # type: ignore[arg-type]

        assert synced == 2
        assert len(repo.inserted) == 2
        assert buffer.pending_count() == 0

    def test_sync_to_timescale_with_nothing_pending_is_noop(
        self, tmp_path: Path
    ) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        repo = FakeTickRepository()

        assert buffer.sync_to_timescale(repo) == 0  # type: ignore[arg-type]
        assert repo.inserted == []

    def test_sync_to_timescale_failure_leaves_rows_unsynced(
        self, tmp_path: Path
    ) -> None:
        buffer = SQLiteFailoverBuffer(path=tmp_path / "buffer.db")
        buffer.append([_tick()])
        failing_repo = FakeTickRepository(fail=True)

        try:
            buffer.sync_to_timescale(failing_repo)  # type: ignore[arg-type]
        except ConnectionError:
            pass

        assert (
            buffer.pending_count() == 1
        ), "rows must stay pending if the sync itself fails"

    def test_buffer_creates_parent_directory(self, tmp_path: Path) -> None:
        nested_path = tmp_path / "nested" / "dir" / "buffer.db"

        SQLiteFailoverBuffer(path=nested_path)

        assert nested_path.exists()

    def test_buffer_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "buffer.db"
        SQLiteFailoverBuffer(path=path).append([_tick()])

        reopened = SQLiteFailoverBuffer(path=path)

        assert reopened.pending_count() == 1
