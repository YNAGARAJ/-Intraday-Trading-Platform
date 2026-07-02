"""Redis-backed token store with in-memory fallback (M15).

Stores broker access tokens with TTL.  In-memory fallback activates automatically
when Redis is unavailable (RULE 5 degraded-state policy).  Tokens are never logged.
"""

from __future__ import annotations

import json
import time
from typing import Protocol

import structlog

from shared.auth.models import AuthMode, TokenRecord
from shared.core.constants import KITE_TOKEN_REDIS_KEY

logger = structlog.get_logger(__name__)


class RedisClient(Protocol):
    """Minimal Redis interface needed by ``TokenStore``."""

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def get(self, name: str) -> bytes | None:
        ...

    def delete(self, *names: str) -> int:
        ...


class AuthError(Exception):
    """Raised when no valid token is available and login is not possible."""


class TokenStore:
    """Stores and retrieves broker access tokens.

    Args:
        redis_client: Connected Redis client.  ``None`` = in-memory only.
    """

    def __init__(self, redis_client: RedisClient | None = None) -> None:
        self._redis = redis_client
        self._memory: dict[str, str] = {}

    def save(self, record: TokenRecord, ttl_seconds: int) -> None:
        """Persist a token record.

        Args:
            record: Token to store.  ``access_token`` is never logged.
            ttl_seconds: Redis key TTL (seconds).  In-memory store ignores TTL
                (process-lifetime only).
        """
        key = self._key(record.broker)
        payload = json.dumps(
            {
                "broker": record.broker,
                "access_token": record.access_token,
                "issued_at_ms": record.issued_at_ms,
                "expires_at_ms": record.expires_at_ms,
                "user_id": record.user_id,
                "mode": record.mode.value,
            }
        )
        if self._redis is not None:
            self._redis.set(key, payload, ex=ttl_seconds)
        else:
            self._memory[key] = payload
        logger.info(
            "token_saved",
            broker=record.broker,
            user_id=record.user_id,
            mode=record.mode.value,
            ttl_seconds=ttl_seconds,
        )

    def load(self, broker: str) -> TokenRecord | None:
        """Return the stored token for a broker, or ``None`` if absent/expired.

        Args:
            broker: Broker identifier (``"kite"`` or ``"ibkr"``).
        """
        key = self._key(broker)
        raw: str | bytes | None = None
        if self._redis is not None:
            raw = self._redis.get(key)
        else:
            raw = self._memory.get(key)

        if raw is None:
            return None

        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        record = TokenRecord(
            broker=data["broker"],
            access_token=data["access_token"],
            issued_at_ms=data["issued_at_ms"],
            expires_at_ms=data["expires_at_ms"],
            user_id=data["user_id"],
            mode=AuthMode(data["mode"]),
        )
        now_ms = int(time.time() * 1000)
        if not record.is_valid(now_ms):
            logger.info("token_expired", broker=broker)
            self.delete(broker)
            return None
        return record

    def delete(self, broker: str) -> None:
        """Remove the token for a broker."""
        key = self._key(broker)
        if self._redis is not None:
            self._redis.delete(key)
        else:
            self._memory.pop(key, None)

    def _key(self, broker: str) -> str:
        if broker == "kite":
            return KITE_TOKEN_REDIS_KEY
        return f"auth:{broker}:access_token"
