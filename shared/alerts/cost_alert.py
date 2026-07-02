"""M20 Alerting & Notification — LLM daily cost monitor.

Aggregates spend from M10 (sentiment scoring) and M18 (orchestrator LLM calls)
and fires an LLM_COST alert when 80% of the $1/day target is consumed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

import structlog

from shared.alerts.models import Alert, AlertLevel, AlertType
from shared.core.constants import (
    LLM_COMPLEX_DAILY_COUNTER_KEY,
    LLM_COST_ALERT_THRESHOLD_USD,
    LLM_DAILY_COST_TARGET_USD,
    SENTIMENT_COST_REDIS_KEY_PREFIX,
)

logger = structlog.get_logger(__name__)


class _RedisClient(Protocol):
    """Structural protocol for the Redis read operations needed here."""

    def get(self, name: str) -> bytes | None:
        """Return the value at ``name``, or None if the key does not exist."""
        ...


class _Dispatcher(Protocol):
    """Structural protocol for an alert dispatcher."""

    def dispatch(self, alert: Alert) -> bool:
        """Dispatch an alert; return True if accepted by at least one channel."""
        ...


class LLMCostAlerter:
    """Reads daily LLM spend from Redis and fires a WARNING when near budget.

    Reads two Redis keys:
    - ``sentiment:cost:daily:{YYYYMMDD}`` (M10 sentiment scoring cost).
    - ``orchestrator:llm:complex:{date}`` (M18 orchestrator LLM call cost).

    Fires at most one LLM_COST alert per calendar day (deduplication).

    Args:
        redis_client: Redis client for reading cost counters.
        dispatcher: Alert dispatcher to receive the LLM_COST alert.
        threshold_usd: Dispatch alert when total spend reaches this USD amount.
            Defaults to ``LLM_COST_ALERT_THRESHOLD_USD`` (80% of $1/day target).
    """

    def __init__(
        self,
        redis_client: _RedisClient,
        dispatcher: _Dispatcher,
        threshold_usd: float = LLM_COST_ALERT_THRESHOLD_USD,
    ) -> None:
        self._redis = redis_client
        self._dispatcher = dispatcher
        self._threshold = threshold_usd
        self._alerted_today: date | None = None

    def _read_cost(self, key: str) -> float:
        """Read a float cost value from Redis; return 0.0 on any error."""
        import math

        try:
            raw = self._redis.get(key)
            if raw is None:
                return 0.0
            value = float(raw.decode())
            return value if math.isfinite(value) else 0.0
        except Exception:
            return 0.0

    def check(self, now_date: date | None = None) -> float:
        """Return today's total LLM cost in USD and fire an alert if over threshold.

        Args:
            now_date: Date to check (defaults to today UTC).

        Returns:
            Aggregated USD cost from all LLM cost Redis keys for the given date.
        """
        today = now_date or datetime.now(tz=timezone.utc).date()
        date_str = today.strftime("%Y%m%d")

        sentiment_key = f"{SENTIMENT_COST_REDIS_KEY_PREFIX}:{date_str}"
        orchestrator_key = LLM_COMPLEX_DAILY_COUNTER_KEY.format(date=date_str)

        total = self._read_cost(sentiment_key) + self._read_cost(orchestrator_key)

        logger.debug(
            "llm_cost_check",
            total_usd=round(total, 4),
            threshold_usd=self._threshold,
            date=date_str,
        )

        if total >= self._threshold and self._alerted_today != today:
            self._alerted_today = today
            pct = round(total / LLM_DAILY_COST_TARGET_USD * 100, 1)
            self._dispatcher.dispatch(
                Alert(
                    alert_type=AlertType.LLM_COST,
                    level=AlertLevel.WARNING,
                    message=(
                        f"LLM daily cost ${total:.4f} "
                        f"({pct}% of ${LLM_DAILY_COST_TARGET_USD}/day target)"
                    ),
                    metadata={
                        "total_usd": str(round(total, 4)),
                        "threshold_usd": str(self._threshold),
                        "date": date_str,
                    },
                )
            )
        return total
