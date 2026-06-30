"""Relative Strength Index: RSI(14)."""

import talib

from shared.core.constants import RSI_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("RSI", min_candles=RSI_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    rsi = talib.RSI(candles.close, timeperiod=RSI_PERIOD)
    return {f"RSI_{RSI_PERIOD}": last_value(rsi)}
