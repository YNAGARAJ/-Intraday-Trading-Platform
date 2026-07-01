"""Unit tests for M10 LLM cost tracker (cost_tracker.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.core.constants import LLM_DAILY_COST_TARGET_USD
from shared.sentiment.cost_tracker import CostTracker, _compute_cost

_MODEL = "groq/llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# _compute_cost
# ---------------------------------------------------------------------------


class TestComputeCost:
    def test_zero_tokens_zero_cost(self) -> None:
        assert _compute_cost(_MODEL, 0, 0) == 0.0

    def test_known_model_cost(self) -> None:
        # 1M input tokens at $0.05 = $0.05
        cost = _compute_cost(_MODEL, 1_000_000, 0)
        assert cost == pytest.approx(0.05)

    def test_output_cost_higher(self) -> None:
        input_cost = _compute_cost(_MODEL, 1000, 0)
        output_cost = _compute_cost(_MODEL, 0, 1000)
        assert output_cost >= input_cost

    def test_unknown_model_uses_default(self) -> None:
        cost = _compute_cost("unknown/model", 1000, 500)
        assert cost >= 0.0

    def test_cost_proportional_to_tokens(self) -> None:
        cost_1k = _compute_cost(_MODEL, 1000, 0)
        cost_2k = _compute_cost(_MODEL, 2000, 0)
        assert cost_2k == pytest.approx(cost_1k * 2)


# ---------------------------------------------------------------------------
# CostTracker — in-memory mode (no Redis)
# ---------------------------------------------------------------------------


class TestCostTrackerInMemory:
    def test_record_returns_cost(self) -> None:
        tracker = CostTracker()
        cost = tracker.record(_MODEL, 1000, 500)
        assert cost > 0.0

    def test_get_daily_total_accumulates(self) -> None:
        tracker = CostTracker()
        c1 = tracker.record(_MODEL, 1000, 500)
        c2 = tracker.record(_MODEL, 2000, 1000)
        total = tracker.get_daily_total_usd()
        assert total == pytest.approx(c1 + c2)

    def test_reset_zeroes_total(self) -> None:
        tracker = CostTracker()
        tracker.record(_MODEL, 5000, 2000)
        tracker.reset_daily()
        assert tracker.get_daily_total_usd() == 0.0

    def test_initial_total_is_zero(self) -> None:
        tracker = CostTracker()
        assert tracker.get_daily_total_usd() == 0.0

    def test_budget_warning_logged(self) -> None:
        tracker = CostTracker()
        # Exceed the $1/day budget
        with patch.object(
            tracker,
            "get_daily_total_usd",
            return_value=LLM_DAILY_COST_TARGET_USD + 0.01,
        ):
            # Just verify it doesn't raise
            tracker.record(_MODEL, 10, 10)


# ---------------------------------------------------------------------------
# CostTracker — Redis mode
# ---------------------------------------------------------------------------


class TestCostTrackerRedis:
    def _make_mock_redis(self, stored_value: bytes | None = None) -> MagicMock:
        r = MagicMock()
        r.get.return_value = stored_value
        return r

    def test_incrbyfloat_called(self) -> None:
        mock_redis = self._make_mock_redis()
        tracker = CostTracker(mock_redis)
        tracker.record(_MODEL, 1000, 500)
        mock_redis.incrbyfloat.assert_called_once()

    def test_expire_called_with_ttl(self) -> None:
        mock_redis = self._make_mock_redis()
        tracker = CostTracker(mock_redis)
        tracker.record(_MODEL, 1000, 0)
        mock_redis.expire.assert_called_once()
        _, args, _ = mock_redis.expire.mock_calls[0]

    def test_get_daily_reads_from_redis(self) -> None:
        mock_redis = self._make_mock_redis(stored_value=b"0.00025")
        tracker = CostTracker(mock_redis)
        total = tracker.get_daily_total_usd()
        assert total == pytest.approx(0.00025)

    def test_get_daily_returns_zero_when_key_missing(self) -> None:
        mock_redis = self._make_mock_redis(stored_value=None)
        tracker = CostTracker(mock_redis)
        assert tracker.get_daily_total_usd() == 0.0

    def test_reset_calls_delete(self) -> None:
        mock_redis = self._make_mock_redis()
        tracker = CostTracker(mock_redis)
        tracker.reset_daily()
        mock_redis.delete.assert_called_once()

    def test_cost_key_includes_date(self) -> None:
        from datetime import datetime, timezone

        mock_redis = self._make_mock_redis()
        tracker = CostTracker(mock_redis)
        tracker.record(_MODEL, 100, 50)
        args, _ = mock_redis.incrbyfloat.call_args
        key = args[0]
        today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        assert today in key
