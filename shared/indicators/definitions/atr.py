"""Average True Range: ATR(14) -- the same period M12 uses for stop-loss sizing."""

import talib

from shared.core.constants import ATR_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("ATR", min_candles=ATR_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    atr = talib.ATR(candles.high, candles.low, candles.close, timeperiod=ATR_PERIOD)
    return {f"ATR_{ATR_PERIOD}": last_value(atr)}
