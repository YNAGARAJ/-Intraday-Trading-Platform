"""M10 — Sentiment & News Agent.

Pre-market RSS scraping, batched Groq sentiment scoring, GPTCache semantic
dedup, FII/DII + India VIX feed, and LLM cost tracking.

Public API
----------
SentimentAgent       — orchestrator; call ``.run(exchange)``
MarketSentiment      — primary output consumed by M11 Gate 8
Headline             — single news item
SentimentScore       — per-headline LLM sentiment result
FIIDIIData           — daily provisional FII/DII flows
VIXData              — India VIX + put-call ratio snapshot
CostTracker          — LLM cost logging
SentimentCache       — semantic dedup cache (injectable embedding model)
EmbeddingModel       — Protocol for embedding model injection
fetch_all_feeds      — fetch + deduplicate RSS headlines for an exchange
score_headlines_batch — batched LLM scoring (max 20 per call)
fetch_india_vix      — India VIX from NSE allIndices API
fetch_fii_dii        — Provisional FII/DII from NSE fiidiiTradeReact
"""

from shared.sentiment.agent import SentimentAgent
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

__all__ = [
    "SentimentAgent",
    "MarketSentiment",
    "Headline",
    "SentimentScore",
    "FIIDIIData",
    "VIXData",
    "CostTracker",
    "SentimentCache",
    "EmbeddingModel",
    "fetch_all_feeds",
    "score_headlines_batch",
    "fetch_india_vix",
    "fetch_fii_dii",
]
