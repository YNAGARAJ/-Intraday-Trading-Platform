"""ACT-R tiered memory for M18 Agent Orchestrator.

Three memory tiers per the ACT-R architecture spec:

1. **Working Memory** (in-process dict): current market snapshot, active positions,
   last 5 trades.  Pruned when token budget (2 000 tokens) is exceeded.

2. **Short-Term Memory** (Redis, TTL 1 hour): transient signal structures, order
   flow anomalies, sentiment shifts.

3. **Long-Term Memory** (PostgreSQL + pgvector): successful setups and loss
   post-mortems.  Scored nightly via the ACT-R Power-Law Decay Formula:

       activation = ln(Σ t_i^(−d))   where d = ACT_R_DECAY_PARAM (0.5)
       t_i = seconds since the i-th retrieval of that memory

   High-scoring nodes stay in the vectorised core; low-scoring patterns rotate
   to cold storage.
"""

from __future__ import annotations

import math
import time
from typing import Protocol

import structlog

from shared.core.constants import (
    ACT_R_DECAY_PARAM,
    SHORT_TERM_MEMORY_REDIS_KEY_PREFIX,
    SHORT_TERM_MEMORY_TTL_SECONDS,
    WORKING_MEMORY_MAX_TOKENS,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Redis Protocol
# ---------------------------------------------------------------------------


class _RedisKV(Protocol):
    """Minimal Redis interface for short-term memory."""

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def get(self, name: str) -> bytes | None:
        ...

    def delete(self, *names: str) -> int:
        ...


# ---------------------------------------------------------------------------
# Working Memory
# ---------------------------------------------------------------------------


def _approx_tokens(text: str) -> int:
    """Rough token count: ~4 characters per token (GPT-style estimate)."""
    return max(1, len(text) // 4)


class WorkingMemory:
    """In-process dict-based working memory with token-budget pruning.

    Entries are stored in insertion order.  When the total token count
    exceeds ``max_tokens``, the oldest entries are evicted first (FIFO).

    Args:
        max_tokens: Maximum token budget (default ``WORKING_MEMORY_MAX_TOKENS``).
    """

    def __init__(self, max_tokens: int = WORKING_MEMORY_MAX_TOKENS) -> None:
        self._max_tokens = max_tokens
        self._store: dict[str, str] = {}
        self._order: list[str] = []

    def put(self, key: str, value: str) -> None:
        """Store a key-value pair, pruning old entries if over budget.

        Args:
            key: Logical name for this memory entry.
            value: String content of the entry.
        """
        if key in self._store:
            self._order.remove(key)
        self._store[key] = value
        self._order.append(key)
        self._prune()

    def get(self, key: str) -> str | None:
        """Retrieve a memory entry by key.

        Args:
            key: Entry name.

        Returns:
            The stored string, or ``None`` if not present.
        """
        return self._store.get(key)

    def delete(self, key: str) -> None:
        """Remove an entry from working memory.

        Args:
            key: Entry to remove.
        """
        if key in self._store:
            del self._store[key]
            self._order.remove(key)

    def token_count(self) -> int:
        """Approximate total tokens currently in working memory."""
        return sum(_approx_tokens(v) for v in self._store.values())

    def keys(self) -> list[str]:
        """Return all keys in insertion order."""
        return list(self._order)

    def _prune(self) -> None:
        while self.token_count() > self._max_tokens and self._order:
            evicted_key = self._order.pop(0)
            del self._store[evicted_key]
            logger.debug("working_memory_evicted", key=evicted_key)


# ---------------------------------------------------------------------------
# Short-Term Memory
# ---------------------------------------------------------------------------


class ShortTermMemory:
    """Redis-backed short-term memory with rolling 1-hour TTL.

    Falls back to an in-memory dict when Redis is unavailable (fail-open).

    Args:
        redis_client: Redis client for persistence.  ``None`` → in-memory only.
        ttl_seconds: TTL per entry (default ``SHORT_TERM_MEMORY_TTL_SECONDS``).
        key_prefix: Redis key namespace prefix.
    """

    def __init__(
        self,
        redis_client: _RedisKV | None = None,
        ttl_seconds: int = SHORT_TERM_MEMORY_TTL_SECONDS,
        key_prefix: str = SHORT_TERM_MEMORY_REDIS_KEY_PREFIX,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._prefix = key_prefix
        self._memory: dict[str, str] = {}

    def put(self, key: str, value: str) -> None:
        """Store a key-value pair with the configured TTL.

        Args:
            key: Logical name for this memory entry.
            value: String content.
        """
        redis_key = f"{self._prefix}:{key}"
        if self._redis is not None:
            try:
                self._redis.set(redis_key, value, ex=self._ttl)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("stm_redis_put_failed", key=key, error=str(exc))
        self._memory[key] = value

    def get(self, key: str) -> str | None:
        """Retrieve a short-term memory entry.

        Args:
            key: Entry name.

        Returns:
            Stored string, or ``None`` if expired or absent.
        """
        redis_key = f"{self._prefix}:{key}"
        if self._redis is not None:
            try:
                raw = self._redis.get(redis_key)
                if raw is not None:
                    return raw.decode() if isinstance(raw, bytes) else str(raw)
                return None
            except Exception as exc:  # noqa: BLE001
                logger.warning("stm_redis_get_failed", key=key, error=str(exc))
        return self._memory.get(key)

    def delete(self, key: str) -> None:
        """Remove a short-term memory entry.

        Args:
            key: Entry to remove.
        """
        redis_key = f"{self._prefix}:{key}"
        if self._redis is not None:
            try:
                self._redis.delete(redis_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("stm_redis_delete_failed", key=key, error=str(exc))
        self._memory.pop(key, None)


# ---------------------------------------------------------------------------
# Long-Term Memory (ACT-R)
# ---------------------------------------------------------------------------


class LongTermMemoryEntry:
    """A single long-term memory record with ACT-R retrieval history.

    Args:
        key: Unique identifier for this memory.
        content: Serialisable string content.
        retrieved_at_seconds: List of Unix timestamps (seconds) of past retrievals.
    """

    def __init__(
        self,
        key: str,
        content: str,
        retrieved_at_seconds: list[float] | None = None,
    ) -> None:
        self.key = key
        self.content = content
        self.retrieved_at_seconds: list[float] = retrieved_at_seconds or []

    def record_retrieval(self, now_s: float | None = None) -> None:
        """Record that this entry was retrieved at ``now_s`` (defaults to wall time).

        Args:
            now_s: Unix timestamp of retrieval.  ``None`` → current time.
        """
        self.retrieved_at_seconds.append(now_s if now_s is not None else time.time())

    def activation_score(self, now_s: float | None = None) -> float:
        """Compute the ACT-R activation score for this entry.

        Formula: ``ln(Σ t_i^(−d))`` where ``t_i`` is elapsed seconds since the
        i-th retrieval and ``d = ACT_R_DECAY_PARAM`` (0.5).

        Returns ``-inf`` (no retrievals yet → lowest possible priority).

        Args:
            now_s: Current Unix timestamp.  ``None`` → wall time.

        Returns:
            Activation score (higher = more likely to be retrieved).
        """
        if not self.retrieved_at_seconds:
            return float("-inf")
        ts = now_s if now_s is not None else time.time()
        total = 0.0
        for t_retrieved in self.retrieved_at_seconds:
            elapsed = ts - t_retrieved
            if elapsed <= 0:
                elapsed = 0.001  # guard against zero / negative
            total += elapsed ** (-ACT_R_DECAY_PARAM)
        return math.log(total)


class _DBCursor(Protocol):
    """Minimal cursor protocol for long-term memory SQL operations."""

    def execute(self, query: str, params: tuple[str, ...] | None = None) -> None:
        ...


class _DBConn(Protocol):
    """Minimal PostgreSQL connection protocol for long-term memory."""

    def cursor(self) -> _DBCursor:
        ...

    def commit(self) -> None:
        ...


class LongTermMemory:
    """PostgreSQL-backed long-term memory with ACT-R activation scoring.

    Falls back to an in-memory dict when the database is unavailable.

    Args:
        db_conn: psycopg2 connection.  ``None`` → in-memory fallback.
    """

    def __init__(self, db_conn: _DBConn | None = None) -> None:
        self._db = db_conn
        self._memory: dict[str, LongTermMemoryEntry] = {}

    def store(self, key: str, content: str) -> None:
        """Store or update a long-term memory entry.

        Args:
            key: Unique identifier.
            content: String content to persist.
        """
        if key in self._memory:
            self._memory[key].content = content
        else:
            self._memory[key] = LongTermMemoryEntry(key=key, content=content)
        if self._db is not None:
            self._persist(key, content)
        logger.debug("ltm_stored", key=key)

    def retrieve(
        self, key: str, record_access: bool = True
    ) -> LongTermMemoryEntry | None:
        """Retrieve a memory entry by key, optionally updating access history.

        Args:
            key: Unique identifier.
            record_access: If ``True``, records this retrieval in the ACT-R history.

        Returns:
            The ``LongTermMemoryEntry``, or ``None`` if not found.
        """
        entry = self._memory.get(key)
        if entry is not None and record_access:
            entry.record_retrieval()
        return entry

    def retrieve_top_k(
        self, top_k: int = 5, now_s: float | None = None
    ) -> list[LongTermMemoryEntry]:
        """Return the top-k entries ranked by ACT-R activation score.

        Args:
            top_k: Maximum number of entries to return.
            now_s: Reference timestamp for score computation.

        Returns:
            Up to ``top_k`` entries in descending activation order.
        """
        scored = [
            (e, e.activation_score(now_s)) for e in self._memory.values()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:top_k]]

    def score_nightly(self, now_s: float | None = None) -> dict[str, float]:
        """Compute activation scores for all entries (nightly maintenance task).

        Args:
            now_s: Reference timestamp.  ``None`` → current wall time.

        Returns:
            Dict mapping key → activation score.
        """
        ts = now_s if now_s is not None else time.time()
        scores: dict[str, float] = {}
        for key, entry in self._memory.items():
            scores[key] = entry.activation_score(ts)
        logger.info("ltm_nightly_scored", entry_count=len(scores))
        return scores

    def _persist(self, key: str, content: str) -> None:
        """Write or upsert to PostgreSQL (best-effort; silently skips on error).

        Args:
            key: Entry key.
            content: Serialised content.
        """
        try:
            cur = self._db.cursor()  # type: ignore[union-attr]
            cur.execute(
                """
                INSERT INTO orchestrator_long_term_memory (key, content, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key)
                DO UPDATE SET content = EXCLUDED.content,
                              updated_at = NOW()
                """,
                (key, content),
            )
            self._db.commit()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ltm_db_persist_failed", key=key, error=str(exc))

    @staticmethod
    def apply_schema(db_conn: _DBConn) -> None:
        """Create the long-term memory table if it does not exist.

        Args:
            db_conn: psycopg2 connection to the target database.
        """
        try:
            cur = db_conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestrator_long_term_memory (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            db_conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ltm_schema_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Unified ACT-R Memory facade
# ---------------------------------------------------------------------------


class ACTRMemory:
    """Unified facade exposing all three ACT-R memory tiers.

    Args:
        redis_client: Redis client for short-term memory.
        db_conn: PostgreSQL connection for long-term memory.
        working_max_tokens: Token budget for working memory.
    """

    def __init__(
        self,
        redis_client: _RedisKV | None = None,
        db_conn: _DBConn | None = None,
        working_max_tokens: int = WORKING_MEMORY_MAX_TOKENS,
    ) -> None:
        self.working = WorkingMemory(max_tokens=working_max_tokens)
        self.short_term = ShortTermMemory(redis_client=redis_client)
        self.long_term = LongTermMemory(db_conn=db_conn)

    def remember(self, key: str, value: str, tier: str = "working") -> None:
        """Store a fact in the specified memory tier.

        Args:
            key: Entry identifier.
            value: String content.
            tier: One of ``"working"``, ``"short_term"``, ``"long_term"``.
        """
        if tier == "short_term":
            self.short_term.put(key, value)
        elif tier == "long_term":
            self.long_term.store(key, value)
        else:
            self.working.put(key, value)

    def recall(self, key: str, tier: str = "working") -> str | None:
        """Retrieve a fact from the specified tier.

        Args:
            key: Entry identifier.
            tier: One of ``"working"``, ``"short_term"``, ``"long_term"``.

        Returns:
            The stored string, or ``None`` if absent.
        """
        if tier == "short_term":
            return self.short_term.get(key)
        if tier == "long_term":
            entry = self.long_term.retrieve(key, record_access=True)
            return entry.content if entry is not None else None
        return self.working.get(key)
