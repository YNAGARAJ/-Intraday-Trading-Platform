"""Unit tests for M14 DeadLetterQueue."""

from __future__ import annotations

from shared.execution.dead_letter import DeadLetterQueue


class TestDeadLetterQueueInMemory:
    def test_enqueue_returns_entry(self) -> None:
        dlq = DeadLetterQueue()
        entry = dlq.enqueue("ORD-1", "TCS", "NSE", "timeout", 3, "STRAT001")
        assert entry.client_order_id == "ORD-1"
        assert entry.symbol == "TCS"
        assert entry.exchange == "NSE"
        assert entry.last_error == "timeout"
        assert entry.attempt_count == 3
        assert entry.strategy_tag == "STRAT001"
        assert entry.enqueued_at_ms > 0

    def test_peek_returns_last_n(self) -> None:
        dlq = DeadLetterQueue()
        for i in range(5):
            dlq.enqueue(f"ORD-{i}", "SYM", "NSE", "err", 1, "STRAT001")
        items = dlq.peek(3)
        assert len(items) == 3
        assert items[-1].client_order_id == "ORD-4"

    def test_peek_empty_queue(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.peek(10) == []

    def test_size_in_memory(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.size() == 0
        dlq.enqueue("A", "SYM", "NSE", "err", 1, "STRAT001")
        dlq.enqueue("B", "SYM", "NSE", "err", 1, "STRAT001")
        assert dlq.size() == 2

    def test_enqueue_multiple_order(self) -> None:
        dlq = DeadLetterQueue()
        dlq.enqueue("X1", "INFY", "NSE", "perm err", 5, "STRAT002")
        dlq.enqueue("X2", "WIPRO", "BSE", "network err", 3, "STRAT003")
        items = dlq.peek(10)
        assert items[0].client_order_id == "X1"
        assert items[1].client_order_id == "X2"

    def test_strategy_tag_preserved(self) -> None:
        dlq = DeadLetterQueue()
        dlq.enqueue("Z", "HDFC", "NSE", "err", 3, "GENALG01")
        items = dlq.peek(1)
        assert items[0].strategy_tag == "GENALG01"


class TestDeadLetterQueueWithFakeRedis:
    def _make_redis(self) -> object:
        class FakeRedis:
            def __init__(self) -> None:
                self._lists: dict[str, list[bytes]] = {}

            def rpush(self, name: str, *values: str) -> int:
                lst = self._lists.setdefault(name, [])
                for v in values:
                    lst.append(v.encode() if isinstance(v, str) else v)
                return len(lst)

            def lrange(self, name: str, start: int, end: int) -> list[bytes]:
                lst = self._lists.get(name, [])
                length = len(lst)
                # Handle negative indices
                s = start if start >= 0 else max(0, length + start)
                e = end + 1 if end >= 0 else length + end + 1
                return lst[s:e]

        return FakeRedis()

    def test_enqueue_with_redis(self) -> None:
        redis = self._make_redis()
        dlq = DeadLetterQueue(redis_client=redis)  # type: ignore[arg-type]
        entry = dlq.enqueue("ORD-R1", "TCS", "NSE", "err", 2, "STRAT001")
        assert entry.client_order_id == "ORD-R1"

    def test_peek_from_redis(self) -> None:
        redis = self._make_redis()
        dlq = DeadLetterQueue(redis_client=redis)  # type: ignore[arg-type]
        dlq.enqueue("R1", "SYM1", "NSE", "e1", 1, "STRAT001")
        dlq.enqueue("R2", "SYM2", "NSE", "e2", 2, "STRAT001")
        items = dlq.peek(10)
        assert len(items) == 2
        assert items[0].client_order_id == "R1"
        assert items[1].client_order_id == "R2"
