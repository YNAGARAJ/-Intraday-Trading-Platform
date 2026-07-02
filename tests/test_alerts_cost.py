"""Tests for M20 LLMCostAlerter."""

from __future__ import annotations

from datetime import date

import pytest

from shared.alerts.cost_alert import LLMCostAlerter
from shared.alerts.models import Alert, AlertLevel, AlertType
from shared.core.constants import (
    LLM_COST_ALERT_THRESHOLD_USD,
    SENTIMENT_COST_REDIS_KEY_PREFIX,
)

_THRESHOLD = LLM_COST_ALERT_THRESHOLD_USD


class _FakeRedis:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = store or {}

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None


class _FakeDispatcher:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def dispatch(self, alert: Alert) -> bool:
        self.alerts.append(alert)
        return True


def _make_alerter(
    redis: _FakeRedis | None = None,
    threshold: float = _THRESHOLD,
) -> tuple[LLMCostAlerter, _FakeDispatcher]:
    r = redis or _FakeRedis()
    d = _FakeDispatcher()
    return LLMCostAlerter(r, d, threshold_usd=threshold), d


def _today() -> date:
    return date(2026, 1, 15)


def _sentiment_key(d: date) -> str:
    return f"{SENTIMENT_COST_REDIS_KEY_PREFIX}:{d.strftime('%Y%m%d')}"


def _orchestrator_key(d: date) -> str:
    return f"orchestrator:llm:complex:{d.strftime('%Y%m%d')}"


class TestReadCost:
    def test_no_redis_data_returns_zero(self) -> None:
        alerter, _ = _make_alerter()
        assert alerter.check(now_date=_today()) == 0.0

    def test_reads_sentiment_cost(self) -> None:
        today = _today()
        alerter, _ = _make_alerter(_FakeRedis({_sentiment_key(today): "0.35"}))
        assert abs(alerter.check(now_date=today) - 0.35) < 1e-9

    def test_reads_orchestrator_cost(self) -> None:
        today = _today()
        alerter, _ = _make_alerter(_FakeRedis({_orchestrator_key(today): "0.20"}))
        assert abs(alerter.check(now_date=today) - 0.20) < 1e-9

    def test_combines_both_costs(self) -> None:
        today = _today()
        store = {_sentiment_key(today): "0.40", _orchestrator_key(today): "0.30"}
        alerter, _ = _make_alerter(_FakeRedis(store))
        assert abs(alerter.check(now_date=today) - 0.70) < 1e-9

    def test_redis_error_fails_open(self) -> None:
        class _BadRedis:
            def get(self, name: str) -> bytes | None:
                raise RuntimeError("refused")

        d = _FakeDispatcher()
        alerter = LLMCostAlerter(_BadRedis(), d)
        assert alerter.check(now_date=_today()) == 0.0

    def test_corrupt_redis_value_fails_open(self) -> None:
        today = _today()
        alerter, _ = _make_alerter(_FakeRedis({_sentiment_key(today): "nan"}))
        assert alerter.check(now_date=today) == 0.0


class TestAlertFiring:
    def test_below_threshold_no_alert(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.50"}), threshold=0.90
        )
        alerter.check(now_date=today)
        assert len(disp.alerts) == 0

    def test_at_threshold_fires_alert(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.80"})
        )
        alerter.check(now_date=today)
        assert len(disp.alerts) == 1

    def test_above_threshold_fires_alert(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.95"})
        )
        alerter.check(now_date=today)
        assert len(disp.alerts) == 1

    def test_alert_has_llm_cost_type(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.90"})
        )
        alerter.check(now_date=today)
        assert disp.alerts[0].alert_type is AlertType.LLM_COST

    def test_alert_has_warning_level(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.85"})
        )
        alerter.check(now_date=today)
        assert disp.alerts[0].level is AlertLevel.WARNING

    def test_alert_message_mentions_cost(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.82"})
        )
        alerter.check(now_date=today)
        assert "$" in disp.alerts[0].message

    def test_dedup_same_day_fires_once(self) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.90"})
        )
        alerter.check(now_date=today)
        alerter.check(now_date=today)
        assert len(disp.alerts) == 1

    def test_dedup_resets_next_day(self) -> None:
        today = _today()
        tomorrow = date(today.year, today.month, today.day + 1)
        store = {
            _sentiment_key(today): "0.90",
            _sentiment_key(tomorrow): "0.90",
        }
        alerter, disp = _make_alerter(_FakeRedis(store))
        alerter.check(now_date=today)
        alerter.check(now_date=tomorrow)
        assert len(disp.alerts) == 2

    def test_alert_metadata_includes_date(self) -> None:
        today = date(2026, 1, 15)
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): "0.85"})
        )
        alerter.check(now_date=today)
        assert disp.alerts[0].metadata.get("date") == "20260115"

    @pytest.mark.parametrize("cost", [0.80, 0.85, 0.99, 1.20])
    def test_various_costs_above_threshold(self, cost: float) -> None:
        today = _today()
        alerter, disp = _make_alerter(
            _FakeRedis({_sentiment_key(today): str(cost)})
        )
        alerter.check(now_date=today)
        assert len(disp.alerts) == 1
