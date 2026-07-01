"""Unit tests for shared.backtesting.engine — vectorbt runner + EMA signal generator."""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from shared.backtesting.engine import (
    _count_trading_days,
    _infer_bars_per_day,
    _infer_freq,
    ema_crossover_signals,
    run_backtest,
)
from shared.backtesting.models import BacktestConfig, BacktestResult
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
_DATE = date(2024, 1, 15)


def _candle(minutes: int, close: float, date_offset: int = 0) -> OHLCVCandle:
    t = _T0 + timedelta(days=date_offset, minutes=minutes)
    return OHLCVCandle(
        time=t,
        symbol="RELIANCE",
        exchange="NSE",
        open=close * 0.999,
        high=close * 1.001,
        low=close * 0.998,
        close=close,
        volume=10_000,
    )


def _trending_candles(
    n: int = 60, start: float = 2500.0, slope: float = 5.0
) -> list[OHLCVCandle]:
    """Generate monotonically rising candles across multiple days."""
    candles = []
    for i in range(n):
        day = i // 10
        minute = (i % 10) * 5
        close = start + i * slope
        candles.append(_candle(minute, close, date_offset=day))
    return candles


def _v_shape_candles(n: int = 80) -> list[OHLCVCandle]:
    """Generate a V-shaped series: falls for n//2 bars then rises.

    This produces a genuine EMA fast-crosses-above-slow event because the fast EMA
    first drops below the slow EMA during the decline, then crosses back up when the
    uptrend resumes — satisfying ema_crossover_signals' cross_up condition.
    """
    candles = []
    half = n // 2
    for i in range(n):
        day = i // 10
        minute = (i % 10) * 5
        if i < half:
            close = 2500.0 - i * 8.0
        else:
            close = 2500.0 - half * 8.0 + (i - half) * 12.0
        candles.append(_candle(minute, close, date_offset=day))
    return candles


def _config() -> BacktestConfig:
    return BacktestConfig(
        strategy_id="TST",
        symbol="RELIANCE",
        exchange="NSE",
        start_date=_DATE,
        end_date=_DATE + timedelta(days=30),
        initial_capital=100_000.0,
        position_size_pct=0.02,
        risk_free_rate_annual=0.065,
    )


class TestInferHelpers:
    def test_infer_freq_5min(self) -> None:
        c = [_candle(0, 100.0), _candle(5, 101.0)]
        assert _infer_freq(c) == "5T"

    def test_infer_freq_daily(self) -> None:
        c = [_candle(0, 100.0, 0), _candle(0, 101.0, 1)]
        assert _infer_freq(c) == "1D"

    def test_infer_freq_single_candle(self) -> None:
        assert _infer_freq([_candle(0, 100.0)]) == "1D"

    def test_bars_per_day_5min(self) -> None:
        c = [_candle(0, 100.0), _candle(5, 101.0)]
        bpd = _infer_bars_per_day(c)
        assert bpd == pytest.approx(75.0, rel=0.01)

    def test_count_trading_days(self) -> None:
        candles = _trending_candles(n=20)  # 2 days
        assert _count_trading_days(candles) == 2


class TestEmaCrossoverSignals:
    def test_returns_correct_length(self) -> None:
        candles = _trending_candles(n=50)
        entries, exits = ema_crossover_signals(candles)
        assert len(entries) == 50
        assert len(exits) == 50

    def test_too_few_candles_all_false(self) -> None:
        candles = _trending_candles(n=5)
        entries, exits = ema_crossover_signals(candles)
        assert not any(entries)
        assert not any(exits)

    def test_trending_market_generates_entry(self) -> None:
        # V-shape: fall then rise forces a genuine fast-crosses-above-slow event
        candles = _v_shape_candles(n=80)
        entries, exits = ema_crossover_signals(candles)
        assert any(entries), "EMA cross-up entry expected on V-shaped series"

    def test_no_simultaneous_entry_and_exit(self) -> None:
        candles = _trending_candles(n=60)
        entries, exits = ema_crossover_signals(candles)
        for e, x in zip(entries, exits, strict=False):
            assert not (e and x), "Entry and exit cannot both be True at the same bar"

    def test_custom_periods_accepted(self) -> None:
        candles = _trending_candles(n=60)
        entries, exits = ema_crossover_signals(candles, fast_period=5, slow_period=15)
        assert len(entries) == 60


class TestRunBacktest:
    def test_raises_on_too_few_candles(self) -> None:
        candles = _trending_candles(n=5)
        with pytest.raises(ValueError, match="candles"):
            run_backtest(_config(), candles, [False] * 5, [False] * 5)

    def test_raises_on_mismatched_signal_length(self) -> None:
        candles = _trending_candles(n=50)
        with pytest.raises(ValueError, match="length"):
            run_backtest(_config(), candles, [False] * 40, [False] * 50)

    def test_returns_backtest_result(self) -> None:
        candles = _trending_candles(n=60)
        entries, exits = ema_crossover_signals(candles)
        result = run_backtest(
            _config(),
            candles,
            entries,
            exits,
            slippage_rng=np.random.default_rng(42),
        )
        assert isinstance(result, BacktestResult)

    def test_run_id_is_8_hex_chars(self) -> None:
        candles = _trending_candles(n=60)
        entries, exits = ema_crossover_signals(candles)
        result = run_backtest(
            _config(), candles, entries, exits, slippage_rng=np.random.default_rng(1)
        )
        assert len(result.run_id) == 8
        assert all(c in "0123456789abcdef" for c in result.run_id)

    def test_no_signals_produces_zero_trades(self) -> None:
        candles = _trending_candles(n=60)
        entries = [False] * 60
        exits = [False] * 60
        result = run_backtest(
            _config(), candles, entries, exits, slippage_rng=np.random.default_rng(0)
        )
        assert result.metrics.total_trades == 0

    def test_equity_curve_length_matches_candles(self) -> None:
        candles = _trending_candles(n=60)
        entries, exits = ema_crossover_signals(candles)
        result = run_backtest(
            _config(), candles, entries, exits, slippage_rng=np.random.default_rng(2)
        )
        assert len(result.equity_curve) == len(candles)

    def test_promotion_gate_evaluated(self) -> None:
        candles = _trending_candles(n=60)
        entries, exits = ema_crossover_signals(candles)
        result = run_backtest(
            _config(), candles, entries, exits, slippage_rng=np.random.default_rng(3)
        )
        # passed_promotion_gate must be a bool, failures must be a list
        assert isinstance(result.passed_promotion_gate, bool)
        assert isinstance(result.promotion_failures, list)

    def test_slippage_applied_nonzero_on_entry(self) -> None:
        candles = _trending_candles(n=60, slope=20.0)
        entries, exits = ema_crossover_signals(candles)
        result = run_backtest(
            _config(),
            candles,
            entries,
            exits,
            spread_bps=10.0,
            slippage_rng=np.random.default_rng(4),
        )
        if result.metrics.total_trades > 0:
            total_slip = sum(
                t.entry_slippage_bps + t.exit_slippage_bps for t in result.trades
            )
            assert total_slip > 0.0, "Expected non-zero slippage with spread_bps=10"
