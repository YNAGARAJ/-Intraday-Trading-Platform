"""Unit tests for M11 SignalEngine: end-to-end gate orchestration."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from shared.patterns.models import (
    CandlestickSignal,
    MultiTimeframePatterns,
    ORBState,
    PatternSnapshot,
    SRLevel,
)
from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures
from shared.signals.engine import SignalEngine
from shared.signals.models import SignalContext
from shared.storage.models import OHLCVCandle

_NOW = datetime.now(UTC)
_PRICE = 2450.0
_SESSION_OPEN = _NOW.replace(hour=3, minute=45, second=0, microsecond=0)
_SESSION_CLOSE = _NOW.replace(hour=10, minute=0, second=0, microsecond=0)
_EVAL_TIME = _SESSION_OPEN + timedelta(minutes=30)


def _make_regime(r: MarketRegime) -> RegimeClassification:
    return RegimeClassification(
        regime=r,
        confidence=0.85,
        features=RegimeFeatures(
            adx=30.0, rsi=60.0, bb_width_pct=2.0, atr_pct=1.0,
            vwap_deviation_pct=0.2, volume_ratio=1.8, vix=14.0, atr_spike=False,
        ),
        hmm_state=0,
        classified_at=_NOW,
    )


def _good_context(direction: str = "LONG") -> SignalContext:
    """Build a SignalContext that should pass all 9 gates."""
    long_ = direction == "LONG"
    price = _PRICE
    inds = {
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
        "VOLUME_DELTA": {"VOLUME_DELTA": 50_000.0 if long_ else -50_000.0},
    }
    cdl_dir = 100 if long_ else -100
    orb_dir = 1 if long_ else -1
    sr_type = "SUPPORT" if long_ else "RESISTANCE"
    sr_price = price * (0.999 if long_ else 1.001)

    cdl = CandlestickSignal(name="CDLHAMMER", direction=cdl_dir, bar_index=28)
    orb = ORBState(
        orb_high=price * 1.002, orb_low=price * 0.998, orb_range=price * 0.004,
        session_open=_SESSION_OPEN, range_formed=True,
        breakout_direction=orb_dir, breakout_price=price * 1.002,
    )
    sr = SRLevel(
        price=sr_price, level_type=sr_type, strength=0.8, touches=3, last_touch_bar=25
    )
    snap = PatternSnapshot(
        symbol="RELIANCE", exchange="NSE", timeframe="5m",
        computed_at=_NOW, candle_time=_NOW,
        candlestick_signals=[cdl], orb_state=orb, sr_levels=[sr],
    )
    snap_1h = PatternSnapshot(
        symbol="RELIANCE", exchange="NSE", timeframe="1h",
        computed_at=_NOW, candle_time=_NOW,
        candlestick_signals=[CandlestickSignal("CDLHAMMER", cdl_dir, 5)],
        orb_state=None, sr_levels=[sr],
    )
    mtf = MultiTimeframePatterns(
        symbol="RELIANCE", exchange="NSE", computed_at=_NOW,
        snapshots={"5m": snap, "1h": snap_1h},
        confirmed_bullish_patterns=["CDLHAMMER"] if long_ else [],
        confirmed_bearish_patterns=["CDLHAMMER"] if not long_ else [],
    )
    candle = OHLCVCandle(
        time=_NOW, symbol="RELIANCE", exchange="NSE",
        open=price, high=price * 1.003, low=price * 0.997, close=price, volume=150_000,
    )
    regime = _make_regime(MarketRegime.BULL_TREND if long_ else MarketRegime.BEAR_TREND)

    return SignalContext(
        symbol="RELIANCE", exchange="NSE",
        direction=direction, strategy_id="EMAVWAP1",
        regime=regime, indicator_values=inds,
        pattern_snapshot=snap, multi_tf_patterns=mtf,
        current_price=price, current_volume=150_000.0, avg_volume=100_000.0,
        atr=25.0, is_snapshot_window=False,
        session_open=_SESSION_OPEN, session_close=_SESSION_CLOSE,
        evaluated_at=_EVAL_TIME, candles={"5m": [candle]}, sentiment=None,
    )


class TestSignalEngineGoodPath:
    def test_long_signal_generated(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("LONG")
        result = engine.evaluate(ctx)
        assert result.generated
        assert result.direction == "LONG"
        assert result.confidence > 0.6
        assert result.failed_at_gate is None

    def test_short_signal_generated(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("SHORT")
        result = engine.evaluate(ctx)
        assert result.generated
        assert result.direction == "SHORT"

    def test_9_gate_results_returned(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context())
        assert len(result.gate_results) == 9

    def test_all_gates_pass_in_good_context(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context())
        for gr in result.gate_results:
            assert gr.passed, f"Gate {gr.gate_number} failed: {gr.reason}"

    def test_confirming_indicators_populated(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context())
        assert len(result.confirming_indicators) >= 3

    def test_confirming_timeframes_populated(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context())
        assert len(result.confirming_timeframes) >= 1

    def test_candlestick_pattern_populated(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context())
        assert result.candlestick_pattern != ""

    def test_stop_and_targets_valid(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context("LONG"))
        assert result.stop_loss < result.entry_price < result.target1 < result.target2

    def test_strategy_id_preserved(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context())
        assert result.strategy_id == "EMAVWAP1"

    def test_regime_str_in_result(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate(_good_context("LONG"))
        assert result.regime == "BULL_TREND"


class TestSignalEngineChaosHalt:
    """VERIFY: zero signals during HIGH_VOL_CHAOS (RULE 2)."""

    def test_chaos_regime_blocks_long(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("LONG")
        chaos_ctx = SignalContext(
            **{
                **ctx.__dict__,
                "regime": _make_regime(MarketRegime.HIGH_VOL_CHAOS),
            }
        )
        result = engine.evaluate(chaos_ctx)
        assert not result.generated
        assert result.failed_at_gate == 1

    def test_chaos_regime_blocks_short(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("SHORT")
        chaos_ctx = SignalContext(
            **{
                **ctx.__dict__,
                "regime": _make_regime(MarketRegime.HIGH_VOL_CHAOS),
            }
        )
        result = engine.evaluate(chaos_ctx)
        assert not result.generated
        assert result.failed_at_gate == 1

    def test_chaos_failure_at_gate_1(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("LONG")
        chaos_ctx = SignalContext(
            **{**ctx.__dict__, "regime": _make_regime(MarketRegime.HIGH_VOL_CHAOS)}
        )
        result = engine.evaluate(chaos_ctx)
        assert result.gate_results[0].gate_number == 1
        assert "HIGH_VOL_CHAOS" in result.gate_results[0].reason


class TestSignalEngineGateFails:
    def test_fails_at_gate_1_wrong_direction(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("LONG")
        bad = SignalContext(
            **{**ctx.__dict__, "regime": _make_regime(MarketRegime.BEAR_TREND)}
        )
        result = engine.evaluate(bad)
        assert not result.generated
        assert result.failed_at_gate == 1

    def test_fails_at_gate_7_opening_noise(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("LONG")
        early_time = _SESSION_OPEN + timedelta(minutes=5)
        early = SignalContext(**{**ctx.__dict__, "evaluated_at": early_time})
        result = engine.evaluate(early)
        assert not result.generated
        assert result.failed_at_gate == 7

    def test_gate_results_truncated_at_failure(self) -> None:
        engine = SignalEngine()
        ctx = _good_context("LONG")
        chaos = SignalContext(
            **{**ctx.__dict__, "regime": _make_regime(MarketRegime.HIGH_VOL_CHAOS)}
        )
        result = engine.evaluate(chaos)
        # Only Gate 1 result returned on failure at Gate 1
        assert len(result.gate_results) == 1


class TestSignalEngineLatency:
    """RULE 4: signal evaluation must complete in < 100ms."""

    def test_evaluate_under_100ms(self) -> None:
        engine = SignalEngine()
        ctx = _good_context()
        times = []
        for _ in range(10):
            t0 = time.monotonic()
            engine.evaluate(ctx)
            times.append((time.monotonic() - t0) * 1000)
        avg_ms = sum(times) / len(times)
        assert avg_ms < 100, f"Average latency {avg_ms:.1f}ms exceeds 100ms budget"

    def test_single_evaluation_under_100ms(self) -> None:
        engine = SignalEngine()
        ctx = _good_context()
        t0 = time.monotonic()
        engine.evaluate(ctx)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 100


class TestSignalEngineExpiry:
    def test_expiry_ms_after_evaluated_at(self) -> None:
        engine = SignalEngine()
        now = datetime.now(UTC)
        expiry_ms = engine.signal_expiry_ms(now)
        now_ms = int(now.timestamp() * 1000)
        assert expiry_ms > now_ms

    def test_expiry_ms_is_5_minutes_later(self) -> None:
        from shared.core.constants import SIGNAL_EXPIRY_MINUTES  # noqa: PLC0415

        engine = SignalEngine()
        now = datetime.now(UTC)
        expiry_ms = engine.signal_expiry_ms(now)
        expected_ms = int(now.timestamp() * 1000) + SIGNAL_EXPIRY_MINUTES * 60 * 1000
        assert abs(expiry_ms - expected_ms) < 100
