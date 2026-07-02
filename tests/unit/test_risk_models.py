"""Unit tests for M12 risk data models."""

from __future__ import annotations

import pytest

from shared.risk.models import (
    OpenPosition,
    PositionSize,
    RiskCheck,
    RiskDecision,
    RiskParameters,
)


class TestRiskCheck:
    def test_defaults(self) -> None:
        c = RiskCheck(name="X", passed=True, detail="ok")
        assert c.name == "X"
        assert c.passed is True
        assert c.detail == "ok"

    def test_frozen(self) -> None:
        c = RiskCheck(name="X", passed=True, detail="ok")
        with pytest.raises(AttributeError):
            c.passed = False  # type: ignore[misc]


class TestPositionSize:
    def test_fields(self) -> None:
        ps = PositionSize(
            quantity=10,
            notional_value=24_500.0,
            risk_amount=370.0,
            risk_pct=0.37,
            sizing_method="ATR_FIXED_RISK",
            regime_multiplier=1.0,
            snapshot_multiplier=1.0,
        )
        assert ps.quantity == 10
        assert ps.sizing_method == "ATR_FIXED_RISK"

    def test_frozen(self) -> None:
        ps = PositionSize(
            quantity=1,
            notional_value=100.0,
            risk_amount=10.0,
            risk_pct=0.01,
            sizing_method="ATR_FIXED_RISK",
            regime_multiplier=1.0,
            snapshot_multiplier=1.0,
        )
        with pytest.raises(AttributeError):
            ps.quantity = 2  # type: ignore[misc]


class TestOpenPosition:
    def test_defaults(self) -> None:
        p = OpenPosition(
            symbol="RELIANCE",
            exchange="NSE",
            direction="LONG",
            quantity=100,
            entry_price=2450.0,
            stop_loss=2413.0,
            sector="ENERGY",
            risk_amount=3_700.0,
        )
        assert p.returns == []
        assert p.sector == "ENERGY"

    def test_with_returns(self) -> None:
        returns = [0.01, -0.005, 0.008]
        p = OpenPosition(
            symbol="TCS",
            exchange="NSE",
            direction="LONG",
            quantity=50,
            entry_price=3500.0,
            stop_loss=3430.0,
            sector="IT",
            risk_amount=3_500.0,
            returns=returns,
        )
        assert len(p.returns) == 3


class TestRiskParameters:
    def _regime(self) -> object:
        from datetime import UTC, datetime

        from shared.regime.models import (
            MarketRegime,
            RegimeClassification,
            RegimeFeatures,
        )

        return RegimeClassification(
            regime=MarketRegime.BULL_TREND,
            confidence=0.9,
            features=RegimeFeatures(
                adx=30.0, rsi=60.0, bb_width_pct=2.0, atr_pct=1.0,
                vwap_deviation_pct=0.2, volume_ratio=1.5, vix=14.0, atr_spike=False,
            ),
            hmm_state=0,
            classified_at=datetime.now(UTC),
        )

    def test_defaults(self) -> None:
        params = RiskParameters(
            capital=100_000.0,
            open_positions=[],
            daily_pnl=0.0,
            daily_trade_count=0,
            is_snapshot_window=False,
            regime=self._regime(),  # type: ignore[arg-type]
        )
        assert params.use_kelly is False
        assert params.halted is False
        assert params.proposed_sector == "UNKNOWN"
        assert list(params.proposed_returns) == []

    def test_frozen(self) -> None:
        params = RiskParameters(
            capital=100_000.0,
            open_positions=[],
            daily_pnl=0.0,
            daily_trade_count=0,
            is_snapshot_window=False,
            regime=self._regime(),  # type: ignore[arg-type]
        )
        with pytest.raises(AttributeError):
            params.capital = 999.0  # type: ignore[misc]


class TestRiskDecision:
    def test_approved(self) -> None:
        ps = PositionSize(
            quantity=5,
            notional_value=12_250.0,
            risk_amount=185.0,
            risk_pct=0.185,
            sizing_method="ATR_FIXED_RISK",
            regime_multiplier=1.0,
            snapshot_multiplier=1.0,
        )
        d = RiskDecision(
            approved=True,
            position_size=ps,
            rejection_reason=None,
            checks=[RiskCheck("CB", True, "ok")],
        )
        assert d.approved is True
        assert d.position_size is not None
        assert d.rejection_reason is None

    def test_rejected(self) -> None:
        d = RiskDecision(
            approved=False,
            position_size=None,
            rejection_reason="circuit breaker",
            checks=[RiskCheck("CB", False, "circuit breaker")],
        )
        assert not d.approved
        assert d.position_size is None
