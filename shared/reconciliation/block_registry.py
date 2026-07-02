"""Per-symbol entry-block registry for M17 Reconciliation Agent.

When a reconciliation mismatch is detected for a symbol, new entry signals on that
symbol are blocked until the mismatch is cleared.  The block flag lives in Redis
(``reconciliation:blocked:<EXCHANGE>:<SYMBOL>``); falls back to an in-memory set
when Redis is unavailable.

M18 (orchestrator) must check ``is_blocked(symbol, exchange)`` before forwarding
any new-entry signal to the execution engine.
"""

from __future__ import annotations

from typing import Protocol

import structlog

from shared.core.constants import RECONCILIATION_BLOCKED_REDIS_KEY_PREFIX

logger = structlog.get_logger(__name__)


class _RedisKV(Protocol):
    """Minimal Redis interface for key-value flag operations."""

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def delete(self, *names: str) -> int:
        ...

    def get(self, name: str) -> bytes | None:
        ...


def _block_key(symbol: str, exchange: str) -> str:
    return f"{RECONCILIATION_BLOCKED_REDIS_KEY_PREFIX}:{exchange}:{symbol}"


class BlockRegistry:
    """Tracks which symbols are blocked for new entries after a mismatch.

    Args:
        redis_client: Redis client for persistent flag storage.
            ``None`` → in-memory fallback (survives only the current process).
        block_ttl_seconds: Optional TTL on block keys (safety net auto-expiry).
            ``None`` = no expiry (block persists until explicitly cleared).
    """

    def __init__(
        self,
        redis_client: _RedisKV | None = None,
        block_ttl_seconds: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._ttl = block_ttl_seconds
        self._memory: set[str] = set()

    def block(self, symbol: str, exchange: str) -> None:
        """Block new entries on ``symbol`` until cleared.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier.
        """
        key = _block_key(symbol, exchange)
        if self._redis is not None:
            try:
                self._redis.set(key, "true", ex=self._ttl)
                logger.warning(
                    "reconciliation_entry_blocked",
                    symbol=symbol,
                    exchange=exchange,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "reconciliation_block_redis_failed",
                    symbol=symbol,
                    error=str(exc),
                )
        self._memory.add(key)
        logger.warning(
            "reconciliation_entry_blocked_in_memory",
            symbol=symbol,
            exchange=exchange,
        )

    def clear(self, symbol: str, exchange: str) -> None:
        """Unblock entries on ``symbol`` after mismatch is resolved.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier.
        """
        key = _block_key(symbol, exchange)
        if self._redis is not None:
            try:
                self._redis.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "reconciliation_clear_redis_failed",
                    symbol=symbol,
                    error=str(exc),
                )
        self._memory.discard(key)
        logger.info(
            "reconciliation_entry_unblocked",
            symbol=symbol,
            exchange=exchange,
        )

    def is_blocked(self, symbol: str, exchange: str) -> bool:
        """Return True if new entries on this symbol are currently blocked.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange identifier.

        Returns:
            ``True`` when a block is active, ``False`` otherwise.
        """
        key = _block_key(symbol, exchange)
        if key in self._memory:
            return True
        if self._redis is not None:
            try:
                return self._redis.get(key) is not None
            except Exception:  # noqa: BLE001
                pass
        return False

    def blocked_symbols(self) -> set[str]:
        """Return the set of block keys currently active in the in-memory store.

        Note: does not enumerate Redis keys (would require SCAN); use only for
        diagnostics when Redis is unavailable.

        Returns:
            Set of raw Redis key strings for in-memory blocks.
        """
        return set(self._memory)
