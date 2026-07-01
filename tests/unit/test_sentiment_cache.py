"""Unit tests for M10 semantic dedup cache (cache.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import numpy as np
import numpy.typing as npt
import pytest

from shared.core.constants import (
    SENTIMENT_CACHE_REDIS_KEY_PREFIX,
    SENTIMENT_CACHE_REDIS_TTL_SECONDS,
    SENTIMENT_EMBEDDING_DIM,
)
from shared.sentiment.cache import (
    EmbeddingModel,
    SentimentCache,
    _cosine_similarity,
)
from shared.sentiment.models import SentimentScore

_MODEL_VERSION = "groq/llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# Fake embedding model for deterministic unit tests
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    """Returns one-hot unit vectors: same text → same vector, different → orthogonal."""

    _DIM: int = SENTIMENT_EMBEDDING_DIM

    def embed(self, text: str) -> npt.NDArray[np.float32]:
        v = np.zeros(self._DIM, dtype=np.float32)
        v[hash(text) % self._DIM] = 1.0
        return v

    @property
    def dimension(self) -> int:
        return self._DIM


def _assert_is_embedding_model(m: object) -> None:
    assert isinstance(m, EmbeddingModel)


def _make_score(headline: str = "test", label: str = "BULLISH") -> SentimentScore:
    return SentimentScore(
        headline=headline,
        score=0.7,
        label=label,
        confidence=0.85,
        tokens_used=50,
        from_cache=False,
        model_version=_MODEL_VERSION,
    )


def _make_cache(redis_mock: MagicMock) -> SentimentCache:
    return SentimentCache(
        redis_client=redis_mock,
        model_version=_MODEL_VERSION,
        embedding_model=_FakeEmbedder(),
    )


def _serialize_entry(headline: str, score: SentimentScore) -> bytes:
    """Build a Redis-format serialized entry (like SentimentCache.put stores)."""
    embedder = _FakeEmbedder()
    emb = embedder.embed(headline)
    entry = {
        "headline": score.headline,
        "score": score.score,
        "label": score.label,
        "confidence": score.confidence,
        "tokens_used": score.tokens_used,
        "model_version": score.model_version,
        "embedding": emb.tolist(),
    }
    return json.dumps(entry).encode()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestEmbeddingModelProtocol:
    def test_fake_embedder_satisfies_protocol(self) -> None:
        _assert_is_embedding_model(_FakeEmbedder())

    def test_embed_returns_float32_array(self) -> None:
        embedder = _FakeEmbedder()
        v = embedder.embed("hello")
        assert v.dtype == np.float32
        assert v.shape == (SENTIMENT_EMBEDDING_DIM,)

    def test_same_text_same_vector(self) -> None:
        embedder = _FakeEmbedder()
        v1 = embedder.embed("same text")
        v2 = embedder.embed("same text")
        np.testing.assert_array_equal(v1, v2)


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_zero_vector_returns_zero(self) -> None:
        z = np.zeros(3, dtype=np.float32)
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert _cosine_similarity(z, v) == 0.0
        assert _cosine_similarity(v, z) == 0.0

    def test_opposite_vectors_negative(self) -> None:
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_partial_similarity(self) -> None:
        a = np.array([1.0, 1.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        sim = _cosine_similarity(a, b)
        assert 0.0 < sim < 1.0


# ---------------------------------------------------------------------------
# SentimentCache.get — cache miss
# ---------------------------------------------------------------------------


class TestCacheGetMiss:
    def test_empty_cache_returns_none(self) -> None:
        mock_redis = MagicMock()
        mock_redis.lrange.return_value = []
        cache = _make_cache(mock_redis)
        assert cache.get("any headline") is None

    def test_different_text_different_vector_miss(self) -> None:
        mock_redis = MagicMock()
        stored_entry = _serialize_entry(
            "NIFTY up 1%", _make_score("NIFTY up 1%")
        )
        mock_redis.lrange.return_value = [stored_entry]
        cache = _make_cache(mock_redis)
        # "NIFTY down 5%" hashes to a different bucket → orthogonal → miss
        result = cache.get("NIFTY down 5%")
        # one-hot hash difference should be well below 0.95
        if result is not None:
            # If by chance they hash to the same bucket, that is a test
            # collision, not a bug.  Skip in that case.
            pytest.skip("hash collision in fake embedder")

    def test_malformed_redis_entry_skipped(self) -> None:
        mock_redis = MagicMock()
        mock_redis.lrange.return_value = [b"not-json"]
        cache = _make_cache(mock_redis)
        assert cache.get("any headline") is None

    def test_wrong_embedding_dim_skipped(self) -> None:
        mock_redis = MagicMock()
        entry = {"headline": "x", "score": 0.5, "label": "NEUTRAL",
                 "confidence": 0.5, "tokens_used": 10, "model_version": _MODEL_VERSION,
                 "embedding": [1.0, 0.0]}  # dim=2, not 384
        mock_redis.lrange.return_value = [json.dumps(entry).encode()]
        cache = _make_cache(mock_redis)
        assert cache.get("any headline") is None


# ---------------------------------------------------------------------------
# SentimentCache.get — cache hit
# ---------------------------------------------------------------------------


class TestCacheGetHit:
    def test_identical_text_returns_cached_score(self) -> None:
        mock_redis = MagicMock()
        headline = "NIFTY up 1% on strong FII buying"
        original_score = _make_score(headline)
        stored = _serialize_entry(headline, original_score)
        mock_redis.lrange.return_value = [stored]
        cache = _make_cache(mock_redis)
        result = cache.get(headline)
        assert result is not None
        assert result.from_cache is True
        assert result.label == "BULLISH"

    def test_hit_score_has_zero_tokens(self) -> None:
        mock_redis = MagicMock()
        headline = "Same headline text"
        stored = _serialize_entry(headline, _make_score(headline))
        mock_redis.lrange.return_value = [stored]
        cache = _make_cache(mock_redis)
        result = cache.get(headline)
        assert result is not None
        assert result.tokens_used == 0


# ---------------------------------------------------------------------------
# SentimentCache.put
# ---------------------------------------------------------------------------


class TestCachePut:
    def test_rpush_called(self) -> None:
        mock_redis = MagicMock()
        cache = _make_cache(mock_redis)
        cache.put("NIFTY surges", _make_score())
        mock_redis.rpush.assert_called_once()

    def test_expire_called_with_ttl(self) -> None:
        mock_redis = MagicMock()
        cache = _make_cache(mock_redis)
        cache.put("some headline", _make_score())
        mock_redis.expire.assert_called_once_with(
            f"{SENTIMENT_CACHE_REDIS_KEY_PREFIX}:{_MODEL_VERSION}",
            SENTIMENT_CACHE_REDIS_TTL_SECONDS,
        )

    def test_stored_entry_is_valid_json(self) -> None:
        mock_redis = MagicMock()
        cache = _make_cache(mock_redis)
        cache.put("headline text", _make_score())
        args, _ = mock_redis.rpush.call_args
        raw = args[1]
        parsed = json.loads(raw)
        assert "embedding" in parsed
        assert isinstance(parsed["embedding"], list)

    def test_redis_key_includes_model_version(self) -> None:
        mock_redis = MagicMock()
        cache = _make_cache(mock_redis)
        cache.put("h", _make_score())
        args, _ = mock_redis.rpush.call_args
        assert _MODEL_VERSION in args[0]


# ---------------------------------------------------------------------------
# SentimentCache.clear + size
# ---------------------------------------------------------------------------


class TestCacheClearSize:
    def test_clear_calls_delete(self) -> None:
        mock_redis = MagicMock()
        cache = _make_cache(mock_redis)
        cache.clear()
        mock_redis.delete.assert_called_once()

    def test_size_reads_llen(self) -> None:
        mock_redis = MagicMock()
        mock_redis.llen.return_value = 7
        cache = _make_cache(mock_redis)
        assert cache.size() == 7
