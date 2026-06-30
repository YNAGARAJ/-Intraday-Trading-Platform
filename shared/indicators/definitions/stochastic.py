"""Stochastic Oscillator: STOCH(14, 3, 3) -- %K and %D."""

import talib

from shared.core.constants import (
    STOCH_FASTK_PERIOD,
    STOCH_SLOWD_PERIOD,
    STOCH_SLOWK_PERIOD,
)
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("STOCHASTIC", min_candles=STOCH_FASTK_PERIOD + STOCH_SLOWK_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    slowk, slowd = talib.STOCH(
        candles.high,
        candles.low,
        candles.close,
        fastk_period=STOCH_FASTK_PERIOD,
        slowk_period=STOCH_SLOWK_PERIOD,
        slowd_period=STOCH_SLOWD_PERIOD,
    )
    return {"STOCH_K": last_value(slowk), "STOCH_D": last_value(slowd)}
