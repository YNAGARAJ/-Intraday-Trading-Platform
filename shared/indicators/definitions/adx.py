"""Average Directional Index: ADX(14) -- trend strength, used by Gate 2/5 later."""

import talib

from shared.core.constants import ADX_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("ADX", min_candles=ADX_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    adx = talib.ADX(candles.high, candles.low, candles.close, timeperiod=ADX_PERIOD)
    return {f"ADX_{ADX_PERIOD}": last_value(adx)}
