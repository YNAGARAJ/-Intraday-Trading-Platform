"""Dependency injection factories for the M22 FastAPI layer."""

from __future__ import annotations

from collections.abc import Generator

import redis

from shared.core.config import settings


def get_redis() -> Generator[redis.Redis, None, None]:
    """Yield a synchronous Redis client; close it after the request completes."""
    client: redis.Redis = redis.Redis.from_url(
        settings.redis_url, decode_responses=True
    )
    try:
        yield client
    finally:
        client.close()  # type: ignore[no-untyped-call]
