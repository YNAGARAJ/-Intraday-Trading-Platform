"""Fixtures for M10 sentiment integration tests.

These tests require a running Redis instance.  They are skipped automatically
when Redis is unreachable (same pattern as other integration test suites).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import redis as redis_module

REDIS_URL = "redis://localhost:6379/0"


@pytest.fixture(scope="session")
def redis_client() -> "Iterator[redis_module.Redis[bytes]]":
    """Return a live Redis client; skip the test if Redis is unreachable."""
    redis = pytest.importorskip("redis")
    client: redis_module.Redis[bytes] = redis.Redis.from_url(
        REDIS_URL, decode_responses=False
    )
    try:
        client.ping()
    except Exception:  # noqa: BLE001
        pytest.skip(f"No Redis reachable at {REDIS_URL} — start one to run these")
    yield client
    client.close()
