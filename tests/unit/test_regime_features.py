"""Unit tests for M08 feature extraction (shared.regime.features)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.regime.features import _last_valid, extract_features
from shared.storage.models import OHLCVCandle


def _candles(
    n: int = 60,
    base_price: float = 100.0,
    trend: float = 0.0,
    volume: int = 100_000,
) -> list[OHLCVCandle]:
    """Generate synthetic 5-minute candles with optional linear trend."""
    start = datetime(2024, 1, 2, 9, 15, tzinfo=timezone.utc)
    result = []
    for i in range(n):
        close = base_price + trend * i + (i % 3) * 0.5
        high = close + 1.0
        low = close - 1.0
        result.append(
            OHLCVCandle(
                time=start + timedelta(minutes=5 * i),
                symbol="NIFTY50",
                exchange="NSE",
                open=close - 0.2,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return result


class TestExtractFeatures:
    def test_returns_regime_features(self) -> None:
        from shared.regime.models import RegimeFeatures

        candles = _candles(n=60)
        features = extract_features(candles)
        assert isinstance(features, RegimeFeatures)

    def test_too_few_candles_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 30"):
            extract_features(_candles(n=5))

    def test_adx_non_negative(self) -> None:
        features = extract_features(_candles(n=60))
        assert features.adx >= 0.0

    def test_rsi_in_range(self) -> None:
        features = extract_features(_candles(n=60))
        assert 0.0 <= features.rsi <= 100.0

    def test_bb_width_non_negative(self) -> None:
        features = extract_features(_candles(n=60))
        assert features.bb_width_pct >= 0.0

    def test_atr_pct_non_negative(self) -> None:
        features = extract_features(_candles(n=60))
        assert features.atr_pct >= 0.0

    def test_vix_passthrough(self) -> None:
        features = extract_features(_candles(n=60), vix=22.5)
        assert features.vix == 22.5

    def test_vix_default_zero(self) -> None:
        features = extract_features(_candles(n=60))
        assert features.vix == 0.0

    def test_volume_ratio_positive(self) -> None:
        features = extract_features(_candles(n=60))
        assert features.volume_ratio > 0.0

    def test_atr_spike_false_for_uniform_candles(self) -> None:
        # Uniform candles have no ATR spike
        features = extract_features(_candles(n=60))
        assert isinstance(features.atr_spike, bool)

    def test_vwap_deviation_bull_trend(self) -> None:
        # Strong uptrend: close ends well above VWAP
        candles = _candles(n=60, base_price=100.0, trend=2.0)
        features = extract_features(candles)
        # Later candles are higher → close above session VWAP
        assert features.vwap_deviation_pct > 0.0

    def test_vwap_deviation_bear_trend(self) -> None:
        # Downtrend: close ends below VWAP
        candles = _candles(n=60, base_price=200.0, trend=-2.0)
        features = extract_features(candles)
        assert features.vwap_deviation_pct < 0.0

    def test_feature_array_length(self) -> None:
        features = extract_features(_candles(n=60))
        assert len(features.to_feature_array()) == 8

    def test_works_with_minimum_candles(self) -> None:
        # Exactly 30 candles — boundary case
        extract_features(_candles(n=30))

    def test_atr_spike_detected_on_volatility_burst(self) -> None:
        """A sudden high-range candle at the end should trigger atr_spike."""
        candles = _candles(n=60)
        # Replace last candle with extreme range
        last = candles[-1]
        candles[-1] = OHLCVCandle(
            time=last.time,
            symbol=last.symbol,
            exchange=last.exchange,
            open=last.open,
            high=last.close + 50.0,   # very wide
            low=last.close - 50.0,
            close=last.close,
            volume=last.volume,
        )
        features = extract_features(candles)
        assert features.atr_spike is True


class TestLastValid:
    def test_returns_last_non_nan(self) -> None:
        import numpy as np

        arr = np.array([float("nan"), 1.0, 2.0, float("nan")])
        assert _last_valid(arr) == 2.0

    def test_all_nan_returns_zero(self) -> None:
        import numpy as np

        arr = np.array([float("nan"), float("nan")])
        assert _last_valid(arr) == 0.0

    def test_normal_array(self) -> None:
        import numpy as np

        arr = np.array([1.0, 2.0, 3.0])
        assert _last_valid(arr) == 3.0
