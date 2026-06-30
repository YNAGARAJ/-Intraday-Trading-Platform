"""Commodity Channel Index: CCI(20)."""

import talib

from shared.core.constants import CCI_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("CCI", min_candles=CCI_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    cci = talib.CCI(candles.high, candles.low, candles.close, timeperiod=CCI_PERIOD)
    return {f"CCI_{CCI_PERIOD}": last_value(cci)}
