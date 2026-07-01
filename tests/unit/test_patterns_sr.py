"""Unit tests for shared.patterns.support_resistance -- S/R level detection."""

from datetime import datetime, timedelta, timezone

import pytest

from shared.patterns.models import SRLevel
from shared.patterns.support_resistance import _cluster, detect_sr_levels
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)


def _candle(
    i: int,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: int = 1000,
) -> OHLCVCandle:
    return OHLCVCandle(
        time=_T0 + timedelta(minutes=5 * i),
        symbol="TEST",
        exchange="NSE",
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _flat_range(n: int, price: float = 100.0) -> list[OHLCVCandle]:
    """Candles oscillating gently around `price` with no strong swing extremes."""
    candles = []
    for i in range(n):
        p = price + (i % 3) * 0.1
        candles.append(_candle(i, p, p + 0.2, p - 0.2, p))
    return candles


class TestCluster:
    def test_empty_list_returns_empty(self) -> None:
        assert _cluster([], 0.5) == []

    def test_single_price_returns_itself(self) -> None:
        assert _cluster([100.0], 0.5) == pytest.approx([100.0])

    def test_nearby_prices_merged(self) -> None:
        prices = [100.0, 100.1, 100.2]  # within 0.3% of each other
        result = _cluster(prices, 0.5)
        assert len(result) == 1
        assert result[0] == pytest.approx(100.1, abs=0.05)

    def test_distant_prices_not_merged(self) -> None:
        prices = [100.0, 110.0]  # 10% apart
        result = _cluster(prices, 0.5)
        assert len(result) == 2

    def test_output_sorted_ascending(self) -> None:
        prices = [110.0, 100.0, 105.0]
        result = _cluster(prices, 0.1)
        assert result == sorted(result)


class TestDetectSRLevels:
    def test_too_few_candles_returns_empty(self) -> None:
        candles = _flat_range(5)
        assert detect_sr_levels(candles, swing_window=5) == []

    def test_returns_list_of_sr_levels(self) -> None:
        candles = _flat_range(30)
        result = detect_sr_levels(candles)
        assert isinstance(result, list)
        for lv in result:
            assert isinstance(lv, SRLevel)

    def test_level_type_is_support_or_resistance(self) -> None:
        candles = _flat_range(30)
        for lv in detect_sr_levels(candles):
            assert lv.level_type in ("SUPPORT", "RESISTANCE")

    def test_strength_in_0_to_1(self) -> None:
        candles = _flat_range(30)
        for lv in detect_sr_levels(candles):
            assert 0.0 <= lv.strength <= 1.0

    def test_sorted_by_price_ascending(self) -> None:
        candles = _flat_range(40)
        result = detect_sr_levels(candles)
        prices = [lv.price for lv in result]
        assert prices == sorted(prices)

    def test_swing_high_becomes_resistance(self) -> None:
        """A local price peak higher than neighbours → resistance level at that high."""
        # Build 25 candles with a clear peak at bar 12
        candles: list[OHLCVCandle] = []
        for i in range(25):
            base = 100.0
            high = base + 0.5
            low = base - 0.5
            if i == 12:
                high = 110.0  # prominent swing high
            candles.append(_candle(i, base, high, low, base))

        result = detect_sr_levels(candles, swing_window=5, min_touches=1)
        resistance_prices = [lv.price for lv in result if lv.level_type == "RESISTANCE"]
        # At least one resistance level should be near 110
        assert any(
            abs(p - 110.0) < 1.0 for p in resistance_prices
        ), f"Expected resistance near 110; found: {resistance_prices}"

    def test_swing_low_becomes_support(self) -> None:
        """A local price trough lower than neighbours → support level at that low."""
        candles: list[OHLCVCandle] = []
        for i in range(25):
            base = 100.0
            high = base + 0.5
            low = base - 0.5
            if i == 12:
                low = 88.0  # prominent swing low
            candles.append(_candle(i, base, high, low, base))

        result = detect_sr_levels(candles, swing_window=5, min_touches=1)
        support_prices = [lv.price for lv in result if lv.level_type == "SUPPORT"]
        assert any(
            abs(p - 88.0) < 1.0 for p in support_prices
        ), f"Expected support near 88; found: {support_prices}"

    def test_min_touches_filters_single_touch_levels(self) -> None:
        """With min_touches=2, levels touched only once should be excluded."""
        candles: list[OHLCVCandle] = []
        for i in range(25):
            base = 100.0
            high = base + 0.5
            low = base - 0.5
            if i == 12:
                high = 110.0  # single peak -- only touches this level once
            candles.append(_candle(i, base, high, low, base))

        result_2 = detect_sr_levels(candles, swing_window=5, min_touches=2)
        # The isolated peak at 110 should NOT survive the 2-touch filter
        near_110 = [lv for lv in result_2 if abs(lv.price - 110.0) < 1.0]
        assert not near_110

    def test_repeated_support_level_has_high_touch_count(self) -> None:
        """Price bouncing off the same low three times → support with touches >= 3."""
        support_price = 95.0
        candles: list[OHLCVCandle] = []
        bounce_bars = {5, 12, 19}  # three bounces
        for i in range(25):
            low = support_price if i in bounce_bars else 97.0
            high = 103.0
            close = 100.0
            candles.append(_candle(i, close, high, low, close))

        result = detect_sr_levels(candles, swing_window=5, min_touches=2)
        support_near = [
            lv
            for lv in result
            if lv.level_type == "SUPPORT" and abs(lv.price - support_price) < 1.0
        ]
        assert support_near, f"Expected support near {support_price}; found: {result}"
        assert support_near[0].touches >= 3

    def test_most_touched_level_has_strength_1(self) -> None:
        """The level with the highest touch count should have strength == 1.0."""
        support_price = 95.0
        candles: list[OHLCVCandle] = []
        bounce_bars = {5, 10, 15, 20}
        for i in range(25):
            low = support_price if i in bounce_bars else 97.0
            candles.append(_candle(i, 100.0, 103.0, low, 100.0))

        result = detect_sr_levels(candles, swing_window=5, min_touches=2)
        if result:
            max_strength = max(lv.strength for lv in result)
            assert max_strength == pytest.approx(1.0)
