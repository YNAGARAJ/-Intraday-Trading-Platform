"""Tests for M17 BlockRegistry."""

from __future__ import annotations

from shared.reconciliation.block_registry import BlockRegistry


class TestBlockRegistryInMemory:
    def test_initially_not_blocked(self) -> None:
        reg = BlockRegistry()
        assert not reg.is_blocked("RELIANCE", "NSE")

    def test_block_and_check(self) -> None:
        reg = BlockRegistry()
        reg.block("INFY", "NSE")
        assert reg.is_blocked("INFY", "NSE")

    def test_clear_removes_block(self) -> None:
        reg = BlockRegistry()
        reg.block("TCS", "NSE")
        reg.clear("TCS", "NSE")
        assert not reg.is_blocked("TCS", "NSE")

    def test_clear_nonexistent_is_safe(self) -> None:
        reg = BlockRegistry()
        reg.clear("WIPRO", "NSE")  # should not raise
        assert not reg.is_blocked("WIPRO", "NSE")

    def test_block_multiple_symbols(self) -> None:
        reg = BlockRegistry()
        reg.block("HDFC", "NSE")
        reg.block("SBIN", "NSE")
        assert reg.is_blocked("HDFC", "NSE")
        assert reg.is_blocked("SBIN", "NSE")
        assert not reg.is_blocked("MARUTI", "NSE")

    def test_blocked_symbols_returns_keys(self) -> None:
        reg = BlockRegistry()
        reg.block("AXISBANK", "NSE")
        keys = reg.blocked_symbols()
        assert any("AXISBANK" in k for k in keys)

    def test_exchange_discrimination(self) -> None:
        reg = BlockRegistry()
        reg.block("RELIANCE", "NSE")
        assert not reg.is_blocked("RELIANCE", "BSE")


class TestBlockRegistryWithRedis:
    def test_block_uses_redis(self) -> None:
        store: dict[str, str] = {}

        class FakeRedis:
            def set(self, name: str, value: str, ex: int | None = None) -> None:
                store[name] = value

            def delete(self, *names: str) -> int:
                for n in names:
                    store.pop(n, None)
                return len(names)

            def get(self, name: str) -> bytes | None:
                v = store.get(name)
                return v.encode() if v else None

        reg = BlockRegistry(redis_client=FakeRedis())
        reg.block("RELIANCE", "NSE")
        assert reg.is_blocked("RELIANCE", "NSE")
        assert len(store) == 1

    def test_clear_removes_redis_key(self) -> None:
        store: dict[str, str] = {}

        class FakeRedis:
            def set(self, name: str, value: str, ex: int | None = None) -> None:
                store[name] = value

            def delete(self, *names: str) -> int:
                for n in names:
                    store.pop(n, None)
                return len(names)

            def get(self, name: str) -> bytes | None:
                v = store.get(name)
                return v.encode() if v else None

        reg = BlockRegistry(redis_client=FakeRedis())
        reg.block("TCS", "NSE")
        reg.clear("TCS", "NSE")
        assert not reg.is_blocked("TCS", "NSE")
        assert len(store) == 0

    def test_redis_failure_falls_back_to_memory(self) -> None:
        class BrokenRedis:
            def set(self, name: str, value: str, ex: int | None = None) -> None:
                raise ConnectionError("redis down")

            def delete(self, *names: str) -> int:
                raise ConnectionError("redis down")

            def get(self, name: str) -> bytes | None:
                raise ConnectionError("redis down")

        reg = BlockRegistry(redis_client=BrokenRedis())
        reg.block("WIPRO", "NSE")
        assert reg.is_blocked("WIPRO", "NSE")

    def test_ttl_passed_to_redis(self) -> None:
        received_ttl: list[int | None] = []

        class FakeRedis:
            def set(self, name: str, value: str, ex: int | None = None) -> None:
                received_ttl.append(ex)

            def delete(self, *names: str) -> int:
                return 0

            def get(self, name: str) -> bytes | None:
                return None

        reg = BlockRegistry(redis_client=FakeRedis(), block_ttl_seconds=300)
        reg.block("HDFC", "NSE")
        assert received_ttl == [300]
