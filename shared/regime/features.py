"""Feature extraction for the M08 market regime classifier.

Computes the RegimeFeatures vector from a window of OHLCVCandle objects using
TA-Lib for ADX, RSI, ATR, BBANDS and NumPy for VWAP and volume statistics.
The caller injects the VIX level because it is an external time-series that
cannot be derived from equity OHLCV data alone.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import talib

from shared.core.constants import (
    REGIME_ATR_SPIKE_LOOKBACK,
    REGIME_ATR_SPIKE_MULTIPLIER,
    REGIME_FEATURE_LOOKBACK,
)
from shared.regime.models import RegimeFeatures
from shared.storage.models import OHLCVCandle

_MIN_CANDLES_FOR_FEATURES: int = 30
"""Minimum bars needed so TA-Lib indicators have a valid unstable period."""


def extract_features(
    candles: list[OHLCVCandle],
    vix: float = 0.0,
) -> RegimeFeatures:
    """Compute a RegimeFeatures vector from the most-recent candle window.

    Only the last ``REGIME_FEATURE_LOOKBACK`` candles are used for indicator
    computation; the full list may be longer (callers pass a rolling buffer).

    Args:
        candles: OHLCV candle list, oldest first.  Must have at least
            ``_MIN_CANDLES_FOR_FEATURES`` entries.
        vix: Current VIX level.  Pass 0.0 when unavailable.

    Returns:
        RegimeFeatures dataclass with all fields populated.

    Raises:
        ValueError: When fewer than ``_MIN_CANDLES_FOR_FEATURES`` candles
            are provided.
    """
    if len(candles) < _MIN_CANDLES_FOR_FEATURES:
        raise ValueError(
            f"Need at least {_MIN_CANDLES_FOR_FEATURES} candles for feature "
            f"extraction, got {len(candles)}"
        )

    window = candles[-REGIME_FEATURE_LOOKBACK:]
    high = np.array([c.high for c in window], dtype=np.float64)
    low = np.array([c.low for c in window], dtype=np.float64)
    close = np.array([c.close for c in window], dtype=np.float64)
    volume = np.array([c.volume for c in window], dtype=np.float64)

    adx_arr = talib.ADX(high, low, close, timeperiod=14)
    rsi_arr = talib.RSI(close, timeperiod=14)
    atr_arr = talib.ATR(high, low, close, timeperiod=14)
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)

    # Use the last non-NaN value for each indicator
    adx = _last_valid(adx_arr)
    rsi = _last_valid(rsi_arr)
    atr = _last_valid(atr_arr)
    bb_mid = _last_valid(middle)
    bb_upper = _last_valid(upper)
    bb_lower = _last_valid(lower)

    current_close = float(close[-1])
    bb_width_pct = (
        (bb_upper - bb_lower) / bb_mid * 100.0 if bb_mid > 0.0 else 0.0
    )
    atr_pct = atr / current_close * 100.0 if current_close > 0.0 else 0.0

    # Session VWAP: sum(typical_price * volume) / sum(volume) over the window
    typical = (high + low + close) / 3.0
    total_vol = float(np.sum(volume))
    vwap = (
        float(np.sum(typical * volume)) / total_vol
        if total_vol > 0.0
        else current_close
    )
    vwap_deviation_pct = (
        (current_close - vwap) / vwap * 100.0 if vwap > 0.0 else 0.0
    )

    # Volume ratio: current bar vs rolling mean of last REGIME_ATR_SPIKE_LOOKBACK bars
    vol_window = volume[-REGIME_ATR_SPIKE_LOOKBACK:]
    vol_mean = (
        float(np.mean(vol_window[:-1])) if len(vol_window) > 1 else float(volume[-1])
    )
    volume_ratio = float(volume[-1]) / vol_mean if vol_mean > 0.0 else 1.0

    # ATR spike: current ATR vs rolling mean of recent ATR values
    valid_atr = atr_arr[~np.isnan(atr_arr)]
    if len(valid_atr) >= 2:
        rolling_mean_atr = float(np.mean(valid_atr[-REGIME_ATR_SPIKE_LOOKBACK:]))
        atr_spike = atr > REGIME_ATR_SPIKE_MULTIPLIER * rolling_mean_atr
    else:
        atr_spike = False

    return RegimeFeatures(
        adx=round(adx, 4),
        rsi=round(rsi, 4),
        bb_width_pct=round(bb_width_pct, 4),
        atr_pct=round(atr_pct, 4),
        vwap_deviation_pct=round(vwap_deviation_pct, 4),
        volume_ratio=round(volume_ratio, 4),
        vix=float(vix),
        atr_spike=bool(atr_spike),
    )


def _last_valid(arr: npt.NDArray[np.float64]) -> float:
    """Return the last non-NaN element of a TA-Lib output array."""
    valid = arr[~np.isnan(arr)]
    return float(valid[-1]) if len(valid) > 0 else 0.0
