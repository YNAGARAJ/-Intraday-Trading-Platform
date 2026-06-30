"""Redis-backed fixtures, scoped to tests/integration/ only.

These tests require a real Redis server (Lua script atomicity cannot be meaningfully
faked). The fixture skips the test module if nothing is reachable, so `pytest` stays
green on a bare host with no Docker -- bring up Redis (e.g. `docker run --rm -p
6379:6379 redis:7.2.4-alpine`) to actually exercise these.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import redis as redis_lib

REDIS_TEST_URL = "redis://localhost:6379/15"
"""Db 15 is reserved for integration tests so it never collides with dev data."""

LUA_DIR = Path(__file__).resolve().parents[2] / "shared" / "lua"


@pytest.fixture(scope="session")
def redis_client() -> Iterator[redis_lib.Redis]:
    client = redis_lib.Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.ConnectionError:
        pytest.skip(f"No Redis reachable at {REDIS_TEST_URL} -- start one to run these")
    yield client
    client.close()  # type: ignore[no-untyped-call]  # redis-py 5.0.3 stub gap: close() is untyped


@pytest.fixture(autouse=True)
def _clean_redis_db15(redis_client: redis_lib.Redis) -> Iterator[None]:
    redis_client.flushdb()
    yield
    redis_client.flushdb()


@pytest.fixture
def load_lua(
    redis_client: redis_lib.Redis,
) -> Callable[[str], redis_lib.commands.core.Script]:
    """Return a loader that compiles a named script from shared/lua/ via SCRIPT LOAD."""

    def _load(filename: str) -> redis_lib.commands.core.Script:
        script_body = (LUA_DIR / filename).read_text()
        return redis_client.register_script(script_body)

    return _load
