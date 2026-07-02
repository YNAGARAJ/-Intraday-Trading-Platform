"""Unit tests for shared.auth.ibkr_auth (M15)."""

from __future__ import annotations

import pytest

from shared.auth.ibkr_auth import IBKRConnectionPool
from shared.auth.models import AuthMode, IBKRClientSlot
from shared.auth.token_store import AuthError
from shared.core.constants import (
    IBKR_CLIENT_ID_POOL_MAX,
    IBKR_LIVE_PORT,
    IBKR_PAPER_PORT,
)


class TestIBKRConnectionPool:
    def test_paper_port(self) -> None:
        pool = IBKRConnectionPool(mode=AuthMode.PAPER)
        assert pool.port == IBKR_PAPER_PORT

    def test_live_port(self) -> None:
        pool = IBKRConnectionPool(mode=AuthMode.LIVE)
        assert pool.port == IBKR_LIVE_PORT

    def test_pool_size_exceeds_max_raises(self) -> None:
        with pytest.raises(ValueError, match="IBKR_CLIENT_ID_POOL_MAX"):
            IBKRConnectionPool(pool_size=IBKR_CLIENT_ID_POOL_MAX + 1)

    def test_pool_size_at_max_allowed(self) -> None:
        pool = IBKRConnectionPool(pool_size=IBKR_CLIENT_ID_POOL_MAX)
        assert pool.pool_size() == IBKR_CLIENT_ID_POOL_MAX

    def test_acquire_marks_in_use(self) -> None:
        pool = IBKRConnectionPool(pool_size=2)
        slot = pool.acquire()
        assert slot.in_use

    def test_acquire_decrements_available(self) -> None:
        pool = IBKRConnectionPool(pool_size=3)
        assert pool.available_count() == 3
        pool.acquire()
        assert pool.available_count() == 2

    def test_release_increments_available(self) -> None:
        pool = IBKRConnectionPool(pool_size=2)
        slot = pool.acquire()
        pool.release(slot)
        assert pool.available_count() == 2

    def test_release_clears_in_use(self) -> None:
        pool = IBKRConnectionPool(pool_size=2)
        slot = pool.acquire()
        pool.release(slot)
        assert not slot.in_use

    def test_pool_exhausted_raises_auth_error(self) -> None:
        pool = IBKRConnectionPool(pool_size=2)
        pool.acquire()
        pool.acquire()
        with pytest.raises(AuthError, match="pool exhausted"):
            pool.acquire()

    def test_acquire_sequential_client_ids(self) -> None:
        pool = IBKRConnectionPool(pool_size=3, start_client_id=10)
        s1 = pool.acquire()
        s2 = pool.acquire()
        assert s1.client_id == 10
        assert s2.client_id == 11

    def test_heartbeat_thread_is_daemon(self) -> None:
        pool = IBKRConnectionPool(pool_size=1, enable_heartbeat=True)
        assert pool._heartbeat_thread is not None
        assert pool._heartbeat_thread.daemon is True
        pool.shutdown()

    def test_heartbeat_thread_not_started_by_default(self) -> None:
        pool = IBKRConnectionPool(pool_size=1, enable_heartbeat=False)
        assert pool._heartbeat_thread is None

    def test_shutdown_releases_all_slots(self) -> None:
        pool = IBKRConnectionPool(pool_size=2)
        pool.acquire()
        pool.shutdown()
        assert pool.available_count() == 2

    def test_connect_returns_false_without_ibapi(self) -> None:
        pool = IBKRConnectionPool(pool_size=1)
        slot = pool.acquire()
        result = pool.connect(slot)
        assert result is False  # ibapi not installed in dev env

    def test_pool_size_property(self) -> None:
        pool = IBKRConnectionPool(pool_size=4)
        assert pool.pool_size() == 4

    def test_default_pool_size_is_4(self) -> None:
        pool = IBKRConnectionPool()
        assert pool.pool_size() == 4
