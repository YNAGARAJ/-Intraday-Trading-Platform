"""M10 Sentiment & News Agent — SentimentAgent orchestrator.

Wires together RSS feed scraping, GPTCache semantic dedup, LiteLLM batched
scoring, market indicator fetching, and cost tracking into a single ``run()``
call that produces a ``MarketSentiment`` result.

Public API
----------
SentimentAgent(model, api_key, redis_client, embedding_model)
    .run(exchange, custom_headlines) → MarketSentiment
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis
import structlog

from shared.core.constants import (
    SENTIMENT_DEFAULT_MODEL,
    SENTIMENT_GROQ_COST_PER_1M_INPUT_USD,
    SENTIMENT_GROQ_COST_PER_1M_OUTPUT_USD,
)
from shared.sentiment.cache import EmbeddingModel, SentimentCache
from shared.sentiment.cost_tracker import CostTracker
from shared.sentiment.feeds import fetch_all_feeds
from shared.sentiment.market_indicators import fetch_fii_dii, fetch_india_vix
from shared.sentiment.models import (
    FIIDIIData,
    Headline,
    MarketSentiment,
    SentimentScore,
    VIXData,
)
from shared.sentiment.scorer import score_headlines_batch

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _compute_aggregate_score(scores: list[SentimentScore]) -> float:
    """Return a confidence-weighted mean of all sentiment scores.

    Scores with confidence 0.0 (e.g. parse-failure fallbacks) are excluded.
    Returns 0.0 when the list is empty or all confidence values are zero.
    """
    total_weight = 0.0
    weighted_sum = 0.0
    for s in scores:
        if s.confidence > 0.0:
            weighted_sum += s.score * s.confidence
            total_weight += s.confidence
    return weighted_sum / total_weight if total_weight > 0.0 else 0.0


class SentimentAgent:
    """Orchestrates the full sentiment pipeline for a given exchange.

    The agent:
    1. Fetches RSS headlines (or accepts caller-supplied ones).
    2. For each headline, checks the GPTCache semantic dedup cache.
    3. Batches cache-miss headlines and scores them via LiteLLM (Groq 8B).
    4. Stores new scores in the cache.
    5. Fetches India VIX and FII/DII data (NSE only; fail-open).
    6. Computes a confidence-weighted aggregate score.
    7. Logs LLM cost per call (structlog + Redis counter).

    All LLM calls follow RULE 4 (hot path is zero-LLM): the agent is invoked
    pre-market and produces a ``MarketSentiment`` that is cached for the
    session.  Signal evaluation itself (M11) reads the aggregate without
    issuing any new LLM calls.

    Args:
        model:           LiteLLM model string. Defaults to
                         ``SENTIMENT_DEFAULT_MODEL`` (Groq Llama 3.1 8B).
        api_key:         Optional provider API key override.  When ``None``,
                         the relevant environment variable is used
                         (e.g. ``GROQ_API_KEY``).
        redis_client:    Redis client for semantic cache + cost tracking.
                         When ``None`` both operate in memory-only mode.
        embedding_model: Injection point for the embedding model used by
                         ``SentimentCache``.  ``None`` uses
                         ``OnnxEmbeddingModel`` (downloads on first use).
    """

    def __init__(
        self,
        model: str = SENTIMENT_DEFAULT_MODEL,
        api_key: str | None = None,
        redis_client: redis.Redis | None = None,
        embedding_model: EmbeddingModel | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._cost_tracker = CostTracker(redis_client)
        self._cache: SentimentCache | None = (
            SentimentCache(redis_client, model, embedding_model)
            if redis_client is not None
            else None
        )

    def run(
        self,
        exchange: str,
        custom_headlines: list[str] | None = None,
    ) -> MarketSentiment:
        """Run the full sentiment pipeline.

        Args:
            exchange:         ``"NSE"`` or ``"ASX"``.
            custom_headlines: When provided, skip RSS fetch and use these
                              headline strings directly (useful for testing
                              and VERIFY scenarios).

        Returns:
            ``MarketSentiment`` with all scored headlines, market indicators,
            aggregate score, and cost metadata.
        """
        now = datetime.now(tz=timezone.utc)
        logger.info("sentiment_agent_run_start", exchange=exchange, model=self._model)

        # --- 1. Fetch headlines ---
        if custom_headlines is not None:
            headlines: list[Headline] = [
                Headline(
                    text=h,
                    url=None,
                    source="custom",
                    published_at=now,
                    exchange=(
                        exchange.upper()
                        if exchange.upper() in ("NSE", "ASX")
                        else None
                    ),
                )
                for h in custom_headlines
            ]
        else:
            try:
                headlines = fetch_all_feeds(exchange)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sentiment_feed_fetch_failed",
                    exchange=exchange,
                    error=str(exc),
                )
                headlines = []

        if not headlines:
            logger.info("sentiment_no_headlines", exchange=exchange)
            return MarketSentiment.empty(exchange)

        # --- 2. Cache lookup + batched scoring ---
        scores: list[SentimentScore] = []
        to_score_indices: list[int] = []
        to_score_texts: list[str] = []
        cache_hits = 0

        for i, h in enumerate(headlines):
            if self._cache is not None:
                cached = self._cache.get(h.text)
                if cached is not None:
                    scores.append(cached)
                    cache_hits += 1
                    continue
            scores.append(None)  # type: ignore[arg-type]  # placeholder
            to_score_indices.append(i)
            to_score_texts.append(h.text)

        cache_misses = len(to_score_texts)

        if to_score_texts:
            new_scores, total_tokens = score_headlines_batch(
                to_score_texts, self._model, self._api_key
            )
            # Approximate input/output split: 80/20 for Groq prompt-heavy calls
            input_toks = int(total_tokens * 0.8)
            output_toks = total_tokens - input_toks
            self._cost_tracker.record(self._model, input_toks, output_toks)

            for original_idx, new_score in zip(
                to_score_indices, new_scores, strict=False
            ):
                scores[original_idx] = new_score
                if self._cache is not None:
                    self._cache.put(headlines[original_idx].text, new_score)
        else:
            total_tokens = 0

        # Compute cost for this run from session tracker
        blended_rate = (
            SENTIMENT_GROQ_COST_PER_1M_INPUT_USD * 0.8
            + SENTIMENT_GROQ_COST_PER_1M_OUTPUT_USD * 0.2
        )
        call_cost = total_tokens * blended_rate / 1_000_000

        # --- 3. Market indicators (NSE only; ASX indicators out of scope for M10) ---
        fii_dii: FIIDIIData | None = None
        vix_data: VIXData | None = None
        if exchange.upper() == "NSE" and custom_headlines is None:
            try:
                vix_data = fetch_india_vix()
            except Exception as exc:  # noqa: BLE001
                logger.warning("sentiment_vix_fetch_failed", error=str(exc))
            try:
                fii_dii = fetch_fii_dii()
            except Exception as exc:  # noqa: BLE001
                logger.warning("sentiment_fii_dii_fetch_failed", error=str(exc))

        # --- 4. Aggregate ---
        final_scores: list[SentimentScore] = [
            s for s in scores if s is not None
        ]
        agg = _compute_aggregate_score(final_scores)

        logger.info(
            "sentiment_agent_run_complete",
            exchange=exchange,
            headlines=len(headlines),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            aggregate_score=round(agg, 4),
            total_tokens=total_tokens,
            cost_usd=round(call_cost, 6),
        )

        return MarketSentiment(
            exchange=exchange.upper(),
            headlines=headlines,
            scores=final_scores,
            aggregate_score=agg,
            fii_dii=fii_dii,
            vix_data=vix_data,
            total_tokens_used=total_tokens,
            total_cost_usd=call_cost,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            scored_at=now,
        )
