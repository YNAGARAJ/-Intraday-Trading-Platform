"""Integration tests for M10 Sentiment & News Agent.

VERIFY scenario (from spec §M10):
  score 20 headlines → second run shows cache hits → cost reduced.

These tests require:
  - A running Redis instance (see conftest.py — auto-skip if unreachable)
  - No live LLM key needed: all LLM calls are mocked at the litellm layer

The cache itself (SentimentCache + SentimentAgent) runs against real Redis so
we validate the full round-trip: embed → store → retrieve → cosine similarity.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import numpy as np
import numpy.typing as npt
import pytest

from shared.sentiment.agent import SentimentAgent
from shared.sentiment.models import MarketSentiment

if TYPE_CHECKING:
    import redis as redis_module

_MODEL = "groq/llama-3.1-8b-instant"
_CACHE_KEY_PREFIX = f"sentiment:cache:{_MODEL}"
_N_HEADLINES = 20


# ---------------------------------------------------------------------------
# Fake embedding model (deterministic, no HuggingFace download)
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    """One-hot unit vectors: same text → cosine = 1.0, different → cosine = 0.0."""

    _DIM: int = 384

    def embed(self, text: str) -> npt.NDArray[np.float32]:
        v = np.zeros(self._DIM, dtype=np.float32)
        v[hash(text) % self._DIM] = 1.0
        return v

    @property
    def dimension(self) -> int:
        return self._DIM


# ---------------------------------------------------------------------------
# Fake LLM response builder
# ---------------------------------------------------------------------------


def _make_litellm_response(n: int) -> MagicMock:
    """Return a fake litellm ModelResponse scoring n headlines as NEUTRAL."""
    content = json.dumps(
        {"results": [{"score": 0.0, "label": "NEUTRAL", "confidence": 0.5}] * n}
    )
    resp = MagicMock()
    resp.usage.total_tokens = n * 10
    resp.choices[0].message.content = content
    return resp


# ---------------------------------------------------------------------------
# VERIFY: spec §M10 — score 20 headlines → second run shows cache hits
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSentimentCacheRoundTrip:
    """VERIFY: score 20 headlines → second run returns cache hits → cost = 0."""

    @pytest.fixture(autouse=True)
    def _flush_cache(self, redis_client: "redis_module.Redis[bytes]") -> None:
        """Remove any leftover cache entries before and after each test."""
        redis_client.delete(_CACHE_KEY_PREFIX)
        yield  # type: ignore[misc]
        redis_client.delete(_CACHE_KEY_PREFIX)

    @patch("shared.sentiment.scorer.litellm")
    def test_first_run_all_misses(
        self,
        mock_litellm: MagicMock,
        redis_client: "redis_module.Redis[bytes]",
    ) -> None:
        """First run with empty cache → all headlines go to LLM."""
        mock_litellm.completion.return_value = _make_litellm_response(
            _N_HEADLINES
        )
        headlines = [f"Headline {i}: market update" for i in range(_N_HEADLINES)]

        agent = SentimentAgent(
            model=_MODEL,
            redis_client=redis_client,
            embedding_model=_FakeEmbedder(),
        )
        result: MarketSentiment = agent.run("NSE", custom_headlines=headlines)

        assert result.cache_hits == 0
        assert result.cache_misses == _N_HEADLINES
        assert result.cache_hit_rate == 0.0
        # LLM was called (batched into at most 20-headline batches)
        assert mock_litellm.completion.called

    @patch("shared.sentiment.scorer.litellm")
    def test_second_run_all_hits(
        self,
        mock_litellm: MagicMock,
        redis_client: "redis_module.Redis[bytes]",
    ) -> None:
        """VERIFY: second run with same 20 headlines → all cache hits → no LLM call."""
        mock_litellm.completion.return_value = _make_litellm_response(
            _N_HEADLINES
        )
        headlines = [f"Headline {i}: market update" for i in range(_N_HEADLINES)]
        embedder = _FakeEmbedder()

        agent = SentimentAgent(
            model=_MODEL,
            redis_client=redis_client,
            embedding_model=embedder,
        )

        # First run — populates cache
        first_result = agent.run("NSE", custom_headlines=headlines)
        assert first_result.cache_misses == _N_HEADLINES

        # Reset call counter
        mock_litellm.completion.reset_mock()

        # Second run — same agent, same headlines, same Redis
        second_result = agent.run("NSE", custom_headlines=headlines)

        assert second_result.cache_hits == _N_HEADLINES
        assert second_result.cache_misses == 0
        assert second_result.cache_hit_rate == 1.0
        # No LLM calls on second run
        mock_litellm.completion.assert_not_called()

    @patch("shared.sentiment.scorer.litellm")
    def test_second_run_cost_is_zero(
        self,
        mock_litellm: MagicMock,
        redis_client: "redis_module.Redis[bytes]",
    ) -> None:
        """VERIFY: second run total_cost_usd == 0.0 (all from cache, 0 tokens)."""
        mock_litellm.completion.return_value = _make_litellm_response(
            _N_HEADLINES
        )
        headlines = [f"Headline {i}: cost check" for i in range(_N_HEADLINES)]
        embedder = _FakeEmbedder()

        agent = SentimentAgent(
            model=_MODEL,
            redis_client=redis_client,
            embedding_model=embedder,
        )

        # First run
        agent.run("NSE", custom_headlines=headlines)
        mock_litellm.completion.reset_mock()

        # Second run
        result = agent.run("NSE", custom_headlines=headlines)

        assert result.total_tokens_used == 0
        assert result.total_cost_usd == 0.0

    @patch("shared.sentiment.scorer.litellm")
    def test_partial_cache_hit(
        self,
        mock_litellm: MagicMock,
        redis_client: "redis_module.Redis[bytes]",
    ) -> None:
        """10 headlines cached, 10 new → 10 hits + 10 misses on second run."""
        mock_litellm.completion.return_value = _make_litellm_response(10)
        first_10 = [f"Cached headline {i}" for i in range(10)]
        next_10 = [f"New headline {i}" for i in range(10)]
        embedder = _FakeEmbedder()

        agent = SentimentAgent(
            model=_MODEL,
            redis_client=redis_client,
            embedding_model=embedder,
        )

        # First run: cache first 10
        agent.run("NSE", custom_headlines=first_10)
        mock_litellm.completion.reset_mock()
        mock_litellm.completion.return_value = _make_litellm_response(10)

        # Second run: first 10 from cache, next 10 from LLM
        result = agent.run("NSE", custom_headlines=first_10 + next_10)

        assert result.cache_hits == 10
        assert result.cache_misses == 10
        assert result.cache_hit_rate == pytest.approx(0.5)
        mock_litellm.completion.assert_called_once()
