"""Williams %R(14). Spec lists this with no explicit period -- 14 matches the other
oscillators (RSI, ADX, MFI, Stochastic fast-K) built alongside it."""

import talib

from shared.core.constants import WILLR_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("WILLR", min_candles=WILLR_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    willr = talib.WILLR(
        candles.high, candles.low, candles.close, timeperiod=WILLR_PERIOD
    )
    return {f"WILLR_{WILLR_PERIOD}": last_value(willr)}
