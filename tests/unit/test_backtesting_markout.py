"""Unit tests for shared.backtesting.markout — T+1m / T+5m curve computation."""

from datetime import datetime, timedelta, timezone

import pytest

from shared.backtesting.markout import compute_markout_curves
from shared.backtesting.models import DIRECTION_LONG, Trade
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)


def _candle(minutes: int, close: float, high: float | None = None) -> OHLCVCandle:
    return OHLCVCandle(
        time=_T0 + timedelta(minutes=minutes),
        symbol="TEST",
        exchange="NSE",
        open=close,
        high=high or close,
        low=close,
        close=close,
        volume=1000,
    )


def _trade(entry_minutes: int, entry_price: float) -> Trade:
    return Trade(
        trade_id="0",
        symbol="TEST",
        exchange="NSE",
        strategy_id="TST",
        direction=DIRECTION_LONG,
        entry_time=_T0 + timedelta(minutes=entry_minutes),
        exit_time=_T0 + timedelta(minutes=entry_minutes + 10),
        entry_price=entry_price,
        exit_price=entry_price * 1.01,
        entry_slippage_bps=5.0,
        exit_slippage_bps=4.0,
        quantity=10.0,
        pnl=entry_price * 0.01 * 10.0,
        pnl_pct=1.0,
    )


class TestComputeMarkoutCurves:
    def test_empty_trades_returns_empty(self) -> None:
        candles = [_candle(0, 100.0), _candle(1, 101.0)]
        result = compute_markout_curves([], candles)
        assert result == []

    def test_empty_candles_returns_empty(self) -> None:
        trade = _trade(0, 100.0)
        result = compute_markout_curves([trade], [])
        assert result == []

    def test_returns_two_offset_points(self) -> None:
        candles = [_candle(m, 100.0 + m) for m in range(10)]
        trade = _trade(0, 100.0)
        result = compute_markout_curves([trade], candles)
        # T+1m and T+5m
        assert len(result) == 2
        labels = {p.offset_label for p in result}
        assert "T+1m" in labels
        assert "T+5m" in labels

    def test_positive_return_at_offset_for_rising_market(self) -> None:
        # Candles: 100, 102, 104, 106, 108, 110 at t=0,1,2,3,4,5
        candles = [_candle(m, 100.0 + m * 2) for m in range(10)]
        trade = _trade(0, 100.0)
        result = compute_markout_curves([trade], candles)
        for point in result:
            assert point.avg_return_pct > 0.0
            assert point.win_rate_at_offset == pytest.approx(1.0)

    def test_negative_return_at_offset_for_falling_market(self) -> None:
        # Candles: 100, 98, 96, 94, 92, 90 at t=0..5
        candles = [_candle(m, 100.0 - m * 2) for m in range(10)]
        trade = _trade(0, 100.0)
        result = compute_markout_curves([trade], candles)
        for point in result:
            assert point.avg_return_pct < 0.0
            assert point.win_rate_at_offset == pytest.approx(0.0)

    def test_missing_offset_candle_excluded_gracefully(self) -> None:
        # Only 3 candles — T+5m candle not present
        candles = [_candle(0, 100.0), _candle(1, 101.0), _candle(2, 102.0)]
        trade = _trade(0, 100.0)
        result = compute_markout_curves([trade], candles)
        # T+1m should have sample_count=1, T+5m should have sample_count=0
        t1 = next(p for p in result if p.offset_label == "T+1m")
        t5 = next(p for p in result if p.offset_label == "T+5m")
        assert t1.sample_count == 1
        assert t5.sample_count == 0

    def test_multiple_trades_averaged(self) -> None:
        candles = [_candle(m, 100.0 + m) for m in range(20)]
        trades = [_trade(0, 100.0), _trade(5, 105.0)]
        result = compute_markout_curves(trades, candles)
        for point in result:
            assert point.sample_count == 2
