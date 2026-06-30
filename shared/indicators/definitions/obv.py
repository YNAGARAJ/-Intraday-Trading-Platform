"""On-Balance Volume."""

import talib

from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value

_MIN_CANDLES = 2
"""OBV is a running cumulative sum -- meaningful from the second candle onward."""


@register_indicator("OBV", min_candles=_MIN_CANDLES)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    obv = talib.OBV(candles.close, candles.volume)
    return {"OBV": last_value(obv)}
