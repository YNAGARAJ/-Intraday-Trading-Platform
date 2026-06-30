"""Rate of Change: ROC(10)."""

import talib

from shared.core.constants import ROC_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("ROC", min_candles=ROC_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    roc = talib.ROC(candles.close, timeperiod=ROC_PERIOD)
    return {f"ROC_{ROC_PERIOD}": last_value(roc)}
