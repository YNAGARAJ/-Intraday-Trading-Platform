"""Unit tests for M11 signal models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.signals.models import (
    GateResult,
    SignalDirection,
    SignalResult,
)


class TestSignalDirection:
    def test_long_value(self) -> None:
        assert SignalDirection.LONG == "LONG"

    def test_short_value(self) -> None:
        assert SignalDirection.SHORT == "SHORT"

    def test_is_str(self) -> None:
        assert isinstance(SignalDirection.LONG, str)


class TestGateResult:
    def test_defaults(self) -> None:
        g = GateResult(gate_number=1, passed=True, reason="ok")
        assert g.confidence_contribution == 0.0
        assert g.confirming_indicators == []
        assert g.confirming_timeframes == []
        assert g.candlestick_pattern == ""

    def test_frozen(self) -> None:
        g = GateResult(gate_number=1, passed=True, reason="ok")
        with pytest.raises(AttributeError):
            g.passed = False  # type: ignore[misc]

    def test_with_contributions(self) -> None:
        g = GateResult(
            gate_number=2,
            passed=True,
            reason="5 agree",
            confidence_contribution=0.10,
            confirming_indicators=["EMA", "RSI"],
        )
        assert g.confidence_contribution == 0.10
        assert "EMA" in g.confirming_indicators

    def test_failed_gate_zero_contribution(self) -> None:
        g = GateResult(gate_number=1, passed=False, reason="chaos")
        assert g.confidence_contribution == 0.0


class TestSignalResult:
    def _make(self, **kwargs: object) -> SignalResult:
        defaults: dict[str, object] = dict(
            generated=True,
            symbol="RELIANCE",
            exchange="NSE",
            direction="LONG",
            confidence=0.75,
            entry_price=2450.0,
            stop_loss=2412.5,
            target1=2487.5,
            target2=2525.0,
            atr=25.0,
            strategy_id="EMAVWAP1",
            gate_results=[],
            failed_at_gate=None,
            confirming_indicators=["EMA", "RSI"],
            confirming_timeframes=["5m", "1h"],
            candlestick_pattern="CDLHAMMER",
            regime="BULL_TREND",
            evaluated_at=datetime.now(UTC),
        )
        defaults.update(kwargs)
        return SignalResult(**defaults)  # type: ignore[arg-type]

    def test_generated_signal(self) -> None:
        r = self._make()
        assert r.generated is True
        assert r.confidence == 0.75
        assert r.failed_at_gate is None

    def test_failed_signal(self) -> None:
        r = self._make(generated=False, confidence=0.0, failed_at_gate=1)
        assert r.generated is False
        assert r.failed_at_gate == 1

    def test_frozen(self) -> None:
        r = self._make()
        with pytest.raises(AttributeError):
            r.generated = False  # type: ignore[misc]

    def test_strategy_id_stored(self) -> None:
        r = self._make(strategy_id="ORBBRK01")
        assert r.strategy_id == "ORBBRK01"
