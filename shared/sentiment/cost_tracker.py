"""M10 Sentiment & News Agent — LLM cost tracker.

Logs per-call LLM token usage and estimated cost to Redis (daily counter) and
structlog.  Triggers a warning log when the daily total approaches the budget
target (``LLM_DAILY_COST_TARGET_USD``).

Public API
----------
CostTracker(redis_client=None)
    .record(model, input_tokens, output_tokens)  → float  (call cost USD)
    .get_daily_total_usd()                        → float
    .reset_daily()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import redis
import structlog

from shared.core.constants import (
    LLM_DAILY_COST_TARGET_USD,
    SENTIMENT_COST_REDIS_KEY_PREFIX,
    SENTIMENT_GROQ_COST_PER_1M_INPUT_USD,
    SENTIMENT_GROQ_COST_PER_1M_OUTPUT_USD,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Model cost table (USD per 1M tokens, input/output)
# ---------------------------------------------------------------------------

_COST_TABLE: dict[str, tuple[float, float]] = {
    "groq/llama-3.1-8b-instant": (
        SENTIMENT_GROQ_COST_PER_1M_INPUT_USD,
        SENTIMENT_GROQ_COST_PER_1M_OUTPUT_USD,
    ),
    "groq/llama-3.3-70b-versatile": (0.27, 0.27),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.25, 1.25),
}

_DEFAULT_COST_PER_1M: tuple[float, float] = (
    SENTIMENT_GROQ_COST_PER_1M_INPUT_USD,
    SENTIMENT_GROQ_COST_PER_1M_OUTPUT_USD,
)

_REDIS_TTL_SECONDS: int = 90_000  # 25h — survives full trading day + post-close


def _redis_key(dt: datetime) -> str:
    return f"{SENTIMENT_COST_REDIS_KEY_PREFIX}:{dt.strftime('%Y%m%d')}"


def _compute_cost(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Compute estimated USD cost for an LLM call.

    Args:
        model:         LiteLLM model string.
        input_tokens:  Number of input/prompt tokens.
        output_tokens: Number of completion tokens.

    Returns:
        Estimated cost in USD.
    """
    cost_in, cost_out = _COST_TABLE.get(model, _DEFAULT_COST_PER_1M)
    return (input_tokens * cost_in + output_tokens * cost_out) / 1_000_000


class CostTracker:
    """Records LLM call costs in Redis and emits structured log entries.

    When ``redis_client`` is ``None`` the tracker operates in memory-only mode
    (no persistence; ``get_daily_total_usd()`` returns the session total).

    Args:
        redis_client: Optional Redis client for persistent daily cost counter.
    """

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
    ) -> None:
        self._redis = redis_client
        self._session_total: float = 0.0

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record one LLM call and return its estimated cost (USD).

        Args:
            model:         LiteLLM model string.
            input_tokens:  Prompt tokens consumed.
            output_tokens: Completion tokens consumed.

        Returns:
            Estimated cost in USD for this call.
        """
        cost = _compute_cost(model, input_tokens, output_tokens)
        self._session_total += cost

        logger.info(
            "llm_cost_recorded",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            call_cost_usd=round(cost, 6),
            session_total_usd=round(self._session_total, 6),
        )

        if self._redis is not None:
            key = _redis_key(datetime.now(tz=timezone.utc))
            self._redis.incrbyfloat(key, cost)
            self._redis.expire(key, _REDIS_TTL_SECONDS)

        daily = self.get_daily_total_usd()
        if daily >= LLM_DAILY_COST_TARGET_USD:
            logger.warning(
                "llm_daily_cost_budget_reached",
                daily_total_usd=round(daily, 4),
                budget_usd=LLM_DAILY_COST_TARGET_USD,
            )

        return cost

    def get_daily_total_usd(self) -> float:
        """Return today's total LLM cost (USD).

        Reads from Redis if available; falls back to in-process session total.

        Returns:
            Accumulated cost for today (UTC) in USD.
        """
        if self._redis is None:
            return self._session_total

        key = _redis_key(datetime.now(tz=timezone.utc))
        raw = self._redis.get(key)
        # redis-py 5.x stubs .get() as Awaitable[Any]|Any; cast to concrete type.
        value = cast(bytes | None, raw)
        if value is None:
            return 0.0
        try:
            return float(value.decode() if isinstance(value, bytes) else value)
        except (ValueError, AttributeError):
            return self._session_total

    def reset_daily(self) -> None:
        """Delete today's Redis cost counter (for testing / forced resets)."""
        if self._redis is not None:
            key = _redis_key(datetime.now(tz=timezone.utc))
            self._redis.delete(key)
        self._session_total = 0.0
        logger.info("llm_daily_cost_reset")
