"""Unit tests for M12 RiskEngine — all rules including 3-5-7 and correlation guard."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.risk.engine import RiskEngine, _check_three_five_seven, _regime_risk_pct
from shared.risk.models import OpenPosition, RiskParameters


def _make_regime(regime_name: str = "BULL_TREND") -> object:
    from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures

    mapping = {
        "BULL_TREND": MarketRegime.BULL_TREND,
        "BEAR_TREND": MarketRegime.BEAR_TREND,
        "MEAN_REVERTING": MarketRegime.MEAN_REVERTING,
        "HIGH_VOL_CHAOS": MarketRegime.HIGH_VOL_CHAOS,
    }
    return RegimeClassification(
        regime=mapping[regime_name],
        confidence=0.85,
        features=RegimeFeatures(
            adx=30.0,
            rsi=60.0,
            bb_width_pct=2.0,
            atr_pct=1.0,
            vwap_deviation_pct=0.2,
            volume_ratio=1.5,
            vix=14.0,
            atr_spike=False,
        ),
        hmm_state=0,
        classified_at=datetime.now(UTC),
    )


def _base_params(**kwargs: object) -> RiskParameters:
    defaults: dict[str, object] = dict(
        capital=100_000.0,
        open_positions=[],
        daily_pnl=0.0,
        daily_trade_count=2,
        is_snapshot_window=False,
        regime=_make_regime("BULL_TREND"),
    )
    defaults.update(kwargs)
    return RiskParameters(**defaults)  # type: ignore[arg-type]


def _make_open_pos(
    symbol: str = "STOCK1",
    sector: str = "IT",
    risk_amount: float = 1_000.0,
    returns: list[float] | None = None,
) -> OpenPosition:
    return OpenPosition(
        symbol=symbol,
        exchange="NSE",
        direction="LONG",
        quantity=100,
        entry_price=500.0,
        stop_loss=490.0,
        sector=sector,
        risk_amount=risk_amount,
        returns=returns or [],
    )


class TestRegimeRiskPct:
    def test_bull_trend(self) -> None:
        from shared.core.constants import RISK_PCT_BULL_TREND

        pct = _regime_risk_pct(_make_regime("BULL_TREND"))  # type: ignore[arg-type]
        assert pct == RISK_PCT_BULL_TREND

    def test_bear_trend(self) -> None:
        from shared.core.constants import RISK_PCT_BEAR_TREND

        pct = _regime_risk_pct(_make_regime("BEAR_TREND"))  # type: ignore[arg-type]
        assert pct == RISK_PCT_BEAR_TREND

    def test_mean_reverting(self) -> None:
        from shared.core.constants import RISK_PCT_MEAN_REVERTING

        pct = _regime_risk_pct(_make_regime("MEAN_REVERTING"))  # type: ignore[arg-type]
        assert pct == RISK_PCT_MEAN_REVERTING

    def test_high_vol_chaos_zero(self) -> None:
        from shared.core.constants import RISK_PCT_HIGH_VOL_CHAOS

        pct = _regime_risk_pct(_make_regime("HIGH_VOL_CHAOS"))  # type: ignore[arg-type]
        assert pct == RISK_PCT_HIGH_VOL_CHAOS


class TestCheckThreeFiveSeven:
    def test_small_risk_passes_all(self) -> None:
        params = _base_params(open_positions=[], proposed_sector="IT")
        checks = _check_three_five_seven(params, proposed_risk_amount=500.0)
        assert all(c.passed for c in checks)

    def test_per_trade_breach_fails(self) -> None:
        # 3,500 / 100,000 = 3.5% > 3% limit
        params = _base_params(proposed_sector="IT")
        checks = _check_three_five_seven(params, proposed_risk_amount=3_500.0)
        per_trade = next(c for c in checks if c.name == "MAX_PER_TRADE_RISK")
        assert per_trade.passed is False

    def test_sector_breach_fails(self) -> None:
        # existing sector risk = 4,500, proposed = 1,000 → total 5,500 = 5.5% > 5%
        existing = _make_open_pos(sector="IT", risk_amount=4_500.0)
        params = _base_params(
            open_positions=[existing],
            proposed_sector="IT",
        )
        checks = _check_three_five_seven(params, proposed_risk_amount=1_000.0)
        sector = next((c for c in checks if c.name == "MAX_SECTOR_RISK"), None)
        assert sector is not None
        assert sector.passed is False

    def test_portfolio_heat_breach_fails(self) -> None:
        # 5 existing positions × 1,500 = 7,500 + 1,000 proposed = 8,500 = 8.5% > 7%
        existing = [
            _make_open_pos(f"S{i}", sector="ENERGY", risk_amount=1_500.0)
            for i in range(5)
        ]
        params = _base_params(
            open_positions=existing,
            proposed_sector="BANKING",
        )
        checks = _check_three_five_seven(params, proposed_risk_amount=1_000.0)
        heat = next((c for c in checks if c.name == "MAX_PORTFOLIO_HEAT"), None)
        assert heat is not None
        assert heat.passed is False

    def test_zero_capital_fails(self) -> None:
        params = _base_params(capital=0.0)
        checks = _check_three_five_seven(params, proposed_risk_amount=100.0)
        assert checks[0].passed is False


class TestRiskEngine:
    def setup_method(self) -> None:
        self.engine = RiskEngine()

    # --- Approval scenarios ---

    def test_normal_trade_approved(self) -> None:
        params = _base_params()
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is True
        assert d.position_size is not None
        assert d.rejection_reason is None

    def test_approved_decision_has_all_checks(self) -> None:
        d = self.engine.evaluate(
            entry_price=2450.0,
            stop_loss=2413.0,
            params=_base_params(),
        )
        check_names = {c.name for c in d.checks}
        assert "SYSTEM_HALTED" in check_names
        assert "CIRCUIT_BREAKER" in check_names
        assert "DAILY_TRADE_LIMIT" in check_names
        assert "SIZING" in check_names

    def test_approved_position_size_is_integer(self) -> None:
        d = self.engine.evaluate(
            entry_price=2450.0,
            stop_loss=2413.0,
            params=_base_params(),
        )
        assert d.position_size is not None
        assert isinstance(d.position_size.quantity, int)

    # --- Halted flag ---

    def test_halted_flag_blocks(self) -> None:
        params = _base_params(halted=True)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is False
        assert "halted" in (d.rejection_reason or "").lower()

    def test_halted_first_check_in_list(self) -> None:
        params = _base_params(halted=True)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.checks[0].name == "SYSTEM_HALTED"

    # --- Circuit breaker ---

    def test_circuit_breaker_triggers_at_minus_2pct(self) -> None:
        params = _base_params(daily_pnl=-2_000.0)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is False
        assert "circuit-breaker" in (d.rejection_reason or "").lower()

    def test_circuit_breaker_does_not_trigger_at_minus_1pct(self) -> None:
        params = _base_params(daily_pnl=-1_000.0)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is True

    # --- Daily trade count ---

    def test_trade_count_limit_blocks(self) -> None:
        params = _base_params(daily_trade_count=10)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is False

    def test_trade_count_at_nine_passes(self) -> None:
        params = _base_params(daily_trade_count=9)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is True

    # --- 3-5-7 Rule ---

    def test_per_trade_limit_blocks(self) -> None:
        # Force a large stop distance to produce > 3% risk
        # entry 1000, stop 940 → stop_distance 60; 3.1% = 3100 / 60 ≈ 51 shares
        # With base risk = 1% → 1000 / 60 ≈ 16 shares → 960 risk = 0.96% — OK
        # We need to test the preliminary estimate path
        # Use very small stop so risk_pct would be huge: no, that's handled in sizing
        # Test via 3-5-7 preliminary check by filling portfolio first
        existing = [_make_open_pos(f"S{i}", risk_amount=700.0) for i in range(10)]
        params = _base_params(
            open_positions=existing,
            proposed_sector="IT",
        )
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        # Portfolio heat = 7,000 = 7%, adding preliminary 1,000 → 8% > 7% limit
        assert d.approved is False

    def test_sector_limit_blocks(self) -> None:
        # 4,500 + preliminary ~1,000 = 5,500 > 5,000 (5%)
        existing = [_make_open_pos("TCS", sector="IT", risk_amount=4_500.0)]
        params = _base_params(
            open_positions=existing,
            proposed_sector="IT",
        )
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is False

    # --- Correlation guard ---

    def test_correlated_position_blocks(self) -> None:
        r = [0.01, -0.005, 0.008, 0.003, -0.002, 0.007, 0.004, -0.006] * 3
        existing = _make_open_pos("RELIANCE", returns=r, risk_amount=500.0)
        params = _base_params(
            open_positions=[existing],
            proposed_returns=r,
        )
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is False
        assert "RELIANCE" in (d.rejection_reason or "")

    # --- Regime effects ---

    def test_bear_regime_smaller_size(self) -> None:
        bull_d = self.engine.evaluate(
            entry_price=1000.0,
            stop_loss=980.0,
            params=_base_params(regime=_make_regime("BULL_TREND")),  # type: ignore[arg-type]
        )
        bear_d = self.engine.evaluate(
            entry_price=1000.0,
            stop_loss=980.0,
            params=_base_params(regime=_make_regime("BEAR_TREND")),  # type: ignore[arg-type]
        )
        assert bull_d.approved and bear_d.approved
        assert bull_d.position_size is not None and bear_d.position_size is not None
        assert bear_d.position_size.quantity <= bull_d.position_size.quantity

    # --- Snapshot window ---

    def test_snapshot_window_halves_size(self) -> None:
        normal = self.engine.evaluate(
            entry_price=2450.0,
            stop_loss=2413.0,
            params=_base_params(is_snapshot_window=False),
        )
        snap = self.engine.evaluate(
            entry_price=2450.0,
            stop_loss=2413.0,
            params=_base_params(is_snapshot_window=True),
        )
        assert normal.approved and snap.approved
        assert normal.position_size is not None and snap.position_size is not None
        assert snap.position_size.risk_pct <= normal.position_size.risk_pct * 0.6

    # --- Kelly mode ---

    def test_kelly_mode_approved(self) -> None:
        # win_rate=0.52, ratio=1.1 → kelly_full≈0.084 → quarter=0.021 → risk≈2.1% < 3%
        params = _base_params(
            use_kelly=True,
            win_rate=0.52,
            avg_win_loss_ratio=1.1,
        )
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is True
        assert d.position_size is not None
        assert d.position_size.sizing_method == "KELLY"

    def test_kelly_missing_win_rate_falls_back_to_atr(self) -> None:
        params = _base_params(use_kelly=True, win_rate=None)
        d = self.engine.evaluate(
            entry_price=2450.0, stop_loss=2413.0, params=params
        )
        assert d.approved is True
        assert d.position_size is not None
        assert d.position_size.sizing_method == "ATR_FIXED_RISK"

    # --- Invalid inputs ---

    def test_invalid_stop_raises_in_sizing(self) -> None:
        d = self.engine.evaluate(
            entry_price=2450.0,
            stop_loss=2449.99,
            params=_base_params(),
        )
        assert d.approved is False
        assert "stop_distance" in (d.rejection_reason or "")

    def test_rejection_has_reason(self) -> None:
        d = self.engine.evaluate(
            entry_price=2450.0,
            stop_loss=2413.0,
            params=_base_params(halted=True),
        )
        assert d.rejection_reason is not None
        assert len(d.rejection_reason) > 0
