"""Unit tests for M11 9-gate signal evaluation logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared.patterns.models import (
    CandlestickSignal,
    MultiTimeframePatterns,
    ORBState,
    PatternSnapshot,
    SRLevel,
)
from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures
from shared.signals.gates import (
    compute_stop_and_targets,
    gate_1_regime,
    gate_2_indicators,
    gate_3_order_flow,
    gate_4_candlestick,
    gate_5_multi_timeframe,
    gate_6_sr_proximity,
    gate_7_session_timing,
    gate_8_divergence,
    gate_9_confidence,
)
from shared.signals.models import SignalContext
from shared.storage.models import OHLCVCandle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)
_PRICE = 2450.0
_SESSION_OPEN = _NOW.replace(hour=3, minute=45, second=0, microsecond=0)
_SESSION_CLOSE = _NOW.replace(hour=10, minute=0, second=0, microsecond=0)
_EVAL_TIME = _SESSION_OPEN + timedelta(minutes=30)


def _make_regime(
    regime: MarketRegime = MarketRegime.BULL_TREND,
) -> RegimeClassification:
    return RegimeClassification(
        regime=regime,
        confidence=0.85,
        features=RegimeFeatures(
            adx=30.0, rsi=60.0, bb_width_pct=2.0, atr_pct=1.0,
            vwap_deviation_pct=0.2, volume_ratio=1.8, vix=14.0, atr_spike=False,
        ),
        hmm_state=0,
        classified_at=_NOW,
    )


def _make_snap(
    direction: str = "LONG",
    cdl_dir: int | None = None,
    orb_dir: int | None = 1,
    sr_type: str | None = None,
    sr_price: float | None = None,
) -> PatternSnapshot:
    if cdl_dir is None:
        cdl_dir = 100 if direction == "LONG" else -100
    if sr_type is None:
        sr_type = "SUPPORT" if direction == "LONG" else "RESISTANCE"
    if sr_price is None:
        sr_price = _PRICE * 0.999 if direction == "LONG" else _PRICE * 1.001
    cdl = CandlestickSignal(name="CDLHAMMER", direction=cdl_dir, bar_index=28)
    orb: ORBState | None = None
    if orb_dir is not None:
        orb = ORBState(
            orb_high=_PRICE * 1.002, orb_low=_PRICE * 0.998,
            orb_range=_PRICE * 0.004, session_open=_SESSION_OPEN,
            range_formed=True, breakout_direction=orb_dir,
            breakout_price=_PRICE * 1.002,
        )
    sr = SRLevel(
        price=sr_price, level_type=sr_type,
        strength=0.8, touches=3, last_touch_bar=25,
    )
    return PatternSnapshot(
        symbol="RELIANCE", exchange="NSE", timeframe="5m",
        computed_at=_NOW, candle_time=_NOW,
        candlestick_signals=[cdl], orb_state=orb, sr_levels=[sr],
    )


def _make_mtf(direction: str = "LONG") -> MultiTimeframePatterns:
    snap = _make_snap(direction)
    snap_1h = PatternSnapshot(
        symbol="RELIANCE", exchange="NSE", timeframe="1h",
        computed_at=_NOW, candle_time=_NOW,
        candlestick_signals=[
            CandlestickSignal(name="CDLHAMMER",
                              direction=100 if direction == "LONG" else -100,
                              bar_index=5)
        ],
        orb_state=None, sr_levels=[],
    )
    return MultiTimeframePatterns(
        symbol="RELIANCE", exchange="NSE", computed_at=_NOW,
        snapshots={"5m": snap, "1h": snap_1h},
        confirmed_bullish_patterns=["CDLHAMMER"] if direction == "LONG" else [],
        confirmed_bearish_patterns=["CDLHAMMER"] if direction == "SHORT" else [],
    )


def _make_inds(direction: str = "LONG") -> dict[str, dict[str, float | None]]:
    long_ = direction == "LONG"
    price = _PRICE
    return {
        "EMA": {
            "EMA_9": price * (1.001 if long_ else 0.999),
            "EMA_21": price * (0.998 if long_ else 1.002),
        },
        "VWAP": {"VWAP": price * (0.998 if long_ else 1.002)},
        "RSI": {"RSI_14": 62.0 if long_ else 38.0},
        "MACD": {"MACD": 10.0, "MACD_SIGNAL": 8.0, "MACD_HIST": 5.0 if long_ else -5.0},
        "STOCHASTIC": {
            "STOCH_K": 60.0 if long_ else 40.0,
            "STOCH_D": 55.0 if long_ else 45.0,
        },
        "BBANDS": {
            "BB_UPPER": price * 1.01,
            "BB_MIDDLE": price * (0.999 if long_ else 1.001),
            "BB_LOWER": price * 0.99,
        },
        "VOLUME_DELTA": {"VOLUME_DELTA": 50000.0 if long_ else -50000.0},
    }


def _make_ctx(
    direction: str = "LONG",
    regime: MarketRegime = MarketRegime.BULL_TREND,
    is_snapshot_window: bool = False,
    eval_time: datetime | None = None,
    session_open: datetime | None = None,
    session_close: datetime | None = None,
    avg_volume: float = 100_000.0,
    current_volume: float = 150_000.0,
    snap: PatternSnapshot | None = None,
    mtf: MultiTimeframePatterns | None = None,
    indicator_values: dict[str, dict[str, float | None]] | None = None,
    current_price: float = _PRICE,
) -> SignalContext:
    candle = OHLCVCandle(
        time=_NOW, symbol="RELIANCE", exchange="NSE",
        open=_PRICE, high=_PRICE * 1.003, low=_PRICE * 0.997,
        close=_PRICE, volume=int(current_volume),
    )
    return SignalContext(
        symbol="RELIANCE",
        exchange="NSE",
        direction=direction,
        strategy_id="EMAVWAP1",
        regime=_make_regime(regime),
        indicator_values=(
            indicator_values if indicator_values is not None else _make_inds(direction)
        ),
        pattern_snapshot=snap or _make_snap(direction),
        multi_tf_patterns=mtf or _make_mtf(direction),
        current_price=current_price,
        current_volume=current_volume,
        avg_volume=avg_volume,
        atr=25.0,
        is_snapshot_window=is_snapshot_window,
        session_open=session_open or _SESSION_OPEN,
        session_close=session_close or _SESSION_CLOSE,
        evaluated_at=eval_time or _EVAL_TIME,
        candles={"5m": [candle]},
        sentiment=None,
    )


# ---------------------------------------------------------------------------
# Gate 1 — Regime
# ---------------------------------------------------------------------------


class TestGate1Regime:
    def test_chaos_always_fails(self) -> None:
        ctx = _make_ctx(regime=MarketRegime.HIGH_VOL_CHAOS)
        result = gate_1_regime(ctx)
        assert not result.passed
        assert result.gate_number == 1
        assert "HIGH_VOL_CHAOS" in result.reason

    def test_long_in_bull_trend_passes(self) -> None:
        ctx = _make_ctx(direction="LONG", regime=MarketRegime.BULL_TREND)
        assert gate_1_regime(ctx).passed

    def test_short_in_bear_trend_passes(self) -> None:
        ctx = _make_ctx(direction="SHORT", regime=MarketRegime.BEAR_TREND)
        assert gate_1_regime(ctx).passed

    def test_long_in_bear_trend_fails(self) -> None:
        ctx = _make_ctx(direction="LONG", regime=MarketRegime.BEAR_TREND)
        assert not gate_1_regime(ctx).passed

    def test_short_in_bull_trend_fails(self) -> None:
        ctx = _make_ctx(direction="SHORT", regime=MarketRegime.BULL_TREND)
        assert not gate_1_regime(ctx).passed

    def test_long_in_mean_reverting_passes(self) -> None:
        ctx = _make_ctx(direction="LONG", regime=MarketRegime.MEAN_REVERTING)
        assert gate_1_regime(ctx).passed

    def test_short_in_mean_reverting_passes(self) -> None:
        ctx = _make_ctx(direction="SHORT", regime=MarketRegime.MEAN_REVERTING)
        assert gate_1_regime(ctx).passed


# ---------------------------------------------------------------------------
# Gate 2 — Indicator Agreement
# ---------------------------------------------------------------------------


class TestGate2Indicators:
    def test_all_indicators_agree_long(self) -> None:
        ctx = _make_ctx(direction="LONG")
        result = gate_2_indicators(ctx)
        assert result.passed
        assert len(result.confirming_indicators) >= 3

    def test_all_indicators_agree_short(self) -> None:
        ctx = _make_ctx(direction="SHORT")
        result = gate_2_indicators(ctx)
        assert result.passed

    def test_fails_when_fewer_than_3_agree(self) -> None:
        # All indicators flat / missing
        ctx = _make_ctx(
            indicator_values={
                "EMA": {"EMA_9": _PRICE, "EMA_21": _PRICE},
                "VWAP": {"VWAP": _PRICE},
                "RSI": {"RSI_14": 50.0},
                "MACD": {"MACD_HIST": 0.0},
                "STOCHASTIC": {"STOCH_K": 50.0, "STOCH_D": 50.0},
                "BBANDS": {"BB_MIDDLE": _PRICE},
                "VOLUME_DELTA": {"VOLUME_DELTA": 0.0},
            },
            avg_volume=200_000.0,
            current_volume=100_000.0,  # below 1.5× avg
        )
        result = gate_2_indicators(ctx)
        assert not result.passed

    def test_confidence_scales_with_agreement_count(self) -> None:
        ctx_all = _make_ctx(direction="LONG")
        r_all = gate_2_indicators(ctx_all)
        # More agreeing indicators → higher contribution
        assert r_all.confidence_contribution > 0

    def test_missing_ema_values_not_counted(self) -> None:
        inds = _make_inds("LONG")
        inds["EMA"] = {"EMA_9": None, "EMA_21": None}  # type: ignore[dict-item]
        ctx = _make_ctx(indicator_values=inds)
        result = gate_2_indicators(ctx)
        assert "EMA" not in result.confirming_indicators

    def test_volume_confirmation(self) -> None:
        ctx = _make_ctx(current_volume=200_000.0, avg_volume=100_000.0)
        result = gate_2_indicators(ctx)
        assert "VOLUME" in result.confirming_indicators

    def test_volume_fails_below_threshold(self) -> None:
        ctx = _make_ctx(current_volume=100_000.0, avg_volume=200_000.0)
        result = gate_2_indicators(ctx)
        assert "VOLUME" not in result.confirming_indicators


# ---------------------------------------------------------------------------
# Gate 3 — Order Flow
# ---------------------------------------------------------------------------


class TestGate3OrderFlow:
    def test_positive_delta_allows_long(self) -> None:
        inds = _make_inds("LONG")
        inds["VOLUME_DELTA"] = {"VOLUME_DELTA": 50_000.0}
        ctx = _make_ctx(indicator_values=inds)
        assert gate_3_order_flow(ctx).passed

    def test_negative_delta_allows_short(self) -> None:
        inds = _make_inds("SHORT")
        inds["VOLUME_DELTA"] = {"VOLUME_DELTA": -50_000.0}
        ctx = _make_ctx(direction="SHORT", indicator_values=inds)
        assert gate_3_order_flow(ctx).passed

    def test_negative_delta_blocks_long(self) -> None:
        inds = _make_inds("LONG")
        inds["VOLUME_DELTA"] = {"VOLUME_DELTA": -5_000.0}
        ctx = _make_ctx(indicator_values=inds)
        assert not gate_3_order_flow(ctx).passed

    def test_positive_delta_blocks_short(self) -> None:
        inds = _make_inds("SHORT")
        inds["VOLUME_DELTA"] = {"VOLUME_DELTA": 5_000.0}
        ctx = _make_ctx(direction="SHORT", indicator_values=inds)
        assert not gate_3_order_flow(ctx).passed

    def test_absorption_detected_blocks_signal(self) -> None:
        # High volume but tiny delta ratio → absorption
        inds = _make_inds("LONG")
        inds["VOLUME_DELTA"] = {"VOLUME_DELTA": 1_000.0}  # very small
        ctx = _make_ctx(
            indicator_values=inds,
            current_volume=300_000.0,  # > 2× avg
            avg_volume=100_000.0,
        )
        result = gate_3_order_flow(ctx)
        assert not result.passed
        assert "absorption" in result.reason.lower()

    def test_missing_volume_delta_fails(self) -> None:
        ctx = _make_ctx(indicator_values={})
        assert not gate_3_order_flow(ctx).passed

    def test_gate_3_confidence_bonus_on_pass(self) -> None:
        inds = _make_inds("LONG")
        inds["VOLUME_DELTA"] = {"VOLUME_DELTA": 50_000.0}
        ctx = _make_ctx(indicator_values=inds)
        result = gate_3_order_flow(ctx)
        assert result.confidence_contribution > 0


# ---------------------------------------------------------------------------
# Gate 4 — Candlestick
# ---------------------------------------------------------------------------


class TestGate4Candlestick:
    def test_bullish_pattern_confirms_long(self) -> None:
        ctx = _make_ctx(direction="LONG")
        result = gate_4_candlestick(ctx)
        assert result.passed
        assert result.candlestick_pattern != ""

    def test_bearish_pattern_confirms_short(self) -> None:
        ctx = _make_ctx(direction="SHORT")
        result = gate_4_candlestick(ctx)
        assert result.passed

    def test_wrong_direction_pattern_fails_long(self) -> None:
        snap = _make_snap(direction="LONG", cdl_dir=-100, orb_dir=None)
        snap = PatternSnapshot(
            symbol="RELIANCE", exchange="NSE", timeframe="5m",
            computed_at=_NOW, candle_time=_NOW,
            candlestick_signals=[CandlestickSignal("CDLEVENINGSTAR", -100, 28)],
            orb_state=None, sr_levels=[],
        )
        ctx = _make_ctx(direction="LONG", snap=snap)
        assert not gate_4_candlestick(ctx).passed

    def test_orb_breakout_as_pattern(self) -> None:
        snap = PatternSnapshot(
            symbol="RELIANCE", exchange="NSE", timeframe="5m",
            computed_at=_NOW, candle_time=_NOW,
            candlestick_signals=[],
            orb_state=ORBState(
                orb_high=_PRICE * 1.002, orb_low=_PRICE * 0.998,
                orb_range=_PRICE * 0.004, session_open=_SESSION_OPEN,
                range_formed=True, breakout_direction=1, breakout_price=_PRICE,
            ),
            sr_levels=[],
        )
        ctx = _make_ctx(direction="LONG", snap=snap)
        result = gate_4_candlestick(ctx)
        assert result.passed
        assert result.candlestick_pattern == "ORB_BREAKOUT"

    def test_no_patterns_fails(self) -> None:
        snap = PatternSnapshot(
            symbol="RELIANCE", exchange="NSE", timeframe="5m",
            computed_at=_NOW, candle_time=_NOW,
            candlestick_signals=[], orb_state=None, sr_levels=[],
        )
        ctx = _make_ctx(direction="LONG", snap=snap)
        assert not gate_4_candlestick(ctx).passed


# ---------------------------------------------------------------------------
# Gate 5 — Multi-Timeframe
# ---------------------------------------------------------------------------


class TestGate5MultiTimeframe:
    def test_confirmed_bullish_patterns_pass_long(self) -> None:
        ctx = _make_ctx(direction="LONG")
        result = gate_5_multi_timeframe(ctx)
        assert result.passed

    def test_confirmed_bearish_patterns_pass_short(self) -> None:
        ctx = _make_ctx(direction="SHORT")
        result = gate_5_multi_timeframe(ctx)
        assert result.passed

    def test_no_mtf_fails(self) -> None:
        ctx = _make_ctx()
        no_mtf = SignalContext(**{**ctx.__dict__, "multi_tf_patterns": None})
        result = gate_5_multi_timeframe(no_mtf)
        assert not result.passed

    def test_no_confirmed_patterns_fails(self) -> None:
        mtf = MultiTimeframePatterns(
            symbol="RELIANCE", exchange="NSE", computed_at=_NOW,
            snapshots={},
            confirmed_bullish_patterns=[],
            confirmed_bearish_patterns=[],
        )
        ctx = _make_ctx(direction="LONG", mtf=mtf)
        assert not gate_5_multi_timeframe(ctx).passed

    def test_timeframes_in_result(self) -> None:
        ctx = _make_ctx(direction="LONG")
        result = gate_5_multi_timeframe(ctx)
        assert len(result.confirming_timeframes) >= 1


# ---------------------------------------------------------------------------
# Gate 6 — S/R Proximity
# ---------------------------------------------------------------------------


class TestGate6SRProximity:
    def test_passes_when_price_near_support(self) -> None:
        ctx = _make_ctx(direction="LONG")
        result = gate_6_sr_proximity(ctx)
        assert result.passed

    def test_passes_when_price_near_resistance(self) -> None:
        ctx = _make_ctx(direction="SHORT")
        result = gate_6_sr_proximity(ctx)
        assert result.passed

    def test_fails_when_price_far_from_sr(self) -> None:
        snap = _make_snap(direction="LONG", sr_price=_PRICE * 0.95)
        ctx = _make_ctx(direction="LONG", snap=snap)
        assert not gate_6_sr_proximity(ctx).passed

    def test_wrong_sr_type_not_counted(self) -> None:
        # RESISTANCE level for a LONG signal — should not match
        snap = _make_snap(
            direction="LONG", sr_type="RESISTANCE", sr_price=_PRICE * 0.999
        )
        ctx = _make_ctx(direction="LONG", snap=snap)
        assert not gate_6_sr_proximity(ctx).passed

    def test_confidence_bonus_on_pass(self) -> None:
        ctx = _make_ctx(direction="LONG")
        result = gate_6_sr_proximity(ctx)
        if result.passed:
            assert result.confidence_contribution > 0


# ---------------------------------------------------------------------------
# Gate 7 — Session Timing
# ---------------------------------------------------------------------------


class TestGate7SessionTiming:
    def test_passes_during_tradeable_window(self) -> None:
        ctx = _make_ctx(eval_time=_EVAL_TIME)
        assert gate_7_session_timing(ctx).passed

    def test_fails_during_opening_noise(self) -> None:
        # 5 minutes after open < 15 minute filter
        early = _SESSION_OPEN + timedelta(minutes=5)
        ctx = _make_ctx(eval_time=early)
        result = gate_7_session_timing(ctx)
        assert not result.passed
        assert "opening" in result.reason.lower()

    def test_fails_during_closing_window(self) -> None:
        # 20 minutes before close (< 30 minute filter)
        late = _SESSION_CLOSE - timedelta(minutes=20)
        ctx = _make_ctx(eval_time=late)
        result = gate_7_session_timing(ctx)
        assert not result.passed
        assert "closing" in result.reason.lower()

    def test_exactly_at_opening_filter_boundary_passes(self) -> None:
        # Exactly at the end of the opening filter (should pass)
        boundary = _SESSION_OPEN + timedelta(minutes=15, seconds=1)
        ctx = _make_ctx(eval_time=boundary)
        assert gate_7_session_timing(ctx).passed

    def test_exactly_at_closing_window_boundary_fails(self) -> None:
        boundary = _SESSION_CLOSE - timedelta(minutes=30)
        ctx = _make_ctx(eval_time=boundary)
        assert not gate_7_session_timing(ctx).passed


# ---------------------------------------------------------------------------
# Gate 8 — Divergence (non-terminating)
# ---------------------------------------------------------------------------


class TestGate8Divergence:
    def test_always_passes(self) -> None:
        ctx = _make_ctx()
        assert gate_8_divergence(ctx).passed
        assert gate_8_divergence(ctx).gate_number == 8

    def test_overbought_rsi_long_penalty(self) -> None:
        inds = _make_inds("LONG")
        inds["RSI"] = {"RSI_14": 80.0}  # overbought
        ctx = _make_ctx(indicator_values=inds)
        result = gate_8_divergence(ctx)
        assert result.confidence_contribution < 0

    def test_oversold_rsi_short_penalty(self) -> None:
        inds = _make_inds("SHORT")
        inds["RSI"] = {"RSI_14": 20.0}  # oversold for short = divergence
        ctx = _make_ctx(direction="SHORT", indicator_values=inds)
        result = gate_8_divergence(ctx)
        assert result.confidence_contribution < 0

    def test_aligned_rsi_long_bonus(self) -> None:
        inds = _make_inds("LONG")
        inds["RSI"] = {"RSI_14": 62.0}  # in 50-70 bullish zone
        ctx = _make_ctx(indicator_values=inds)
        result = gate_8_divergence(ctx)
        assert result.confidence_contribution >= 0

    def test_macd_aligned_adds_bonus(self) -> None:
        inds = _make_inds("LONG")
        inds["MACD"] = {"MACD_HIST": 10.0}
        ctx = _make_ctx(indicator_values=inds)
        result = gate_8_divergence(ctx)
        assert result.confidence_contribution > 0

    def test_macd_diverges_adds_penalty(self) -> None:
        inds = _make_inds("LONG")
        inds["MACD"] = {"MACD_HIST": -5.0}
        ctx = _make_ctx(indicator_values=inds)
        result = gate_8_divergence(ctx)
        assert result.confidence_contribution < 0

    def test_missing_indicators_no_crash(self) -> None:
        ctx = _make_ctx(indicator_values={})
        result = gate_8_divergence(ctx)
        assert result.passed
        assert result.confidence_contribution == 0.0


# ---------------------------------------------------------------------------
# Gate 9 — Confidence Threshold
# ---------------------------------------------------------------------------


class TestGate9Confidence:
    def test_passes_above_threshold(self) -> None:
        ctx = _make_ctx()
        result = gate_9_confidence(0.75, ctx)
        assert result.passed

    def test_fails_below_threshold(self) -> None:
        ctx = _make_ctx()
        result = gate_9_confidence(0.65, ctx)
        assert not result.passed

    def test_snapshot_window_higher_threshold(self) -> None:
        ctx = _make_ctx(is_snapshot_window=True)
        # 0.75 passes normal threshold but should fail snapshot threshold (0.80)
        result = gate_9_confidence(0.75, ctx)
        assert not result.passed

    def test_snapshot_window_passes_at_0_80(self) -> None:
        ctx = _make_ctx(is_snapshot_window=True)
        result = gate_9_confidence(0.82, ctx)
        assert result.passed

    def test_reason_includes_snapshot_label(self) -> None:
        ctx = _make_ctx(is_snapshot_window=True)
        result = gate_9_confidence(0.65, ctx)
        assert "snapshot" in result.reason.lower()


# ---------------------------------------------------------------------------
# compute_stop_and_targets
# ---------------------------------------------------------------------------


class TestComputeStopAndTargets:
    def test_long_stop_below_entry(self) -> None:
        ctx = _make_ctx(direction="LONG")
        sl, t1, t2 = compute_stop_and_targets(ctx)
        assert sl < ctx.current_price
        assert t1 > ctx.current_price
        assert t2 > t1

    def test_short_stop_above_entry(self) -> None:
        ctx = _make_ctx(direction="SHORT", regime=MarketRegime.BEAR_TREND)
        sl, t1, t2 = compute_stop_and_targets(ctx)
        assert sl > ctx.current_price
        assert t1 < ctx.current_price
        assert t2 < t1

    def test_targets_use_risk_reward_ratios(self) -> None:
        ctx = _make_ctx(direction="LONG")
        sl, t1, t2 = compute_stop_and_targets(ctx)
        risk = ctx.current_price - sl
        assert t1 == pytest.approx(ctx.current_price + 1.5 * risk, rel=1e-3)
        assert t2 == pytest.approx(ctx.current_price + 3.0 * risk, rel=1e-3)
