"""Unit tests for M10 SentimentAgent orchestrator (agent.py)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import numpy.typing as npt
import pytest

from shared.sentiment.agent import SentimentAgent, _compute_aggregate_score
from shared.sentiment.models import (
    FIIDIIData,
    Headline,
    MarketSentiment,
    SentimentScore,
    VIXData,
)

_MODEL = "groq/llama-3.1-8b-instant"
_NOW = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


def _make_score(
    headline: str = "test",
    score: float = 0.7,
    label: str = "BULLISH",
    confidence: float = 0.8,
    from_cache: bool = False,
) -> SentimentScore:
    return SentimentScore(
        headline=headline,
        score=score,
        label=label,
        confidence=confidence,
        tokens_used=50,
        from_cache=from_cache,
        model_version=_MODEL,
    )


# ---------------------------------------------------------------------------
# _compute_aggregate_score
# ---------------------------------------------------------------------------


class TestComputeAggregateScore:
    def test_empty_list_returns_zero(self) -> None:
        assert _compute_aggregate_score([]) == 0.0

    def test_all_zero_confidence_returns_zero(self) -> None:
        scores = [_make_score(confidence=0.0)]
        assert _compute_aggregate_score(scores) == 0.0

    def test_single_score(self) -> None:
        scores = [_make_score(score=0.8, confidence=1.0)]
        assert _compute_aggregate_score(scores) == pytest.approx(0.8)

    def test_confidence_weighted_mean(self) -> None:
        scores = [
            _make_score(score=1.0, confidence=0.9),
            _make_score(score=-1.0, confidence=0.1),
        ]
        agg = _compute_aggregate_score(scores)
        # weighted: (1.0*0.9 + -1.0*0.1) / (0.9+0.1) = 0.8
        assert agg == pytest.approx(0.8)

    def test_symmetric_scores_near_zero(self) -> None:
        scores = [
            _make_score(score=0.8, confidence=0.5),
            _make_score(score=-0.8, confidence=0.5),
        ]
        assert abs(_compute_aggregate_score(scores)) < 1e-9

    def test_mixed_zero_and_nonzero_confidence(self) -> None:
        scores = [
            _make_score(score=0.9, confidence=0.0),  # excluded
            _make_score(score=0.5, confidence=0.8),
        ]
        agg = _compute_aggregate_score(scores)
        assert agg == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Fake embedding model for cache tests
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    _DIM: int = 384

    def embed(self, text: str) -> npt.NDArray[np.float32]:
        v = np.zeros(self._DIM, dtype=np.float32)
        v[hash(text) % self._DIM] = 1.0
        return v

    @property
    def dimension(self) -> int:
        return self._DIM


# ---------------------------------------------------------------------------
# SentimentAgent.run — no cache mode
# ---------------------------------------------------------------------------


class TestSentimentAgentNoCacheMode:
    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_run_with_custom_headlines(self, mock_score: MagicMock) -> None:
        mock_score.return_value = (
            [_make_score("h1", 0.8), _make_score("h2", -0.5, "BEARISH")],
            100,
        )
        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE", custom_headlines=["h1", "h2"])
        assert isinstance(result, MarketSentiment)
        assert result.exchange == "NSE"
        assert len(result.scores) == 2

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_run_empty_headlines_returns_empty(self, mock_score: MagicMock) -> None:
        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE", custom_headlines=[])
        assert result.aggregate_score == 0.0
        assert result.headlines == []
        mock_score.assert_not_called()

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_aggregate_score_computed(self, mock_score: MagicMock) -> None:
        mock_score.return_value = (
            [_make_score("h", 1.0, "BULLISH", 1.0)], 50
        )
        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE", custom_headlines=["h"])
        assert result.aggregate_score == pytest.approx(1.0)

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_no_market_indicators_when_custom_headlines(
        self, mock_score: MagicMock
    ) -> None:
        mock_score.return_value = ([_make_score("h")], 30)
        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE", custom_headlines=["h"])
        # Custom headlines skips market indicator fetch
        assert result.fii_dii is None
        assert result.vix_data is None

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_cache_misses_equals_headline_count_when_no_cache(
        self, mock_score: MagicMock
    ) -> None:
        mock_score.return_value = (
            [_make_score(f"h{i}") for i in range(3)], 150
        )
        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE", custom_headlines=["h0", "h1", "h2"])
        assert result.cache_misses == 3
        assert result.cache_hits == 0


# ---------------------------------------------------------------------------
# SentimentAgent.run — with Redis cache (VERIFY scenario)
# ---------------------------------------------------------------------------


class TestSentimentAgentWithCache:
    def _make_redis(self) -> MagicMock:
        r = MagicMock()
        r.get.return_value = None   # cost tracker: no prior spend
        r.lrange.return_value = []  # cache starts empty
        return r

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_cache_hit_prevents_llm_call(self, mock_score: MagicMock) -> None:
        """Second run with same headlines → all cache hits → LLM not called."""
        redis_mock = self._make_redis()
        embedder = _FakeEmbedder()

        # Manually prime the cache with a pre-stored entry
        headline = "NIFTY rises 2% on FII buying"

        # Simulate a pre-populated cache entry
        emb = embedder.embed(headline)
        entry = {
            "headline": headline,
            "score": 0.8,
            "label": "BULLISH",
            "confidence": 0.9,
            "tokens_used": 50,
            "model_version": _MODEL,
            "embedding": emb.tolist(),
        }
        redis_mock.lrange.return_value = [json.dumps(entry).encode()]

        agent = SentimentAgent(
            model=_MODEL, redis_client=redis_mock, embedding_model=embedder
        )
        result = agent.run("NSE", custom_headlines=[headline])

        assert result.cache_hits == 1
        assert result.cache_misses == 0
        mock_score.assert_not_called()

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_cache_stores_new_scores(self, mock_score: MagicMock) -> None:
        """First run with no cache → LLM called → scores stored in cache."""
        redis_mock = self._make_redis()
        embedder = _FakeEmbedder()

        mock_score.return_value = ([_make_score("new headline", 0.5)], 50)

        agent = SentimentAgent(
            model=_MODEL, redis_client=redis_mock, embedding_model=embedder
        )
        agent.run("NSE", custom_headlines=["new headline"])

        # rpush should have been called to store the new score
        redis_mock.rpush.assert_called()

    @patch("shared.sentiment.agent.score_headlines_batch")
    def test_cost_tracked_on_miss(self, mock_score: MagicMock) -> None:
        redis_mock = self._make_redis()
        embedder = _FakeEmbedder()
        mock_score.return_value = ([_make_score("h", 0.5)], 200)

        agent = SentimentAgent(
            model=_MODEL, redis_client=redis_mock, embedding_model=embedder
        )
        agent.run("NSE", custom_headlines=["h"])

        # incrbyfloat should have been called to record cost
        redis_mock.incrbyfloat.assert_called()


# ---------------------------------------------------------------------------
# SentimentAgent.run — RSS feed path (with mocked fetch_all_feeds)
# ---------------------------------------------------------------------------


class TestSentimentAgentFeedPath:
    @patch("shared.sentiment.agent.fetch_india_vix")
    @patch("shared.sentiment.agent.fetch_fii_dii")
    @patch("shared.sentiment.agent.score_headlines_batch")
    @patch("shared.sentiment.agent.fetch_all_feeds")
    def test_rss_path_fetches_feeds_and_indicators(
        self,
        mock_feeds: MagicMock,
        mock_score: MagicMock,
        mock_fii: MagicMock,
        mock_vix: MagicMock,
    ) -> None:
        mock_feeds.return_value = [
            Headline(
                text="NSE rises",
                url=None,
                source="et",
                published_at=_NOW,
                exchange="NSE",
            )
        ]
        mock_score.return_value = ([_make_score("NSE rises")], 50)
        mock_fii.return_value = FIIDIIData(
            date=_NOW.date(),
            fii_net_crore=1000.0,
            dii_net_crore=500.0,
            fetched_at=_NOW,
        )
        mock_vix.return_value = VIXData(
            vix=14.5, put_call_ratio=0.9, fetched_at=_NOW
        )

        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE")

        assert result.fii_dii is not None
        assert result.vix_data is not None
        mock_feeds.assert_called_once_with("NSE")

    @patch("shared.sentiment.agent.score_headlines_batch")
    @patch("shared.sentiment.agent.fetch_all_feeds")
    def test_feed_exception_returns_empty(
        self, mock_feeds: MagicMock, mock_score: MagicMock
    ) -> None:
        mock_feeds.side_effect = RuntimeError("network error")
        agent = SentimentAgent(model=_MODEL)
        result = agent.run("NSE")
        assert result.headlines == []
        assert result.aggregate_score == 0.0
        mock_score.assert_not_called()
