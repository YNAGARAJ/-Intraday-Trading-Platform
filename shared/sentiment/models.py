"""M10 Sentiment & News Agent — data models.

All dataclasses in this file are frozen (immutable) to prevent accidental
mutation after construction. The ``MarketSentiment`` aggregate result is the
primary output consumed by M11 Signal Generation (Gate 8 sentiment gate).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True)
class Headline:
    """A single news headline fetched from an RSS feed or announcement endpoint.

    Args:
        text:         Headline text used for LLM scoring.
        url:          Source article URL (may be None if not provided by feed).
        source:       Feed or scraper name (e.g. ``"economic_times"``).
        published_at: Publication datetime (UTC).
        exchange:     Target exchange (``"NSE"``, ``"ASX"``, or ``None`` for both).
    """

    text: str
    url: str | None
    source: str
    published_at: datetime
    exchange: str | None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Headline.text must not be blank")
        if self.published_at.tzinfo is None:
            raise ValueError("Headline.published_at must be timezone-aware")
        if self.exchange is not None and self.exchange not in ("NSE", "ASX"):
            raise ValueError(f"Unknown exchange: {self.exchange!r}")


@dataclass(frozen=True)
class SentimentScore:
    """LLM-generated sentiment score for a single headline.

    Args:
        headline:      The scored headline text.
        score:         Sentiment strength in [-1.0, 1.0].  Negative = bearish,
                       zero = neutral, positive = bullish.
        label:         Human-readable label: ``"BULLISH"``, ``"BEARISH"``, or
                       ``"NEUTRAL"``.
        confidence:    Model confidence in [0.0, 1.0].
        tokens_used:   Tokens consumed for this headline (0 for cache hits).
        from_cache:    ``True`` if score was returned from the semantic cache
                       (no LLM call made).
        model_version: Identifier for the LLM used (e.g.
                       ``"groq/llama-3.1-8b-instant"``).
    """

    headline: str
    score: float
    label: str
    confidence: float
    tokens_used: int
    from_cache: bool
    model_version: str

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [-1, 1], got {self.score}")
        if self.label not in ("BULLISH", "BEARISH", "NEUTRAL"):
            raise ValueError(f"Unknown label: {self.label!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
        if self.tokens_used < 0:
            raise ValueError(f"tokens_used must be >= 0, got {self.tokens_used}")


@dataclass(frozen=True)
class FIIDIIData:
    """Daily provisional FII/DII trading activity from NSE.

    Args:
        date:           Trading date this data represents.
        fii_net_crore:  FII net buy/sell in INR crores (negative = net sell).
        dii_net_crore:  DII net buy/sell in INR crores.
        fetched_at:     When the data was retrieved (UTC).
    """

    date: date
    fii_net_crore: float
    dii_net_crore: float
    fetched_at: datetime

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("FIIDIIData.fetched_at must be timezone-aware")

    @property
    def net_institutional(self) -> float:
        """Combined FII + DII net flow (positive = net buyer)."""
        return self.fii_net_crore + self.dii_net_crore


@dataclass(frozen=True)
class VIXData:
    """India VIX (volatility index) and NIFTY put-call ratio snapshot.

    Args:
        vix:            India VIX level at fetch time.
        put_call_ratio: NIFTY option chain PCR (None if unavailable).
        fetched_at:     When the data was retrieved (UTC).
    """

    vix: float
    put_call_ratio: float | None
    fetched_at: datetime

    def __post_init__(self) -> None:
        if self.vix < 0.0:
            raise ValueError(f"VIX must be non-negative, got {self.vix}")
        if self.put_call_ratio is not None and self.put_call_ratio < 0.0:
            raise ValueError(
                f"put_call_ratio must be non-negative, got {self.put_call_ratio}"
            )
        if self.fetched_at.tzinfo is None:
            raise ValueError("VIXData.fetched_at must be timezone-aware")


@dataclass
class MarketSentiment:
    """Aggregated sentiment output from one SentimentAgent.run() call.

    This is the primary artifact consumed by M11's Gate 8 (sentiment gate).
    The ``aggregate_score`` is a confidence-weighted mean of all scored
    headlines; a value near zero indicates balanced or insufficient signal.

    Args:
        exchange:          Exchange this run targeted (``"NSE"`` or ``"ASX"``).
        headlines:         All headlines fetched (before any cap truncation).
        scores:            One SentimentScore per headline (same order).
        aggregate_score:   Confidence-weighted mean score in [-1.0, 1.0].
        fii_dii:           Provisional FII/DII data (``None`` if fetch failed).
        vix_data:          India VIX snapshot (``None`` if unavailable / ASX).
        total_tokens_used: Sum of tokens across all LLM calls.
        total_cost_usd:    Estimated LLM spend for this run (USD).
        cache_hits:        Headlines returned from the semantic cache.
        cache_misses:      Headlines that required a live LLM call.
        scored_at:         UTC timestamp of this run.
    """

    exchange: str
    headlines: list[Headline]
    scores: list[SentimentScore]
    aggregate_score: float
    fii_dii: FIIDIIData | None
    vix_data: VIXData | None
    total_tokens_used: int
    total_cost_usd: float
    cache_hits: int
    cache_misses: int
    scored_at: datetime

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of headlines served from cache (0.0 if no headlines)."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    @classmethod
    def empty(cls, exchange: str) -> "MarketSentiment":
        """Return a zero-cost, no-signal MarketSentiment (e.g. on feed failure)."""
        return cls(
            exchange=exchange,
            headlines=[],
            scores=[],
            aggregate_score=0.0,
            fii_dii=None,
            vix_data=None,
            total_tokens_used=0,
            total_cost_usd=0.0,
            cache_hits=0,
            cache_misses=0,
            scored_at=datetime.now(tz=timezone.utc),
        )
