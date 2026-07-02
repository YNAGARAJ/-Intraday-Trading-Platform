"""Unit tests for shared.ingestion.buffer (M16)."""

from __future__ import annotations

import time

from shared.ingestion.buffer import TickBuffer
from shared.ingestion.models import RawTick


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, list[str]] = {}

    def rpush(self, name: str, *values: str) -> int:
        lst = self._store.setdefault(name, [])
        lst.extend(values)
        return len(lst)

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        lst = self._store.get(name, [])
        sl = lst[start: end + 1] if end >= 0 else lst[start:]
        return [s.encode() for s in sl]

    def llen(self, name: str) -> int:
        return len(self._store.get(name, []))

    def ltrim(self, name: str, start: int, end: int) -> bool:
        lst = self._store.get(name, [])
        self._store[name] = lst[start: end + 1] if end >= 0 else lst[start:]
        return True


def _tick(ltp: float = 100.0) -> RawTick:
    return RawTick(
        symbol="RELIANCE", exchange="NSE", ltp=ltp,
        volume=100, timestamp_ms=int(time.time() * 1000),
    )


class TestTickBufferMemory:
    def test_push_increments_count(self) -> None:
        buf = TickBuffer(redis_client=None)
        buf.push(_tick())
        assert buf.pending_count() == 1

    def test_push_two_ticks(self) -> None:
        buf = TickBuffer(redis_client=None)
        buf.push(_tick())
        buf.push(_tick(200.0))
        assert buf.pending_count() == 2

    def test_drain_all(self) -> None:
        buf = TickBuffer(redis_client=None)
        buf.push(_tick(100.0))
        buf.push(_tick(200.0))
        ticks = buf.drain()
        assert len(ticks) == 2
        assert buf.pending_count() == 0

    def test_drain_partial(self) -> None:
        buf = TickBuffer(redis_client=None)
        for _ in range(5):
            buf.push(_tick())
        ticks = buf.drain(3)
        assert len(ticks) == 3
        assert buf.pending_count() == 2

    def test_drain_preserves_ltp(self) -> None:
        buf = TickBuffer(redis_client=None)
        buf.push(_tick(555.5))
        ticks = buf.drain()
        assert len(ticks) == 1
        assert ticks[0].ltp == 555.5

    def test_pending_count_zero_initially(self) -> None:
        buf = TickBuffer(redis_client=None)
        assert buf.pending_count() == 0

    def test_should_flush_by_count(self) -> None:
        buf = TickBuffer(redis_client=None, flush_count=2)
        buf.push(_tick())
        assert not buf.should_flush()
        buf.push(_tick())
        assert buf.should_flush()


class TestTickBufferRedis:
    def test_push_to_redis(self) -> None:
        redis = _FakeRedis()
        buf = TickBuffer(redis_client=redis)
        buf.push(_tick())
        assert buf.pending_count() == 1

    def test_drain_from_redis(self) -> None:
        redis = _FakeRedis()
        buf = TickBuffer(redis_client=redis)
        buf.push(_tick(777.0))
        ticks = buf.drain(1)
        assert len(ticks) == 1
        assert ticks[0].ltp == 777.0

    def test_drain_removes_from_redis(self) -> None:
        redis = _FakeRedis()
        buf = TickBuffer(redis_client=redis)
        for _ in range(5):
            buf.push(_tick())
        buf.drain(3)
        assert buf.pending_count() == 2

    def test_redis_and_memory_combined_count(self) -> None:
        redis = _FakeRedis()
        buf = TickBuffer(redis_client=redis)
        buf.push(_tick())  # goes to Redis
        # Inject directly into memory fallback to simulate mixed state
        buf._memory.append('{"symbol":"X","exchange":"NSE","ltp":1.0,"volume":1,"timestamp_ms":1}')
        assert buf.pending_count() == 2

    def test_memory_drained_before_redis(self) -> None:
        redis = _FakeRedis()
        buf = TickBuffer(redis_client=redis)
        buf._memory.append(
            '{"symbol":"MEM","exchange":"NSE","ltp":10.0,"volume":1,"timestamp_ms":1}'
        )
        buf.push(_tick(99.0))  # Redis
        ticks = buf.drain(1)
        # Memory drained first
        assert ticks[0].symbol == "MEM"
