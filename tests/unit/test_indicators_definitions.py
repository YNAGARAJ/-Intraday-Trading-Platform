"""Unit tests for the hand-written (non-TA-Lib) indicator definitions: VWAP, VWAP
bands, volume delta, and pivot points. EMA/RSI/MACD/etc. wrap TA-Lib directly and are
covered by shared/indicators/engine's wiring tests instead -- there's no value in
re-deriving TA-Lib's own math by hand here.
"""

from datetime import UTC, datetime, timedelta

import pytest

from shared.indicators.definitions import pivot_points, volume_delta, vwap, vwap_bands
from shared.indicators.models import candle_arrays_from_candles
from shared.storage.models import OHLCVCandle

SYMBOL = "RELIANCE.NS"
EXCHANGE = "NSE"
T0 = datetime(2026, 6, 1, 3, 45, tzinfo=UTC)


def _candle(
    minutes_offset: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> OHLCVCandle:
    return OHLCVCandle(
        time=T0 + timedelta(minutes=minutes_offset),
        symbol=SYMBOL,
        exchange=EXCHANGE,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


class TestVwap:
    def test_single_candle_vwap_equals_its_typical_price(self) -> None:
        candles = [_candle(0, 100, 102, 98, 101, 100)]

        result = vwap.compute(candle_arrays_from_candles(candles))

        assert result["VWAP"] == pytest.approx((102 + 98 + 101) / 3.0)

    def test_two_candles_vwap_is_volume_weighted(self) -> None:
        # typical prices: 100, 110; volumes: 100, 300 -> weighted toward 110
        candles = [
            _candle(0, 99, 101, 99, 100, 100),
            _candle(5, 109, 111, 109, 110, 300),
        ]

        result = vwap.compute(candle_arrays_from_candles(candles))

        expected = (100 * 100 + 110 * 300) / 400
        assert result["VWAP"] == pytest.approx(expected)

    def test_zero_volume_session_yields_none(self) -> None:
        candles = [_candle(0, 100, 101, 99, 100, 0)]

        result = vwap.compute(candle_arrays_from_candles(candles))

        assert result["VWAP"] is None

    def test_new_utc_date_resets_the_session(self) -> None:
        # Second candle is a new UTC day -- VWAP must only reflect that one candle,
        # not be diluted by the prior day's volume.
        day_one = _candle(0, 90, 92, 88, 90, 1000)
        day_two_start = T0 + timedelta(days=1)
        day_two = OHLCVCandle(
            time=day_two_start,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            open=100,
            high=102,
            low=98,
            close=100,
            volume=50,
        )

        result = vwap.compute(candle_arrays_from_candles([day_one, day_two]))

        assert result["VWAP"] == pytest.approx((102 + 98 + 100) / 3.0)


class TestVwapBands:
    def test_constant_typical_price_yields_zero_width_bands(self) -> None:
        # No dispersion around VWAP -> upper and lower bands collapse onto VWAP.
        candles = [_candle(i * 5, 100, 100, 100, 100, 100) for i in range(5)]

        result = vwap_bands.compute(candle_arrays_from_candles(candles))

        assert result["VWAP_BAND_UPPER"] == pytest.approx(100.0)
        assert result["VWAP_BAND_LOWER"] == pytest.approx(100.0)

    def test_upper_band_above_lower_band_when_dispersed(self) -> None:
        candles = [
            _candle(0, 95, 96, 94, 95, 100),
            _candle(5, 105, 106, 104, 105, 100),
            _candle(10, 95, 96, 94, 95, 100),
        ]

        result = vwap_bands.compute(candle_arrays_from_candles(candles))

        assert result["VWAP_BAND_UPPER"] is not None
        assert result["VWAP_BAND_LOWER"] is not None
        assert result["VWAP_BAND_UPPER"] > result["VWAP_BAND_LOWER"]

    def test_zero_volume_session_yields_none_bands(self) -> None:
        candles = [_candle(0, 100, 101, 99, 100, 0), _candle(5, 100, 101, 99, 100, 0)]

        result = vwap_bands.compute(candle_arrays_from_candles(candles))

        assert result["VWAP_BAND_UPPER"] is None
        assert result["VWAP_BAND_LOWER"] is None


class TestVolumeDelta:
    def test_up_candle_is_positive_delta(self) -> None:
        candles = [_candle(0, 100, 102, 99, 101, 500)]  # close > open

        result = volume_delta.compute(candle_arrays_from_candles(candles))

        assert result["VOLUME_DELTA"] == 500.0

    def test_down_candle_is_negative_delta(self) -> None:
        candles = [_candle(0, 101, 102, 98, 100, 500)]  # close < open

        result = volume_delta.compute(candle_arrays_from_candles(candles))

        assert result["VOLUME_DELTA"] == -500.0

    def test_cumulative_sums_across_all_candles(self) -> None:
        candles = [
            _candle(0, 100, 101, 99, 101, 100),  # +100
            _candle(5, 101, 102, 99, 99, 200),  # -200
            _candle(10, 99, 101, 98, 100, 50),  # +50
        ]

        result = volume_delta.compute(candle_arrays_from_candles(candles))

        assert result["VOLUME_DELTA"] == 50.0
        assert result["VOLUME_DELTA_CUMULATIVE"] == pytest.approx(-50.0)


class TestPivotPoints:
    def test_standard_pivot_uses_prior_bar_not_latest(self) -> None:
        prior = _candle(0, 100, 110, 90, 105, 100)
        latest = _candle(5, 105, 999, 1, 999, 100)  # extreme values, must be ignored

        result = pivot_points.compute(candle_arrays_from_candles([prior, latest]))

        expected_pivot = (110 + 90 + 105) / 3.0
        assert result["PIVOT"] == pytest.approx(expected_pivot)
        assert result["PIVOT_R1"] == pytest.approx(2 * expected_pivot - 90)
        assert result["PIVOT_S1"] == pytest.approx(2 * expected_pivot - 110)

    def test_resistance_levels_increase_with_distance(self) -> None:
        prior = _candle(0, 100, 110, 90, 105, 100)
        latest = _candle(5, 105, 106, 104, 105, 100)

        result = pivot_points.compute(candle_arrays_from_candles([prior, latest]))

        assert result["PIVOT_R1"] < result["PIVOT_R2"] < result["PIVOT_R3"]  # type: ignore[operator]
        assert result["PIVOT_S1"] > result["PIVOT_S2"] > result["PIVOT_S3"]  # type: ignore[operator]
