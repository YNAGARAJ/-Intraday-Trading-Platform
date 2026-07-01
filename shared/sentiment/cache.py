"""M10 Sentiment & News Agent — semantic dedup cache.

Uses gptcache's Onnx sentence embeddings (all-MiniLM-L6-v2, 384-dim) stored in
Redis to detect semantically equivalent headlines and return cached scores without
issuing a new LLM call.

Public API
----------
SentimentCache(redis_client, model_version, embedding_model=None)
    .get(headline)    → SentimentScore | None
    .put(headline, score)
    .clear()
    .size()           → int

EmbeddingModel (Protocol)  — injectable for testing.
OnnxEmbeddingModel         — production wrapper for gptcache.embedding.Onnx.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import redis
import structlog

from shared.core.constants import (
    GPTCACHE_SIMILARITY_THRESHOLD,
    SENTIMENT_CACHE_REDIS_KEY_PREFIX,
    SENTIMENT_CACHE_REDIS_TTL_SECONDS,
    SENTIMENT_EMBEDDING_DIM,
)
from shared.sentiment.models import SentimentScore

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Embedding model protocol (enables test injection without live Onnx download)
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingModel(Protocol):
    """Produces a fixed-length float32 embedding vector for a text string."""

    def embed(self, text: str) -> npt.NDArray[np.float32]:
        """Return an embedding vector for ``text``."""
        ...

    @property
    def dimension(self) -> int:
        """Embedding dimension (must match ``SENTIMENT_EMBEDDING_DIM``)."""
        ...


class OnnxEmbeddingModel:
    """Production embedding model backed by gptcache's all-MiniLM-L6-v2 Onnx.

    The underlying ONNX model is downloaded from HuggingFace on first use and
    cached locally by gptcache.  Subsequent calls are fast (< 5ms).

    Note: import of gptcache is deferred to embed() to keep the module
    importable even when gptcache is not installed (graceful degradation in
    unit-test environments that mock this class).
    """

    def __init__(self) -> None:
        self._onnx: object | None = None

    def _load(self) -> None:
        if self._onnx is None:
            from gptcache.embedding import Onnx  # noqa: PLC0415

            self._onnx = Onnx()

    def embed(self, text: str) -> npt.NDArray[np.float32]:
        """Return a 384-dim float32 embedding for ``text``."""
        self._load()
        result = self._onnx.to_embeddings(text)  # type: ignore[union-attr]
        return np.array(result, dtype=np.float32)

    @property
    def dimension(self) -> int:
        """Return embedding dimension (384 for all-MiniLM-L6-v2)."""
        self._load()
        return int(self._onnx.dimension)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Cache entry serialisation helpers
# ---------------------------------------------------------------------------


def _score_to_dict(score: SentimentScore) -> dict[str, object]:
    return {
        "headline": score.headline,
        "score": score.score,
        "label": score.label,
        "confidence": score.confidence,
        "tokens_used": score.tokens_used,
        "model_version": score.model_version,
    }


def _dict_to_score(
    d: dict[str, object], from_cache: bool = True
) -> SentimentScore:
    return SentimentScore(
        headline=str(d["headline"]),
        score=float(str(d["score"])),
        label=str(d["label"]),
        confidence=float(str(d["confidence"])),
        tokens_used=0 if from_cache else int(str(d["tokens_used"])),
        from_cache=from_cache,
        model_version=str(d["model_version"]),
    )


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def _cosine_similarity(
    a: npt.NDArray[np.float32], b: npt.NDArray[np.float32]
) -> float:
    """Return cosine similarity between two vectors (0 to 1)."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# SentimentCache
# ---------------------------------------------------------------------------


class SentimentCache:
    """Semantic dedup cache for sentiment scores backed by Redis.

    Entries are stored as a Redis list (one JSON element per cached headline).
    Each element contains the embedding vector (as a list of floats) and the
    SentimentScore fields.  On lookup, cosine similarity is computed in NumPy
    against all stored embeddings; a result with similarity ≥
    ``GPTCACHE_SIMILARITY_THRESHOLD`` is returned as a cache hit.

    The cache is namespaced by ``model_version`` so a model upgrade cannot
    silently return scores computed under a different embedding space.

    Args:
        redis_client:    Redis client for persistence.
        model_version:   LLM identifier string (used in Redis key and stored
                         on returned scores so the caller knows which model
                         produced the cached value).
        embedding_model: Embedding model to use.  Defaults to
                         ``OnnxEmbeddingModel()`` (production); inject a
                         lightweight fake in unit tests.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        model_version: str,
        embedding_model: EmbeddingModel | None = None,
    ) -> None:
        self._redis = redis_client
        self._model_version = model_version
        self._embedder: EmbeddingModel = (
            embedding_model if embedding_model is not None else OnnxEmbeddingModel()
        )
        self._key = f"{SENTIMENT_CACHE_REDIS_KEY_PREFIX}:{model_version}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, headline: str) -> SentimentScore | None:
        """Return a cached score if a semantically equivalent headline exists.

        Args:
            headline: Incoming headline text.

        Returns:
            ``SentimentScore`` with ``from_cache=True``, or ``None`` on miss.
        """
        raw_entries = self._load_entries()
        if not raw_entries:
            return None

        query_emb = self._embedder.embed(headline)
        best_sim = 0.0
        best_entry: dict[str, object] | None = None

        for entry in raw_entries:
            stored_emb_list = entry.get("embedding")
            if not isinstance(stored_emb_list, list):
                continue
            stored_emb = np.array(stored_emb_list, dtype=np.float32)
            if stored_emb.shape[0] != query_emb.shape[0]:
                continue
            sim = _cosine_similarity(query_emb, stored_emb)
            if sim > best_sim:
                best_sim = sim
                best_entry = entry

        if best_sim >= GPTCACHE_SIMILARITY_THRESHOLD and best_entry is not None:
            logger.debug(
                "sentiment_cache_hit",
                similarity=round(best_sim, 4),
                model_version=self._model_version,
            )
            score_dict = {
                k: v for k, v in best_entry.items() if k != "embedding"
            }
            return _dict_to_score(score_dict, from_cache=True)

        logger.debug(
            "sentiment_cache_miss",
            best_similarity=round(best_sim, 4),
            model_version=self._model_version,
        )
        return None

    def put(self, headline: str, score: SentimentScore) -> None:
        """Store a sentiment score with its embedding in Redis.

        Args:
            headline: The scored headline text (used to compute embedding).
            score:    The SentimentScore to cache.
        """
        emb = self._embedder.embed(headline)
        if emb.shape[0] != SENTIMENT_EMBEDDING_DIM:
            logger.warning(
                "sentiment_cache_unexpected_dim",
                got=emb.shape[0],
                expected=SENTIMENT_EMBEDDING_DIM,
            )
        entry: dict[str, object] = {
            **_score_to_dict(score),
            "embedding": emb.tolist(),
        }
        self._redis.rpush(self._key, json.dumps(entry))
        self._redis.expire(self._key, SENTIMENT_CACHE_REDIS_TTL_SECONDS)
        logger.debug(
            "sentiment_cache_stored",
            model_version=self._model_version,
        )

    def clear(self) -> None:
        """Delete all cached entries for this model version."""
        self._redis.delete(self._key)
        logger.info("sentiment_cache_cleared", model_version=self._model_version)

    def size(self) -> int:
        """Return the number of entries currently in the cache."""
        length = self._redis.llen(self._key)
        # redis-py 5.x stubs type llen as Awaitable[int]|int; the sync client
        # always returns int — cast via int() for mypy.
        return int(length)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_entries(self) -> list[dict[str, object]]:
        """Load all cached entries from Redis."""
        raw_list = self._redis.lrange(self._key, 0, -1)
        entries: list[dict[str, object]] = []
        for raw in raw_list:  # type: ignore[union-attr]
            try:
                data = json.loads(
                    raw if isinstance(raw, str) else raw.decode()
                )
                if isinstance(data, dict):
                    entries.append(data)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning(
                    "sentiment_cache_deserialise_failed", error=str(exc)
                )
        return entries
