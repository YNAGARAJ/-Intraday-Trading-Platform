"""Bollinger Bands: BB(20, 2)."""

import talib

from shared.core.constants import BBANDS_PERIOD, BBANDS_STDDEV
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("BBANDS", min_candles=BBANDS_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    upper, middle, lower = talib.BBANDS(
        candles.close,
        timeperiod=BBANDS_PERIOD,
        nbdevup=BBANDS_STDDEV,
        nbdevdn=BBANDS_STDDEV,
    )
    return {
        "BB_UPPER": last_value(upper),
        "BB_MIDDLE": last_value(middle),
        "BB_LOWER": last_value(lower),
    }
