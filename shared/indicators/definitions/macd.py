"""Moving Average Convergence Divergence: MACD(12, 26, 9)."""

import talib

from shared.core.constants import (
    MACD_FAST_PERIOD,
    MACD_SIGNAL_PERIOD,
    MACD_SLOW_PERIOD,
)
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value

_MIN_CANDLES = MACD_SLOW_PERIOD + MACD_SIGNAL_PERIOD
"""TA-Lib's MACD needs the slow EMA to warm up, then the signal EMA on top of that."""


@register_indicator("MACD", min_candles=_MIN_CANDLES)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    macd, signal, hist = talib.MACD(
        candles.close,
        fastperiod=MACD_FAST_PERIOD,
        slowperiod=MACD_SLOW_PERIOD,
        signalperiod=MACD_SIGNAL_PERIOD,
    )
    return {
        "MACD": last_value(macd),
        "MACD_SIGNAL": last_value(signal),
        "MACD_HIST": last_value(hist),
    }
