"""Exponential Moving Averages: EMA(9), EMA(21), EMA(50), EMA(200)."""

import talib

from shared.core.constants import EMA_PERIODS
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("EMA", min_candles=max(EMA_PERIODS))
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    return {
        f"EMA_{period}": last_value(talib.EMA(candles.close, timeperiod=period))
        for period in EMA_PERIODS
    }
